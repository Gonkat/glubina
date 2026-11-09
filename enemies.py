"""
Враги: базовый класс Enemy и два подкласса (наследование).
"""
import math
import random

import pygame

import soundbank
from settings import (
    AIM_MARK_TIME,
    ENEMY_ATTACK_COOLDOWN,
    ENEMY_COLOR,
    ENEMY_REPATH_INTERVAL,
    ENEMY_WAYPOINT_REACH,
    RUNNER_COLOR,
    TANK_COLOR,
)
from game_object import GameObject
from pathfinding import find_path, has_line_of_sight
import spritebank
import visuals
from utils import circles_collide, distance


class Enemy(GameObject):
    """
    Базовый враг: идёт к игроку, бьёт при касании, получает урон.

    Настройки врага — это АТРИБУТЫ КЛАССА («шаблон»).
    Подклассы их просто переопределяют, не переписывая логику.
    """

    color = ENEMY_COLOR
    radius = 18
    max_hp = 50
    speed = 85
    damage = 10
    score = 100
    attack_delay = ENEMY_ATTACK_COOLDOWN
    # M10: награда за убийство в монетах — главный, ПРЕДСКАЗУЕМЫЙ доход
    # (дроп-монеты ниже — бонус сверху). Как и HP/урон — атрибут
    # класса: настраивается здесь, а не ищется в игровом цикле.
    bounty = 4

    # Таблица дропа (п.5–6 GDD): каждый пункт — независимый бросок.
    # chance — вероятность, min..max — сколько выпадет.
    drops = (
        {"type": "coin", "chance": 0.25, "min": 4, "max": 10},
        # Патроны — расходник, а не «второй кошелёк»: убийство должно
        # окупать хотя бы часть выстрелов, иначе игрок застревает с пустым
        # стволом и без дохода (проверено замером 90-секундного боя).
        {"type": "ammo", "chance": 0.50, "min": 4, "max": 8},
        {"type": "heal", "chance": 0.07, "min": 1, "max": 1},   # редкие аптечки
    )

    sprite_name = "enemy"      # файл assets/sprites/{name}.png (M8)

    def __init__(self, x, y):
        super().__init__(x, y)
        self.hp = self.max_hp
        self.angle = 0.0
        self.attack_timer = 0.0
        self.windup_timer = 0.0      # телеграф удара: 0.34 с на реакцию
        self.windup_total = 0.34
        self.anim_phase = random.uniform(0.0, 6.28)
        self.hurt_timer = 0.0
        self.hp_show_timer = 0.0     # полоска HP гаснет, когда бой утих
        self.slow_timer = 0.0
        self.slow_factor = 1.0
        self.kb_vx = 0.0       # скорость отбрасывания (px/сек)
        self.kb_vy = 0.0
        # ИИ (M9): путь до игрока + таймер пересчёта. Случайные сдвиги
        # нужны, чтобы вся орда не пересчитывала A* в одном кадре.
        self.path = []                       # путевые точки []; [] = напрямую
        self.repath_interval = ENEMY_REPATH_INTERVAL * random.uniform(0.75, 1.35)
        self.path_timer = random.uniform(0.0, self.repath_interval)
        # ВЕТВИ ОРУЖИЯ (M11): две «метки» состояния для синергий
        self.aim_mark = 0.0        # сколько секунд игрок держит на нём прицел
        self.explosion_mark = 0.0  # «след взрыва»: только что взорван — уязвим
        self.vulnerable_timer = 0.0
        self.vulnerable_mul = 1.0  # временная уязвимость от меток/пробоя
        self.bleed_remaining = 0.0
        self.bleed_dps = 0.0
        self.dust_remaining = 0.0
        self.dust_dps = 0.0
        self.dust_stacks = 0
        self.dust_visual_timer = 0.0

    def apply_knockback(self, direction, force):
        """Добавляет импульс отбрасывания в заданном направлении."""
        self.kb_vx += direction[0] * force
        self.kb_vy += direction[1] * force

    def update(self, dt, game):
        player = game.player
        self.angle = math.atan2(player.y - self.y, player.x - self.x)

        # отбрасывание: импульс гаснет экспоненциально, враг врезается в стены
        if self.kb_vx or self.kb_vy:
            self.x += self.kb_vx * dt
            self.y += self.kb_vy * dt
            damping = math.exp(-6.0 * dt)
            self.kb_vx *= damping
            self.kb_vy *= damping
            self.x, self.y = game.world.resolve_circle(
                self.x, self.y, self.radius
            )

        # движение к игроку с обходом препятствий (M9) + отклонение
        # траектории (у обычного врага = 0)
        move_angle = self._steering(game, dt) + self._strafe(game.elapsed)
        speed_factor = self.slow_factor if self.slow_timer > 0.0 else 1.0
        if self.windup_timer > 0.0:
            speed_factor *= 0.25     # перед ударом враг «замахивается»
        self.x += math.cos(move_angle) * self.speed * speed_factor * dt
        self.y += math.sin(move_angle) * self.speed * speed_factor * dt
        self.anim_phase += dt * (4.0 + self.speed * 0.03)
        self.slow_timer = max(0.0, self.slow_timer - dt)
        if self.slow_timer == 0.0:
            self.slow_factor = 1.0
        self._separate(game)
        self.x, self.y = game.world.resolve_circle(self.x, self.y, self.radius)

        self.attack_timer = max(0.0, self.attack_timer - dt)
        self.hurt_timer = max(0.0, self.hurt_timer - dt)
        self.hp_show_timer = max(0.0, self.hp_show_timer - dt)
        self.aim_mark = max(0.0, self.aim_mark - dt)
        self.explosion_mark = max(0.0, self.explosion_mark - dt)
        self.vulnerable_timer = max(0.0, self.vulnerable_timer - dt)
        if self.vulnerable_timer <= 0.0:
            self.vulnerable_mul = 1.0

        # атака по игроку: сначала телеграф, потом удар. Игрок всегда
        # успевает отступить перекатом — урон перестаёт быть «внезапным».
        touching = circles_collide(
            self.x, self.y, self.radius, player.x, player.y, player.radius
        )
        if self.windup_timer > 0.0:
            self.windup_timer -= dt
            if self.windup_timer <= 0.0:
                self.windup_timer = 0.0
                if touching and self.damage > 0:
                    player.take_damage(self.damage, game)
                    self.attack_timer = self.attack_delay
                game.spawn_enemy_attack(self)
        elif touching and self.attack_timer <= 0.0 and self.damage > 0:
            self.windup_timer = self.windup_total
            soundbank.play("swing", 0.28)

    def _steering(self, game, dt):
        """
        Куда идти в этом кадре (M9).

        Раз в repath_interval враг «осматривается»:
          * игрок виден напрямую -> идём по прямой (как раньше);
          * между ними стена -> строим путь A* и идём по точкам;
          * путь не найден -> идём напрямую (упрёмся в стену, но не зависнем).

        Важная экономия: пока текущая первая точка пути ещё достижима
        по прямой, A* НЕ пересчитывается — иначе вся орда строила бы
        новый путь каждые полсекунды, даже не меняя маршрут (стресс-тест
        M9: худший кадр 250 ms без этой проверки).

        Пока идём по пути, каждая достигнутая точка снимается со списка.
        """
        player = game.player
        self.path_timer -= dt
        if self.path_timer <= 0.0:
            self.path_timer = self.repath_interval
            if has_line_of_sight(game.world, self.x, self.y,
                                 player.x, player.y):
                self.path = []
            elif self.path:
                # путь есть — обновляемся, только если до ближайшей
                # точки больше не видно (она стала недостижимой)
                tx, ty = self.path[0]
                if not has_line_of_sight(game.world, self.x, self.y, tx, ty):
                    self.path = find_path(game.world, (self.x, self.y),
                                          (player.x, player.y),
                                          radius=self.radius) or []
            else:
                self.path = find_path(game.world, (self.x, self.y),
                                      (player.x, player.y),
                                      radius=self.radius) or []

        while (self.path
               and distance(self.x, self.y, *self.path[0]) <= ENEMY_WAYPOINT_REACH):
            self.path.pop(0)
        if self.path:
            tx, ty = self.path[0]
            return math.atan2(ty - self.y, tx - self.x)
        return math.atan2(player.y - self.y, player.x - self.x)

    def _strafe(self, elapsed):
        """Дополнительное отклонение от прямой линии. Базовое = нет."""
        return 0.0

    def _separate(self, game):
        """
        Мягко расталкивает соседей. Без этого толпа сходится в один
        комок: не видно, сколько врагов перед тобой, и все удары
        прилетают одновременно. Боссов не толкаем — у них своя арена.
        """
        if getattr(self, "is_boss", False):
            return
        reach = self.radius * 2.2
        for other in game.enemy_index.query(self.x, self.y, reach):
            if other is self or getattr(other, "is_boss", False):
                continue
            dx = self.x - other.x
            dy = self.y - other.y
            d2 = dx * dx + dy * dy
            # 1.18 — чуть больше суммы радиусов: силуэты не наезжают
            # друг на друга, и по толпе видно, сколько врагов реально идёт
            min_d = (self.radius + other.radius) * 1.18
            if d2 >= min_d * min_d:
                continue
            if d2 < 0.0001:
                # ровно в одной точке — расталкиваем по фазе анимации
                dx, dy = math.cos(self.anim_phase), math.sin(self.anim_phase)
                d = 1.0
            else:
                d = math.sqrt(d2)
            push = (min_d - d) * 0.5
            self.x += dx / d * push
            self.y += dy / d * push

    def take_damage(self, amount):
        self.hp -= amount
        self.hurt_timer = 0.12
        self.hp_show_timer = 2.5
        if self.hp <= 0:
            self.kill()

    def draw(self, screen, camera):
        cx, cy = camera.to_screen(self.x, self.y)
        cx, cy = int(cx), int(cy)
        bob = math.sin(self.anim_phase) * 1.2
        by = cy + bob
        body_r = max(15, int(self.radius * 1.35))

        visuals.shadow(screen, cx, cy + self.radius * 0.6, body_r, 0.95)

        # лёгкий наклон/рывок в момент замаха — удар читается телом
        lunge = 0.0
        if self.windup_timer > 0.0:
            t = 1.0 - self.windup_timer / self.windup_total
            lunge = math.sin(t * math.pi) * 4.0
        bx = cx + math.cos(self.angle) * lunge
        by += math.sin(self.angle) * lunge

        sprite = visuals.character(self.sprite_name, body_r, self.angle)
        screen.blit(sprite, sprite.get_rect(center=(bx, by)))

        if self.hurt_timer > 0.0:
            t = min(1.0, self.hurt_timer / 0.12)
            visuals.draw_hit_flash(screen, bx, by, body_r * 0.9, t)

    def draw_overlay(self, screen, camera):
        """Боевые индикаторы ПОВЕРХ темноты: телеграф, HP, метки."""
        if not self.alive:
            return
        cx, cy = camera.to_screen(self.x, self.y)
        cx, cy = int(cx), int(cy)
        body_r = max(15, int(self.radius * 1.35))

        if getattr(self, "elite", False):
            visuals.draw_ring(screen, cx, cy, body_r + 5, (255, 196, 90), 2, 190)
            for dx in (-6, 0, 6):
                pygame.draw.polygon(screen, (255, 214, 110), [
                    (cx + dx, cy - body_r - 12),
                    (cx + dx + 4, cy - body_r - 20),
                    (cx + dx + 8, cy - body_r - 12),
                ])

        # телеграф удара: пульсирующая красная дуга в сторону игрока
        if self.windup_timer > 0.0:
            t = 1.0 - self.windup_timer / self.windup_total
            color = (255, int(80 + 80 * t), 70)
            radius = body_r + 7
            arc = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            pygame.draw.arc(arc, (*color, int(130 + 125 * t)),
                            (4, 4, radius * 2, radius * 2),
                            self.angle - 0.9, self.angle + 0.9, 4)
            screen.blit(arc, arc.get_rect(center=(cx, cy)))
            visuals.draw_ring(screen, cx, cy, radius + 2, color, 1,
                              int(90 + 120 * t))

        # ИНДИКАТОРЫ ВЕТВЕЙ (M11): «метка» снайперки и «след взрыва»
        if self.explosion_mark > 0.0:
            visuals.draw_ring(screen, cx, cy, body_r + 5, (255, 150, 40), 2, 190)
        if self.aim_mark > 0.0:
            t = min(1.0, self.aim_mark / AIM_MARK_TIME)
            side = 6
            color = (255, 230, int(90 + 140 * t))
            pygame.draw.polygon(screen, color, [
                (cx, cy - body_r - 8 - side),
                (cx + side, cy - body_r - 8),
                (cx, cy - body_r - 8 + side),
                (cx - side, cy - body_r - 8),
            ])
        if getattr(self, "bleed_remaining", 0.0) > 0.0:
            visuals.draw_ring(screen, cx, cy, body_r + 2, (196, 76, 104), 1, 110)

        # здоровье: только когда ранен и недавно получал урон, чтобы
        # полоски не висели над каждым задетым врагом всю перестрелку
        if self.hp < self.max_hp and self.hp_show_timer > 0.0:
            w = max(30, int(self.radius * 2.2))
            ratio = max(0.0, self.hp / self.max_hp)
            bar_rect = pygame.Rect(cx - w // 2, cy - body_r - 14, w, 4)
            color = (255, 198, 96) if getattr(self, "elite", False) else (232, 92, 84)
            pygame.draw.rect(screen, (16, 20, 28), bar_rect.inflate(2, 2))
            pygame.draw.rect(screen, color,
                             (bar_rect.x, bar_rect.y, int(w * ratio), 4))


class Runner(Enemy):
    """Быстрый и слабый враг — вьётся зигзагом. Много патронов 9 мм."""

    color = RUNNER_COLOR
    radius = 13
    max_hp = 30
    speed = 175
    damage = 8
    score = 150
    bounty = 4
    sprite_name = "runner"

    drops = (
        {"type": "coin", "chance": 0.18, "min": 4, "max": 8},
        {"type": "ammo", "chance": 0.55, "min": 4, "max": 8},
    )

    def _strafe(self, elapsed):
        # зигзаг: синус меняет направление примерно 4 раза в секунду
        return math.sin(elapsed * 8.0 + self.x * 0.01) * 0.55


class Tank(Enemy):
    """Медленный, но очень живучий враг. Богатый и редкий дроп."""

    color = TANK_COLOR
    radius = 27
    max_hp = 160
    speed = 52
    damage = 22
    score = 300
    bounty = 7          # танк богат и на награде — «целевые» убийства
    attack_delay = 1.4
    sprite_name = "tank"

    drops = (
        {"type": "coin", "chance": 0.35, "min": 12, "max": 25},
        # M11: две типизированные строки (12ga/7.62) схлопнуты в одну
        {"type": "ammo", "chance": 0.55, "min": 6, "max": 10},
        {"type": "heal", "chance": 0.22, "min": 1, "max": 2},
        {"type": "artifact", "chance": 0.08, "min": 1, "max": 1},  # редчайший дроп
        # M7: танк иногда роняет ИМЕННО легендарку — ключ указан прямо
        {"type": "artifact", "chance": 0.03, "key": "heart",
         "min": 1, "max": 1},
    )


class Bomber(Enemy):
    """
    Взрывальщик: когтями НЕ бьёт (damage = 0), но когда игрок
    подходит ближе trigger_range — запускает фитиль и взрывается.
    Отбежал — фитиль сбрасывается. Убит до взрыва — не взрывается,
    но всё равно даёт дроп (грави-гранаты!). Взрыв наносит урон
    ВСЕМ, включая самого бомбера и игрока, — Game.explode() сам
    разберётся, кого и как бить.
    """

    color = (196, 108, 40)
    radius = 16
    max_hp = 40
    speed = 115
    damage = 0
    score = 120
    bounty = 4
    sprite_name = "bomber"

    explosion_radius = 115
    explosion_damage = 38
    explosion_knockback = 460
    fuse_time = 1.0
    trigger_range = 135      # с какой дистанции начинается фитиль
    escape_range = 200       # дальше — фитиль сбрасывается

    drops = (
        {"type": "grenade", "chance": 0.55, "min": 1, "max": 1},
        {"type": "coin", "chance": 0.25, "min": 5, "max": 11},
        {"type": "ammo", "chance": 0.35, "min": 3, "max": 5},
    )

    def __init__(self, x, y):
        super().__init__(x, y)
        self.fuse = None      # None = фитиля нет

    def update(self, dt, game):
        super().update(dt, game)
        if not self.alive:
            return
        dist = distance(self.x, self.y, game.player.x, game.player.y)

        if self.fuse is None:
            if dist <= self.trigger_range:
                self.fuse = self.fuse_time
        elif dist > self.escape_range:
            self.fuse = None               # оторвались — взвод отменён
        else:
            self.fuse -= dt
            if self.fuse <= 0.0:
                # взрыв убивает и самого бомбера: урон и дроп оформит Game
                game.explode(
                    self.x, self.y,
                    self.explosion_radius,
                    self.explosion_damage,
                    self.explosion_knockback,
                )

    def draw_overlay(self, screen, camera):
        super().draw_overlay(screen, camera)
        if self.fuse is None:
            return
        # сжимающееся кольцо + мигание: читается как «сейчас рванёт»
        sx, sy = camera.to_screen(self.x, self.y)
        frac = self.fuse / self.fuse_time
        ring = int(self.radius + 34 * frac)
        blink = int(self.fuse * 12) % 2 == 0
        color = (255, 92, 48) if blink else (255, 196, 84)
        visuals.draw_ring(screen, sx, sy, ring, color, 2, 230)
        visuals.draw_ring(screen, sx, sy, max(6, ring - 7), color, 1, 90)
        visuals.text(screen, f"{max(0.0, self.fuse):.1f}",
                     (sx, sy - ring - 18), 18, color, align="center")


class Stalker(Runner):
    """Поздний быстрый охотник с большим уроном и резким зигзагом."""

    color = (194, 66, 118)
    radius = 15
    max_hp = 65
    speed = 205
    damage = 16
    score = 240
    bounty = 5
    sprite_name = "stalker"

    def _strafe(self, elapsed):
        return math.sin(elapsed * 11.0 + self.x * 0.02) * 0.8


class Brute(Tank):
    """Поздний тяжёлый враг с большим запасом HP и сильными ударами."""

    color = (116, 52, 62)
    radius = 32
    max_hp = 280
    speed = 44
    damage = 34
    score = 500
    bounty = 12         # боссоподобный — главный источник поздних денег
    attack_delay = 1.5
    sprite_name = "brute"


class Spitter(Enemy):
    """
    Дальний враг (M12): держит дистанцию и плюёт кислотой.

    Он не бьёт в упор (damage = 0), а заставляет двигаться: снаряд
    летит по прямой, направление фиксируется в начале телеграфа, и
    рывок в сторону — честный ответ. Вблизи Spitter отступает, поэтому
    его нельзя просто «зажать в углу» очередью.
    """

    color = (88, 182, 138)
    radius = 15
    max_hp = 46
    speed = 96
    damage = 0
    score = 180
    bounty = 5
    sprite_name = "spitter"

    keep_min = 200          # ближе — отступает
    keep_max = 360          # дальше — подходит
    fire_range = 520
    fire_cooldown = 2.35
    telegraph = 0.55
    shot_damage = 12

    drops = (
        {"type": "coin", "chance": 0.20, "min": 4, "max": 9},
        {"type": "ammo", "chance": 0.60, "min": 5, "max": 9},
        {"type": "heal", "chance": 0.05, "min": 1, "max": 1},
    )

    def __init__(self, x, y):
        super().__init__(x, y)
        self.fire_timer = random.uniform(0.7, 1.5)
        self.charge_timer = 0.0
        self.charge_total = self.telegraph
        self.fire_angle = 0.0
        self.strafe_sign = random.choice((-1, 1))
        self._last_distance = 999.0

    def update(self, dt, game):
        super().update(dt, game)
        if not self.alive:
            return
        player = game.player
        dist = distance(self.x, self.y, player.x, player.y)
        self.fire_timer = max(0.0, self.fire_timer - dt)

        if self.charge_timer > 0.0:
            self.charge_timer -= dt
            if self.charge_timer <= 0.0:
                self.charge_timer = 0.0
                if (dist <= self.fire_range * 1.2
                        and has_line_of_sight(game.world, self.x, self.y,
                                              player.x, player.y)):
                    game.spawn_enemy_shot(self, self.fire_angle)
                self.fire_timer = self.fire_cooldown * random.uniform(0.85, 1.2)
        elif (self.fire_timer <= 0.0 and dist <= self.fire_range
              and has_line_of_sight(game.world, self.x, self.y,
                                    player.x, player.y)):
            # направление фиксируется сейчас: игрок видит линию и успевает уйти
            self.fire_angle = math.atan2(player.y - self.y, player.x - self.x)
            self.charge_timer = self.charge_total
            soundbank.play("spit_charge", 0.4)

    def _steering(self, game, dt):
        toward = super()._steering(game, dt)
        player = game.player
        dist = distance(self.x, self.y, player.x, player.y)
        self._last_distance = dist
        if dist < self.keep_min:
            # отход по диагонали: не разворачивается спиной к игроку
            return toward + math.pi * 0.82 * self.strafe_sign
        if dist > self.keep_max:
            return toward
        # в «рабочей» дистанции — круговое движение вокруг цели
        return toward + 1.15 * self.strafe_sign

    def draw_overlay(self, screen, camera):
        super().draw_overlay(screen, camera)
        if not self.alive or self.charge_timer <= 0.0:
            return
        cx, cy = camera.to_screen(self.x, self.y)
        cx, cy = int(cx), int(cy)
        progress = 1.0 - self.charge_timer / max(0.001, self.charge_total)
        color = (150, 255, 188)
        # прицельная линия: куда именно уйдёт сгусток
        length = 250
        ex = cx + math.cos(self.fire_angle) * length
        ey = cy + math.sin(self.fire_angle) * length
        for i in range(0, 9):
            t0 = i / 9
            t1 = t0 + 0.045
            pygame.draw.line(screen, (54, 92, 70),
                             (cx + (ex - cx) * t0, cy + (ey - cy) * t0),
                             (cx + (ex - cx) * t1, cy + (ey - cy) * t1), 2)
        pygame.draw.line(screen, (72, 148, 104),
                         (cx, cy), (ex, ey), 1)
        radius = 13 + int(7 * progress)
        visuals.draw_ring(screen, cx, cy, radius, color, 2,
                          int(120 + 120 * progress))
        pygame.draw.circle(screen, (212, 255, 210), (cx, cy),
                           max(2, int(4 * progress)))
