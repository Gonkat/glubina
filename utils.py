"""
Чистые функции-помощники: математика, коллизии, градиенты.

Сюда НЕ нужно превращать всё в классы: это короткие функции,
которым не нужна память между вызовами. ООП — не догма.
"""
import math

import pygame


def clamp(value, low, high):
    """Ограничивает значение диапазоном [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def distance(x1, y1, x2, y2):
    """Расстояние между двумя точками."""
    return math.hypot(x2 - x1, y2 - y1)


def normalize(dx, dy):
    """Единичный вектор той же стороны или (0, 0), если длина равна нулю."""
    length = math.hypot(dx, dy)
    if length == 0.0:
        return 0.0, 0.0
    return dx / length, dy / length


def mix(color_a, color_b, t):
    """Смешивает два цвета: t=0 → первый, t=1 → второй."""
    t = clamp(t, 0.0, 1.0)
    return tuple(int(a + (b - a) * t) for a, b in zip(color_a, color_b))


def circles_collide(x1, y1, r1, x2, y2, r2):
    """Есть ли пересечение двух кругов."""
    return distance(x1, y1, x2, y2) < r1 + r2


def angle_diff(a, b):
    """Разница углов a − b, приведённая к диапазону [−π, +π].

    Нужна, чтобы не ломались сравнения, когда угол «перепрыгнул»
    через −180°/180° (например, удар начался на 179° и дошёл до −179°).
    """
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def resolve_circle_rect(cx, cy, radius, rect):
    """
    Выталкивает круг из прямоугольника (стены).
    Возвращает новые (x, y): круг сдвинут ровно настолько,
    чтобы пересечение исчезло — по кратчайшей оси.
    """
    nearest_x = clamp(cx, rect.left, rect.right)
    nearest_y = clamp(cy, rect.top, rect.bottom)
    dx = cx - nearest_x
    dy = cy - nearest_y
    dist_sq = dx * dx + dy * dy

    if dist_sq >= radius * radius:
        return cx, cy                      # столкновения нет

    if dist_sq > 0.0001:                   # центр снаружи — толкаем по нормали
        dist = math.sqrt(dist_sq)
        push = radius - dist
        return cx + dx / dist * push, cy + dy / dist * push

    # центр оказался ВНУТРИ стены — выходим через кратчайшую сторону
    left = cx - rect.left
    right = rect.right - cx
    top = cy - rect.top
    bottom = rect.bottom - cy
    shortest = min(left, right, top, bottom)
    if shortest == left:
        return rect.left - radius, cy
    if shortest == right:
        return rect.right + radius, cy
    if shortest == top:
        return cx, rect.top - radius
    return cx, rect.bottom + radius


def make_radial_glow(radius, color):
    """
    Создаёт поверхность с мягким круговым свечением (радиальный градиент).

    Приём: градиент строится МАЛЕНЬКИМ (48 px) и затем растягивается
    через smoothscale — линейная интерполяция сглаживает ступеньки.
    Сделано один раз при старте, а не каждый кадр.
    """
    build = 48
    steps = 48
    surf = pygame.Surface((build * 2, build * 2), pygame.SRCALPHA)
    for i in range(steps, 0, -1):
        t = i / steps
        r = max(1, int(build * t))
        alpha = int(255 * (1 - t) ** 1.6)
        pygame.draw.circle(surf, (*color, alpha), (build, build), r)
    return pygame.transform.smoothscale(surf, (radius * 2, radius * 2))
