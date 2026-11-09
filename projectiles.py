"""
Снаряды и визуальные эффекты: пуля, вспышка выстрела, частицы.
"""
import math
import random

import pygame
import spritebank
import visuals

from settings import (
    BULLET_COLOR,
    BULLET_LIFETIME,
    FLASH_DURATION,
    GRENADE_DAMAGE,
    GRENADE_FUSE,
    GRENADE_KNOCKBACK,
    GRENADE_RADIUS,
    GRENADE_SPEED,
    HOMING_RANGE,
    HOMING_TURN,
    TILE,
    WALL_PEN_LOSS,
)
from game_object import GameObject
from utils import mix


class Bullet(GameObject):
    """
    Пуля: летит по прямой, живёт ограничено, светится в темноте.

    Характеристики приходят ИЗ ОРУЖИЯ в конструкторе (weapon.resolve_shot)
    — одна пуля обслуживает пистолет, дробовик и винтовку (принцип DRY).

    M11 — механики ветвей читаются из тех же kwargs:
      wall_pen     — сколько ТОЛЩИН СТЕН пуля проходит («Пробой»);
      ricochets    — сколько раз может отразиться от стен;
      homing       — после отражения наводится на ближайшую цель;
      enemy_bounce — рикошет ОТ ВРАГА, когда пробитие исчерпано;
      growth       — на сколько растёт урон после каждого попадания;
      explode      — радиус взрыва при попадании («Подрывник»);
      cascade      — радиус вторичного взрыва при убийстве;
      knockback    — сила отбрасывания при попадании;
      close_bonus  — множитель урона вблизи точки выстрела;
      mark_id/mark_bonus   — «Метка»: бьём именно отмеченную цель;
      refund_kill_*        — «Экономист»: возврат боезапаса за убийство.
    """

    emissive = True          # рисуется ПОСЛЕ темноты — видна даже в темноте

    def __init__(self, x, y, angle, damage, speed, radius, pierce=0,
                 ricochets=0, wall_pen=0, homing=0, enemy_bounce=0,
                 growth=0.0, explode=0.0, cascade=0.0, knockback=0.0,
                 close_bonus=0.0, mark_id=None, mark_bonus=0.0,
                 refund_kill_chance=0.0, refund_kill_amount=0,
                 bleed=0.0, bleed_spread=0.0, bleed_spread_radius=90.0,
                 explosion_bleed=0.0, explosion_slow=0.0,
                 close_stun=0.0, close_stun_range=0.0,
                 impact_slow=0.0, impact_slow_factor=0.5,
                 impact_slow_radius=0.0, bounce_growth=0.0,
                 bounced_bonus=0.0, bounced_mark=0.0,
                 pierce_vulnerable=0.0, mark_vulnerable=0.0,
                 mark_duration=1.5, cascade_shrapnel=0,
                 explosion_power=1.0, explosion_vulnerable=0.0,
                 explosion_color=None, style="bullet", color=None,
                 charge=0.0, blast_stun=0.0, return_range=0.0,
                 return_speed_mul=1.0, return_damage_mul=0.0,
                 recall_speed_mul=1.0, catch_refund=0.0, chain_jumps=0,
                 chain_range=0.0, chain_falloff=0.72,
                 chain_damage_mul=1.0, heat=0.0):
        super().__init__(x, y)
        self.spawn_x, self.spawn_y = x, y   # точка выстрела (для «в упор»)
        self.damage = damage
        self.radius = radius
        self.pierce = pierce            # сколько врагов пуля задевает «бесплатно»
        self.hits = 0                   # сколько уже задела
        self.hit_enemies = set()        # id() врагов — чтобы не бить одного дважды
        self.life = BULLET_LIFETIME
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        # --- механики ветвей (M11) ---
        self.ricochets = ricochets
        self.wall_pen = wall_pen
        self.homing = bool(homing)
        self.enemy_bounce = enemy_bounce
        self.growth = growth
        self.explode = explode
        self.cascade = cascade
        self.knockback = knockback
        self.close_bonus = close_bonus
        self.mark_id = mark_id
        self.mark_bonus = mark_bonus
        self.refund_kill_chance = refund_kill_chance
        self.refund_kill_amount = refund_kill_amount
        # --- поздние доктрины (tier 5) ---
        self.bleed = bleed
        self.bleed_spread = bleed_spread
        self.bleed_spread_radius = bleed_spread_radius
        self.explosion_bleed = explosion_bleed
        self.explosion_slow = explosion_slow
        self.close_stun = close_stun
        self.close_stun_range = close_stun_range
        self.impact_slow = impact_slow
        self.impact_slow_factor = impact_slow_factor
        self.impact_slow_radius = impact_slow_radius
        self.bounce_growth = bounce_growth
        self.bounced_bonus = bounced_bonus
        self.bounced_mark = bounced_mark
        self.pierce_vulnerable = pierce_vulnerable
        self.mark_vulnerable = mark_vulnerable
        self.mark_duration = mark_duration
        self.cascade_shrapnel = cascade_shrapnel
        # --- энергетический снаряд (M14) ---
        self.explosion_power = explosion_power
        self.explosion_vulnerable = explosion_vulnerable
        self.explosion_color = explosion_color
        self.style = style
        self.color = tuple(color or BULLET_COLOR)
        self.charge = max(0.0, min(1.0, charge))
        self.blast_stun = blast_stun
        # --- управляемая траектория (магнитный диск, M16) ---
        self.return_range = float(return_range)
        self.return_speed_mul = float(return_speed_mul)
        self.return_damage_mul = float(return_damage_mul)
        self.recall_speed_mul = float(recall_speed_mul)
        self.catch_refund = float(catch_refund)
        self.returning = False
        self.recalling = False
        self.caught = False
        self.return_speed = 0.0
        # --- цепная атака (дуговая пушка, M16) ---
        self.chain_jumps = int(chain_jumps)
        self.chain_range = float(chain_range)
        self.chain_falloff = float(chain_falloff)
        self.chain_damage_mul = float(chain_damage_mul)
        self.chain_hit = set()
        # --- тепло (плазменный резак, M16) ---
        self.heat = max(0.0, min(1.0, float(heat)))
        # --- управляемая траектория (магнитный диск, M16) ---
        self.return_range = float(return_range)
        self.return_speed_mul = float(return_speed_mul)
        self.return_damage_mul = float(return_damage_mul)
        self.recall_speed_mul = float(recall_speed_mul)
        self.catch_refund = float(catch_refund)
        self.returning = False
        self.recalling = False
        self.caught = False
        self.return_speed = 0.0
        # --- цепная атака (дуговая пушка, M16) ---
        self.chain_jumps = int(chain_jumps)
        self.chain_range = float(chain_range)
        self.chain_falloff = float(chain_falloff)
        self.chain_damage_mul = float(chain_damage_mul)
        self.chain_hit = set()
        # --- тепло (плазменный резак, M16) ---
        self.heat = max(0.0, min(1.0, float(heat)))
        self.bounced = False             # было ли уже отражение (включает наведение)
        self._pen_tiles = set()          # блоки стен, в которые пуля уже вошла
        self._bounce_tiles = set()       # тайлы, от которых уже отражались
        # мягкое свечение вокруг пули рисуем один раз; размер зависит от
        # хитбокса, поэтому плазменный шар не выглядит маленькой пулей.
        halo_r = max(9, int(round(self.radius * 3)))
        self._halo = pygame.Surface((halo_r * 2, halo_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(self._halo, (*self.color, 44),
                           (halo_r, halo_r), halo_r)
        pygame.draw.circle(self._halo, (*self.color, 68),
                           (halo_r, halo_r), max(2, int(halo_r * 0.62)))

    def pierces_further(self):
        """Можно ли лететь дальше после очередного попадания."""
        return self.hits <= self.pierce

    def update(self, dt, game):
        if self.return_range > 0.0:
            if self.returning:
                self._steer_home(game)
            elif math.hypot(self.x - self.spawn_x,
                            self.y - self.spawn_y) >= self.return_range:
                self.begin_return()
                self._steer_home(game)
        if self.homing and self.bounced:
            self._steer(dt, game)
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.kill()
            return
        if game.world.is_solid_at(self.x, self.y):
            self._hit_wall(game)
        elif self.style == "plasma" and self.radius > 10:
            # Крупный плазменный шар не должен «залезать» в стену углом:
            # проверяем несколько точек по его краю, а не только центр.
            if self._edge_hits_wall(game):
                self.kill()

    def _edge_hits_wall(self, game):
        probe = max(4.0, self.radius * 0.72)
        for i in range(8):
            angle = math.tau * i / 8
            if game.world.is_solid_at(self.x + math.cos(angle) * probe,
                                      self.y + math.sin(angle) * probe):
                return True
        return False

    # ---------------------------------------------------- СТЕНЫ (M11)
    def _hit_wall(self, game):
        """
        Пуля упёрлась в стену. Порядок решений:
        1) есть неизведанная толщина стены + wall_pen → пробить
           (урон умножается на 1 − WALL_PEN_LOSS);
        2) есть рикошеты и этот тайл ещё не отражался → отразиться;
        3) иначе — пуля погибает (как в M1–M10).
        """
        tile = (math.floor(self.x / TILE), math.floor(self.y / TILE))
        if tile in self._pen_tiles:
            return
        if self.wall_pen > 0:
            self._pen_tiles.add(tile)
            self.wall_pen -= 1
            self.damage *= 1.0 - WALL_PEN_LOSS   # толща стены «съедает» половину
            return                                # летим сквозь
        if self.returning and tile not in self._bounce_tiles:
            # Диск на возврате не гаснет о первую же колонну: он
            # отскакивает и продолжает путь к герою.
            self._bounce_tiles.add(tile)
            self._reflect(game)
            return
        if self.ricochets > 0 and tile not in self._bounce_tiles:
            self._bounce_tiles.add(tile)
            self.ricochets -= 1
            self._reflect(game)
            return
        self.kill()

    def _reflect(self, game):
        """Отражение от стены: узнаём ориентацию поверхности зондом."""
        eps = 4.0
        solid_x = game.world.is_solid_at(
            self.x + math.copysign(eps, self.vx), self.y)
        solid_y = game.world.is_solid_at(
            self.x, self.y + math.copysign(eps, self.vy))
        if solid_x and not solid_y:
            self.vx = -self.vx            # вертикальная стена — меняем dx
        elif solid_y and not solid_x:
            self.vy = -self.vy            # горизонтальная — меняем dy
        else:
            self.vx, self.vy = -self.vx, -self.vy   # угол/диагональ
        self.bounced = True
        if self.bounce_growth:
            self.damage *= 1.0 + self.bounce_growth
        # выпихиваем пулю из стены в новом направлении
        angle = math.atan2(self.vy, self.vx)
        self.x += math.cos(angle) * 3.0
        self.y += math.sin(angle) * 3.0

    # ---------------------------------------------------- НАВЕДЕНИЕ (M11)
    def _steer(self, dt, game):
        """После отражения пуля доворачивает к ближайшей цели («Наведение»)."""
        best, best_d = None, HOMING_RANGE
        for enemy in game.enemies:
            if not enemy.alive:
                continue
            d = math.hypot(enemy.x - self.x, enemy.y - self.y)
            if d < best_d:
                best, best_d = enemy, d
        if best is None:
            return
        want = math.atan2(best.y - self.y, best.x - self.x)
        cur = math.atan2(self.vy, self.vx)
        diff = (want - cur + math.pi) % math.tau - math.pi   # кратчайший поворот
        turn = max(-HOMING_TURN * dt, min(HOMING_TURN * dt, diff))
        speed = math.hypot(self.vx, self.vy)
        new = cur + turn
        self.vx, self.vy = math.cos(new) * speed, math.sin(new) * speed

    def retarget(self, enemies):
        """
        Рикошет ОТ ВРАГА («Цепной рикошет»): пробитие исчерпано, но пуля
        перенаправляется на ближайшую ещё не задетую цель и летит дальше.
        """
        best, best_d = None, HOMING_RANGE
        for enemy in enemies:
            if not enemy.alive or id(enemy) in self.hit_enemies:
                continue
            d = math.hypot(enemy.x - self.x, enemy.y - self.y)
            if d < best_d:
                best, best_d = enemy, d
        if best is None:
            return False
        angle = math.atan2(best.y - self.y, best.x - self.x)
        speed = math.hypot(self.vx, self.vy)
        self.vx, self.vy = math.cos(angle) * speed, math.sin(angle) * speed
        self.bounced = True
        if self.bounce_growth:
            self.damage *= 1.0 + self.bounce_growth
        return True

    # ---------------------------------------------------- ВОЗВРАТ (M16)
    def begin_return(self, recalled=False):
        """Диск достиг предела (или его подозвали) и летит назад."""
        if self.returning or self.return_range <= 0.0:
            return False
        speed = math.hypot(self.vx, self.vy) or 1.0
        self.returning = True
        self.recalling = self.recalling or recalled
        self.return_speed = speed * (self.recall_speed_mul
                                     if recalled else self.return_speed_mul)
        # Обратный проход — вторая атака: те же враги снова уязвимы.
        self.hits = 0
        self.hit_enemies.clear()
        self.chain_hit.clear()
        return True

    def recall(self):
        """Ручной подзыв: игрок завершает проход раньше срока."""
        if self.returning:
            self.recalling = True
            self.return_speed *= self.recall_speed_mul
            return True
        return self.begin_return(recalled=True)

    def _steer_home(self, game):
        """Обратный путь всегда ведёт к герою: движение «рулит» диском."""
        player = getattr(game, "player", None)
        if player is None or not getattr(player, "alive", True):
            return
        dx, dy = player.x - self.x, player.y - self.y
        dist = math.hypot(dx, dy) or 1.0
        speed = max(self.return_speed, 1.0)
        self.vx = dx / dist * speed
        self.vy = dy / dist * speed

    def draw(self, screen, camera):
        cx, cy = camera.to_screen(self.x, self.y)
        cx, cy = int(cx), int(cy)
        speed = math.hypot(self.vx, self.vy) or 1.0
        if self.style in ("disc", "arc", "cutter"):
            self._draw_special(screen, cx, cy)
            return
        if self.style == "plasma":
            # Плазменный сгусток: длинный цветной шлейф, ядро и кольцо.
            # Чем сильнее заряд, тем крупнее и ярче — читается без HUD.
            tail = min(78.0, speed * 0.040 + self.radius * 1.5)
            tx = int(cx - self.vx / speed * tail)
            ty = int(cy - self.vy / speed * tail)
            dim = mix(self.color, (18, 34, 52), 0.45)
            pygame.draw.line(screen, dim, (tx, ty), (cx, cy),
                             max(3, int(self.radius * 1.15)))
            pygame.draw.line(screen, self.color, (tx, ty), (cx, cy),
                             max(1, int(self.radius * 0.48)))
            screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
            r = max(2, int(round(self.radius)))
            pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.12),
                               (cx, cy), r)
            pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.55),
                               (cx, cy), max(1, int(r * 0.62)))
            pygame.draw.circle(screen, (255, 255, 255), (cx, cy),
                               max(1, int(r * 0.28)))
            visuals.draw_ring(screen, cx, cy, r + 4, self.color, 1,
                              105 + int(90 * self.charge))
            return
        # трассер: короткий шлейф делает скорость оружия читаемой
        tail = min(30.0, speed * 0.035)
        tx = int(cx - self.vx / speed * tail)
        ty = int(cy - self.vy / speed * tail)
        pygame.draw.line(screen, (255, 166, 70), (tx, ty), (cx, cy),
                         max(2, int(self.radius * 0.9)))
        screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
        sprite = spritebank.get_scaled("projectile/bullet", (max(4, self.radius * 2), max(4, self.radius * 2)))
        if sprite is not None:
            screen.blit(sprite, sprite.get_rect(center=(cx, cy)))
        else:
            pygame.draw.circle(screen, self.color, (cx, cy), self.radius)
            pygame.draw.circle(screen, (255, 250, 220), (cx, cy), max(1, self.radius // 2))


    def _draw_special(self, screen, cx, cy):
        """Стили новых школ: диск, дуга и резак читаются по силуэту."""
        speed = math.hypot(self.vx, self.vy) or 1.0
        ux, uy = self.vx / speed, self.vy / speed
        if self.style == "disc":
            # Диск: короткий след поперёк движения и светящееся кольцо.
            trail = 26.0 if self.returning else 18.0
            pygame.draw.line(screen, mix(self.color, (40, 30, 20), 0.55),
                             (cx - ux * trail, cy - uy * trail), (cx, cy),
                             max(2, int(self.radius * 0.7)))
            screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
            r = max(3, int(self.radius))
            pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.2),
                               (cx, cy), r, 2)
            pygame.draw.circle(screen, mix(self.color, (20, 24, 30), 0.35),
                               (cx, cy), max(1, r - 4))
            pygame.draw.circle(screen, (255, 252, 236), (cx, cy),
                               max(1, int(r * 0.3)))
            if self.returning:
                visuals.draw_ring(screen, cx, cy, r + 5, self.color, 1, 150)
            return
        if self.style == "arc":
            # Электрическая игла: дрожащий штрих с ярким ядром.
            tail = min(34.0, speed * 0.03 + self.radius * 2.0)
            jitter = 2.0 if int(self.life * 60) % 2 else -2.0
            pygame.draw.line(screen, mix(self.color, (24, 30, 52), 0.5),
                             (cx - ux * tail, cy - uy * tail + jitter),
                             (cx, cy), max(2, int(self.radius * 0.8)))
            pygame.draw.line(screen, self.color,
                             (cx - ux * tail, cy - uy * tail - jitter),
                             (cx, cy), 1)
            screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
            pygame.draw.circle(screen, (240, 250, 255), (cx, cy), 2)
            return
        # Резак: короткая горячая струя, длина растёт с нагревом.
        tail = min(46.0, speed * 0.03 + 12.0 * (1.0 + self.heat))
        hot = mix(self.color, (255, 236, 190), 0.35 + 0.5 * self.heat)
        pygame.draw.line(screen, mix(self.color, (40, 20, 18), 0.5),
                         (cx - ux * tail, cy - uy * tail), (cx, cy),
                         max(3, int(self.radius * 1.4)))
        pygame.draw.line(screen, hot,
                         (cx - ux * tail * 0.6, cy - uy * tail * 0.6),
                         (cx, cy), max(1, int(self.radius * 0.7)))
        screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
        pygame.draw.circle(screen, (255, 248, 226), (cx, cy),
                           max(1, int(self.radius * 0.7)))


class ArcBolt(GameObject):
    """
    Дуга между двумя целями: молния живёт долю секунды и урона не
    наносит (его считает Game._chain_arc). Нужна, чтобы цепь читалась
    даже без цифр урона.
    """

    emissive = True

    def __init__(self, x1, y1, x2, y2, color=(150, 190, 255), life=0.18):
        super().__init__(x1, y1)
        self.color = tuple(color)
        self.life = self.max_life = life
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        self.points = [(x1, y1)]
        segments = 4
        for i in range(1, segments):
            t = i / segments
            offset = math.sin(t * math.pi) * random.uniform(-9.0, 9.0)
            self.points.append((x1 + dx * t + nx * offset,
                                y1 + dy * t + ny * offset))
        self.points.append((x2, y2))

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0.0:
            self.kill()

    def draw(self, screen, camera):
        alpha = max(0.0, self.life / max(self.max_life, 0.001))
        points = [camera.to_screen(x, y) for x, y in self.points]
        width = max(1, int(1 + 3 * alpha))
        for first, second in zip(points, points[1:]):
            pygame.draw.line(screen, mix(self.color, (16, 22, 40), 0.45),
                             first, second, width + 2)
        for first, second in zip(points, points[1:]):
            pygame.draw.line(screen, (236, 246, 255), first, second, 1)


    def _draw_special(self, screen, cx, cy):
        """Стили новых школ: диск, дуга и резак читаются по силуэту."""
        speed = math.hypot(self.vx, self.vy) or 1.0
        ux, uy = self.vx / speed, self.vy / speed
        if self.style == "disc":
            # Диск: короткий след поперёк движения и светящееся кольцо.
            trail = 26.0 if self.returning else 18.0
            pygame.draw.line(screen, mix(self.color, (40, 30, 20), 0.55),
                             (cx - ux * trail, cy - uy * trail), (cx, cy),
                             max(2, int(self.radius * 0.7)))
            screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
            r = max(3, int(self.radius))
            pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.2),
                               (cx, cy), r, 2)
            pygame.draw.circle(screen, mix(self.color, (20, 24, 30), 0.35),
                               (cx, cy), max(1, r - 4))
            pygame.draw.circle(screen, (255, 252, 236), (cx, cy),
                               max(1, int(r * 0.3)))
            if self.returning:
                visuals.draw_ring(screen, cx, cy, r + 5, self.color, 1, 150)
            return
        if self.style == "arc":
            # Электрическая игла: дрожащий штрих с ярким ядром.
            tail = min(34.0, speed * 0.03 + self.radius * 2.0)
            jitter = 2.0 if int(self.life * 60) % 2 else -2.0
            pygame.draw.line(screen, mix(self.color, (24, 30, 52), 0.5),
                             (cx - ux * tail, cy - uy * tail + jitter),
                             (cx, cy), max(2, int(self.radius * 0.8)))
            pygame.draw.line(screen, self.color,
                             (cx - ux * tail, cy - uy * tail - jitter),
                             (cx, cy), 1)
            screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
            pygame.draw.circle(screen, (240, 250, 255), (cx, cy), 2)
            return
        # Резак: короткая горячая струя, длина растёт с нагревом.
        tail = min(46.0, speed * 0.03 + 12.0 * (1.0 + self.heat))
        hot = mix(self.color, (255, 236, 190), 0.35 + 0.5 * self.heat)
        pygame.draw.line(screen, mix(self.color, (40, 20, 18), 0.5),
                         (cx - ux * tail, cy - uy * tail), (cx, cy),
                         max(3, int(self.radius * 1.4)))
        pygame.draw.line(screen, hot,
                         (cx - ux * tail * 0.6, cy - uy * tail * 0.6),
                         (cx, cy), max(1, int(self.radius * 0.7)))
        screen.blit(self._halo, self._halo.get_rect(center=(cx, cy)))
        pygame.draw.circle(screen, (255, 248, 226), (cx, cy),
                           max(1, int(self.radius * 0.7)))


class ArcBolt(GameObject):
    """
    Дуга между двумя целями: молния живёт долю секунды и урона не
    наносит (его считает Game._chain_arc). Нужна, чтобы цепь читалась
    даже без цифр урона.
    """

    emissive = True

    def __init__(self, x1, y1, x2, y2, color=(150, 190, 255), life=0.18):
        super().__init__(x1, y1)
        self.color = tuple(color)
        self.life = self.max_life = life
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        self.points = [(x1, y1)]
        segments = 4
        for i in range(1, segments):
            t = i / segments
            offset = math.sin(t * math.pi) * random.uniform(-9.0, 9.0)
            self.points.append((x1 + dx * t + nx * offset,
                                y1 + dy * t + ny * offset))
        self.points.append((x2, y2))

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0.0:
            self.kill()

    def draw(self, screen, camera):
        alpha = max(0.0, self.life / max(self.max_life, 0.001))
        points = [camera.to_screen(x, y) for x, y in self.points]
        width = max(1, int(1 + 3 * alpha))
        for first, second in zip(points, points[1:]):
            pygame.draw.line(screen, mix(self.color, (16, 22, 40), 0.45),
                             first, second, width + 2)
        for first, second in zip(points, points[1:]):
            pygame.draw.line(screen, (236, 246, 255), first, second, 1)


class MuzzleFlash(GameObject):
    """Короткая яркая «звезда» у дула оружия."""

    emissive = True
    life_time = FLASH_DURATION

    def __init__(self, x, y, angle, color=None):
        super().__init__(x, y)
        self.angle = angle
        self.color = tuple(color or (255, 214, 120))
        self.life = self.life_time

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        x, y = camera.to_screen(self.x, self.y)
        t = max(0.0, self.life / self.life_time)
        # восьмиконечная звезда + кольцо: выстрел видно даже в тёмном коридоре
        points = []
        for i in range(16):
            a = self.angle + i * math.pi / 8
            r = (20 if i % 2 == 0 else 8) * (0.7 + 0.3 * t)
            points.append((x + math.cos(a) * r, y + math.sin(a) * r))
        pygame.draw.polygon(screen, self.color, points)
        core = []
        for i in range(16):
            a = self.angle + i * math.pi / 8
            r = (12 if i % 2 == 0 else 5) * (0.7 + 0.3 * t)
            core.append((x + math.cos(a) * r, y + math.sin(a) * r))
        pygame.draw.polygon(screen, mix(self.color, (255, 255, 255), 0.55), core)
        pygame.draw.circle(screen, (255, 255, 240), (int(x), int(y)), 4)
        visuals.draw_ring(screen, x, y, 13, self.color, 1, int(150 * t))


class Particle(GameObject):
    """Мелкая искра/капля: рождается со случайной скоростью и угасает."""

    def __init__(self, x, y, color):
        super().__init__(x, y)
        a = random.uniform(0, math.tau)
        speed = random.uniform(50, 160)
        self.vx = math.cos(a) * speed
        self.vy = math.sin(a) * speed
        self.life = self.max_life = random.uniform(0.3, 0.6)
        self.color = color
        self.size = random.randint(2, 4)

    def update(self, dt, game):
        self.x += self.vx * dt
        self.y += self.vy * dt
        damping = math.exp(-5.0 * dt)     # затухание, не зависящее от FPS
        self.vx *= damping
        self.vy *= damping
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        t = self.life / self.max_life     # 1 → только родился, 0 → угас
        color = mix((0, 0, 0), self.color, t)
        x, y = camera.to_screen(self.x, self.y)
        pygame.draw.circle(screen, color, (int(x), int(y)), self.size)


class Grenade(GameObject):
    """
    Брошенная граната (клавиша Q): летит, упирается в стену и
    «прилипает» к ней, а фитиль продолжает идти. Взрыв делает Game —
    этот класс отвечает только за полёт и таймер.
    """

    def __init__(self, x, y, angle):
        super().__init__(x, y)
        self.vx = math.cos(angle) * GRENADE_SPEED
        self.vy = math.sin(angle) * GRENADE_SPEED
        self.fuse = GRENADE_FUSE

    def update(self, dt, game):
        self.fuse -= dt
        if self.fuse <= 0.0:
            self.kill()
            game.explode(self.x, self.y, GRENADE_RADIUS,
                         GRENADE_DAMAGE, GRENADE_KNOCKBACK)
            return
        if self.vx or self.vy:
            nx = self.x + self.vx * dt
            ny = self.y + self.vy * dt
            if game.world.is_solid_at(nx, ny):
                self.vx = self.vy = 0.0     # врезалась — стоит на месте
            else:
                self.x, self.y = nx, ny

    def draw(self, screen, camera):
        x, y = camera.to_screen(self.x, self.y)
        cx, cy = int(x), int(y)
        sprite = spritebank.get_scaled("projectile/grenade", (16, 16))
        if sprite is not None:
            screen.blit(sprite, sprite.get_rect(center=(cx, cy)))
            return
        pygame.draw.circle(screen, (74, 96, 66), (cx, cy), 7)
        pygame.draw.circle(screen, (34, 44, 32), (cx, cy), 7, 2)
        # последняя секунда: красная точка мигает
        if self.fuse < 0.4 and int(self.fuse * 12) % 2 == 0:
            pygame.draw.circle(screen, (255, 80, 60), (cx, cy - 8), 3)


class Explosion(GameObject):
    """
    Визуал взрыва + источник света (light_radius). Сам УРОН наносит
    Game.explode() — этот класс лишь показывает и светит.
    """

    emissive = True            # рисуется после темноты — светится сам
    life_time = 0.35
    light_color = (255, 168, 84)

    def __init__(self, x, y, radius, color=None):
        super().__init__(x, y)
        self.color = tuple(color or (255, 168, 84))
        self.light_color = self.color
        self.max_radius = radius
        self.life = self.life_time
        self.current = radius * 0.4
        self.light_radius = int(self.current * 1.5)

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0.0:
            self.light_radius = 0
            self.kill()
            return
        progress = 1.0 - self.life / self.life_time      # 0 → 1
        self.current = self.max_radius * (0.4 + 0.6 * progress)
        self.light_radius = int(self.current * 1.5)      # свет растёт вместе с огнём

    def draw(self, screen, camera):
        x, y = camera.to_screen(self.x, self.y)
        cx, cy = int(x), int(y)
        r = int(self.current)
        progress = 1.0 - self.life / self.life_time
        # внешняя ударная волна
        ring = int(self.max_radius * (0.55 + 0.6 * progress))
        visuals.draw_ring(screen, cx, cy, ring, self.color, 3,
                          int(190 * (1 - progress)))
        sprite = spritebank.get_scaled("projectile/explosion", (r * 2, r * 2))
        if sprite is not None and self.color == (255, 168, 84):
            screen.blit(sprite, sprite.get_rect(center=(cx, cy)))
            return
        pygame.draw.circle(screen, mix(self.color, (120, 40, 10), 0.35),
                           (cx, cy), r)
        pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.18),
                           (cx, cy), int(r * 0.78))
        pygame.draw.circle(screen, mix(self.color, (255, 255, 255), 0.55),
                           (cx, cy), int(r * 0.5))
        pygame.draw.circle(screen, (255, 250, 220), (cx, cy), int(r * 0.24))


class FloatingText(GameObject):
    """Всплывающая цифра урона/награды. Живёт после темноты."""

    emissive = True

    def __init__(self, x, y, value, color=(255, 236, 190), size=20, rise=52.0):
        super().__init__(x, y)
        self.life = self.max_life = 0.72
        self.vx = random.uniform(-18.0, 18.0)
        self.vy = -rise
        self.color = color
        self.surface = visuals.font(size).render(str(value), True, color)
        self.dark = visuals.font(size).render(str(value), True, (6, 8, 14))

    def update(self, dt, game):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy *= math.exp(-2.4 * dt)
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        x, y = camera.to_screen(self.x, self.y)
        t = max(0.0, self.life / self.max_life)
        alpha = int(255 * min(1.0, t * 1.6))
        image = self.surface
        dark = self.dark
        image.set_alpha(alpha)
        dark.set_alpha(alpha)
        rect = image.get_rect(center=(int(x), int(y)))
        screen.blit(dark, (rect.x + 1, rect.y + 2))
        screen.blit(image, rect)


class Spark(GameObject):
    """Короткая искра-штрих от попадания."""

    emissive = True

    def __init__(self, x, y, angle, color=(255, 226, 160), speed=None):
        super().__init__(x, y)
        self.life = self.max_life = random.uniform(0.10, 0.20)
        speed = speed if speed is not None else random.uniform(130, 320)
        a = angle + random.uniform(-0.7, 0.7)
        self.vx = math.cos(a) * speed
        self.vy = math.sin(a) * speed
        self.color = color

    def update(self, dt, game):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= math.exp(-7.0 * dt)
        self.vy *= math.exp(-7.0 * dt)
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        t = max(0.0, self.life / self.max_life)
        x, y = camera.to_screen(self.x, self.y)
        pygame.draw.line(screen, self.color,
                         (int(x), int(y)),
                         (int(x - self.vx * 0.02), int(y - self.vy * 0.02)), 2)
        if t > 0.5:
            pygame.draw.circle(screen, (255, 250, 220), (int(x), int(y)), 1)


class DashGhost(GameObject):
    """Полупрозрачный след переката."""

    emissive = True

    def __init__(self, x, y, angle, radius, kind="player"):
        super().__init__(x, y)
        self.life = self.max_life = 0.22
        self.sprite = visuals.character(kind, radius, angle).copy()
        self.sprite.fill((110, 230, 220, 255), special_flags=pygame.BLEND_RGBA_MULT)

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        t = max(0.0, self.life / self.max_life)
        self.sprite.set_alpha(int(150 * t))
        screen.blit(self.sprite, self.sprite.get_rect(
            center=camera.to_screen(self.x, self.y)))


class Casing(GameObject):
    """Гильза: вылетает вбок от ствола и остывает на полу."""

    emissive = True

    def __init__(self, x, y, angle):
        super().__init__(x, y)
        side = angle + math.pi / 2
        speed = random.uniform(70, 130)
        self.vx = math.cos(side) * speed
        self.vy = math.sin(side) * speed
        self.life = self.max_life = 0.65
        self.spin = random.uniform(0, 6.28)

    def update(self, dt, game):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= math.exp(-4.0 * dt)
        self.vy *= math.exp(-4.0 * dt)
        self.spin += dt * 14
        self.life -= dt
        if self.life <= 0:
            self.kill()

    def draw(self, screen, camera):
        x, y = camera.to_screen(self.x, self.y)
        t = max(0.0, self.life / self.max_life)
        color = (226, 178, 84) if t > 0.35 else (150, 112, 58)
        rect = pygame.Rect(0, 0, 5, 2)
        rect.center = (int(x), int(y))
        pygame.draw.rect(screen, color, rect)


class EnemyShot(GameObject):
    """
    Сгусток кислоты, который выпускает Spitter (M12).

    Летит по прямой, гаснет о стену и подсвечивает коридор холодным
    фиолетово-зелёным светом. Урон наносит Game — класс отвечает
    только за полёт и читаемый визуал.
    """

    emissive = True
    light_color = (142, 222, 186)

    def __init__(self, x, y, angle, damage=12, speed=340.0, radius=7):
        super().__init__(x, y)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.damage = damage
        self.radius = radius
        self.life = 2.4
        self.light_radius = 54
        self._halo = pygame.Surface((radius * 6, radius * 6), pygame.SRCALPHA)
        pygame.draw.circle(self._halo, (120, 242, 176, 46),
                           (radius * 3, radius * 3), radius * 3)
        pygame.draw.circle(self._halo, (176, 255, 206, 70),
                           (radius * 3, radius * 3), radius * 2)

    def update(self, dt, game):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.kill()
            return
        if game.world.is_solid_at(self.x, self.y):
            for _ in range(5):
                game.effects.append(Spark(
                    self.x, self.y, random.uniform(0, math.tau),
                    (150, 248, 190), 120))
            self.kill()

    def draw(self, screen, camera):
        cx, cy = camera.to_screen(self.x, self.y)
        cx, cy = int(cx), int(cy)
        speed = math.hypot(self.vx, self.vy) or 1.0
        tx = int(cx - self.vx / speed * 16)
        ty = int(cy - self.vy / speed * 16)
        pygame.draw.line(screen, (34, 68, 54), (tx, ty), (cx, cy), 5)
        pygame.draw.line(screen, (126, 240, 168), (tx, ty), (cx, cy), 3)
        halo = self._halo
        screen.blit(halo, halo.get_rect(center=(cx, cy)))
        pygame.draw.circle(screen, (186, 255, 202), (cx, cy), self.radius)
        pygame.draw.circle(screen, (246, 255, 236), (cx, cy),
                           max(1, self.radius // 2))


class Lightning(GameObject):
    """
    Разряд молнии между двумя точками (M7, «Громовержец»).

    Как и Explosion: только ВИЗУАЛ и СВЕТ — урон уже нанесён
    к моменту создания. Ломаная генерируется ОДИН раз в конструкторе,
    поэтому во время жизни не «прыгает», а лишь гаснет.
    """

    emissive = True
    life_time = 0.18
    light_color = (120, 176, 255)

    def __init__(self, x1, y1, x2, y2):
        super().__init__((x1 + x2) / 2, (y1 + y2) / 2)   # центр — для света
        self.start = (x1, y1)
        self.end = (x2, y2)
        self.life = self.life_time
        self.light_radius = 80
        self.points = self._make_bolt(x1, y1, x2, y2)

    def _make_bolt(self, x1, y1, x2, y2):
        """Ломаная из 6 сегментов с отклонением перпендикуляру линии."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length          # единичный перпендикуляр
        pts = [self.start]
        steps = 6
        for i in range(1, steps):
            t = i / steps
            offset = random.uniform(-16, 16)
            pts.append((x1 + dx * t + nx * offset,
                        y1 + dy * t + ny * offset))
        pts.append(self.end)
        return pts

    def update(self, dt, game):
        self.life -= dt
        if self.life <= 0.0:
            self.light_radius = 0
            self.kill()
            return
        # свет гаснет вместе с разрядом
        self.light_radius = int(80 * self.life / self.life_time)

    def draw(self, screen, camera):
        pts = [camera.to_screen(x, y) for x, y in self.points]
        t = self.life / self.life_time
        # белое ядро в первые мгновения, затем холодный синий
        core = (255, 255, 255) if t > 0.5 else (170, 210, 255)
        pygame.draw.lines(screen, core, False, pts, 3)
        pygame.draw.lines(screen, (110, 160, 255), False, pts, 1)