"""
Метрики кадра: сколько миллисекунд стоит update, draw и презентация.

Сборщик намеренно крошечный и без зависимостей: он вызывается каждый
кадр, поэтому не должен сам становиться узким местом.  Внутри — кольцевой
буфер на секцию (последние N замеров), поэтому память не растёт.

Использование:

    metrics = FrameMetrics()
    with metrics.measure("draw"):
        draw_scene()
    metrics.snapshot()          # {'draw': {'count': 1, 'avg': 12.4, ...}}
"""
from __future__ import annotations

import math
import time
from collections import deque
from contextlib import contextmanager


class FrameMetrics:
    """Кольцевой буфер замеров по именованным секциям кадра."""

    def __init__(self, capacity: int = 240):
        self.capacity = max(8, int(capacity))
        self._samples: dict[str, deque[float]] = {}

    def add(self, section: str, milliseconds: float) -> None:
        """Добавляет один замер (мс) в секцию."""
        if milliseconds < 0:
            milliseconds = 0.0
        samples = self._samples.get(section)
        if samples is None:
            samples = deque(maxlen=self.capacity)
            self._samples[section] = samples
        samples.append(float(milliseconds))

    @contextmanager
    def measure(self, section: str):
        """Меряет блок кода и записывает результат в секцию."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add(section, (time.perf_counter() - started) * 1000.0)

    def reset(self) -> None:
        self._samples.clear()

    def over_count(self, section: str, threshold: float) -> int:
        """Сколько замеров секции длиннее порога (кадры > 33 мс)."""
        samples = self._samples.get(section)
        if not samples:
            return 0
        return sum(1 for value in samples if value > threshold)

    def sections(self) -> list[str]:
        return sorted(self._samples)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        """Ближайший ранг: p95 при 10 замерах — это максимум, а не среднее."""
        if not values:
            return 0.0
        rank = math.ceil(percentile / 100.0 * len(values))
        index = min(len(values) - 1, max(0, rank - 1))
        return values[index]

    def snapshot(self, percentiles: tuple[float, ...] = (50.0, 95.0)) -> dict:
        """Сводка по секциям: count, avg, p50/p95 (и другие), max."""
        summary: dict[str, dict[str, float]] = {}
        for section, samples in self._samples.items():
            if not samples:
                continue
            values = sorted(samples)
            entry: dict[str, float] = {
                "count": len(values),
                "avg": sum(values) / len(values),
                "max": values[-1],
            }
            for percentile in percentiles:
                entry[f"p{percentile:g}"] = self._percentile(values, percentile)
            summary[section] = entry
        return summary
