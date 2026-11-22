"""CPU/SDL-презентер: тот же путь вывода, что был до OpenGL."""
from __future__ import annotations

from contextlib import nullcontext

import pygame

from render_metrics import FrameMetrics
from settings import HEIGHT, WIDTH


class CPUDisplay:
    """Обычный SDL-дисплей: игра рисует прямо в окно, кадр выводит flip."""

    name = "CPU (SDL)"
    version = ""
    vendor = ""

    def __init__(self, size: tuple[int, int] = (WIDTH, HEIGHT),
                 metrics: FrameMetrics | None = None, vsync: bool = False):
        self.size = (int(size[0]), int(size[1]))
        # SDL требует OPENGL/SCALED для vsync; без них параметр игнорируется.
        try:
            self.surface = pygame.display.set_mode(self.size, vsync=1 if vsync else 0)
        except pygame.error:
            self.surface = pygame.display.set_mode(self.size)
        self.effects = False
        self.metrics = metrics

    def set_effects(self, enabled: bool):
        self.effects = bool(enabled)

    def present(self):
        timer = (
            self.metrics.measure("present") if self.metrics is not None
            else nullcontext()
        )
        with timer:
            pygame.display.flip()

    def close(self):
        pass
