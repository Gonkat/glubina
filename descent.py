"""
Спуск (M12): маяки, лифт и усиления между секторами.

Сектор — это не бесконечная арена, а маленькая задача с понятным
финалом: найти три сигнальных маяка, удержать каждый под наплывом
врагов и спуститься лифтом ниже. Между секторами игрок выбирает одну
из трёх карт усиления — так каждый забег получает собственный характер.

Модуль намеренно не знает о Game больше, чем нужно: он просит спавнить
волну, выдаёт награды и возвращает подсказки. Вся отрисовка — здесь же,
чтобы новый слой не расползался по HUD и world.
"""
import math
import random

import pygame

import soundbank
import visuals
from settings import (
    BEACON_COUNT,
    BEACON_DEFENSE_TIME,
    BEACON_INTERACT_RANGE,
    BEACON_LINK_RANGE,
    BEACON_REWARD_AMMO,
    BEACON_REWARD_MONEY,
    BEACON_REWARD_TOKEN,
    BEACON_SURGE_INTERVAL,
    LIFT_INTERACT_RANGE,
)
from utils import distance
from weapon_data import TOKEN_KEYS, TOKEN_NAMES


_CONE_CACHE = {}


def _cone_surface(height, half_width, color):
    """Кэш формы конуса: перерисовываем только при смене состояния маяка."""
    key = (height, half_width, color)
    surf = _CONE_CACHE.get(key)
    if surf is not None:
        return surf
    surf = pygame.Surface((half_width * 2 + 4, height), pygame.SRCALPHA)
    width = surf.get_width()
    centre = width // 2
    for row in range(height):
        # 0 — вершина, 1 — основание
        t = row / max(1, height - 1)
        row_half = max(1, int(half_width * (0.16 + 0.84 * t ** 0.75)))
        alpha = int(255 * (0.10 + 0.90 * t ** 1.5))
        if alpha <= 0:
            continue
        # три слоя дают мягкий край без пиксельных градиентов
        for scale, divisor in ((1.0, 1), (0.62, 2), (0.30, 3)):
            half = max(1, int(row_half * scale))
            layer_alpha = max(1, alpha // divisor)
            pygame.draw.line(surf, (*color, layer_alpha),
                             (centre - half, row), (centre + half, row))
    _CONE_CACHE[key] = surf
    return surf


def _draw_cone(screen, sx, base_y, height, half_width, color, strength,
               pulse=1.0):
    """Мягкий сужающийся вверх конус света.

    Раньше луч рисовался прямоугольником: он читался как плотный столб.
    Здесь яркость падает к вершине и к краям, поэтому объект остаётся
    ориентиром, но не перекрывает бой.
    """
    if height <= 0 or strength <= 0 or half_width <= 0:
        return
    surf = _cone_surface(height, half_width, color)
    surf.set_alpha(max(0, min(255, int(strength * pulse))))
    screen.blit(surf, (sx - surf.get_width() // 2, base_y - height))


# ------------------------------------------------------------------ УСИЛЕНИЯ
def _mult(owner, field, factor):
    setattr(owner, field, getattr(owner, field, 1.0) * factor)


def _add(owner, field, amount):
    setattr(owner, field, getattr(owner, field, 0.0) + amount)


BOONS = (
    {
        "key": "hollow",
        "name": "ПУСТОТЕЛЫЕ",
        "color": (255, 196, 96),
        "lines": ("+18% урона", "всего оружия"),
        "apply": lambda p, g: _mult(p, "boon_damage_mult", 1.18),
    },
    {
        "key": "plating",
        "name": "НАПЛАВЛЕНИЕ",
        "color": (144, 206, 246),
        "lines": ("-12% входящего", "урона"),
        "apply": lambda p, g: _mult(p, "boon_hurt_mult", 0.88),
    },
    {
        "key": "vitality",
        "name": "РЕЗЕРВ",
        "color": (128, 232, 158),
        "lines": ("+25 к максимуму HP", "и лечение 25"),
        "apply": lambda p, g: _vitality(p),
    },
    {
        "key": "servo",
        "name": "СЕРВОПРИВОД",
        "color": (104, 220, 208),
        "lines": ("+12% скорости", "передвижения"),
        "apply": lambda p, g: _servo(p),
    },
    {
        "key": "marauder",
        "name": "МАРОДЁР",
        "color": (255, 208, 108),
        "lines": ("+30% монет", "с врагов"),
        "apply": lambda p, g: _mult(p, "boon_loot_mult", 1.30),
    },
    {
        "key": "regen",
        "name": "РЕГЕНЕРАЦИЯ",
        "color": (242, 138, 160),
        "lines": ("+0.7 HP/сек", "постоянно"),
        "apply": lambda p, g: _add(p, "boon_regen", 0.7),
    },
    {
        "key": "pierce",
        "name": "БРОНЕБОЙ",
        "color": (244, 190, 116),
        "lines": ("+1 пробитие", "каждой пули"),
        "apply": lambda p, g: _add(p, "boon_pierce", 1),
    },
    {
        "key": "execute",
        "name": "ДОБИВАНИЕ",
        "color": (242, 116, 116),
        "lines": ("+35% урона", "целям ниже 35% HP"),
        "apply": lambda p, g: _add(p, "boon_execute", 0.35),
    },
    {
        "key": "leech",
        "name": "ПАРАЗИТ",
        "color": (192, 124, 232),
        "lines": ("+2 HP", "за каждое убийство"),
        "apply": lambda p, g: _add(p, "boon_lifesteal", 2.0),
    },
    {
        "key": "phase",
        "name": "ФАЗОВЫЙ СДВИГ",
        "color": (128, 208, 255),
        "lines": ("-25% откат рывка", "и +1 аптечка"),
        "apply": lambda p, g: _phase(p),
    },
    {
        "key": "trigger",
        "name": "АВТОМАТИКА",
        "color": (255, 228, 128),
        "lines": ("+15% темпа", "стрельбы"),
        "apply": lambda p, g: _mult(p, "boon_fire_rate_mult", 0.87),
    },
    {
        "key": "satchel",
        "name": "ПОДСУМОК",
        "color": (198, 212, 232),
        "lines": ("+60 патронов", "+2 гранаты"),
        "apply": lambda p, g: _satchel(p),
    },
)
BOON_BY_KEY = {boon["key"]: boon for boon in BOONS}


def _vitality(player):
    player.max_hp += 25
    player.heal(25)


def _servo(player):
    _mult(player, "boon_speed_mult", 1.12)
    player.refresh_speed()


def _phase(player):
    _mult(player, "boon_dash_mult", 0.75)
    player.equipment.add_item("medkit", 1)


def _satchel(player):
    player.equipment.add_ammo(60)
    player.equipment.add_item("grenade", 2)


def choose_boons(rng, taken, count=3):
    """Три разные карты, которых ещё нет в забеге (без повторов)."""
    pool = [boon for boon in BOONS if boon["key"] not in taken]
    if len(pool) < count:
        pool = list(BOONS)
    return rng.sample(pool, min(count, len(pool)))


# ------------------------------------------------------------------ МАЯК
class Beacon:
    radius = 22

    def __init__(self, x, y, index):
        self.x = x
        self.y = y
        self.index = index
        self.state = "idle"          # idle -> charging -> active
        self.progress = 0.0
        self.surge_timer = 0.0
        self.pulse = random.uniform(0, math.tau)
        self.linked = False

    @property
    def color(self):
        if self.state == "active":
            return (94, 242, 202)
        if self.state == "charging":
            return (255, 198, 96)
        return (116, 170, 190)

    def label(self):
        return f"МАЯК {self.index + 1}"

    def activate(self, game):
        if game.descent.charging is not None:
            game.toast("Сначала удержите текущий маяк", color=(240, 190, 110))
            return True
        self.state = "charging"
        self.progress = 0.0
        self.surge_timer = BEACON_SURGE_INTERVAL
        player = game.player
        self.linked = distance(self.x, self.y, player.x, player.y) <= BEACON_LINK_RANGE
        game.spawn_beacon_surge(self, count=2)
        soundbank.play("beacon_start", 0.8)
        game.toast(f"{self.label()}: удерживайте позицию {int(BEACON_DEFENSE_TIME)} с",
                   3.2, color=(255, 214, 130))
        return True

    def update(self, dt, game):
        self.pulse += dt
        if self.state != "charging":
            return
        player = game.player
        self.linked = distance(self.x, self.y, player.x, player.y) <= BEACON_LINK_RANGE
        if not self.linked:
            return
        self.progress = min(1.0, self.progress + dt / BEACON_DEFENSE_TIME)
        self.surge_timer -= dt
        if self.surge_timer <= 0.0:
            self.surge_timer = BEACON_SURGE_INTERVAL * random.uniform(0.85, 1.15)
            game.spawn_beacon_surge(self, count=1)
        if self.progress >= 1.0:
            self.complete(game)

    def complete(self, game):
        self.state = "active"
        self.progress = 1.0
        self.linked = False
        depth = getattr(game, "depth", 1)
        money = int(BEACON_REWARD_MONEY * (1 + 0.2 * (depth - 1)))
        ammo = BEACON_REWARD_AMMO + (depth - 1) * 5
        game.money += money
        game.player.equipment.add_ammo(ammo)
        game.player.heal(12)
        token_names = []
        reward_count = min(BEACON_REWARD_TOKEN, len(TOKEN_KEYS))
        for key in random.sample(TOKEN_KEYS, reward_count):
            game.player.add_weapon_token(key, 1)
            token_names.append(TOKEN_NAMES[key])
        game.score += 250 * depth
        game.camera.add_shake(6.0)
        soundbank.play("beacon_done", 0.85)
        token_note = ""
        if token_names:
            label = "жетон" if len(token_names) == 1 else "жетоны"
            names = ", ".join(f"«{name}»" for name in token_names)
            token_note = f" · {label} {names}"
        if game.descent.all_active:
            game.toast("ВСЕ МАЯКИ АКТИВНЫ · лифт открыт · "
                       f"+{money} монет · +{ammo} патронов{token_note}", 4.2,
                       color=(126, 248, 212))
        else:
            game.toast(f"{self.label()} активен · +{money} монет · "
                       f"+{ammo} патронов{token_note}", 3.0,
                       color=(130, 246, 210))

    # ---------------------------------------------------------- РИСОВАНИЕ
    def draw(self, screen, camera, elapsed):
        sx, sy = camera.to_screen(self.x, self.y)
        if not (-90 < sx < screen.get_width() + 90
                and -120 < sy < screen.get_height() + 90):
            return
        sx, sy = int(sx), int(sy)
        visuals.shadow(screen, sx, sy + 12, 28, 0.9)
        # основание
        pygame.draw.ellipse(screen, (20, 26, 34), (sx - 30, sy - 2, 60, 22))
        pygame.draw.ellipse(screen, (58, 70, 88), (sx - 27, sy - 4, 54, 18), 2)
        pygame.draw.rect(screen, (24, 30, 40), (sx - 18, sy + 2, 36, 8),
                         border_radius=3)
        # мачта
        pygame.draw.rect(screen, (30, 36, 48), (sx - 8, sy - 52, 16, 54),
                         border_radius=3)
        pygame.draw.rect(screen, (70, 84, 104), (sx - 5, sy - 50, 10, 50),
                         border_radius=2)
        for i in range(4):
            yy = sy - 44 + i * 11
            pygame.draw.line(screen, (34, 42, 56), (sx - 8, yy), (sx + 8, yy), 2)
        # антенна
        pygame.draw.line(screen, (88, 104, 126), (sx, sy - 52), (sx, sy - 70), 2)
        pygame.draw.circle(screen, (22, 28, 36), (sx, sy - 74), 8)
        pygame.draw.circle(screen, self.color, (sx, sy - 74), 5)

    def draw_overlay(self, screen, camera, elapsed, game):
        if not game.camera.is_visible(self.x, self.y, 120):
            return
        sx, sy = camera.to_screen(self.x, self.y)
        sx, sy = int(sx), int(sy)
        color = self.color
        pulse = 0.75 + 0.25 * math.sin(elapsed * 3.0 + self.pulse)
        dist_world = distance(game.player.x, game.player.y, self.x, self.y)

        # луч маяка: виден сквозь тьму и служит ориентиром
        if self.state == "active":
            height, half_width, strength = 168, 23, 118
        elif self.state == "charging":
            height, half_width, strength = 140, 18, 96
        else:
            height, half_width, strength = 110, 13, 34
        _draw_cone(screen, sx, sy - 64, height, half_width, color,
                   strength, pulse)
        visuals.glow(screen, sx, sy - 74, 34, color,
                     86 if self.state != "idle" else 38)

        visuals.draw_ring(screen, sx, sy + 9, 34, color, 2,
                          int(110 + 90 * pulse))
        if self.state == "charging":
            ring = pygame.Rect(sx - 42, sy - 33, 84, 84)
            pygame.draw.arc(screen, color, ring, -math.pi / 2,
                            -math.pi / 2 + math.tau * self.progress, 4)
            visuals.draw_ring(screen, sx, sy - 74, 12 + int(6 * pulse),
                              (255, 230, 160), 2, 220)
        elif self.state == "active":
            for i in range(3):
                r = 34 + int((elapsed * 24 + i * 14) % 52)
                visuals.draw_ring(screen, sx, sy + 9, r, (110, 246, 208), 1,
                                  max(0, 90 - i * 22))

        dist_m = int(dist_world / 32)
        # вплотную подсказку несёт HUD: мировая подпись только мешает
        if dist_world >= 120:
            if self.state == "idle":
                label = f"{self.label()} · {dist_m} м"
            elif self.state == "charging":
                label = f"{self.label()} · {int(self.progress * 100)}%"
            else:
                label = f"{self.label()} · АКТИВЕН"
            visuals.text(screen, label, (sx, sy + 34), 16, color,
                         align="center")
            if self.state == "charging" and not self.linked:
                visuals.text(screen, "вернитесь в зону сигнала",
                             (sx, sy + 54), 13, (238, 170, 120),
                             align="center")


# ------------------------------------------------------------------ ЛИФТ
class Lift:
    radius = 26

    def __init__(self, x, y, target_depth):
        self.x = x
        self.y = y
        self.target_depth = target_depth
        self.open = False
        self.pulse = 0.0

    def draw(self, screen, camera, elapsed):
        sx, sy = camera.to_screen(self.x, self.y)
        if not (-100 < sx < screen.get_width() + 100
                and -100 < sy < screen.get_height() + 100):
            return
        sx, sy = int(sx), int(sy)
        visuals.shadow(screen, sx, sy + 8, 42, 1.0)
        points = []
        for i in range(8):
            a = i * math.pi / 4 + math.pi / 8
            points.append((sx + math.cos(a) * 42, sy + math.sin(a) * 26))
        pygame.draw.polygon(screen, (18, 23, 32), points)
        pygame.draw.polygon(screen, (58, 72, 92), points, 2)
        pygame.draw.ellipse(screen, (16, 21, 30), (sx - 26, sy - 15, 52, 30))
        pygame.draw.ellipse(screen, (46, 58, 76), (sx - 26, sy - 15, 52, 30), 2)
        if self.open:
            pygame.draw.ellipse(screen, (10, 32, 34), (sx - 20, sy - 11, 40, 22))
            for i in range(3):
                yy = sy - 4 + i * 5
                pygame.draw.line(screen, (82, 210, 190),
                                 (sx - 9, yy), (sx + 9, yy), 2)

    def draw_overlay(self, screen, camera, elapsed, game):
        if not game.camera.is_visible(self.x, self.y, 120):
            return
        sx, sy = camera.to_screen(self.x, self.y)
        sx, sy = int(sx), int(sy)
        color = (104, 238, 208) if self.open else (126, 140, 160)
        pulse = 0.7 + 0.3 * math.sin(elapsed * 4.0)
        close = distance(game.player.x, game.player.y, self.x, self.y) < 120
        if self.open:
            _draw_cone(screen, sx, sy + 2, 196, 36, color, 82, pulse)
            visuals.glow(screen, sx, sy - 8, 56, color, 96)
            visuals.draw_ring(screen, sx, sy, 44, color, 3, 220)
            if not close:
                visuals.text(screen, "ЛИФТ НИЖЕ", (sx, sy + 38), 17, color,
                             align="center")
                visuals.text(screen, f"СЕКТОР {self.target_depth:02d}",
                             (sx, sy + 57), 14, (184, 208, 214), align="center")
        else:
            visuals.draw_ring(screen, sx, sy, 40, color, 2, 90)
            if not close:
                visuals.text(screen, "ЛИФТ ЗАКРЫТ", (sx, sy + 38), 15,
                             (166, 176, 194), align="center")


# ------------------------------------------------------------------ МЕНЕДЖЕР
class DescentManager:
    """Владеет маяками и лифтом одного сектора."""

    def __init__(self, game, depth):
        self.depth = depth
        self.beacons = []
        self.lift = None
        self._place(game, depth)
        self.notice_timer = 0.0

    # ---------------------------------------------------------- ГЕНЕРАЦИЯ
    def _place(self, game, depth):
        world = game.world
        start_x, start_y = world.player_start()
        rng = random.Random(f"{world.seed}:descent:{depth}")
        base_angle = -math.pi / 2 + rng.uniform(-0.35, 0.35)
        points = []
        for index in range(BEACON_COUNT):
            chosen = None
            for attempt in range(110):
                angle = base_angle + index * math.tau / BEACON_COUNT
                angle += rng.uniform(-0.20, 0.20)
                dist = rng.uniform(560, 840) - attempt * 2.0
                x = start_x + math.cos(angle) * max(420, dist)
                y = start_y + math.sin(angle) * max(420, dist)
                if not world.is_valid_position(x, y, 34):
                    continue
                if any(distance(x, y, px, py) < 230 for px, py in points):
                    continue
                chosen = (x, y)
                break
            if chosen is None:
                for _ in range(80):
                    try:
                        x, y = world.random_floor_position(
                            34, center=(start_x, start_y),
                            min_distance=300, max_distance=1400)
                    except RuntimeError:
                        break
                    if all(distance(x, y, px, py) >= 200 for px, py in points):
                        chosen = (x, y)
                        break
            if chosen is None:
                # крайний случай: выталкиваем точку кольца из стены
                angle = base_angle + index * math.tau / BEACON_COUNT
                chosen = world.resolve_circle(
                    start_x + math.cos(angle) * 470,
                    start_y + math.sin(angle) * 470, 34)
            points.append(chosen)
        self.beacons = [Beacon(x, y, i) for i, (x, y) in enumerate(points)]

        # лифт ставится рядом с последним маяком, но не поверх него
        last = self.beacons[-1]
        angle = math.atan2(last.y - start_y, last.x - start_x) + math.pi / 2
        lift_x = last.x + math.cos(angle) * 92
        lift_y = last.y + math.sin(angle) * 92
        if not world.is_valid_position(lift_x, lift_y, 34):
            found = False
            for step in range(16):
                test_angle = angle + step * math.pi / 8
                tx = last.x + math.cos(test_angle) * 92
                ty = last.y + math.sin(test_angle) * 92
                if world.is_valid_position(tx, ty, 34):
                    lift_x, lift_y = tx, ty
                    found = True
                    break
            if not found:
                for _ in range(60):
                    try:
                        tx, ty = world.random_floor_position(
                            34, center=(last.x, last.y),
                            min_distance=70, max_distance=280)
                    except RuntimeError:
                        break
                    lift_x, lift_y = tx, ty
                    found = True
                    break
            if not found:
                lift_x, lift_y = world.resolve_circle(
                    last.x, last.y + 92, 34)
        self.lift = Lift(lift_x, lift_y, depth + 1)

    # ---------------------------------------------------------- ЛОГИКА
    @property
    def active_count(self):
        return sum(1 for beacon in self.beacons if beacon.state == "active")

    @property
    def all_active(self):
        return self.active_count >= len(self.beacons)

    @property
    def charging(self):
        for beacon in self.beacons:
            if beacon.state == "charging":
                return beacon
        return None

    def update(self, dt, game):
        for beacon in self.beacons:
            beacon.update(dt, game)
        if self.lift is not None:
            self.lift.pulse += dt
            if self.all_active and not self.lift.open:
                self.lift.open = True
                game.score += 500 * self.depth
                game.camera.add_shake(8.0)
                soundbank.play("lift_open", 0.9)
        self._push_player(game)

    def _push_player(self, game):
        player = game.player
        for obj in self.beacons + ([self.lift] if self.lift else []):
            radius = 30 if isinstance(obj, Beacon) else 34
            dx = player.x - obj.x
            dy = player.y - obj.y
            d = math.hypot(dx, dy)
            if d < radius + player.radius:
                if d < 0.01:
                    dx, dy, d = 1.0, 0.0, 1.0
                px = obj.x + dx / d * (radius + player.radius)
                py = obj.y + dy / d * (radius + player.radius)
                player.x, player.y = game.world.resolve_circle(px, py, player.radius)

    def interact(self, game):
        target = self.nearest_interactable(game)
        if target is None:
            return False
        if isinstance(target, Beacon):
            return target.activate(game)
        if not target.open:
            game.toast(f"Лифт закрыт · маяки {self.active_count}/{len(self.beacons)}",
                       2.2, color=(240, 190, 110))
            return True
        game.descend_to_next()
        return True

    def nearest_interactable(self, game):
        player = game.player
        best = None
        best_d = 1e9
        for beacon in self.beacons:
            # активный или уже заряжающийся маяк не перехватывает E у лифта
            if beacon.state != "idle":
                continue
            d = distance(beacon.x, beacon.y, player.x, player.y)
            if d <= BEACON_INTERACT_RANGE + beacon.radius and d < best_d:
                best, best_d = beacon, d
        if self.lift is not None:
            d = distance(self.lift.x, self.lift.y, player.x, player.y)
            if d <= LIFT_INTERACT_RANGE + self.lift.radius and d < best_d:
                best, best_d = self.lift, d
        return best

    def compass_target(self):
        if self.lift is not None and self.lift.open:
            return self.lift
        charging = self.charging
        if charging is not None:
            return charging
        candidates = [b for b in self.beacons if b.state != "active"]
        if not candidates:
            return self.lift
        return candidates[0]

    def objective_text(self, game):
        if self.all_active:
            return "ЛИФТ ОТКРЫТ · спуститесь ниже"
        charging = self.charging
        if charging is not None:
            if charging.linked:
                return f"УДЕРЖИТЕ МАЯК {charging.index + 1} · {int(charging.progress * 100)}%"
            return f"ВЕРНИТЕСЬ К МАЯКУ {charging.index + 1}"
        return f"МАЯКИ {self.active_count}/{len(self.beacons)} · найдите сигнал"

    def lights(self):
        lights = []
        for beacon in self.beacons:
            radius = 220 if beacon.state == "active" else (
                150 if beacon.state == "charging" else 86)
            lights.append((beacon.x, beacon.y, radius, beacon.color))
        if self.lift is not None and self.lift.open:
            lights.append((self.lift.x, self.lift.y, 230, (88, 232, 204)))
        return lights

    # ---------------------------------------------------------- РИСОВАНИЕ
    def draw(self, screen, camera, elapsed):
        for beacon in self.beacons:
            beacon.draw(screen, camera, elapsed)
        if self.lift is not None:
            self.lift.draw(screen, camera, elapsed)

    def draw_overlay(self, screen, camera, elapsed, game):
        for beacon in self.beacons:
            beacon.draw_overlay(screen, camera, elapsed, game)
        if self.lift is not None:
            self.lift.draw_overlay(screen, camera, elapsed, game)
