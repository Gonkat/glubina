"""
ГЕНЕРАТОР АССЕТОВ:  python assets_gen.py

Создаёт/пересоздаёт содержимое папки assets/:

  assets/sounds/*.wav  — 22 звука, синтезированные кодом ниже
                         (синусы, шум, огибающие — без внешних файлов);
  assets/sprites/*.png — монстры, предметы, герой (рисунки внизу файла);
  assets/sprites/weapons/*.png — стволы: берутся у САМОГО Firearm
                         (_build_proc_sprite), поэтому код рисунка
                         оружия существует в одном экземпляре.

Генератор идемпотентен: запускать можно сколько угодно раз.
После генерации игра грузит файлы из assets/, а при их отсутствии
катится на процедурные фолбэки (см. soundbank.py / spritebank.py).
"""
import math
import os
import random
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spritebank import _FALLBACK_SIZE          # один источник габаритов

ROOT = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(ROOT, "assets", "sounds")
SPRITES_DIR = os.path.join(ROOT, "assets", "sprites")
WEAPONS_DIR = os.path.join(SPRITES_DIR, "weapons")

RATE = 44100                      # частота дискретизации WAV
RNG = random.Random(20261025)     # детерминизм: одинаковые ассеты на всех


# ================================================================ ЗВУКИ
def _n(dur):
    return max(1, int(RATE * dur))


def tone(freq, dur, vol=0.5, end=None, exp_decay=4.0):
    """Синус: freq -> end за dur, экспоненциальная огибающая."""
    n = _n(dur)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / n
        f = freq if end is None else freq + (end - freq) * t
        phase += 2.0 * math.pi * f / RATE
        out.append(vol * math.exp(-exp_decay * t) * math.sin(phase))
    return out


def noise(dur, vol=0.5, bell=False, exp_decay=6.0):
    """Шум: bell=True — «выхлоп» (всплывает и гаснет), иначе затухание."""
    n = _n(dur)
    out = []
    for i in range(n):
        t = i / n
        env = math.sin(math.pi * t) if bell else math.exp(-exp_decay * t)
        out.append(vol * env * RNG.uniform(-1.0, 1.0))
    return out


def place(total, *parts):
    """Слоить сегменты со сдвигом: place(0.3, (seg, 0.0), (seg, 0.15))."""
    out = [0.0] * _n(total)
    for seg, at in parts:
        start = int(at * RATE)
        for i, v in enumerate(seg):
            if start + i < len(out):
                out[start + i] += v
    return out


def mix(*segments):
    """Сложить сегменты (длины могут различаться) с ограничением клиппинга."""
    length = max(len(s) for s in segments)
    out = [0.0] * length
    for seg in segments:
        for i, v in enumerate(seg):
            out[i] += v
    return out


def write_wav(name, samples):
    """16-бит моно WAV."""
    path = os.path.join(SOUNDS_DIR, name + ".wav")
    frames = bytearray()
    for v in samples:
        v = max(-1.0, min(1.0, v))
        frames += int(v * 32767).to_bytes(2, "little", signed=True)
    with open(path, "wb") as f:
        import wave
        with wave.open(f, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(frames))


SOUNDS = {
    # --- бой -------------------------------------------------------------
    "shoot":     lambda: mix(tone(190, 0.05, 0.5), noise(0.045, 0.45)),
    "shotgun":   lambda: mix(noise(0.16, 0.60, exp_decay=18),
                             tone(95, 0.12, 0.5)),
    "sniper":    lambda: mix(noise(0.10, 0.50, exp_decay=30),
                             tone(320, 0.14, 0.35, end=90)),
    "swing":     lambda: noise(0.14, 0.35, bell=True),     # свист веера
    "hit":       lambda: mix(tone(340, 0.05, 0.4), noise(0.04, 0.3)),
    "enemy_die": lambda: mix(tone(420, 0.24, 0.45, end=120),
                             noise(0.18, 0.3)),
    "hurt":      lambda: mix(tone(240, 0.18, 0.5, end=110), noise(0.10, 0.25)),
    "explosion": lambda: mix(noise(0.50, 0.75, exp_decay=7),
                             tone(70, 0.40, 0.55, end=45)),
    "reload":    lambda: place(0.24, (tone(880, 0.03, 0.35), 0.0),
                               (tone(660, 0.04, 0.35), 0.14)),
    "kill":      lambda: mix(tone(300, 0.20, 0.42, end=80),
                             noise(0.14, 0.30, exp_decay=12)),
    "combo":     lambda: place(0.30, (tone(660, 0.08, 0.34), 0.0),
                               (tone(880, 0.08, 0.34), 0.08),
                               (tone(1174, 0.12, 0.34), 0.16)),
    "empty":     lambda: mix(tone(150, 0.045, 0.30), noise(0.03, 0.12)),
    "heartbeat": lambda: place(0.42, (tone(58, 0.10, 0.55, end=44), 0.0),
                               (tone(50, 0.14, 0.42, end=38), 0.15)),
    "boss_roar": lambda: mix(tone(82, 0.85, 0.50, end=48, exp_decay=2.0),
                             noise(0.65, 0.32, bell=True), tone(48, 0.8, 0.35)),
    # --- спуск: маяки, лифт, усиления (M12) ------------------------------
    "beacon_start": lambda: mix(
        place(0.55, (tone(220, 0.10, 0.35), 0.0),
              (tone(330, 0.10, 0.35), 0.10),
              (tone(440, 0.28, 0.32, end=520), 0.20)),
        noise(0.30, 0.10, bell=True)),
    "beacon_done": lambda: place(
        0.75,
        (tone(523, 0.14, 0.34), 0.0),
        (tone(659, 0.14, 0.34), 0.12),
        (tone(784, 0.16, 0.34), 0.24),
        (tone(1046, 0.28, 0.30), 0.38)),
    "lift_open": lambda: mix(
        tone(60, 1.10, 0.42, end=110, exp_decay=2.2),
        place(0.90, (tone(330, 0.10, 0.24), 0.0),
              (tone(440, 0.10, 0.24), 0.14),
              (tone(660, 0.22, 0.24), 0.28)),
        noise(0.70, 0.12, bell=True)),
    "descend": lambda: mix(
        tone(180, 1.20, 0.38, end=42, exp_decay=1.8),
        noise(0.90, 0.16, bell=True),
        place(1.00, (tone(90, 0.35, 0.26, end=60), 0.20),
              (tone(72, 0.45, 0.24, end=48), 0.55))),
    "boon_pick": lambda: place(
        0.62,
        (tone(587, 0.10, 0.32), 0.0),
        (tone(880, 0.10, 0.32), 0.10),
        (tone(1174, 0.14, 0.30), 0.20),
        (tone(1568, 0.24, 0.24), 0.32)),
    "enemy_shot": lambda: mix(
        tone(520, 0.16, 0.30, end=180),
        noise(0.12, 0.26, exp_decay=16)),
    "spit_charge": lambda: mix(
        tone(180, 0.50, 0.20, end=620, exp_decay=1.0),
        noise(0.30, 0.08, bell=True)),
    # --- артефакты / способности -----------------------------------------
    "lightning": lambda: mix(noise(0.28, 0.60, exp_decay=14),
                             tone(1300, 0.22, 0.35, end=260)),
    "dash":      lambda: tone(420, 0.13, 0.4, end=1150),
    "shield":    lambda: tone(500, 0.16, 0.4, end=820),
    # --- предметы и экономика --------------------------------------------
    "coin":      lambda: place(0.16, (tone(988, 0.06, 0.4), 0.0),
                               (tone(1319, 0.09, 0.4), 0.06)),
    "pickup":    lambda: place(0.14, (tone(660, 0.06, 0.35), 0.0),
                               (tone(880, 0.07, 0.35), 0.06)),
    "artifact":  lambda: place(0.34, (tone(523, 0.10, 0.35), 0.0),
                               (tone(784, 0.10, 0.35), 0.10),
                               (tone(1046, 0.14, 0.35), 0.20)),
    "heal":      lambda: place(0.20, (tone(660, 0.09, 0.35), 0.0),
                               (tone(990, 0.10, 0.35), 0.09)),
    "throw":     lambda: tone(520, 0.10, 0.25, end=880),
    "buy":       lambda: place(0.22, (tone(784, 0.09, 0.4), 0.0),
                               (tone(1046, 0.12, 0.4), 0.09)),
    "error":     lambda: tone(220, 0.16, 0.45, end=170),
    # --- интерфейс --------------------------------------------------------
    "ui_move":   lambda: tone(500, 0.035, 0.3),
    "open":      lambda: tone(440, 0.12, 0.35, end=660),
    "close":     lambda: tone(660, 0.12, 0.35, end=440),
    # --- атмосфера --------------------------------------------------------
    "ambient":   lambda: ambient_drone(8.0),
}


def ambient_drone(duration):
    """Бесшовная низкая «гулушка»: частоты кратны длине петли."""
    n = _n(duration)
    out = []
    for i in range(n):
        t = i / RATE
        swell = 0.65 + 0.2 * math.sin(2 * math.pi * 0.125 * t) \
            + 0.1 * math.sin(2 * math.pi * 0.375 * t + 1.1)
        rumble = (0.52 * math.sin(2 * math.pi * 55 * t)
                  + 0.28 * math.sin(2 * math.pi * 82.5 * t)
                  + 0.16 * math.sin(2 * math.pi * 110 * t))
        shimmer = 0.07 * math.sin(2 * math.pi * 220 * t) * \
            (0.5 + 0.5 * math.sin(2 * math.pi * 0.25 * t))
        out.append((rumble * swell * 0.30) + shimmer)
    return out


# ================================================================ СПРАЙТЫ
def surf(side):
    return pygame.Surface((side, side), pygame.SRCALPHA)


def draw_player():
    """Герой: каска, смотрит вправо (angle 0)."""
    s = surf(_FALLBACK_SIZE["player"])
    c = s.get_width() // 2
    pygame.draw.circle(s, (24, 28, 38), (c, c), 18)             # шлем-контур
    pygame.draw.circle(s, (66, 124, 214), (c, c), 16)           # каска
    pygame.draw.circle(s, (108, 166, 242), (c - 4, c - 5), 10)  # блик
    pygame.draw.circle(s, (236, 242, 250), (c + 7, c), 6)       # визор
    pygame.draw.circle(s, (32, 44, 66), (c + 9, c), 3)          # зрачок
    pygame.draw.circle(s, (24, 28, 38), (c, c), 16, 2)
    return s


def draw_enemy():
    """Базовый мотылёк: жёлтые глаза вправо, усики."""
    s = surf(_FALLBACK_SIZE["enemy"])
    c = s.get_width() // 2
    pygame.draw.ellipse(s, (128, 92, 150), (c - 14, c - 6, 12, 14))  # крыло
    pygame.draw.circle(s, (24, 22, 30), (c, c), 20)
    pygame.draw.circle(s, (150, 110, 170), (c, c), 18)
    pygame.draw.circle(s, (24, 22, 30), (c, c), 18, 2)
    for side in (-1, 1):                                            # глаза вправо
        pygame.draw.circle(s, (245, 214, 74), (c + 9, c + side * 7), 5)
        pygame.draw.circle(s, (30, 26, 18), (c + 11, c + side * 7), 2)
    pygame.draw.line(s, (60, 50, 70), (c + 6, c - 14), (c + 16, c - 20), 2)
    pygame.draw.line(s, (60, 50, 70), (c + 6, c + 14), (c + 16, c + 20), 2)
    return s


def draw_runner():
    """Быстрый: заострённый хвост-шипы назад, один глаз."""
    s = surf(_FALLBACK_SIZE["runner"])
    c = s.get_width() // 2
    for dy in (-8, 0, 8):                                          # шипы назад
        pygame.draw.polygon(s, (96, 150, 54),
                            [(c - 8, c + dy), (c - 20, c + dy - 4),
                             (c - 20, c + dy + 4)])
    pygame.draw.circle(s, (24, 30, 20), (c, c), 14)
    pygame.draw.circle(s, (140, 200, 80), (c, c), 12)
    pygame.draw.circle(s, (24, 30, 20), (c, c), 12, 2)
    pygame.draw.circle(s, (255, 110, 90), (c + 5, c), 4)           # глаз-цель
    return s


def draw_tank():
    """Танк: панцирь из плит, заклёпки, суровые глаза."""
    s = surf(_FALLBACK_SIZE["tank"])
    c = s.get_width() // 2
    pygame.draw.circle(s, (30, 34, 42), (c, c), 34)
    pygame.draw.circle(s, (110, 120, 135), (c, c), 31)
    for i in range(6):                                             # плиты панциря
        a0 = i * 60 + 8
        pygame.draw.arc(s, (70, 78, 92), (c - 31, c - 31, 62, 62),
                        math.radians(a0), math.radians(a0 + 44), 7)
    for i in range(6):                                             # заклёпки
        a = math.radians(i * 60 + 30)
        pygame.draw.circle(s, (158, 168, 182),
                           (int(c + math.cos(a) * 24),
                            int(c + math.sin(a) * 24)), 3)
    pygame.draw.circle(s, (245, 200, 74), (c + 14, c - 7), 5)
    pygame.draw.circle(s, (245, 200, 74), (c + 14, c + 7), 5)
    pygame.draw.circle(s, (30, 26, 18), (c + 16, c - 7), 2)
    pygame.draw.circle(s, (30, 26, 18), (c + 16, c + 7), 2)
    return s


def draw_bomber():
    """Бомбер: оранжевый, злые глаза, фитиль сверху."""
    s = surf(_FALLBACK_SIZE["bomber"])
    c = s.get_width() // 2
    pygame.draw.circle(s, (40, 30, 18), (c, c), 19)
    pygame.draw.circle(s, (196, 108, 40), (c, c), 17)
    pygame.draw.circle(s, (232, 150, 70), (c - 4, c - 5), 10)      # блик
    pygame.draw.circle(s, (40, 30, 18), (c, c), 17, 2)
    pygame.draw.line(s, (90, 70, 40), (c + 2, c - 16), (c + 8, c - 22), 3)
    pygame.draw.circle(s, (255, 214, 90), (c + 8, c - 23), 4)       # искра фитиля
    pygame.draw.line(s, (30, 24, 16), (c + 4, c - 4), (c + 13, c - 8), 3)
    pygame.draw.line(s, (30, 24, 16), (c + 4, c + 6), (c + 13, c + 10), 3)
    return s


def draw_coin():
    s = surf(_FALLBACK_SIZE["coin"])
    c = s.get_width() // 2
    pygame.draw.circle(s, (150, 112, 26), (c, c), 9)
    pygame.draw.circle(s, (235, 196, 62), (c, c), 8)
    pygame.draw.circle(s, (255, 236, 150), (c - 2, c - 3), 3)
    pygame.draw.line(s, (150, 112, 26), (c - 3, c), (c + 3, c), 2)
    return s


def draw_ammo():
    s = surf(_FALLBACK_SIZE["ammo"])
    c = s.get_width() // 2
    pygame.draw.rect(s, (58, 46, 30), (c - 8, c - 2, 16, 10), border_radius=2)
    pygame.draw.rect(s, (104, 82, 48), (c - 7, c - 1, 14, 8), border_radius=2)
    pygame.draw.ellipse(s, (214, 174, 92), (c - 5, c - 8, 10, 7))   # гильза сверху
    pygame.draw.circle(s, (238, 208, 130), (c, c - 6), 3)
    return s


def draw_grenade():
    s = surf(_FALLBACK_SIZE["grenade"])
    c = s.get_width() // 2
    pygame.draw.circle(s, (26, 34, 24), (c, c + 2), 9)
    pygame.draw.circle(s, (74, 96, 66), (c, c + 2), 8)
    pygame.draw.rect(s, (140, 144, 150), (c - 3, c - 11, 6, 5))     # горлышко
    pygame.draw.line(s, (170, 174, 180), (c + 3, c - 9), (c + 8, c - 4), 2)
    return s


def draw_medkit():
    s = surf(_FALLBACK_SIZE["medkit"])
    c = s.get_width() // 2
    box = pygame.Rect(c - 10, c - 8, 20, 16)
    pygame.draw.rect(s, (96, 96, 106), box, border_radius=3)
    pygame.draw.rect(s, (236, 236, 240), box.inflate(-4, -4),
                     border_radius=2)
    pygame.draw.line(s, (214, 60, 60), (c - 5, c), (c + 5, c), 4)
    pygame.draw.line(s, (214, 60, 60), (c, c - 5), (c, c + 5), 4)
    return s


def draw_artifact():
    s = surf(_FALLBACK_SIZE["artifact"])
    c = s.get_width() // 2
    pts = [(c, c - 13), (c + 11, c), (c, c + 13), (c - 11, c)]
    pygame.draw.polygon(s, (96, 52, 150), pts)
    pygame.draw.polygon(s, (196, 122, 255), pts, 3)
    pygame.draw.polygon(s, (238, 216, 255),
                        [(c, c - 6), (c + 4, c), (c, c + 2), (c - 4, c)])
    return s


def draw_broom():
    """Метка-боевая метла: деревянный черенок и хорошо читаемая щетина."""
    surface = pygame.Surface((72, 36), pygame.SRCALPHA)
    dark_wood = (78, 52, 34)
    wood = (178, 126, 67)
    wood_light = (226, 178, 100)
    bristle_dark = (94, 66, 39)
    bristle = (178, 137, 77)
    bristle_light = (224, 185, 112)

    pygame.draw.line(surface, dark_wood, (5, 31), (49, 5), 7)
    pygame.draw.line(surface, wood, (6, 29), (48, 5), 4)
    pygame.draw.line(surface, wood_light, (9, 27), (45, 7), 1)
    pygame.draw.polygon(surface, bristle_dark, [
        (45, 4), (54, 2), (67, 13), (68, 20), (62, 28), (54, 23), (46, 9)
    ])
    pygame.draw.polygon(surface, bristle, [
        (47, 5), (54, 5), (64, 14), (65, 19), (61, 24), (55, 20), (48, 9)
    ])
    for start, end in (
        ((49, 7), (58, 22)), ((51, 6), (61, 23)), ((53, 5), (64, 20)),
        ((55, 6), (66, 17)), ((48, 9), (57, 24)), ((52, 8), (62, 25)),
    ):
        pygame.draw.line(surface, bristle_light, start, end, 1)
    pygame.draw.line(surface, (112, 75, 43), (46, 7), (53, 4), 2)
    return surface


SPRITE_BUILDERS = {
    "player": draw_player, "enemy": draw_enemy, "runner": draw_runner,
    "tank": draw_tank, "bomber": draw_bomber, "coin": draw_coin,
    "ammo": draw_ammo, "grenade": draw_grenade, "medkit": draw_medkit,
    "artifact": draw_artifact,
}


# ================================================================ ТОЧКА ВХОДА
def main(overwrite=False):
    pygame.init()
    for path in (SOUNDS_DIR, SPRITES_DIR, WEAPONS_DIR):
        os.makedirs(path, exist_ok=True)

    # звуки
    for name, builder in SOUNDS.items():
        if overwrite or not os.path.isfile(os.path.join(SOUNDS_DIR, name + ".wav")):
            write_wav(name, builder())
    print(f"sounds: {len(SOUNDS)} wav -> {SOUNDS_DIR}")

    # монстры и предметы
    for name, builder in SPRITE_BUILDERS.items():
        target = os.path.join(SPRITES_DIR, name + ".png")
        if overwrite or not os.path.isfile(target):
            pygame.image.save(builder(), target)
    print(f"sprites: {len(SPRITE_BUILDERS)} png -> {SPRITES_DIR}")

    # оружие — спрайт берём у самой игры (один источник рисунка)
    from weapon_data import FIREARMS
    from weapons import Firearm
    for key, spec in FIREARMS.items():
        gun = Firearm(key, spec)
        target = os.path.join(WEAPONS_DIR, key + ".png")
        if overwrite or not os.path.isfile(target):
            pygame.image.save(gun._build_proc_sprite(), target)
    broom_target = os.path.join(WEAPONS_DIR, "shovel.png")
    if overwrite or not os.path.isfile(broom_target):
        pygame.image.save(draw_broom(), broom_target)
    print(f"weapons: {len(FIREARMS)} png -> {WEAPONS_DIR}")
    print("assets готовы.")


if __name__ == "__main__":
    main(overwrite="--overwrite" in sys.argv)
