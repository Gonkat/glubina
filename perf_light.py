# -*- coding: utf-8 -*-
"""Замер времени draw() в тёмной зоне (гейт LOS + клип ореола)."""
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from game import Game
from settings import STATE_PLAYING

game = Game()
game.state = STATE_PLAYING
game.zone_key = game.zone_prev = "dark"
# Несколько врагов/дропов, чтобы LOS считал по объектам.
from enemies import Enemy
for i in range(12):
    game.spawn_enemy_at(game.player.x + 120 + i * 30,
                        game.player.y + (i % 4) * 60 - 90,
                        Enemy, allow_elite=False)

for _ in range(10):          # прогрев кэшей
    game.draw()


def bench(label, n=120):
    import gc
    gc.collect()             # чистый лист: замер без пауз GC в цикле
    gc.disable()
    t0 = time.perf_counter()
    for _ in range(n):
        game.draw()
    dt = (time.perf_counter() - t0) / n * 1000
    gc.enable()
    print("%-38s %.2f ms/кадр" % (label, dt))


bench("всё включено (конус+ореол+LOS)")
game.lighting.shadows_enabled = False
bench("без теней (конус/ореол без обрезки)")
game.lighting.shadows_enabled = True
game._line_of_sight_px = lambda x, y, step_px=6.0: 0.0
bench("тени есть, LOS выключен")
game._line_of_sight_px = (
    lambda x, y, step_px=6.0: Game._line_of_sight_px(game, x, y))
bench("оба включены (контроль)")
