"""Spatial hash for broad-phase enemy queries. Coordinates are world-space pixels."""
from collections import defaultdict
from math import floor


class EnemySpatialIndex:
    def __init__(self, cell_size=192):
        self.cell_size = cell_size
        self.cells = defaultdict(list)
        self.max_radius = 0.0

    def rebuild(self, enemies):
        self.cells.clear()
        self.max_radius = 0.0
        size = self.cell_size
        for enemy in enemies:
            if not enemy.alive:
                continue
            self.cells[(floor(enemy.x / size), floor(enemy.y / size))].append(enemy)
            self.max_radius = max(self.max_radius, enemy.radius)

    def query(self, x, y, radius):
        size = self.cell_size
        padding = self.max_radius + 16.0
        left = floor((x - radius - padding) / size)
        right = floor((x + radius + padding) / size)
        top = floor((y - radius - padding) / size)
        bottom = floor((y + radius + padding) / size)
        for cx in range(left, right + 1):
            for cy in range(top, bottom + 1):
                for enemy in self.cells.get((cx, cy), ()):
                    if enemy.alive:
                        yield enemy
