# -*- coding: utf-8 -*-
"""
Диагностика света/видимости: скриншоты + числа.

Строим сцену у НАСТОЯЩЕЙ стены комнаты (сплошной тайл с полом по обеим
сторонам). Игрок лицом к стене, фронтальный враг — ДО стены (в конусе),
враг ЗА стеной, враг за спиной. Замеряем свет у лицевой стороны стены и
за стеной + считаем вызовы обрезки теней.

Запуск: python diag_light.py  ->  картинки в TEMP/glubina_diag/
"""
import os
import math

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game import Game
from settings import STATE_PLAYING, TILE, BEAM_HALF_ANGLE, BEAM_RANGE

OUT = os.path.join(os.environ.get("TEMP", "."), "glubina_diag")
os.makedirs(OUT, exist_ok=True)


def _clear_line(world, x0, y0, x1, y1, step=6.0):
    """Свободен ли отрезок (для сцены «враг за спиной»)."""
    dist = math.hypot(x1 - x0, y1 - y0)
    steps = max(2, int(dist / step))
    for i in range(1, steps):
        t = i / steps
        if world.is_solid_at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t):
            return False
    return not world.is_solid_at(x1, y1)


def find_room_wall(game):
    """
    Ближайшая стена комнаты: сплошной тайл, по обеим сторонам вдоль
    нормали — пол. Возвращает (cx, cy, nx, ny).

    Дополнительно требуем свободное место за спиной игрока (сцена
    «враг за спиной» должна показывать именно отсутствие света, а не
    вторую стену).
    """
    px, py = game.player.x, game.player.y
    ptx, pty = int(px // TILE), int(py // TILE)
    best = None
    for tx in range(ptx - 14, ptx + 15):
        for ty in range(pty - 14, pty + 15):
            if not game.world.is_solid_tile(tx, ty):
                continue
            cx, cy = (tx + 0.5) * TILE, (ty + 0.5) * TILE
            for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ax, ay = cx + nx * TILE * 1.6, cy + ny * TILE * 1.6
                bx, by = cx - nx * TILE * 1.6, cy - ny * TILE * 1.6
                if (game.world.is_solid_at(ax, ay)
                        or game.world.is_solid_at(bx, by)):
                    continue
                spot_x = cx - nx * (TILE + 52)
                spot_y = cy - ny * (TILE + 52)
                rear_x = spot_x - nx * 210
                rear_y = spot_y - ny * 210
                if not _clear_line(game.world, spot_x, spot_y,
                                   rear_x, rear_y):
                    continue
                d = math.hypot(cx - px, cy - py)
                if best is None or d < best[0]:
                    best = (d, cx, cy, nx, ny)
    return best


def _rear_spot(game, nx, ny, prof):
    """
    Точка за спиной игрока: прямая видимость есть, а света — нет.

    Сначала ищем по-настоящему тёмную точку (reveal ниже порога), чтобы
    проверить правило «в темноте не видно». Если вся округа освещена
    лампами — возвращаем ближайшую свободную (там видимость честно
    зависит от света лампы).
    """
    px, py = game.player.x, game.player.y
    threshold = float(prof.get("light_threshold", 0.0))
    fallback = None
    for dist in (240, 210, 180, 150, 120, 95, 70):
        rx = px - nx * dist
        ry = py - ny * dist
        if game._line_of_sight_px(rx, ry) > 0.0:
            continue
        if fallback is None:
            fallback = (rx, ry)
        sx, sy = game.camera.to_screen(rx, ry)
        if game.lighting.reveal_at(sx, sy) < threshold:
            return rx, ry
    return fallback


def scene(game, tag):
    game.state = STATE_PLAYING
    game.elapsed = 10.0
    game.enemies.clear()

    hit = find_room_wall(game)
    assert hit, "стена комнаты не найдена"
    _d, cx, cy, nx, ny = hit
    aim = math.atan2(ny, nx)              # игрок смотрит НА стену
    # Игрок перед стеной, лицом к ней.
    game.player.x = cx - nx * (TILE + 52)
    game.player.y = cy - ny * (TILE + 52)
    game.player.angle = aim
    game.camera.follow(game.player.x, game.player.y)
    # Штору строим ДО расстановки врагов: по ней выбираем тёмную точку
    # за спиной (иначе там может оказаться свет лампы — и это честно).
    game.draw()

    from enemies import Enemy

    # 1) ДО стены, между игроком и стеной — в конусе фонарика
    front = game.spawn_enemy_at(cx - nx * 44, cy - ny * 44,
                                Enemy, allow_elite=False)
    # 2) ЗА стеной (пол за стеной гарантирован find_room_wall)
    behind = game.spawn_enemy_at(cx + nx * (TILE + 60),
                                 cy + ny * (TILE + 60),
                                 Enemy, allow_elite=False)
    # 3) за спиной игрока — в темноте, вне конуса
    rx, ry = _rear_spot(game, nx, ny, game.zone_profile())
    rear = game.spawn_enemy_at(rx, ry, Enemy, allow_elite=False)

    # Счётчик вызовов обрезки теней.
    clip_calls = []
    orig_clip = game.lighting._clip_cone_to_shadows
    game.lighting._clip_cone_to_shadows = \
        lambda *a, **k: (clip_calls.append(1), orig_clip(*a, **k))[1]

    game.draw()
    game.lighting._clip_cone_to_shadows = orig_clip

    path = os.path.join(OUT, "scene_%s.png" % tag)
    pygame.image.save(game.screen, path)

    prof = game.zone_profile()
    gated = bool(prof.get("gated"))
    print("\n=== %s (zone=%s gated=%s shadows=%s clip_calls=%d) ==="
          % (tag, game.zone_key, gated, prof.get("shadows"),
             len(clip_calls)))
    for name, e in (("front(до стены)", front),
                    ("behind(за стеной)", behind),
                    ("rear(за спиной)", rear)):
        a = game.entity_fade(e.x, e.y)
        sx, sy = game.camera.to_screen(e.x, e.y)
        print("  %-18s alpha=%.3f  reveal=%.3f  рисуется=%s"
              % (name, a, game.lighting.reveal_at(sx, sy), a > 0.01))

    # Свет: у лицевой стороны стены (на луче) и сразу за стеной.
    for name, sgn in (("Лицо стены (на луче)", -1.0),
                      ("За стеной (+30px)", +1.0)):
        wx = cx + nx * sgn * (TILE * 0.6 if sgn < 0 else TILE + 30)
        wy = cy + ny * sgn * (TILE * 0.6 if sgn < 0 else TILE + 30)
        sx, sy = game.camera.to_screen(wx, wy)
        print("  %-24s light=%.3f" % (name, game.lighting.light_at(sx, sy)))

    # Лучи raycast: до какой дистанции дошёл свет.
    hits = game.lighting._ray_distances(
        (game.player.x, game.player.y),
        game.player.angle, math.radians(BEAM_HALF_ANGLE),
        BEAM_RANGE * prof.get("cone_mul", 1.0), 14.0, 36,
        game.world.is_solid_at)
    print("  raycast: min_hit=%.0f  стена на %.0f px от игрока"
          % (min(hits),
             math.hypot(cx - game.player.x, cy - game.player.y)))
    print("  -> %s" % path)
    game.enemies.clear()
    return path


def _floor_near(world, x, y):
    """Ближайшая к (x, y) клетка пола — чтобы не поставить игрока в стену."""
    tx0, ty0 = int(x // TILE), int(y // TILE)
    for radius in range(0, 14):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                tx, ty = tx0 + dx, ty0 + dy
                if not world.is_solid_tile(tx, ty):
                    return (tx + 0.5) * TILE, (ty + 0.5) * TILE
    return x, y


def main():
    game = Game()
    game.state = STATE_PLAYING
    # Фиксированный сид: у диагностики должна быть ОДНА планировка,
    # иначе числа «плавают» от запуска к запуску. Игрок — в соседнем
    # чанке, подальше от стартовой площадки с её постоянными лампами.
    from world import World
    seed = 20260101
    paths = []
    for tag in ("dark", "medium"):
        game.zone_key = game.zone_prev = tag
        game.world = World(seed=seed, zone_key=tag)
        center = game.world.chunk_pixels * 1.5
        game.player.x, game.player.y = _floor_near(game.world, center, center)
        paths.append(scene(game, tag))
    print("\nГотово:\n  %s\n  %s" % (paths[0], paths[1]))


if __name__ == "__main__":
    main()
