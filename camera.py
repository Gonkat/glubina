"""Камера следует за игроком в бесконечном мире и умеет трястись.

Обычный режим рисует мир один-в-один с экраном. Снайперская оптика умеет
отдалять камеру: тогда мир рисуется на большем виртуальном полотне, а затем
масштабируется в окно. Поэтому координаты `to_screen()` — это координаты
полотна, а `to_ui()` — уже настоящие координаты экрана для HUD.
"""
import math
import random

import pygame

from settings import HEIGHT, WIDTH

MAX_SHAKE_AMOUNT = 16.0
MAX_SHAKE_OFFSET = 8.0
MIN_ZOOM = 0.55
MAX_ZOOM = 1.0
DEFAULT_ZOOM = 1.0
ZOOM_STEP = 0.07


class Camera:
    """
    Мир бесконечен, поэтому всё рисуется со сдвигом:
        экран = мир - камера

    Тряска хранится отдельно от базовой позиции: follow() запоминает,
    где камера должна быть, а update() гасит амплитуду и добавляет
    смещение. Так один и тот же удар не «сдвигает» мир навсегда.
    """

    def __init__(self):
        self.base_x = 0.0
        self.base_y = 0.0
        self.x = 0.0
        self.y = 0.0
        self.shake_amount = 0.0
        self.shake_time = 0.0
        self.shake_vx = 0.0
        self.shake_vy = 0.0

        # --- оптика: 1.0 = обычный обзор, меньше = шире карта ---
        self.zoom = DEFAULT_ZOOM
        self.min_zoom = DEFAULT_ZOOM
        self.zoom_step = ZOOM_STEP
        self.view_w = WIDTH
        self.view_h = HEIGHT
        # Виртуальные пиксели на пиксель экрана. При отдалении > 1.
        self.scale_x = 1.0
        self.scale_y = 1.0

    @property
    def is_zoomed(self):
        return self.zoom < MAX_ZOOM - 1e-4

    @property
    def zoom_percent(self):
        return int(round(self.zoom * 100))

    def reset_zoom(self):
        self.min_zoom = MAX_ZOOM
        self._apply_zoom(MAX_ZOOM)

    def set_zoom_range(self, min_zoom, step=ZOOM_STEP):
        """Задаёт предел отдаления (1.0 = колесо не работает)."""
        min_zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(min_zoom)))
        self.zoom_step = max(0.02, float(step))
        self.min_zoom = min_zoom
        clamped = max(self.min_zoom, min(MAX_ZOOM, self.zoom))
        if abs(clamped - self.zoom) > 1e-4:
            self._apply_zoom(clamped)

    def zoom_by(self, direction):
        """Один шаг колеса: +1 ближе, -1 шире. False — упёрлись в предел."""
        if not direction or self.min_zoom >= MAX_ZOOM - 1e-4:
            return False
        target = self.zoom + self.zoom_step * (1 if direction > 0 else -1)
        target = max(self.min_zoom, min(MAX_ZOOM, target))
        if abs(target - self.zoom) < 1e-4:
            return False
        self._apply_zoom(target)
        return True

    def _apply_zoom(self, zoom):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
        center_x = self.base_x + self.view_w / 2.0
        center_y = self.base_y + self.view_h / 2.0
        self.zoom = zoom
        self.view_w = max(1, int(round(WIDTH / zoom)))
        self.view_h = max(1, int(round(HEIGHT / zoom)))
        self.scale_x = self.view_w / float(WIDTH)
        self.scale_y = self.view_h / float(HEIGHT)
        self.base_x = center_x - self.view_w / 2.0
        self.base_y = center_y - self.view_h / 2.0
        self.x = self.base_x + self.shake_vx
        self.y = self.base_y + self.shake_vy

    def reset_shake(self):
        self.shake_amount = self.shake_time = 0.0
        self.shake_vx = self.shake_vy = 0.0
        self.x, self.y = self.base_x, self.base_y

    def follow(self, target_x, target_y):
        """Центрирует видимую область на цели без ограничения координат."""
        self.base_x = target_x - self.view_w / 2.0
        self.base_y = target_y - self.view_h / 2.0
        self.x = self.base_x + self.shake_vx
        self.y = self.base_y + self.shake_vy

    def add_shake(self, amount, angle=None):
        """Добавляет затухающий импульс с насыщением при частых попаданиях."""
        amount = max(0.0, min(14.0, amount))
        remaining = max(0.15, 1.0 - self.shake_amount / MAX_SHAKE_AMOUNT)
        impulse = amount * remaining
        self.shake_amount = min(MAX_SHAKE_AMOUNT, self.shake_amount + impulse)
        self.shake_time = max(self.shake_time, 0.12 + impulse * 0.012)
        if angle is None:
            angle = random.uniform(0, math.tau)
        self.shake_vx += math.cos(angle) * impulse
        self.shake_vy += math.sin(angle) * impulse
        self._limit_shake_offset()

    def _limit_shake_offset(self):
        magnitude = math.hypot(self.shake_vx, self.shake_vy)
        if magnitude > MAX_SHAKE_OFFSET:
            scale = MAX_SHAKE_OFFSET / magnitude
            self.shake_vx *= scale
            self.shake_vy *= scale

    def update(self, dt):
        if self.shake_amount > 0.0:
            decay = math.exp(-12.0 * dt)
            self.shake_vx *= decay
            self.shake_vy *= decay
            self.shake_amount = max(0.0, self.shake_amount - dt * 26.0)
            # Едва заметный шум сохраняет ощущение удара, не усиливая дрожание.
            noise = self.shake_amount * 0.02
            self.shake_vx += random.uniform(-noise, noise)
            self.shake_vy += random.uniform(-noise, noise)
            self._limit_shake_offset()
            self.shake_time = max(0.0, self.shake_time - dt)
            if self.shake_time <= 0.0:
                self.shake_vx *= 0.5
                self.shake_vy *= 0.5
        else:
            self.shake_vx *= 0.82
            self.shake_vy *= 0.82
            if abs(self.shake_vx) < 0.05 and abs(self.shake_vy) < 0.05:
                self.shake_vx = self.shake_vy = 0.0
        self.x = self.base_x + self.shake_vx
        self.y = self.base_y + self.shake_vy

    def to_screen(self, world_x, world_y):
        """Координаты на виртуальном полотне мира (до масштабирования)."""
        return world_x - self.x, world_y - self.y

    def to_ui(self, world_x, world_y):
        """Координаты на настоящем экране — для HUD поверх зума."""
        return ((world_x - self.x) / self.scale_x,
                (world_y - self.y) / self.scale_y)

    def to_world(self, screen_x, screen_y):
        """Мышь в координатах окна -> мир (учитывает отдаление)."""
        return (screen_x * self.scale_x + self.x,
                screen_y * self.scale_y + self.y)

    def view_rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.view_w, self.view_h)

    def is_visible(self, world_x, world_y, margin=80):
        sx, sy = self.to_screen(world_x, world_y)
        return (-margin <= sx <= self.view_w + margin
                and -margin <= sy <= self.view_h + margin)
