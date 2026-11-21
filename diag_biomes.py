# -*- coding: utf-8 -*-
"""
Диагностика биомов: генерация и свет в трёх типах локаций.

Один и тот же сид — три биома (тёмный / средний / уютный). Скрипт
считает статистику генерации (комнаты, стены-препятствия, лампы),
ставит игрока рядом с лампой и сохраняет скриншот: видно разницу в
тесноте, декоре, числе источников света и то, как видимость работает
в мраке.

Запуск: python diag_biomes.py  ->  картинки в TEMP/glubina_diag/
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game import Game
from world import World
from settings import STATE_PLAYING

OUT = os.path.join(os.environ.get("TEMP", "."), "glubina_diag")
os.makedirs(OUT, exist_ok=True)
SEED = 424242
CHUNKS = [(cx, cy) for cx in range(-2, 3) for cy in range(-2, 3)]


def collect(world):
    """Комнаты / препятствия / лампы по окрестным чанкам."""
    rooms = walls = lamps = 0
    richest = None
    for cx, cy in CHUNKS:
        plan = world._plan_chunk(cx, cy)
        rooms += len(plan["rooms"])
        chunk = world._generate_chunk(cx, cy)
        walls += sum(row.count(world.WALL) for row in chunk["grid"])
        lamps += len(chunk["lamps"])
        if chunk["lamps"] and (richest is None
                               or len(chunk["lamps"]) > len(richest[2])):
            richest = (cx, cy, chunk["lamps"])
    return rooms, walls, lamps, richest


for zone in ("dark", "medium", "cozy"):
    game = Game()
    game.state = STATE_PLAYING
    game.zone_key = game.zone_prev = zone
    game.world = World(seed=SEED, zone_key=zone)
    game.enemies.clear()
    game.effects.clear()
    rooms, walls, lamps, richest = collect(game.world)
    if richest:
        _, _, lamps_here = richest
        lamp = lamps_here[0]
        game.player.x = lamp["x"] - 90
        game.player.y = lamp["y"] + 60
    game.camera.follow(game.player.x, game.player.y)
    game.elapsed = 6.0
    game.draw()
    path = os.path.join(OUT, "biome_%s.png" % zone)
    pygame.image.save(game.screen, path)
    gen = game.world.gen
    print("%-7s rooms=%-3d walls=%-4d lamps=%-3d decor=%-7s tint=%s"
          % (zone, rooms, walls, lamps, gen["decor"], gen["floor_tint"]))
    print("        -> %s" % path)
