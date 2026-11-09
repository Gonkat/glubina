"""
Звуковой банк (M8): все звуки живут в assets/sounds/.

Поддерживаемые форматы: WAV, OGG, MP3. Если рядом лежат
shoot.wav и shoot.mp3 — играется MP3 (mp3 > ogg > wav),
поэтому заменить звук можно просто подложив файл с тем же
именем и расширением .mp3, не трогая генератор.

Файлы создаёт генератор:  python assets_gen.py

Принцип работы:
  * Загрузка ЛЕНИВАЯ — при первом play(). Игра стартует даже если
    звуков нет вообще (файлы удалены, звуковая карта недоступна);
  * любой сбой молча гасит звук, но НИКОГДА не роняет игру —
    звук не влияет на логику, поэтому его отказ должен быть безопасен;
  * зовётся одной строкой откуда угодно:  soundbank.play("shoot")
    — протаскивать объект банка через 10 сигнатур ради звука не стоит.
"""
import os

import pygame

from settings import SOUND_CHANNELS, SOUND_VOLUME

# поддерживаемые расширения и их приоритет: чем больше — тем лучше.
# Побеждает файл с наивысшим приоритетом, поэтому mp3 перекрывает wav.
SOUND_EXTS = {".wav": 0, ".ogg": 1, ".mp3": 2}

# папка assets/sounds рядом с этим файлом (корень проекта)
SOUNDS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "sounds"
)


class SoundBank:
    """Хранилище загруженных звуков + безопасное воспроизведение."""

    def __init__(self):
        self.sounds = {}        # имя -> pygame.mixer.Sound
        self.enabled = False    # False = все play() — тихие no-op
        self._loaded = False
        self.volume = SOUND_VOLUME
        self._loops = {}        # имя -> (Channel, базовая громкость)

    def _ensure_loaded(self):
        """Ленивая загрузка: один раз пробуем, дальше только читаем кэш."""
        if self._loaded:
            return
        self._loaded = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=1,
                                  buffer=512)
            pygame.mixer.set_num_channels(SOUND_CHANNELS)
            if not os.path.isdir(SOUNDS_DIR):
                return
            for filename in sorted(os.listdir(SOUNDS_DIR)):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in SOUND_EXTS:
                    continue
                name = filename[:-len(ext)]     # shoot.mp3 -> "shoot"
                path = os.path.join(SOUNDS_DIR, filename)
                # при конфликте (shoot.wav + shoot.mp3) оставляем файл
                # с наивысшим приоритетом расширения
                prev = self.sounds.get(name)
                if prev is None or SOUND_EXTS[ext] > SOUND_EXTS[prev[0]]:
                    self.sounds[name] = (ext, path)
            loaded = {}
            for name, (ext, path) in self.sounds.items():
                try:
                    loaded[name] = pygame.mixer.Sound(path)
                except Exception:
                    # битый/неподдерживаемый файл пропускаем,
                    # остальные звуки продолжают работать
                    continue
            self.sounds = loaded
            self.enabled = bool(self.sounds)
        except Exception:
            # нет звуковой карты / нет папки / битый файл — играем тишиной
            self.sounds = {}
            self.enabled = False

    def play(self, name, volume=1.0):
        """Проиграть звук. Неизвестное имя или отказ аудио — no-op."""
        self._ensure_loaded()
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        try:
            sound.set_volume(max(0.0, min(1.0, volume * self.volume)))
            sound.play()
        except pygame.error:
            pass                     # каналов нет — молчим, не падаем

    def play_loop(self, name, volume=0.3, fade_ms=900):
        """Зацикленный фон (например, гул подземелья)."""
        self._ensure_loaded()
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None or name in self._loops:
            return
        try:
            channel = pygame.mixer.Channel(SOUND_CHANNELS - 1)
            channel.set_volume(max(0.0, min(1.0, volume * self.volume)))
            channel.play(sound, loops=-1, fade_ms=fade_ms)
            self._loops[name] = (channel, volume)
        except pygame.error:
            pass

    def stop_loop(self, name, fade_ms=500):
        entry = self._loops.pop(name, None)
        if entry is None:
            return
        try:
            entry[0].fadeout(fade_ms)
        except pygame.error:
            pass

    def set_volume(self, volume):
        """Установить общую громкость эффектов в диапазоне 0..1."""
        self.volume = max(0.0, min(1.0, volume))
        for channel, base in self._loops.values():
            try:
                channel.set_volume(max(0.0, min(1.0, base * self.volume)))
            except pygame.error:
                pass

    def get_volume(self):
        return self.volume


_bank = SoundBank()


def get_bank():
    """Тот самый экземпляр (лениво создаётся при первом обращении)."""
    return _bank


def play(name, volume=1.0):
    """Проиграть именованный звук из assets/sounds — основной API."""
    _bank.play(name, volume)


def play_loop(name, volume=0.3, fade_ms=900):
    _bank.play_loop(name, volume, fade_ms)


def stop_loop(name, fade_ms=500):
    _bank.stop_loop(name, fade_ms)


def set_volume(volume):
    _bank.set_volume(volume)


def get_volume():
    return _bank.get_volume()
