"""
Свет и темнота.

Приём остался прежним (умножение сцены на «штору»), но штора теперь
строится иначе: холодный ambient + АДДИТИВНЫЕ цветные источники. Это
позволяет делать тёплый фонарик, бирюзовые лампы и оранжевые взрывы,
не превращая экран в чёрную дыру. Края экрана затемняются виньеткой,
а при низком HP появляется красная пульсация.
"""
import math

import pygame

from settings import (
    AMBIENT_LIGHT,
    BEAM_COLOR,
    BEAM_HALF_ANGLE,
    BEAM_RANGE,
    FLASH_COLOR,
    FLASH_RADIUS,
    GLOW_COLOR,
    GLOW_RADIUS,
    HEIGHT,
    VIGNETTE_COLOR,
    WIDTH,
)
from utils import mix

CONE_SCALE = 3
_LIGHT_CACHE = {}


def _light_surface(radius, color, strength=1.0):
    """Аддитивный радиальный свет: чёрный снаружи, цвет — к центру."""
    radius = max(6, int(radius))
    strength = round(max(0.05, min(1.5, strength)), 2)
    key = (radius, tuple(color), strength)
    surf = _LIGHT_CACHE.get(key)
    if surf is not None:
        return surf
    surf = pygame.Surface((radius * 2, radius * 2))
    surf.fill((0, 0, 0))
    steps = 28
    for i in range(steps, 0, -1):
        t = i / steps                        # 1 — край, 0 — центр
        falloff = (1.0 - t) ** 1.7 * strength
        value = tuple(min(255, int(c * falloff)) for c in color)
        pygame.draw.circle(surf, value, (radius, radius),
                           max(1, int(radius * t)))
    if len(_LIGHT_CACHE) > 90:
        _LIGHT_CACHE.clear()
    _LIGHT_CACHE[key] = surf
    return surf


class LightingManager:
    """Работает в координатах полотна мира: при оптике оно больше окна."""

    def __init__(self):
        self.view_w = WIDTH
        self.view_h = HEIGHT
        self.mask = pygame.Surface((WIDTH, HEIGHT))
        self.cone_small = pygame.Surface(
            (WIDTH // CONE_SCALE, HEIGHT // CONE_SCALE)
        )
        self.cone_scaled = pygame.Surface((WIDTH, HEIGHT))
        self.vignette = self._build_vignette(WIDTH, HEIGHT)
        self._flash_cache = _light_surface(FLASH_RADIUS, FLASH_COLOR, 0.95)

    def set_view(self, width, height):
        """Пересобирает световые слои, когда оптика меняет размер обзора."""
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == (self.view_w, self.view_h):
            return
        self.view_w, self.view_h = width, height
        size = (width, height)
        self.mask = pygame.Surface(size)
        self.cone_small = pygame.Surface(
            (max(1, width // CONE_SCALE), max(1, height // CONE_SCALE))
        )
        self.cone_scaled = pygame.Surface(size)
        self.vignette = self._build_vignette(width, height)

    # ------------------------------------------------------------ СВЕТ
    def render(self, screen, player_screen_pos, muzzle_screen_pos,
               angle, flash_timer, flashes=(), time=0.0, danger=0.0,
               hurt=0.0):
        """
        flashes — (x, y, radius) или (x, y, radius, color),
        уже в экранных координатах. color по умолчанию — цвет взрыва.
        """
        mask = self.mask
        mask.fill(AMBIENT_LIGHT)

        # 1. конус фонарика: несколько вложенных конусов дают мягкий край
        self._add_cone(mask, player_screen_pos, angle, time)

        # 2. личный ореол героя (тёплый, чтобы видеть ноги и стены рядом)
        self._add(mask, GLOW_RADIUS, GLOW_COLOR, player_screen_pos, 0.90)

        # 3. статические лампы и прочие цветные источники
        for light in flashes:
            if len(light) >= 4:
                x, y, radius, color = light[:4]
            else:
                x, y, radius = light[:3]
                color = (255, 170, 90)
            # лёгкое мерцание делает свет живым
            flicker = 0.92 + 0.08 * math.sin(time * 7.0 + x * 0.07 + y * 0.05)
            self._add(mask, radius, color, (x, y), flicker)

        # 4. вспышка выстрела
        if flash_timer > 0.0:
            trail = max(0.0, min(1.0, flash_timer / 0.09))
            mask.blit(self._flash_cache,
                      (muzzle_screen_pos[0] - FLASH_RADIUS,
                       muzzle_screen_pos[1] - FLASH_RADIUS),
                      special_flags=pygame.BLEND_RGB_ADD)
            self._add(mask, 90, (255, 230, 190), player_screen_pos,
                      0.55 * trail)

        # 5. накладываем штору умножением
        screen.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

        # 6. виньетка + красная пульсация при опасности/уроне
        screen.blit(self.vignette, (0, 0))
        if danger > 0.0:
            self._draw_danger(screen, danger, time)
        if hurt > 0.0:
            self._draw_hurt(screen, hurt)

    # ------------------------------------------------------------ ВНУТРЕННЕЕ
    @staticmethod
    def _add(mask, radius, color, pos, strength=1.0):
        light = _light_surface(radius, color, strength)
        mask.blit(light, (int(pos[0] - radius), int(pos[1] - radius)),
                  special_flags=pygame.BLEND_RGB_ADD)

    def _add_cone(self, mask, pos, angle, time):
        """Три вложенных конуса, нарисованных в 1/3 и растянутых."""
        surf = self.cone_small
        surf.fill((0, 0, 0))
        cx, cy = pos[0] / CONE_SCALE, pos[1] / CONE_SCALE
        base = math.radians(BEAM_HALF_ANGLE)
        drift = math.sin(time * 1.3) * 0.012       # живое покачивание луча
        layers = (
            (base, BEAM_RANGE, (46, 42, 34)),
            (base * 0.78, BEAM_RANGE * 0.94, (74, 68, 54)),
            (base * 0.46, BEAM_RANGE * 0.80, (118, 106, 82)),
        )
        for half, length, color in layers:
            pts = [(cx, cy)]
            steps = 18
            for i in range(steps + 1):
                a = angle + drift - half + 2 * half * i / steps
                pts.append((cx + math.cos(a) * length / CONE_SCALE,
                            cy + math.sin(a) * length / CONE_SCALE))
            pygame.draw.polygon(surf, color, pts)
        beam = pygame.transform.scale(
            surf, (self.view_w, self.view_h), self.cone_scaled)
        mask.blit(beam, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _build_vignette(self, width, height):
        """Заранее собранная виньетка: края темнее, центр прозрачный."""
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        # дешёвый градиент из вложенных рамок
        steps = 26
        for i in range(steps):
            t = i / steps
            inset = int(min(width, height) * 0.18 * t)
            alpha = int(170 * (1.0 - t) ** 1.4)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(surf, (*VIGNETTE_COLOR, alpha), rect, 12,
                             border_radius=30)
        # углы — сильнее
        corner = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(12):
            t = i / 12
            pygame.draw.rect(corner, (*VIGNETTE_COLOR, int(30 * (1 - t))),
                             (0, 0, width, height), int(40 * (1 - t)) + 6,
                             border_radius=60)
        surf.blit(corner, (0, 0))
        return surf

    def _draw_hurt(self, screen, strength):
        """Кратковременная красная кромка — сигнал урона без заливки экрана."""
        alpha = int(150 * max(0.0, min(1.0, strength)))
        if alpha <= 0:
            return
        width, height = screen.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(12):
            t = i / 12
            inset = int(min(width, height) * 0.04 * t)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(overlay, (200, 34, 42, int(alpha * (1 - t) ** 1.4)),
                             rect, 22, border_radius=44)
        screen.blit(overlay, (0, 0))

    def _draw_danger(self, screen, danger, time):
        pulse = 0.55 + 0.45 * math.sin(time * 6.5)
        alpha = int(120 * max(0.0, min(1.0, danger)) * pulse)
        if alpha <= 0:
            return
        width, height = screen.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(10):
            t = i / 10
            inset = int(min(width, height) * 0.08 * t)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(overlay, (180, 28, 40, int(alpha * (1 - t) ** 1.6)),
                             rect, 18, border_radius=40)
        screen.blit(overlay, (0, 0))
