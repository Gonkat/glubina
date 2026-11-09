"""
shop.py

Магазин как ОБЪЕКТ МИРА: стоит в процедурной карте, светится,
открывается по E. Что именно продаёт — решает shop_data.py,
как продаёт (окно, ввод) — shop_ui.py. Здесь только «здание».
"""
import math

import pygame

import visuals
from game_object import GameObject
from settings import (
    SHOP_INTERIOR_RADIUS,
    SHOP_LIGHT_RADIUS,
    SHOP_OPEN_DIST,
)
from shop_data import SHOP_TYPES
from utils import distance


class Shop(GameObject):
    """
    Точка магазина. Два важных свойства:
      * всегда светится (light_radius) — его видно в темноте издалека;
      * interior_radius — зона, куда Game не пускает врагов:
        магазин остаётся безопасным местом (GDD).
    """

    light_radius = SHOP_LIGHT_RADIUS
    GLYPHS = {"weapons": "gun", "supplies": "box", "artifacts": "gem"}

    def __init__(self, x, y, store_type, inventory,
                 upgrade_price_multiplier):
        super().__init__(x, y)
        self.interior_radius = SHOP_INTERIOR_RADIUS
        self.store_type = store_type
        self.name = SHOP_TYPES[store_type]["name"]
        self.color = SHOP_TYPES[store_type]["color"]
        self.inventory = inventory
        self.upgrade_price_multiplier = upgrade_price_multiplier
        self.time = 0.0        # для пульсации вывески

    def update(self, dt, game):
        self.time += dt

    def near_player(self, game):
        """Достаточно ли герой близко, чтобы открыть магазин (клавиша E)."""
        return distance(self.x, self.y, game.player.x, game.player.y) < SHOP_OPEN_DIST

    def push_out(self, obj):
        """
        Выталкивает врага за границу безопасной зоны — работает как
        невидимая стена вокруг магазина. Игнорирует объекты с radius=0.
        """
        d = distance(self.x, self.y, obj.x, obj.y)
        limit = self.interior_radius + getattr(obj, "radius", 0)
        if d >= limit:
            return
        if d < 1e-6:
            nx, ny = 1.0, 0.0      # объект в самом центре — направление любое
        else:
            nx = (obj.x - self.x) / d
            ny = (obj.y - self.y) / d
        obj.x = self.x + nx * limit
        obj.y = self.y + ny * limit

    # ------------------------------------------------------------ ОТРИСОВКА
    def _glyph(self, screen, cx, cy, color):
        kind = self.GLYPHS.get(self.store_type, "box")
        if kind == "gun":
            pygame.draw.rect(screen, color, (cx - 11, cy - 3, 20, 5),
                             border_radius=2)
            pygame.draw.rect(screen, color, (cx - 9, cy + 1, 5, 7),
                             border_radius=2)
        elif kind == "gem":
            pygame.draw.polygon(screen, color, [
                (cx, cy - 10), (cx + 9, cy), (cx, cy + 10), (cx - 9, cy),
            ], 2)
            pygame.draw.polygon(screen, color, [
                (cx, cy - 4), (cx + 3, cy), (cx, cy + 3), (cx - 3, cy),
            ])
        else:
            pygame.draw.rect(screen, color, (cx - 10, cy - 8, 20, 16),
                             border_radius=3)
            pygame.draw.rect(screen, color, (cx - 6, cy - 11, 12, 4),
                             border_radius=2)
            pygame.draw.line(screen, (16, 20, 28), (cx, cy - 5), (cx, cy + 5), 2)
            pygame.draw.line(screen, (16, 20, 28), (cx - 5, cy), (cx + 5, cy), 2)

    def draw(self, screen, camera):
        sx, sy = camera.to_screen(self.x, self.y)
        cx, cy = int(sx), int(sy)
        visuals.shadow(screen, cx, cy + 8, 40, 0.9, squash=0.38)

        # платформа и корпус павильона
        pygame.draw.rect(screen, (36, 41, 53), (cx - 42, cy - 2, 84, 30),
                         border_radius=6)
        body = pygame.Rect(cx - 34, cy - 22, 68, 40)
        pygame.draw.rect(screen, (48, 55, 70), body, border_radius=5)
        pygame.draw.rect(screen, (30, 34, 46), body, 2, border_radius=5)
        # прилавок
        pygame.draw.rect(screen, (88, 96, 116), (body.x + 3, body.bottom - 14,
                                                 body.w - 6, 9),
                         border_radius=3)
        pygame.draw.rect(screen, (130, 140, 160), (body.x + 3, body.bottom - 14,
                                                   body.w - 6, 2))
        # товары на прилавке
        for i in range(3):
            pygame.draw.rect(screen, (120, 128, 144),
                             (body.x + 10 + i * 15, body.bottom - 22, 8, 7),
                             border_radius=2)
        # столбики навеса
        pygame.draw.rect(screen, (40, 44, 56), (body.x - 4, body.y - 6, 5, 48))
        pygame.draw.rect(screen, (40, 44, 56), (body.right - 1, body.y - 6, 5, 48))
        # навес в цвет магазина
        pulse = 0.55 + 0.45 * math.sin(self.time * 2.4)
        shade = tuple(int(c * (0.55 + 0.3 * pulse)) for c in self.color)
        pygame.draw.polygon(screen, (28, 32, 42), [
            (cx - 48, body.y - 5), (cx + 48, body.y - 5),
            (cx + 42, body.y + 8), (cx - 42, body.y + 8),
        ])
        for i in range(4):
            x0 = cx - 46 + i * 24
            pygame.draw.polygon(screen, shade if i % 2 == 0 else (70, 78, 94),
                                [(x0, body.y - 5), (x0 + 20, body.y - 5),
                                 (x0 + 17, body.y + 8), (x0 - 3, body.y + 8)])
        # вывеска
        sign = pygame.Rect(cx - 25, body.y - 38, 50, 25)
        pygame.draw.rect(screen, (22, 26, 36), sign, border_radius=5)
        pygame.draw.rect(screen, shade, sign, 2, border_radius=5)
        self._glyph(screen, cx, sign.y + 12, shade)
        visuals.glow(screen, cx, sign.y + 12, 34, self.color, 45)

    def draw_overlay(self, screen, camera, time):
        """После темноты: обозначение безопасной зоны и живая вывеска."""
        sx, sy = camera.to_screen(self.x, self.y)
        pulse = 0.5 + 0.5 * math.sin(time * 2.4 + self.time)
        visuals.draw_ring(screen, sx, sy, self.interior_radius,
                          self.color, 1, int(34 + 22 * pulse))
        visuals.glow(screen, sx, sy - 26, 60, self.color,
                     int(38 + 22 * pulse))
