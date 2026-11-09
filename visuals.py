"""
Процедурная графика: силуэты героя, врагов и мелкие помощники отрисовки.

Зачем отдельный модуль:
  * все персонажи рисуются в одном месте и в одном стиле;
  * вид кэшируется по (тип, радиус, угол) — 60 врагов не перерисовываются
    десятками примитивов каждый кадр;
  * исходные PNG в assets/sprites остаются нетронутыми: код рисует
    собственные читаемые силуэты, а заменяемый спрайт-банк продолжает
    работать для предметов и оружия.

Стиль: тёмный индустриальный мир, холодные бирюзовые тени и тёплый
золотой свет игрока. Враги отличаются формой, а не только цветом.
"""
import math

import pygame

# ------------------------------------------------------------------ ПАЛИТРА
INK = (10, 13, 22)
INK_SOFT = (22, 27, 42)
STEEL = (78, 92, 116)
STEEL_LIGHT = (146, 166, 194)
TEAL = (72, 208, 196)
TEAL_DARK = (30, 118, 116)
GOLD = (255, 206, 116)
GOLD_DIM = (176, 132, 62)
BLOOD = (198, 66, 78)
PAPER = (236, 242, 250)

_CHAR_CACHE = {}
_ROT_CACHE = {}
_SHADOWS = {}
_GLOWS = {}
_FONTS = {}
_FONT_PATH = "?"


def _font_path():
    """Один системный шрифт с кириллицей на весь интерфейс."""
    global _FONT_PATH
    if _FONT_PATH == "?":
        _FONT_PATH = None
        for name in ("bahnschrift", "segoeui", "verdana", "dejavusans"):
            path = pygame.font.match_font(name)
            if path:
                _FONT_PATH = path
                break
    return _FONT_PATH


def font(size):
    """Шрифт по размеру — создаётся один раз."""
    key = max(8, int(size))
    if key not in _FONTS:
        path = _font_path()
        _FONTS[key] = (pygame.font.Font(path, key) if path
                       else pygame.font.Font(None, key))
    return _FONTS[key]


# ------------------------------------------------------------------ УТИЛИТЫ
def _p(cx, cy, u, x, y):
    return (cx + x * u, cy + y * u)


def _rot(x, y, angle):
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


def _circle(surf, color, cx, cy, u, x, y, r):
    pygame.draw.circle(surf, color, (int(cx + x * u), int(cy + y * u)),
                       max(1, int(r * u)))


def _ellipse(surf, color, cx, cy, u, x, y, rx, ry):
    rect = pygame.Rect(0, 0, max(1, int(rx * u * 2)), max(1, int(ry * u * 2)))
    rect.center = (int(cx + x * u), int(cy + y * u))
    pygame.draw.ellipse(surf, color, rect)


def _line(surf, color, cx, cy, u, x1, y1, x2, y2, width):
    pygame.draw.line(surf, color,
                     (int(cx + x1 * u), int(cy + y1 * u)),
                     (int(cx + x2 * u), int(cy + y2 * u)),
                     max(1, int(width * u)))


def _poly(surf, color, cx, cy, u, points):
    pygame.draw.polygon(surf, color,
                        [(int(cx + x * u), int(cy + y * u)) for x, y in points])


# ------------------------------------------------------------------ ТЕНИ / СВЕТ
def shadow(screen, sx, sy, radius, strength=1.0, squash=0.48):
    """Мягкая эллиптическая тень под персонажем (кэшируется по размеру)."""
    w = max(8, int(radius * 2.1))
    h = max(5, int(radius * 2.1 * squash))
    key = (w, h)
    surf = _SHADOWS.get(key)
    if surf is None:
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        steps = 5
        for i in range(steps, 0, -1):
            t = i / steps
            rect = pygame.Rect(0, 0, int(w * t), int(h * t))
            rect.center = (w // 2, h // 2)
            pygame.draw.ellipse(surf, (4, 6, 12, int(80 * (1.0 - t) ** 0.7 + 28)),
                                rect)
        _SHADOWS[key] = surf
    alpha = max(0.0, min(1.0, strength))
    if alpha < 1.0:
        ghost = surf.copy()
        ghost.fill((255, 255, 255, int(255 * alpha)), special_flags=pygame.BLEND_RGBA_MULT)
        screen.blit(ghost, ghost.get_rect(center=(int(sx), int(sy))))
    else:
        screen.blit(surf, surf.get_rect(center=(int(sx), int(sy))))


def glow(screen, x, y, radius, color, alpha=110):
    """Мягкий аддитивный ореол — дешёвая альтернатива настоящему bloom.

    Поверхность непрозрачная и чёрная снаружи: BLEND_RGB_ADD добавляет
    ровно столько света, сколько нужно, не заливая фон цветной кляксой.
    """
    key = (max(4, int(radius)), tuple(color), int(alpha))
    surf = _GLOWS.get(key)
    if surf is None:
        surf = pygame.Surface((radius * 2, radius * 2))
        surf.fill((0, 0, 0))
        steps = 10
        for i in range(steps, 0, -1):
            t = i / steps
            strength = (1.0 - t) ** 1.8 * (alpha / 255.0)
            value = tuple(min(255, int(c * strength)) for c in color)
            pygame.draw.circle(surf, value, (radius, radius), max(1, int(radius * t)))
        _GLOWS[key] = surf
    screen.blit(surf, (int(x - radius), int(y - radius)),
                special_flags=pygame.BLEND_RGB_ADD)


# ------------------------------------------------------------------ БАРЫ / ТЕКСТ
def bar(screen, rect, ratio, color, back=(18, 21, 30), border=None, segments=0):
    """Полоса со скруглением и опциональными сегментами."""
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(screen, back, rect, border_radius=rect.height // 2)
    if ratio > 0:
        inner = pygame.Rect(rect.x, rect.y, max(1, int(rect.w * ratio)), rect.h)
        pygame.draw.rect(screen, color, inner, border_radius=rect.height // 2)
        shine = pygame.Rect(inner.x + 2, inner.y + 2,
                            max(0, inner.w - 4), max(1, inner.h // 3))
        if shine.w > 2:
            pygame.draw.rect(screen, tuple(min(255, c + 38) for c in color),
                             shine, border_radius=max(1, shine.h // 2))
    if segments > 1:
        for i in range(1, segments):
            x = rect.x + rect.w * i / segments
            pygame.draw.line(screen, back, (x, rect.y + 1), (x, rect.bottom - 1), 2)
    if border:
        pygame.draw.rect(screen, border, rect, 1, border_radius=rect.height // 2)


def text(screen, value, pos, size=22, color=PAPER, align="left", shadow=True):
    """Текст с короткой тенью — читается поверх тёмного мира."""
    image = font(size).render(str(value), True, color)
    x, y = pos
    if align == "center":
        x -= image.get_width() // 2
    elif align == "right":
        x -= image.get_width()
    if shadow:
        dark = font(size).render(str(value), True, (4, 6, 10))
        screen.blit(dark, (x + 1, y + 2))
    screen.blit(image, (x, y))
    return image.get_size()


def text_width(value, size=22):
    return font(size).size(str(value))[0]


def key_badge(screen, label, x, y, color=GOLD, size=18, align="left"):
    """Клавиша в рамке: [E] — открыть."""
    w, h = font(size).size(label)
    pad = 6
    rect = pygame.Rect(x, y, w + pad * 2, h + 4)
    if align == "center":
        rect.x -= rect.w // 2
    elif align == "right":
        rect.x -= rect.w
    pygame.draw.rect(screen, (20, 24, 34), rect, border_radius=4)
    pygame.draw.rect(screen, color, rect, 1, border_radius=4)
    screen.blit(font(size).render(label, True, color), (rect.x + pad, rect.y + 2))
    return rect.w


# ------------------------------------------------------------------ ПЕРСОНАЖИ
def _build_player(surf, c, u):
    # плащ позади корпуса
    _poly(surf, (18, 27, 44), c, c, u, [
        (-0.35, -0.95), (-1.55, -1.30), (-1.95, 0.0),
        (-1.55, 1.30), (-0.35, 0.95),
    ])
    _poly(surf, (34, 54, 76), c, c, u, [
        (-0.30, -0.72), (-1.40, -1.02), (-1.62, 0.0),
        (-1.40, 1.02), (-0.30, 0.72),
    ])
    # ноги
    _ellipse(surf, (23, 31, 45), c, c, u, -0.35, -0.62, 0.34, 0.22)
    _ellipse(surf, (23, 31, 45), c, c, u, -0.35, 0.62, 0.34, 0.22)
    _ellipse(surf, (78, 110, 122), c, c, u, -0.26, -0.64, 0.18, 0.12)
    _ellipse(surf, (78, 110, 122), c, c, u, -0.26, 0.64, 0.18, 0.12)
    # корпус
    _circle(surf, (12, 18, 28), c, c, u, -0.02, 0.0, 0.95)
    _circle(surf, (44, 108, 118), c, c, u, -0.02, 0.0, 0.84)
    _circle(surf, (72, 158, 162), c, c, u, -0.12, -0.18, 0.55)
    # нагрудная пластина
    _poly(surf, (32, 74, 86), c, c, u, [
        (-0.10, -0.48), (0.42, -0.24), (0.45, 0.24), (-0.10, 0.48),
    ])
    _line(surf, TEAL, c, c, u, -0.05, 0.0, 0.38, 0.0, 0.07)
    # наплечники (небольшие — не должны читаться как вторые глаза)
    _circle(surf, (16, 24, 36), c, c, u, -0.02, -0.86, 0.36)
    _circle(surf, (16, 24, 36), c, c, u, -0.02, 0.86, 0.36)
    _circle(surf, (75, 112, 132), c, c, u, 0.0, -0.86, 0.25)
    _circle(surf, (75, 112, 132), c, c, u, 0.0, 0.86, 0.25)
    # шлем и визор: голова выдвинута вперёд, чтобы направление читалось
    _circle(surf, (11, 16, 25), c, c, u, 0.70, 0.0, 0.68)
    _circle(surf, (48, 74, 92), c, c, u, 0.72, 0.0, 0.58)
    _poly(surf, (58, 96, 112), c, c, u, [
        (0.55, -0.48), (1.05, -0.20), (1.10, 0.0), (0.55, 0.48),
    ])
    _ellipse(surf, (12, 18, 28), c, c, u, 1.00, 0.0, 0.22, 0.32)
    _ellipse(surf, GOLD, c, c, u, 1.04, 0.0, 0.16, 0.25)
    _ellipse(surf, (255, 244, 200), c, c, u, 1.08, 0.0, 0.07, 0.13)
    # шарф, уходящий назад
    _poly(surf, (24, 142, 138), c, c, u, [
        (0.28, -0.18), (-0.70, -0.55), (-1.05, -0.20), (-0.55, -0.02),
    ])
    _poly(surf, (20, 102, 104), c, c, u, [
        (0.20, 0.15), (-0.82, 0.62), (-1.18, 0.30), (-0.55, 0.06),
    ])
    # кисти к оружию
    _circle(surf, (14, 20, 30), c, c, u, 0.46, -0.52, 0.23)
    _circle(surf, (14, 20, 30), c, c, u, 0.46, 0.52, 0.23)
    # контур
    pygame.draw.circle(surf, (8, 12, 20), (int(c), int(c)), max(1, int(0.93 * u)), 2)
    pygame.draw.circle(surf, (130, 210, 205), (int(c), int(c)), max(1, int(0.93 * u)), 1)


def _legs(surf, c, u, color, count=3, length=1.42, width=0.15):
    for side in (-1, 1):
        for i in range(count):
            x = -0.62 + i * 0.30
            y0 = side * 0.88
            knee_x = x - 0.12
            knee_y = side * (length * 0.62)
            tip_x = x - 0.28
            tip_y = side * length
            _line(surf, color, c, c, u, x, y0, knee_x, knee_y, width)
            _line(surf, color, c, c, u, knee_x, knee_y, tip_x, tip_y, width * 0.8)
            _circle(surf, color, c, c, u, tip_x, tip_y, width * 1.1)


def _build_crawler(surf, c, u):
    _legs(surf, c, u, (32, 18, 26), count=3, length=1.28)
    _circle(surf, (24, 14, 22), c, c, u, 0.0, 0.0, 1.02)
    _circle(surf, (168, 58, 72), c, c, u, 0.0, 0.0, 0.90)
    _circle(surf, (208, 92, 96), c, c, u, -0.12, -0.18, 0.52)
    # сегменты панциря
    for i in range(3):
        pygame.draw.arc(surf, (94, 30, 44),
                        pygame.Rect(int(c - 0.9 * u), int(c - 0.9 * u),
                                    int(1.8 * u), int(1.8 * u)),
                        math.radians(140 + i * 26), math.radians(220 + i * 26),
                        max(1, int(0.08 * u)))
    # глаза вперёд
    for side in (-1, 1):
        _ellipse(surf, (30, 18, 22), c, c, u, 0.58, side * 0.34, 0.24, 0.20)
        _ellipse(surf, (255, 204, 92), c, c, u, 0.62, side * 0.34, 0.15, 0.13)
        _ellipse(surf, (255, 248, 210), c, c, u, 0.66, side * 0.34, 0.05, 0.06)
    # жвала
    _poly(surf, (42, 22, 28), c, c, u, [(0.82, -0.26), (1.20, -0.12), (0.86, -0.02)])
    _poly(surf, (42, 22, 28), c, c, u, [(0.82, 0.26), (1.20, 0.12), (0.86, 0.02)])


def _build_runner(surf, c, u):
    # шипы-хвост
    for i, dy in enumerate((-0.55, 0.0, 0.55)):
        _poly(surf, (70, 42, 20), c, c, u, [
            (-0.78, dy * 0.7), (-1.55, dy - 0.12), (-1.20, dy + 0.18),
        ])
    _legs(surf, c, u, (52, 30, 18), count=2, length=1.20)
    _ellipse(surf, (26, 17, 12), c, c, u, 0.0, 0.0, 1.04, 0.72)
    _ellipse(surf, (210, 132, 54), c, c, u, 0.0, 0.0, 0.92, 0.61)
    _ellipse(surf, (246, 178, 98), c, c, u, -0.10, 0.0, 0.58, 0.33)
    _circle(surf, (24, 15, 12), c, c, u, 0.55, 0.0, 0.26)
    _circle(surf, (255, 226, 140), c, c, u, 0.58, 0.0, 0.15)
    _circle(surf, (40, 18, 10), c, c, u, 0.60, 0.0, 0.06)
    _poly(surf, (255, 235, 190), c, c, u, [(0.78, -0.12), (1.10, 0.0), (0.78, 0.12)])


def _build_tank(surf, c, u):
    _legs(surf, c, u, (28, 26, 42), count=2, length=1.22, width=0.22)
    # шестигранный панцирь
    pts = [(math.cos(math.radians(a)) * 1.08, math.sin(math.radians(a)) * 1.08)
           for a in range(0, 360, 60)]
    _poly(surf, (22, 22, 36), c, c, u, [(x * 1.08, y * 1.08) for x, y in pts])
    _poly(surf, (88, 82, 132), c, c, u, pts)
    inner = [(x * 0.82, y * 0.82) for x, y in pts]
    _poly(surf, (116, 108, 158), c, c, u, inner)
    for i in range(6):
        a = math.radians(i * 60 + 30)
        _circle(surf, (176, 184, 204), c, c, u, math.cos(a) * 0.84, math.sin(a) * 0.84, 0.08)
    _circle(surf, (46, 44, 70), c, c, u, 0.35, 0.0, 0.52)
    _circle(surf, (142, 138, 176), c, c, u, 0.35, 0.0, 0.40)
    for side in (-1, 1):
        _ellipse(surf, (26, 24, 38), c, c, u, 0.66, side * 0.26, 0.18, 0.16)
        _ellipse(surf, (255, 200, 86), c, c, u, 0.70, side * 0.26, 0.10, 0.09)


def _build_bomber(surf, c, u):
    _legs(surf, c, u, (50, 28, 16), count=2, length=1.05, width=0.14)
    _circle(surf, (34, 20, 12), c, c, u, 0.0, 0.0, 1.02)
    _circle(surf, (212, 104, 46), c, c, u, 0.0, 0.0, 0.92)
    _circle(surf, (246, 148, 70), c, c, u, -0.14, -0.20, 0.55)
    # фитиль
    _line(surf, (92, 72, 40), c, c, u, 0.12, -0.80, 0.38, -1.28, 0.12)
    _circle(surf, (255, 226, 120), c, c, u, 0.40, -1.30, 0.16)
    _circle(surf, (255, 255, 220), c, c, u, 0.40, -1.30, 0.07)
    # злая физиономия
    _line(surf, (42, 24, 16), c, c, u, 0.40, -0.30, 0.66, -0.18, 0.10)
    _line(surf, (42, 24, 16), c, c, u, 0.40, 0.30, 0.66, 0.18, 0.10)
    _ellipse(surf, (255, 214, 100), c, c, u, 0.58, -0.34, 0.12, 0.10)
    _ellipse(surf, (255, 214, 100), c, c, u, 0.58, 0.34, 0.12, 0.10)
    _poly(surf, (56, 30, 18), c, c, u, [(0.70, 0.0), (1.02, 0.16), (0.94, -0.10)])


def _build_stalker(surf, c, u):
    _legs(surf, c, u, (48, 18, 34), count=3, length=1.35, width=0.11)
    # клинки вперёд
    for side in (-1, 1):
        _poly(surf, (236, 210, 228), c, c, u, [
            (0.42, side * 0.48), (1.65, side * 0.20), (0.65, side * 0.74),
        ])
    _ellipse(surf, (32, 14, 26), c, c, u, 0.0, 0.0, 1.02, 0.66)
    _ellipse(surf, (196, 60, 118), c, c, u, 0.0, 0.0, 0.90, 0.55)
    _ellipse(surf, (238, 108, 156), c, c, u, -0.06, 0.0, 0.52, 0.30)
    for side in (-1, 1):
        _ellipse(surf, (28, 12, 22), c, c, u, 0.54, side * 0.24, 0.22, 0.16)
        _ellipse(surf, (255, 190, 232), c, c, u, 0.58, side * 0.24, 0.12, 0.10)
    _poly(surf, (255, 226, 242), c, c, u, [(0.76, 0.0), (1.02, 0.10), (1.02, -0.10)])


def _build_spitter(surf, c, u):
    # тонкие лапы и «мешок» с кислотой — силуэт издалека читается
    _legs(surf, c, u, (22, 40, 38), count=3, length=1.30, width=0.10)
    for i, dy in enumerate((-0.55, -0.15, 0.25, 0.62)):
        _poly(surf, (36, 66, 58), c, c, u, [
            (-0.70, dy * 0.8), (-1.28, dy - 0.10), (-1.02, dy + 0.12),
        ])
    _ellipse(surf, (18, 30, 30), c, c, u, 0.0, 0.0, 1.04, 0.68)
    _ellipse(surf, (72, 160, 128), c, c, u, 0.0, 0.0, 0.92, 0.58)
    # кислотный мешок на спине
    _circle(surf, (30, 54, 42), c, c, u, -0.16, 0.0, 0.52)
    _circle(surf, (146, 238, 154), c, c, u, -0.16, 0.0, 0.42)
    _circle(surf, (214, 255, 198), c, c, u, -0.24, -0.10, 0.18)
    # голова и «сопло»
    _circle(surf, (18, 28, 26), c, c, u, 0.58, 0.0, 0.34)
    _circle(surf, (88, 196, 150), c, c, u, 0.60, 0.0, 0.26)
    _poly(surf, (42, 74, 58), c, c, u, [
        (0.72, -0.20), (1.42, -0.08), (1.42, 0.08), (0.72, 0.20),
    ])
    _ellipse(surf, (206, 255, 190), c, c, u, 1.40, 0.0, 0.08, 0.07)
    for side in (-1, 1):
        _ellipse(surf, (255, 244, 168), c, c, u, 0.64, side * 0.20, 0.10, 0.09)
    _poly(surf, (150, 238, 158), c, c, u, [
        (0.82, -0.16), (1.06, 0.0), (0.82, 0.16),
    ])


def _build_brute(surf, c, u):
    _legs(surf, c, u, (34, 16, 14), count=2, length=1.28, width=0.26)
    _circle(surf, (28, 16, 14), c, c, u, -0.05, 0.0, 1.15)
    _circle(surf, (132, 58, 52), c, c, u, -0.05, 0.0, 1.02)
    # нагрудные пластины
    _poly(surf, (166, 84, 70), c, c, u, [
        (-0.05, -0.82), (0.55, -0.34), (0.55, 0.34), (-0.05, 0.82),
    ])
    # кулаки
    _circle(surf, (24, 14, 12), c, c, u, 0.28, -1.02, 0.48)
    _circle(surf, (24, 14, 12), c, c, u, 0.28, 1.02, 0.48)
    _circle(surf, (118, 58, 52), c, c, u, 0.28, -1.02, 0.34)
    _circle(surf, (118, 58, 52), c, c, u, 0.28, 1.02, 0.34)
    # рога
    _poly(surf, (222, 196, 164), c, c, u, [(0.38, -0.72), (0.70, -1.25), (0.78, -0.58)])
    _poly(surf, (222, 196, 164), c, c, u, [(0.38, 0.72), (0.70, 1.25), (0.78, 0.58)])
    for side in (-1, 1):
        _ellipse(surf, (26, 15, 13), c, c, u, 0.66, side * 0.28, 0.20, 0.16)
        _ellipse(surf, (255, 188, 92), c, c, u, 0.70, side * 0.28, 0.11, 0.10)


def _build_warden(surf, c, u):
    _legs(surf, c, u, (36, 34, 30), count=2, length=1.18, width=0.30)
    for i, (x, y, rr) in enumerate(((-0.35, 0.0, 1.12), (0.15, -0.55, 0.62),
                                   (0.15, 0.55, 0.62), (0.40, 0.0, 0.72))):
        _circle(surf, (40, 38, 34), c, c, u, x, y, rr + 0.07)
        _circle(surf, (128, 120, 100), c, c, u, x, y, rr)
    for i in range(4):
        a = math.radians(35 + i * 90)
        _line(surf, (72, 68, 58), c, c, u,
              math.cos(a) * 0.25, math.sin(a) * 0.25,
              math.cos(a) * 1.0, math.sin(a) * 1.0, 0.09)
    _circle(surf, (70, 208, 172), c, c, u, 0.52, 0.0, 0.20)
    _circle(surf, (200, 255, 226), c, c, u, 0.52, 0.0, 0.10)


def _build_reaper(surf, c, u):
    # космический плащ
    _poly(surf, (28, 14, 40), c, c, u, [
        (0.55, -1.0), (-1.55, -1.25), (-1.95, 0.0),
        (-1.55, 1.25), (0.55, 1.0),
    ])
    _poly(surf, (58, 24, 78), c, c, u, [
        (0.50, -0.82), (-0.95, -0.95), (-1.20, 0.0),
        (-0.95, 0.95), (0.50, 0.82),
    ])
    _circle(surf, (20, 10, 28), c, c, u, 0.55, 0.0, 0.62)
    _circle(surf, (62, 28, 78), c, c, u, 0.55, 0.0, 0.52)
    for side in (-1, 1):
        _ellipse(surf, (255, 116, 212), c, c, u, 0.72, side * 0.24, 0.14, 0.11)
    # коса
    _line(surf, (94, 94, 112), c, c, u, 0.2, 0.9, 0.5, -1.25, 0.12)
    _poly(surf, (184, 224, 226), c, c, u, [(0.5, -1.25), (1.5, -1.0), (0.62, -0.72)])


def _build_overlord(surf, c, u):
    _legs(surf, c, u, (52, 26, 14), count=2, length=1.15, width=0.28)
    _circle(surf, (40, 22, 14), c, c, u, 0.0, 0.0, 1.15)
    _circle(surf, (168, 82, 40), c, c, u, 0.0, 0.0, 1.02)
    for side in (-1, 1):
        _poly(surf, (74, 52, 40), c, c, u, [
            (-0.4, side * 1.0), (0.2, side * 1.35), (0.55, side * 0.9),
        ])
    # топка
    _circle(surf, (70, 30, 16), c, c, u, -0.1, 0.0, 0.55)
    _circle(surf, (255, 144, 54), c, c, u, -0.1, 0.0, 0.42)
    _circle(surf, (255, 230, 150), c, c, u, -0.1, 0.0, 0.22)
    for i in range(6):
        a = math.radians(i * 60)
        _circle(surf, (40, 24, 16), c, c, u, math.cos(a) * 0.82, math.sin(a) * 0.82, 0.14)
    _ellipse(surf, (20, 12, 10), c, c, u, 0.70, 0.0, 0.22, 0.36)
    _ellipse(surf, (255, 120, 60), c, c, u, 0.74, 0.0, 0.12, 0.22)


_BUILDERS = {
    "player": _build_player,
    "enemy": _build_crawler,
    "runner": _build_runner,
    "tank": _build_tank,
    "bomber": _build_bomber,
    "stalker": _build_stalker,
    "spitter": _build_spitter,
    "brute": _build_brute,
    "boss/warden": _build_warden,
    "boss/reaper": _build_reaper,
    "boss/overlord": _build_overlord,
}


def base_sprite(kind, radius):
    """Базовый спрайт «лицом вправо», сглаженный до игрового размера."""
    radius = max(10, int(radius))
    key = (kind, radius)
    cached = _CHAR_CACHE.get(key)
    if cached is not None:
        return cached
    builder = _BUILDERS.get(kind, _build_crawler)
    final = max(40, int(radius * 4.2))
    scale = 3
    surf = pygame.Surface((final * scale, final * scale), pygame.SRCALPHA)
    c = surf.get_width() / 2
    builder(surf, c, radius * scale)
    surf = pygame.transform.smoothscale(surf, (final, final))
    if len(_CHAR_CACHE) > 24:
        _CHAR_CACHE.clear()
    _CHAR_CACHE[key] = surf
    return surf


def character(kind, radius, angle):
    """Повёрнутый силуэт (кэш по 4°), готовый к blit по центру."""
    deg = int(round(math.degrees(angle) / 4) * 4) % 360
    key = (kind, int(radius), deg)
    cached = _ROT_CACHE.get(key)
    if cached is None:
        base = base_sprite(kind, radius)
        cached = pygame.transform.rotate(base, -deg)
        if len(_ROT_CACHE) > 1800:
            _ROT_CACHE.clear()
        _ROT_CACHE[key] = cached
    return cached


def draw_hit_flash(screen, sx, sy, radius, alpha):
    """Белая вспышка по силуэту при получении урона."""
    t = max(0.0, min(1.0, alpha))
    surf = pygame.Surface((int(radius * 2.2), int(radius * 2.2)), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 250, 240, int(150 * t)),
                       (surf.get_width() // 2, surf.get_height() // 2),
                       int(radius * 0.95))
    screen.blit(surf, surf.get_rect(center=(int(sx), int(sy))))


def draw_ring(screen, sx, sy, radius, color, width=2, alpha=255):
    if alpha >= 255:
        pygame.draw.circle(screen, color, (int(sx), int(sy)), int(radius), width)
        return
    surf = pygame.Surface((int(radius * 2 + 4), int(radius * 2 + 4)), pygame.SRCALPHA)
    pygame.draw.circle(surf, (*color, int(alpha)), (int(radius + 2), int(radius + 2)),
                       int(radius), width)
    screen.blit(surf, surf.get_rect(center=(int(sx), int(sy))))


def arrow(screen, x, y, angle, size, color, width=3):
    """Стрелка-указатель в мировых/экранных координатах."""
    tip = (x + math.cos(angle) * size, y + math.sin(angle) * size)
    back = (x - math.cos(angle) * size * 0.55, y - math.sin(angle) * size * 0.55)
    left = (back[0] + math.cos(angle + math.pi / 2) * size * 0.55,
            back[1] + math.sin(angle + math.pi / 2) * size * 0.55)
    right = (back[0] - math.cos(angle + math.pi / 2) * size * 0.55,
             back[1] - math.sin(angle + math.pi / 2) * size * 0.55)
    pygame.draw.polygon(screen, color, [tip, left, right])
    pygame.draw.polygon(screen, (10, 14, 22), [tip, left, right], width)
