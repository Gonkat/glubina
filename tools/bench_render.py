"""
Замер стоимости кадра: update → draw → present.

Скрипт поднимает настоящую игру в headless-режиме (SDL dummy), прокручивает
несколько секунд боя и печатает среднее/p50/p95 по секциям.  Это baseline
для этапа «Renderer»: сначала измеряем, потом оптимизируем.

Запуск:

    python tools/bench_render.py
    python tools/bench_render.py --frames 900 --json baseline.json

Важно: в headless-режиме презентация — это flip dummy-драйвера, поэтому
строка present здесь ничего не говорит о реальном свопе.  Стоимость draw
(сборка сцены на CPU) от этого не зависит и остаётся честной.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from game import Game  # noqa: E402
from settings import STATE_PLAYING  # noqa: E402

DT = 1.0 / 60.0


def measure(frames: int, warmup: int) -> dict:
    """Прокручивает бой и возвращает сводку метрик (мс на кадр)."""
    game = Game()
    try:
        game.reset()
        game.state = STATE_PLAYING
        metrics = game.video.metrics

        for _ in range(warmup):
            game.update(DT)
            game.draw()

        metrics.reset()
        wall_start = time.perf_counter()
        for _ in range(frames):
            with metrics.measure("update"):
                game.update(DT)
            with metrics.measure("draw"):
                game.draw()
            game.video.present()
        wall = time.perf_counter() - wall_start

        summary = metrics.snapshot()
        summary["frame"] = {
            "count": frames,
            "avg": wall * 1000.0 / max(1, frames),
        }
        summary["renderer"] = getattr(game.video, "active_renderer", "")
        summary["mode"] = getattr(game.video, "mode", "")
        return summary
    finally:
        game.video.close()
        pygame.quit()


def print_table(summary: dict) -> None:
    print(f"renderer: {summary.get('renderer') or '—'} "
          f"(mode={summary.get('mode') or '—'})")
    header = f"{'section':<12}{'count':>7}{'avg':>9}{'p50':>8}{'p95':>8}{'max':>8}"
    print(header)
    print("-" * len(header))
    order = ["update", "draw", "tex_upload", "present", "frame"]
    sections = [name for name in order if name in summary]
    sections += [name for name in summary
                 if name not in order and isinstance(summary[name], dict)]
    for name in sections:
        row = summary[name]
        if "avg" not in row:
            continue
        def value(key: str) -> str:
            if key not in row:
                return "—"
            return f"{row[key]:.2f}м"

        print(
            f"{name:<12}{row.get('count', 0):>7}"
            f"{row['avg']:>8.2f}м"
            f"{value('p50'):>7}"
            f"{value('p95'):>7}"
            f"{value('max'):>8}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=600,
                        help="кадров после прогрева (по умолчанию 600)")
    parser.add_argument("--warmup", type=int, default=120,
                        help="кадров прогрева, не попадают в статистику")
    parser.add_argument("--json", type=Path, default=None,
                        help="сохранить сводку в JSON")
    args = parser.parse_args(argv)

    summary = measure(max(1, args.frames), max(0, args.warmup))
    print_table(summary)
    if args.json:
        args.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
