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

Позиционный звук в кооперативе:
  * ``emit(source, name, volume)`` — звук, который издал ИГРОК. Хост
    проигрывает его локально с затуханием по расстоянию до своего героя
    и (если он сервер) отдаёт событие в сеть через ``bind_audio``;
  * ``play_remote(name, x, y, volume)`` — событие, пришедшее по сети:
    гость сам считает расстояние до своего героя и панораму. По сети
    едет только позиция и базовая громкость — никакого аудио.
  * ``spatial`` — чистая функция затухания, её же проверяют тесты.
"""
import math
import os

import pygame

from settings import SOUND_CHANNELS, SOUND_VOLUME

# Слышимость: ближе NEAR_RADIUS — полная громкость, дальше HEAR_RADIUS —
# тишина. Между ними — плавная кривая, без «щелчка» на границе.
HEAR_RADIUS = 1600.0
NEAR_RADIUS = 280.0
# Расстояние, на котором панорама набирает полную силу (0..1).
PAN_FULL_PX = 420.0

# Минимальный интервал между одинаковыми звуками одного игрока в сети.
# Стрельба — до ~12 выстрелов/с, поэтому 35 мс; редкие действия — больше,
# чтобы очередь не пухла от «пустых щелчков» на высоком FPS хоста.
SOUND_MIN_GAP = {
    "shoot": 0.035, "shotgun": 0.05, "sniper": 0.08, "lightning": 0.06,
    "spit_charge": 0.12, "swing": 0.09, "dash": 0.15, "reload": 0.20,
    "empty": 0.20, "throw": 0.15, "hurt": 0.18, "heal": 0.25,
    "pickup": 0.12, "explosion": 0.12, "shield": 0.25, "artifact": 0.20,
}


def spatial(x, y, listener_x, listener_y):
    """Громкость и панорама звука в точке (x, y) для слушателя.

    Возвращает ``(gain 0..1, pan -1..1)``. Чистая функция: ни pygame,
    ни состояния — поэтому её удобно проверять тестами.
    """
    dx = float(x) - float(listener_x)
    dy = float(y) - float(listener_y)
    distance = math.hypot(dx, dy)
    if distance >= HEAR_RADIUS:
        return 0.0, 0.0
    if distance <= NEAR_RADIUS:
        gain = 1.0
    else:
        t = (distance - NEAR_RADIUS) / (HEAR_RADIUS - NEAR_RADIUS)
        gain = (1.0 - t) ** 1.6
    if distance < 1e-3:
        return gain, 0.0
    # В top-down камера не вращается: лево/право — это знак dx.
    # 0.6 — предел панорамы: полный уход в одно ухо на 400 px звучит
    # неестественно, а лёгкий сдвиг уже читается как направление.
    pan = (dx / distance) * min(1.0, distance / PAN_FULL_PX) * 0.6
    return gain, max(-1.0, min(1.0, pan))

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
        self.stereo = False     # микшер на 2 канала — можно панораму

    def _ensure_loaded(self):
        """Ленивая загрузка: один раз пробуем, дальше только читаем кэш."""
        if self._loaded:
            return
        self._loaded = True
        try:
            if not pygame.mixer.get_init():
                # 2 канала нужны для панорамы (Channel.set_volume(l, r)).
                # Моно-файлы pygame сам поднимет до стерео.
                pygame.mixer.init(frequency=44100, size=-16, channels=2,
                                  buffer=512)
            init = pygame.mixer.get_init()
            self.stereo = bool(init and init[2] >= 2)
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
        self.play_at(name, volume, 0.0)

    def play_at(self, name, volume=1.0, pan=0.0):
        """Проиграть звук с панорамой: pan -1 — слева, +1 — справа.

        Громкость ставится КАНАЛУ, а не Sound: у Sound.set_volume общий
        базовый уровень, и два одновременных выстрела «делили» бы его.
        """
        self._ensure_loaded()
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        try:
            # Канал берём ДО play: громкость выставляется до первого
            # сэмпла, иначе тихий звук успевает щёлкнуть на полной.
            channel = pygame.mixer.find_channel(True)
            if channel is None:
                return
            level = max(0.0, min(1.0, volume * self.volume))
            pan = max(-1.0, min(1.0, float(pan)))
            if self.stereo:
                channel.set_volume(level * min(1.0, 1.0 - pan),
                                   level * min(1.0, 1.0 + pan))
            else:
                channel.set_volume(level)
            channel.play(sound)
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


def play_at(name, volume=1.0, pan=0.0):
    """То же, но с панорамой: pan -1 — слева, +1 — справа."""
    _bank.play_at(name, volume, pan)


def play_loop(name, volume=0.3, fade_ms=900):
    _bank.play_loop(name, volume, fade_ms)


def stop_loop(name, fade_ms=500):
    _bank.stop_loop(name, fade_ms)


def set_volume(volume):
    _bank.set_volume(volume)


# ------------------------------------------------------- ПОЗИЦИОННЫЙ ЗВУК
# Слушатель — тот, чьими ушами играет этот клиент. На хосте это его герой,
# на госте — зеркало его героя. None = одиночная игра: затухания нет.
_listener = None       # callable() -> (x, y) | None
_relay = None          # callable(pid, name, x, y, volume) | None


def bind_audio(listener=None, relay=None):
    """Включает/выключает позиционный звук и сетевую рассылку.

    ``listener`` — функция без аргументов, возвращает позицию слушателя.
    ``relay`` — только у хоста: вызывается с БАЗОВОЙ громкостью, чтобы
    каждый гость сам посчитал своё затухание.
    """
    global _listener, _relay
    _listener = listener
    _relay = relay


def emit(source, name, volume=1.0):
    """Звук игрока: локально с затуханием + (на хосте) в сеть.

    Гость не симулирует, поэтому emit у него не вызывается — он получает
    готовые события и играет их через play_remote.
    """
    x = float(getattr(source, "x", 0.0))
    y = float(getattr(source, "y", 0.0))
    pid = int(getattr(source, "pid", 0) or 0)
    listener = _listener
    if listener is None:
        play_at(name, volume, 0.0)
    else:
        try:
            lx, ly = listener()
        except (TypeError, ValueError):
            lx = ly = None
        if lx is None or ly is None:
            play_at(name, volume, 0.0)
        else:
            gain, pan = spatial(x, y, lx, ly)
            if gain > 0.0:
                play_at(name, volume * gain, pan)
    relay = _relay
    if relay is not None and pid > 0:
        relay(pid, name, x, y, float(volume))


def play_remote(name, x, y, volume=1.0):
    """Звук, пришедший по сети: затухание и панорама — на этом клиенте."""
    listener = _listener
    if listener is None:
        play_at(name, volume, 0.0)
        return
    try:
        lx, ly = listener()
    except (TypeError, ValueError):
        lx = ly = None
    if lx is None or ly is None:
        play_at(name, volume, 0.0)
        return
    gain, pan = spatial(x, y, lx, ly)
    if gain > 0.0:
        play_at(name, volume * gain, pan)


def get_volume():
    return _bank.get_volume()
