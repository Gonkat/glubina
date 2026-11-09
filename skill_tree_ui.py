"""Единая доска навыков: древо героя и все оружейные древа на одной карте.

Почему так, а не вкладками:
  * у игрока есть общий герой и два слота оружия — все три истории развития
    видны одновременно и связаны линиями, как крона одного дерева;
  * доска больше экрана, поэтому её можно таскать мышью, приближать колесом,
    прыгать по зонам (Tab / 1 / 2 / 3) и возвращаться к герою (F);
  * правила покупки остаются в skill_tree.py, геометрия — в skill_board.py,
    а этот модуль только показывает карту и обрабатывает ввод.
"""
import math
import random

import pygame

import skill_board
import skill_tree
import soundbank
import visuals
from settings import HEIGHT, TEXT_DIM, WIDTH
from skill_board import (
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_SUBTITLES,
    MELEE_ORDER,
    RANGED_ORDER,
    WEAPON_SLOT,
    ZONE_ORDER,
    BoardLayout,
    category_of,
    zone_color,
    zone_name,
)
from skill_data import PLAYER_TREE, SKILL_TREES
from weapon_data import PISTOL_MODES

GOLD = (247, 212, 109)
GOOD = (131, 231, 158)
BAD = (240, 150, 110)
LACK = (232, 120, 100)
DIM = (130, 144, 166)
WHITE = (232, 239, 250)
PANEL = (8, 12, 21)
PANEL_EDGE = (48, 62, 84)


class SkillTreeUI:
    TOP = 62
    INFO_H = 166
    VIEW = pygame.Rect(0, TOP, WIDTH, HEIGHT - TOP - INFO_H)
    MIN_ZOOM = 0.34
    MAX_ZOOM = 1.55
    DEFAULT_ZOOM = 0.62
    MESSAGE_TIME = 3.2

    def __init__(self):
        self.tiny = visuals.font(13)
        self.small = visuals.font(16)
        self.font = visuals.font(20)
        self.mid = visuals.font(24)
        self.big = visuals.font(32)
        self.huge = visuals.font(42)

        self.layout = BoardLayout()
        largest_zone = max(self.layout.zone_extents.values(), default=0.0) + 24
        self.MIN_ZOOM = min(
            type(self).MIN_ZOOM,
            min(self.VIEW.w, self.VIEW.h) / (2.0 * largest_zone))
        self.zoom = self.DEFAULT_ZOOM
        self.camera = list(self.layout.center("player"))
        self.focus_zone = "player"
        self.selected_key = None
        self.hover_key = None
        self.slot = "firearm"
        self.message = ""
        self.message_color = GOOD
        self.message_timer = 0.0
        self._last_frame = 0
        self._drag = None

        self._stars = self._make_stars()
        self._mini = pygame.Rect(WIDTH - 216, self.TOP + 12, 196, 132)
        # Геометрия и надписи доски не меняются между кадрами: кэш экономит
        # десятки тысяч временных кортежей и поверхностей при перетаскивании.
        self._curve_cache = {}
        self._link_route_cache = {}
        self._text_cache = {}
        self._chips = []

    # ------------------------------------------------------------ ОТКРЫТИЕ
    def open(self, slot="firearm", game=None):
        self.slot = slot
        self.selected_key = None
        self.hover_key = None
        self.message = ""
        self.message_timer = 0.0
        self._drag = None
        self._last_frame = 0
        zone = "player"
        if game is not None:
            weapon = game.player.equipment.get(slot)
            if weapon is not None and weapon.key in ZONE_ORDER:
                zone = weapon.key
        self.focus_zone = zone
        self.zoom = self._zone_zoom(zone)
        self.camera = list(self.layout.center(zone))
        self._clamp_camera()
        if game is not None:
            self._select_first_in_zone(game, zone)

    # ------------------------------------------------------------ ДАННЫЕ СТРОК
    @staticmethod
    def _zone_branches(zone):
        if zone == "player":
            return PLAYER_TREE["branches"]
        return SKILL_TREES[zone]["branches"]

    def rows(self, game):
        """Все узлы доски.

        state: owned/prev/excluded/depth/training/tokens/ok/unequipped.
        """
        rows = []
        player = game.player
        for bi, branch in enumerate(skill_tree.player_branches()):
            for node in branch["nodes"]:
                rows.append({
                    "kind": "player", "zone": "player", "slot": "player",
                    "branch": branch, "node": node,
                    "state": skill_tree.player_node_state(player, branch, node),
                    "price": skill_tree.player_node_price(player, branch, node),
                    "branch_index": bi, "weapon": None, "equipped": True,
                })
        for zone in ZONE_ORDER[1:]:
            slot = WEAPON_SLOT[zone]
            weapon = game.player.equipment.get(slot)
            equipped = weapon is not None and weapon.key == zone
            for bi, branch in enumerate(SKILL_TREES[zone]["branches"]):
                for node in branch["nodes"]:
                    if equipped:
                        state = skill_tree.node_state(weapon, branch, node, player)
                        price = skill_tree.node_price(weapon, branch, node)
                    else:
                        state = "unequipped"
                        price = node["cost"]
                    rows.append({
                        "kind": "weapon", "zone": zone, "slot": slot,
                        "branch": branch, "node": node, "state": state,
                        "price": price, "branch_index": bi,
                        "weapon": weapon if equipped else None,
                        "equipped": equipped,
                    })
        return rows

    @staticmethod
    def _key(row):
        return (row["zone"], row["node"]["id"])

    def _ensure_selection(self, rows):
        keys = {self._key(row) for row in rows}
        if self.selected_key in keys or not rows:
            return
        in_zone = [r for r in rows if r["zone"] == self.focus_zone]
        available = [r for r in in_zone if r["state"] == "ok"]
        chosen = (available or in_zone or rows)[0]
        self.selected_key = self._key(chosen)

    def _row_by_key(self, rows, key):
        for row in rows:
            if self._key(row) == key:
                return row
        return None

    def _selected_row(self, rows):
        self._ensure_selection(rows)
        row = self._row_by_key(rows, self.selected_key)
        return row or (rows[0] if rows else None)

    # ------------------------------------------------------------ КАМЕРА
    def _clamp_camera(self):
        half_w = self.VIEW.w / (2.0 * self.zoom)
        half_h = self.VIEW.h / (2.0 * self.zoom)
        if half_w * 2 >= self.layout.board_w:
            self.camera[0] = self.layout.board_w / 2.0
        else:
            self.camera[0] = max(half_w - 80, min(self.layout.board_w - half_w + 80,
                                                  self.camera[0]))
        if half_h * 2 >= self.layout.board_h:
            self.camera[1] = self.layout.board_h / 2.0
        else:
            self.camera[1] = max(half_h - 80, min(self.layout.board_h - half_h + 80,
                                                  self.camera[1]))

    def screen(self, wx, wy):
        return (self.VIEW.centerx + (wx - self.camera[0]) * self.zoom,
                self.VIEW.centery + (wy - self.camera[1]) * self.zoom)

    def world(self, sx, sy):
        return (self.camera[0] + (sx - self.VIEW.centerx) / self.zoom,
                self.camera[1] + (sy - self.VIEW.centery) / self.zoom)

    def _zoom_at(self, point, factor):
        wx, wy = self.world(*point)
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self.camera[0] = wx - (point[0] - self.VIEW.centerx) / self.zoom
        self.camera[1] = wy - (point[1] - self.VIEW.centery) / self.zoom
        self._clamp_camera()

    def _zone_zoom(self, zone):
        """Древо целиком влезает в видимую область при прыжке по зонам."""
        radius = self.layout.zone_extents[zone] + 24
        fit = min(self.VIEW.w, self.VIEW.h) / (2.0 * radius)
        return max(self.MIN_ZOOM, min(0.88, fit))

    def _focus_zone(self, zone, game, select=True):
        if zone not in ZONE_ORDER:
            return
        self.focus_zone = zone
        self.zoom = self._zone_zoom(zone)
        self.camera = list(self.layout.center(zone))
        self._clamp_camera()
        if select:
            self._select_first_in_zone(game, zone)

    def _select_first_in_zone(self, game, zone):
        rows = [r for r in self.rows(game) if r["zone"] == zone]
        if not rows:
            return
        available = [r for r in rows if r["state"] == "ok"]
        row = (available or rows)[0]
        self.selected_key = self._key(row)

    # ------------------------------------------------------------ ВВОД
    def handle_event(self, event, game):
        if event.type == pygame.KEYDOWN:
            self._handle_key(event, game)
            return
        if event.type == pygame.MOUSEWHEEL:
            if event.y:
                factor = 1.13 ** event.y
                self._zoom_at(pygame.mouse.get_pos(), factor)
                soundbank.play("ui_move", 0.35)
            return
        if event.type == pygame.MOUSEMOTION:
            if self._drag is not None:
                dx = event.pos[0] - self._drag[0]
                dy = event.pos[1] - self._drag[1]
                self._drag = event.pos
                self.camera[0] -= dx / self.zoom
                self.camera[1] -= dy / self.zoom
                self._clamp_camera()
            self._update_hover(game)
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            self._handle_click(event, game)
            return
        if event.type == pygame.MOUSEBUTTONUP:
            if self._drag is not None and event.button in (1, 2, 3):
                self._drag = None
            self._update_hover(game)

    def _handle_key(self, event, game):
        rows = self.rows(game)
        self._ensure_selection(rows)
        key = event.key
        if key == pygame.K_TAB:
            index = ZONE_ORDER.index(self.focus_zone)
            index += -1 if event.mod & pygame.KMOD_SHIFT else 1
            zone = ZONE_ORDER[index % len(ZONE_ORDER)]
            self._focus_zone(zone, game)
            soundbank.play("ui_move")
        elif key == pygame.K_f:
            self._focus_zone("player", game)
            soundbank.play("ui_move")
        elif key in (pygame.K_1, pygame.K_KP1):
            self._focus_zone("player", game)
            soundbank.play("ui_move")
        elif key in (pygame.K_2, pygame.K_KP2):
            self._focus_equipped(game, "firearm")
        elif key in (pygame.K_3, pygame.K_KP3):
            self._focus_equipped(game, "melee")
        elif key == pygame.K_HOME:
            self.zoom = self._zone_zoom("player")
            self.camera = list(self.layout.center("player"))
            self._clamp_camera()
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            dx = -1 if key == pygame.K_LEFT else 1 if key == pygame.K_RIGHT else 0
            dy = -1 if key == pygame.K_UP else 1 if key == pygame.K_DOWN else 0
            self._select_direction(rows, dx, dy)
        elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.buy(game)
        elif key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self._zoom_at(self.VIEW.center, 1.16)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._zoom_at(self.VIEW.center, 1.0 / 1.16)

    def _focus_equipped(self, game, slot):
        weapon = game.player.equipment.get(slot)
        if weapon is None:
            self._fail("В этом слоте нет оружия")
            return
        self._focus_zone(weapon.key, game)
        soundbank.play("ui_move")

    def _handle_click(self, event, game):
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        pos = event.pos
        if event.button == 1 and pos[1] < self.TOP:
            for rect, category in self._chips:
                if rect.collidepoint(pos):
                    if category == "player":
                        self._focus_zone("player", game)
                    else:
                        self._focus_equipped(game, category)
                    return
            return
        if self._mini.collidepoint(pos):
            if event.button == 1:
                self._mini_jump(pos)
            return
        if not self.VIEW.collidepoint(pos):
            return
        rows = self.rows(game)
        self._ensure_selection(rows)
        if event.button == 1:
            root_zone = self._root_at(pos)
            if root_zone is not None:
                self._focus_zone(root_zone, game)
                soundbank.play("ui_move")
                return
            hit = self._node_at(pos, rows)
            if hit is not None:
                old_key = self.selected_key
                self.selected_key = self._key(hit)
                self.focus_zone = hit["zone"]
                if old_key == self.selected_key:
                    self.buy(game)
                else:
                    soundbank.play("ui_move")
                return
            self._drag = pos
        elif event.button in (2, 3):
            # Правая/средняя кнопка — всегда «схватить доску».
            self._drag = pos

    def _mini_inner(self):
        rect = self._mini.inflate(-16, -28)
        rect.y += 14
        rect.h -= 2
        return rect

    def _mini_jump(self, pos):
        rect = self._mini_inner()
        if rect.w <= 0 or rect.h <= 0:
            return
        wx = (pos[0] - rect.x) / rect.w * self.layout.board_w
        wy = (pos[1] - rect.y) / rect.h * self.layout.board_h
        self.camera = [wx, wy]
        self._clamp_camera()

    def _root_at(self, pos):
        for zone in ZONE_ORDER:
            sx, sy = self.screen(*self.layout.root(zone))
            if math.hypot(pos[0] - sx, pos[1] - sy) <= (skill_board.ROOT_RADIUS + 10) * self.zoom:
                return zone
        return None

    def _node_at(self, pos, rows):
        for row in rows:
            sx, sy = self.screen(*self.layout.node_pos(row["zone"],
                                                       row["node"]["id"]))
            radius = max(9.0, skill_board.BoardLayout.node_radius(row["zone"])
                         * self.zoom + 5.0)
            if (pos[0] - sx) ** 2 + (pos[1] - sy) ** 2 <= radius ** 2:
                return row
        return None

    def _update_hover(self, game):
        if self._drag is not None:
            self.hover_key = None
            return
        pos = pygame.mouse.get_pos()
        if not self.VIEW.collidepoint(pos):
            self.hover_key = None
            return
        hit = self._node_at(pos, self.rows(game))
        self.hover_key = self._key(hit) if hit is not None else None

    def _select_direction(self, rows, dx, dy):
        current = self._selected_row(rows)
        if current is None:
            return
        cx, cy = self.layout.node_pos(current["zone"], current["node"]["id"])
        same_zone = [r for r in rows if r["zone"] == current["zone"]]
        pool = same_zone if len(same_zone) > 1 else rows
        best = None
        best_score = None
        for row in pool:
            if self._key(row) == self.selected_key:
                continue
            px, py = self.layout.node_pos(row["zone"], row["node"]["id"])
            vx, vy = px - cx, py - cy
            dist = math.hypot(vx, vy)
            if dist < 0.001:
                continue
            dot = (vx * dx + vy * dy) / dist
            if dot < 0.28:
                continue
            side = abs(vx * dy - vy * dx)
            score = dist + side * 2.3 - dot * 60.0
            if best_score is None or score < best_score:
                best, best_score = row, score
        if best is None:
            return
        self.selected_key = self._key(best)
        self.focus_zone = best["zone"]
        sx, sy = self.screen(*self.layout.node_pos(best["zone"], best["node"]["id"]))
        safe = self.VIEW.inflate(-80, -60)
        if not safe.collidepoint(sx, sy):
            self.camera = list(self.layout.node_pos(best["zone"], best["node"]["id"]))
            self._clamp_camera()
        soundbank.play("ui_move")

    # ------------------------------------------------------------ ПОКУПКА
    def _fail(self, message):
        self.message = message
        self.message_color = BAD
        self.message_timer = self.MESSAGE_TIME
        soundbank.play("error")

    def buy(self, game):
        rows = self.rows(game)
        row = self._selected_row(rows)
        if row is None:
            return
        state = row["state"]
        node = row["node"]
        if state == "training" and not skill_tree.can_cover_training(
                game.player, node):
            missing = skill_tree.missing_training(game.player, node)
            names = ", ".join(
                f"{skill_tree.training_name(key)} {have}/{need}"
                for key, need, have, _ in missing)
            self._fail(f"Нужна подготовка: {names}. Купите жетон в оружейном магазине")
            return
        if state == "tokens" and row["weapon"] is not None:
            toll = skill_tree.cross_branch_toll(
                row["weapon"], row["branch"], node)
            if not skill_tree.can_pay_cross_toll(
                    game.player, row["weapon"], row["branch"], node):
                self._fail(
                    f"Вторая ветвь: нужен жетон школы ({toll}). "
                    "Подойдёт жетон родственной школы")
                return
        if state not in ("ok", "training", "tokens"):
            reasons = {
                "owned": "Навык уже изучен",
                "prev": "Сначала изучите обязательные навыки",
                "excluded": "Выбрана другая доктрина этой ветви",
                "depth": "Глубина второй ветви ещё не открыта основной",
                "unequipped": f"Сначала экипируйте: {zone_name(row['zone'])}",
            }
            self._fail(reasons.get(state, "Навык недоступен"))
            return
        price = row["price"]
        if game.money < price:
            self._fail(f"Не хватает монет: {price - game.money}")
            return
        if row["kind"] == "player":
            skill_tree.buy_player_node(game.player, row["branch"], node, price)
            zone = "древо героя"
        else:
            weapon = row["weapon"]
            if weapon is None:
                self._fail("Оружие не экипировано")
                return
            skill_tree.buy(weapon, row["branch"], node, price, game.player)
            zone = weapon.name
        game.money -= price
        self.message = f"{zone}: изучено «{node['name']}»"
        if node.get("mods", {}).get("mode_switch"):
            self.message += " · V — переключение режимов"
        if node.get("mode"):
            self.message += " · V — включить режим"
        if state == "training":
            self.message += " · жетон тренировки списан"
        if state == "tokens":
            self.message += " · жетон школы списан за вторую ветвь"
        self.message_color = GOOD
        self.message_timer = self.MESSAGE_TIME
        soundbank.play("buy")

    # ------------------------------------------------------------ КАДР
    def _tick(self):
        now = pygame.time.get_ticks()
        dt = min(0.1, (now - self._last_frame) / 1000.0) if self._last_frame else 0.0
        self._last_frame = now
        self.message_timer = max(0.0, self.message_timer - dt)
        if dt <= 0.0:
            return
        pressed = pygame.key.get_pressed()
        dx = (1 if pressed[pygame.K_d] else 0) - (1 if pressed[pygame.K_a] else 0)
        dy = (1 if pressed[pygame.K_s] else 0) - (1 if pressed[pygame.K_w] else 0)
        # Стрелки — выбор узлов, поэтому WASD двигает доску.
        if dx or dy:
            speed = 760.0 / self.zoom
            self.camera[0] += dx * speed * dt
            self.camera[1] += dy * speed * dt
            self._clamp_camera()

    @staticmethod
    def _fit(font, text, width):
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "...")[0] > width:
            text = text[:-1]
        return text + "..."

    def _text(self, screen, font, value, color, pos=None, center=None):
        text = str(value)
        key = (id(font), text, tuple(color))
        image = self._text_cache.get(key)
        if image is None:
            image = font.render(text, True, tuple(color))
            if len(self._text_cache) >= 800:
                self._text_cache.clear()
            self._text_cache[key] = image
        if center is not None:
            screen.blit(image, image.get_rect(center=center))
        else:
            screen.blit(image, pos)
        return image.get_width()

    def _text_world(self, screen, value, wx, wy, size, color, center=True,
                    max_width=None):
        sx, sy = self.screen(wx, wy)
        font = visuals.font(max(10, int(size * self.zoom)))
        text = str(value)
        if max_width is not None:
            text = self._fit(font, text, max_width * self.zoom)
        return self._text(screen, font, text, color,
                          center=(int(sx), int(sy)) if center else (int(sx), int(sy)))

    def _draw_world_line(self, screen, a, b, color, width=2):
        pygame.draw.line(screen, color, self.screen(*a), self.screen(*b),
                         max(1, int(width * self.zoom)))

    def _curve(self, a, b, bend=0.0, steps=12):
        key = (a[0], a[1], b[0], b[1], bend, steps)
        points = self._curve_cache.get(key)
        if points is not None:
            return points
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        mx = (ax + bx) / 2 - dy / length * bend
        my = (ay + by) / 2 + dx / length * bend
        points = []
        for i in range(steps + 1):
            t = i / steps
            u = 1.0 - t
            points.append((u * u * ax + 2 * u * t * mx + t * t * bx,
                           u * u * ay + 2 * u * t * my + t * t * by))
        if len(self._curve_cache) >= 1200:
            self._curve_cache.clear()
        self._curve_cache[key] = points
        return points

    def _draw_curve(self, screen, points, color, width=2):
        if len(points) < 2:
            return
        camx, camy = self.camera
        zoom = self.zoom
        cx, cy = self.VIEW.centerx, self.VIEW.centery
        screen_points = [(cx + (p[0] - camx) * zoom,
                          cy + (p[1] - camy) * zoom) for p in points]
        pygame.draw.lines(screen, color, False, screen_points,
                          max(1, int(width * zoom)))

    def _zone_visible(self, zone):
        """Корень и его крона не рисуются, если остров целиком за экраном."""
        sx, sy = self.screen(*self.layout.root(zone))
        m = self.layout.zone_extents[zone] * self.zoom
        return (self.VIEW.left - m <= sx <= self.VIEW.right + m
                and self.VIEW.top - m <= sy <= self.VIEW.bottom + m)

    @staticmethod
    def _shade(color, factor):
        return tuple(max(0, min(255, int(c * factor))) for c in color)

    @staticmethod
    def _mix(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    # ------------------------------------------------------------ ФОН
    def _make_stars(self):
        rng = random.Random(1207)
        stars = []
        for _ in range(360):
            stars.append((rng.uniform(0, self.layout.board_w),
                          rng.uniform(0, self.layout.board_h),
                          rng.choice((1, 1, 1, 2)),
                          rng.uniform(0, math.tau), rng.randint(34, 105)))
        return stars

    def _draw_background(self, screen, game):
        screen.fill((4, 7, 15))
        # звёздное поле: глубина доски, а не плоская сетка
        for wx, wy, radius, phase, level in self._stars:
            sx, sy = self.screen(wx, wy)
            if -4 <= sx <= WIDTH + 4 and self.VIEW.top - 4 <= sy <= self.VIEW.bottom + 4:
                pulse = 0.72 + 0.28 * math.sin(game.elapsed * 1.8 + phase)
                color = (int(level * pulse), int(level * pulse * 0.96),
                         int(level * pulse * 0.82))
                pygame.draw.circle(screen, color, (int(sx), int(sy)), radius)

        # крупные туманности под регионами
        for zone in ("player",) + MELEE_ORDER + RANGED_ORDER:
            sx, sy = self.screen(*self.layout.center(zone))
            if -340 < sx < WIDTH + 340 and -280 < sy < HEIGHT + 280:
                visuals.glow(screen, sx, sy, 210, zone_color(zone), 15)

        # сетка помогает читать масштаб при перетаскивании
        step = 160
        left, top = self.world(0, self.VIEW.top)
        right, bottom = self.world(WIDTH, self.VIEW.bottom)
        gx = math.floor(left / step) * step
        while gx <= right:
            sx, _ = self.screen(gx, top)
            pygame.draw.line(screen, (14, 22, 35), (sx, self.VIEW.top),
                             (sx, self.VIEW.bottom), 1)
            gx += step
        gy = math.floor(top / step) * step
        while gy <= bottom:
            _, sy = self.screen(left, gy)
            pygame.draw.line(screen, (14, 22, 35), (0, sy), (WIDTH, sy), 1)
            gy += step

        # короткие корни под ядром героя не пересекают отдельные зоны оружия
        player_center = self.layout.root("player")
        for offset, bend in ((-130, -18), (130, 18)):
            start = (player_center[0] + offset, player_center[1] + 230)
            end = (player_center[0] + offset * 1.8, player_center[1] + 450)
            self._draw_curve(screen, self._curve(end, start, bend),
                             (48, 40, 29), 4)

        # Раньше здесь были «артерии» от героя к каждому древу. На
        # сеточной доске они проходили сквозь чужие узлы и читались как
        # связи не того навыка. Группы и миникарта дают навигацию без
        # линий, пересекающих карточки.

    # ------------------------------------------------------------ ОТРИСОВКА ДРЕВА
    def _draw_path(self, screen, points, color, width=2):
        if len(points) < 2:
            return
        screen_points = [self.screen(p[0], p[1]) for p in points]
        thickness = max(1, int(width * self.zoom))
        if len(screen_points) == 2:
            pygame.draw.line(screen, color, screen_points[0],
                             screen_points[1], thickness)
        else:
            pygame.draw.lines(screen, color, False, screen_points, thickness)
        # Скруглённые стыки: A*-путь состоит из сегментов под углом,
        # без этого изломы выглядят как случайные обрывки линий.
        joint = max(0, int(thickness * 0.5))
        if joint:
            for point in screen_points[1:-1]:
                pygame.draw.circle(screen, color,
                                   (int(point[0]), int(point[1])), joint)

    def _draw_dashed_path(self, screen, points, color, width=2):
        """Пунктир для межветвевых зависимостей: не путается с ветвью."""
        if len(points) < 2:
            return
        screen_points = [self.screen(p[0], p[1]) for p in points]
        thickness = max(1, int(width * self.zoom))
        dash = max(4.0, 8.0 * self.zoom)
        gap = max(3.0, 5.0 * self.zoom)
        for first, second in zip(screen_points, screen_points[1:]):
            ax, ay = first
            bx, by = second
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length <= 0.001:
                continue
            ux, uy = dx / length, dy / length
            offset = 0.0
            while offset < length:
                end = min(length, offset + dash)
                pygame.draw.line(
                    screen, color,
                    (int(ax + ux * offset), int(ay + uy * offset)),
                    (int(ax + ux * end), int(ay + uy * end)),
                    thickness)
                offset = end + gap

    def _draw_route_connection(self, screen, points, color, state,
                               cross_branch=False):
        factor = (0.9 if state == "owned" else 0.48 if state == "ok"
                  else 0.30 if state == "excluded" else 0.22)
        width = 6 if state == "owned" else 4
        if cross_branch:
            # Чужая ветвь — это условие, а не продолжение ствола.
            # Пунктир и меньшая яркость читаются как «мостик».
            self._draw_dashed_path(screen, points,
                                   self._shade(color, factor * 0.30),
                                   width)
            self._draw_dashed_path(screen, points,
                                   self._shade(color, factor * 0.72), 1)
            return
        self._draw_path(screen, points, self._shade(color, factor * 0.45),
                        width + 2)
        self._draw_path(screen, points, self._shade(color, factor), 2)

    def _link_route(self, zone, source_id, target_id, start, goal, rows):
        """Маршрут связи с обходом всех чужих узлов (кэшируется на доску)."""
        key = (zone, source_id, target_id)
        cached = self._link_route_cache.get(key)
        if cached is not None:
            return cached
        obstacles = []
        radius = skill_board.BoardLayout.node_radius(zone) \
            + skill_board.LINK_NODE_CLEARANCE
        for row in rows:
            if row["zone"] != zone:
                continue
            node_id = row["node"]["id"]
            if node_id in (source_id, target_id):
                continue
            x, y = self.layout.node_pos(zone, node_id)
            obstacles.append((x, y, radius))
        # Ядро героя/оружия — тоже препятствие, если связь не начинается
        # или не заканчивается в нём.
        if source_id is not None and target_id is not None:
            x, y = self.layout.root(zone)
            obstacles.append((x, y, skill_board.ROOT_RADIUS
                              + skill_board.LINK_ROOT_CLEARANCE))
        route = skill_board.route_around_circles(
            start, goal, obstacles, skill_board.LINK_GRID_STEP)
        self._link_route_cache[key] = route
        return route

    def _draw_links(self, screen, zone, branches, rows, root):
        """
        Линии идут от каждого requires, а не только «tier-1 -> tier-2».
        Поэтому гибридный узел честно показывает вторую ветвь, а пара
        доктрин расходится из общего tier-4. Маршрут обходит чужие узлы,
        а не раздувается в петлю вокруг всего древа.
        """
        by_id = {r["node"]["id"]: r for r in rows if r["zone"] == zone}
        for bi, branch in enumerate(branches):
            color = skill_board.BoardLayout.branch_color(zone, bi)
            for node in branch["nodes"]:
                row = by_id[node["id"]]
                pos = self.layout.node_pos(zone, node["id"])
                reqs = skill_tree.prerequisites(branch, node)
                sources = (reqs if reqs else ())
                if not sources:
                    route = self._link_route(zone, None, node["id"],
                                             root, pos, rows)
                    self._draw_route_connection(screen, route, color,
                                                row["state"])
                    continue
                for req in sources:
                    source = by_id.get(req)
                    if source is None:
                        continue
                    source_pos = self.layout.node_pos(zone, req)
                    route = self._link_route(zone, req, node["id"],
                                             source_pos, pos, rows)
                    self._draw_route_connection(
                        screen, route, color, row["state"],
                        cross_branch=(source["branch_index"] != bi))

    def _draw_player_tree(self, screen, rows):
        if not self._zone_visible("player"):
            return
        player_rows = [r for r in rows if r["zone"] == "player"]
        player_center = self.layout.root("player")
        self._draw_links(screen, "player", PLAYER_TREE["branches"],
                         player_rows, player_center)

        # ядро героя
        sx, sy = self.screen(*player_center)
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 500.0)
        visuals.glow(screen, sx, sy, int(74 * self.zoom), GOLD, 70)
        pygame.draw.circle(screen, (17, 21, 28), (int(sx), int(sy)),
                           max(12, int(47 * self.zoom)))
        pygame.draw.circle(screen, GOLD, (int(sx), int(sy)),
                           max(12, int(47 * self.zoom)), max(2, int(3 * self.zoom)))
        pygame.draw.circle(screen, (62, 52, 30), (int(sx), int(sy)),
                           max(8, int(36 * self.zoom)), max(1, int(2 * self.zoom)))
        self._draw_player_glyph(screen, sx, sy, max(8, int(20 * self.zoom)), GOLD)
        self._text_world(screen, "ГЕРОЙ", player_center[0], player_center[1] + 65,
                         17, GOLD)
        self._text_world(screen, "ядро вылазки", player_center[0],
                         player_center[1] + 88, 11, (154, 146, 116))
        if self.focus_zone == "player":
            visuals.draw_ring(screen, sx, sy, int((55 + 4 * pulse) * self.zoom),
                              GOLD, 1, 95)

    def _draw_weapon_tree(self, screen, zone, rows):
        if not self._zone_visible(zone):
            return
        weapon_rows = [r for r in rows if r["zone"] == zone]
        if not weapon_rows:
            return
        focused = zone == self.focus_zone
        equipped = any(r["equipped"] for r in weapon_rows)
        color = zone_color(zone)
        root = self.layout.root(zone)
        self._draw_links(screen, zone, SKILL_TREES[zone]["branches"],
                         weapon_rows, root)
        # ореол и корень
        sx, sy = self.screen(*root)
        if focused:
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 420.0)
            visuals.glow(screen, sx, sy, int((64 + 8 * pulse) * self.zoom),
                         color, 74 if equipped else 38)
            visuals.draw_ring(screen, sx, sy, int((55 + 5 * pulse) * self.zoom),
                              color, 1, 110)
        else:
            visuals.glow(screen, sx, sy, int(42 * self.zoom), color, 28 if equipped else 14)
        radius = max(10, int(skill_board.ROOT_RADIUS * self.zoom))
        pygame.draw.circle(screen, (12, 16, 25), (int(sx), int(sy)), radius)
        pygame.draw.circle(screen, color if equipped else self._shade(color, 0.55),
                           (int(sx), int(sy)), radius, max(2, int(2.5 * self.zoom)))
        pygame.draw.circle(screen, self._shade(color, 0.18), (int(sx), int(sy)),
                           max(5, int(radius * 0.72)))
        self._draw_weapon_glyph(screen, zone, sx, sy,
                                max(8, int(23 * self.zoom)),
                                color if equipped else self._shade(color, 0.6))
        # подпись корня; на сильном отдалении её заменяют цветные точки карты
        if self.zoom < 0.47:
            return
        label = zone_name(zone)
        font = visuals.font(max(10, int(14 * self.zoom)))
        label = self._fit(font, label, 230 * self.zoom)
        w = font.size(label)[0]
        tag = "В РУКАХ" if equipped else "НЕ ЭКИПИРОВАНО"
        tag_color = GOOD if equipped else (126, 128, 142)
        tag_font = visuals.font(max(9, int(10 * self.zoom)))
        max_w = max(w, tag_font.size(tag)[0]) + 14
        line_h = font.get_height()
        plate_h = line_h + tag_font.get_height() + 8
        plate = pygame.Rect(0, 0, int(max_w), plate_h)
        plate.midtop = (int(sx), int(sy + radius + 5 * self.zoom))
        pygame.draw.rect(screen, (10, 14, 22), plate, border_radius=5)
        pygame.draw.rect(screen, self._shade(color, 0.45 if equipped else 0.22),
                         plate, 1, border_radius=5)
        self._text(screen, font, label, WHITE if equipped else (158, 164, 178),
                   center=(plate.centerx, plate.y + 4 + line_h // 2))
        self._text(screen, tag_font, tag, tag_color,
                   center=(plate.centerx, plate.y + 4 + line_h
                           + tag_font.get_height() // 2))

    def _branch_label_layout(self, zone, rows):
        """
        Раскладка подписей ветвей с учётом реальных прямоугольников.

        Плашка не ставится в точку branch_end «как есть»: у боковой ветви
        она растянута к центру и может лечь на пару tier-5. Поэтому
        кандидат отодвигается от корня и последовательно проверяется на
        пересечение с узлами и уже поставленными подписями. Если места нет,
        подпись не рисуется — лучше пустое место, чем текст поверх навыка.
        """
        if zone == "player":
            branches = PLAYER_TREE["branches"]
        else:
            branches = SKILL_TREES[zone]["branches"]
        node_rects = []
        for row in rows:
            if row["zone"] != zone:
                continue
            wx, wy = self.layout.node_pos(zone, row["node"]["id"])
            sx, sy = self.screen(wx, wy)
            radius = max(5, int(skill_board.BoardLayout.node_radius(zone)
                                * self.zoom)) + 3
            node_rects.append(pygame.Rect(int(sx - radius), int(sy - radius),
                                          radius * 2, radius * 2))

        root_x, root_y = self.screen(*self.layout.root(zone))
        placed = []
        result = []
        for bi, branch in enumerate(branches):
            ex, ey = self.layout.branch_end(zone, bi)
            anchor_x, anchor_y = self.screen(ex, ey)
            if not (-90 <= anchor_x <= WIDTH + 90
                    and self.VIEW.top - 50 <= anchor_y <= self.VIEW.bottom + 50):
                continue
            font = visuals.font(max(10, int(11 * self.zoom)))
            # Шрифт подписи не опускается ниже 10 px, значит и лимит
            # ширины не должен сжиматься до 190*0.36 = 68 px: иначе
            # длинные названия («Плазменный контур») обрезаются на
            # среднем зуме. Нижняя граница сохраняет полный текст.
            text = self._fit(font, branch["name"], max(150.0, 190.0 * self.zoom))
            width = font.size(text)[0] + 14
            height = font.get_height() + 6
            dx, dy = anchor_x - root_x, anchor_y - root_y
            length = math.hypot(dx, dy) or 1.0
            ux, uy = dx / length, dy / length
            # Сначала отодвигаем по лучу ветви, затем пробуем небольшой
            # боковой сдвиг — этого достаточно для трёх- и четырёхветочных
            # древ и для будущих ветвей с более длинными названиями.
            best = None
            for push in range(0, 249, 8):
                for side in (0, -10, 10, -20, 20, -32, 32):
                    cx = anchor_x + ux * push - uy * side
                    cy = anchor_y + uy * push + ux * side
                    cx = max(width / 2 + 8, min(WIDTH - width / 2 - 8, cx))
                    cy = max(self.VIEW.top + height / 2 + 6,
                             min(self.VIEW.bottom - height / 2 - 6, cy))
                    plate = pygame.Rect(0, 0, width, height)
                    plate.center = (int(cx), int(cy))
                    if plate.colliderect(self._mini.inflate(8, 8)):
                        continue
                    if any(plate.colliderect(other) for other in node_rects):
                        continue
                    if any(plate.colliderect(other) for other in placed):
                        continue
                    best = plate
                    break
                if best is not None:
                    break
            if best is None:
                continue
            result.append({
                "index": bi, "branch": branch, "rect": best,
                "text": text, "font": font, "anchor": (anchor_x, anchor_y),
                "color": skill_board.BoardLayout.branch_color(zone, bi),
            })
            placed.append(best)
        return result

    def _draw_branch_labels(self, screen, rows):
        """Подписи ветвей — только там, где плашка не задевает узлы."""
        if self.zoom < 0.22:
            return
        zone = self.focus_zone
        if not self._zone_visible(zone):
            return
        main_key = None
        if zone != "player":
            weapon = next((r["weapon"] for r in rows
                           if r["zone"] == zone and r["equipped"]), None)
            if weapon is not None:
                main_key = weapon.main_branch
        for item in self._branch_label_layout(zone, rows):
            branch = item["branch"]
            plate = item["rect"]
            color = item["color"]
            anchor = item["anchor"]
            is_main = branch["key"] == main_key
            # Тонкий поводок показывает, от какой ветви ушла плашка.
            nearest_x = max(plate.left, min(plate.right, anchor[0]))
            nearest_y = max(plate.top, min(plate.bottom, anchor[1]))
            if math.hypot(nearest_x - anchor[0],
                          nearest_y - anchor[1]) > 4:
                pygame.draw.line(screen, self._shade(color, 0.45),
                                 (int(anchor[0]), int(anchor[1])),
                                 (int(nearest_x), int(nearest_y)), 1)
            pygame.draw.rect(screen, (8, 12, 20), plate, border_radius=4)
            pygame.draw.rect(screen, GOLD if is_main else self._shade(color, 0.45),
                             plate, 1, border_radius=4)
            self._text(screen, item["font"], item["text"], color,
                       center=plate.center)

    def _draw_all_nodes(self, screen, game, rows):
        selected = self.selected_key
        hover = self.hover_key
        for row in rows:
            zone = row["zone"]
            node = row["node"]
            wx, wy = self.layout.node_pos(zone, node["id"])
            sx, sy = self.screen(wx, wy)
            if not (-30 <= sx <= WIDTH + 30 and self.VIEW.top - 30 <= sy <= self.VIEW.bottom + 30):
                continue
            self._draw_node(screen, game, row, sx, sy,
                            selected == self._key(row), hover == self._key(row))

    def _draw_node(self, screen, game, row, sx, sy, selected, hovered):
        zone = row["zone"]
        state = row["state"]
        radius = max(5, int(skill_board.BoardLayout.node_radius(zone) * self.zoom))
        branch_color = skill_board.BoardLayout.branch_color(zone,
                                                           row["branch_index"])
        # Насадки «Арсенала» окрашены в цвет своего режима: картечь, копьё,
        # молот и надрез различаются без наведения и чтения подписи.
        mode_spec = PISTOL_MODES.get(row["node"].get("mode"))
        if mode_spec is not None and state != "training":
            branch_color = mode_spec.get("color", branch_color)
        focused = zone == "player" or zone == self.focus_zone
        dim_factor = 1.0 if focused else 0.58
        if state == "owned":
            fill = self._mix((14, 24, 20), branch_color, 0.28)
            ring = self._shade(branch_color, dim_factor)
            glyph_color = WHITE
        elif state == "ok":
            fill = (14, 20, 30)
            affordable = game.money >= row["price"]
            ring = self._shade(branch_color, dim_factor if affordable else 0.55)
            glyph_color = branch_color if affordable else (132, 124, 102)
        elif state == "unequipped":
            fill = (12, 16, 23)
            ring = self._shade(branch_color, 0.24)
            glyph_color = (76, 82, 96)
        elif state == "training":
            # замок подготовки: узел виден, но ждёт чужую школу или жетон
            fill = (26, 21, 12)
            ring = self._shade((240, 190, 110), 0.62)
            glyph_color = (238, 196, 116)
        elif state == "tokens":
            # вторая ветвь открыта по глубине, но требует жетон школы
            fill = (28, 18, 26)
            ring = self._shade((232, 150, 236), 0.62)
            glyph_color = (242, 174, 246)
        elif state == "excluded":
            fill = (24, 13, 16)
            ring = self._shade(BAD, 0.42)
            glyph_color = (138, 92, 88)
        else:
            fill = (12, 16, 23)
            ring = self._shade(branch_color, 0.30)
            glyph_color = (88, 94, 108)
        # внешний тёмный кант
        pygame.draw.circle(screen, (3, 5, 9), (int(sx), int(sy)), radius + 2)
        pygame.draw.circle(screen, fill, (int(sx), int(sy)), radius)
        pygame.draw.circle(screen, ring, (int(sx), int(sy)), radius,
                           max(1, int(2.4 * self.zoom)))
        if state == "owned":
            pygame.draw.circle(screen, self._shade(branch_color, 0.16),
                               (int(sx), int(sy)), max(1, int(radius * 0.64)))
        if state == "ok":
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 430.0
                                         + row["branch_index"])
            if game.money >= row["price"]:
                pygame.draw.circle(screen, self._mix(ring, GOLD, 0.25 + 0.35 * pulse),
                                   (int(sx), int(sy)), radius + 2, 1)
        glyph = self._branch_glyph(zone, row["branch"], row["branch_index"])
        self._draw_glyph(screen, glyph, sx, sy,
                         max(4.5, radius * 0.50), glyph_color)
        if state == "excluded":
            # перечёркнутая альтернатива: выбор уже сделан, а не «закрыто»
            pygame.draw.line(screen, self._shade(BAD, 0.9),
                             (sx - radius * 0.7, sy - radius * 0.7),
                             (sx + radius * 0.7, sy + radius * 0.7),
                             max(1, int(2 * self.zoom)))
            pygame.draw.line(screen, self._shade(BAD, 0.9),
                             (sx + radius * 0.7, sy - radius * 0.7),
                             (sx - radius * 0.7, sy + radius * 0.7),
                             max(1, int(2 * self.zoom)))
        if state == "owned":
            dot = (int(sx + radius * 0.55), int(sy + radius * 0.55))
            pygame.draw.circle(screen, (18, 44, 30), dot, max(3, int(4.5 * self.zoom)))
            pygame.draw.circle(screen, GOOD, dot, max(3, int(4.5 * self.zoom)), 1)
        if selected:
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 360.0)
            visuals.draw_ring(screen, sx, sy - 1,
                              int((radius + 7 + 2 * pulse)),
                              GOLD, max(1, int(2 * self.zoom)), 235)
        elif hovered:
            visuals.draw_ring(screen, sx, sy, int(radius + 5), WHITE, 1, 150)

    # ------------------------------------------------------------ ИКОНКИ
    @staticmethod
    def _branch_glyph(zone, branch, branch_index):
        if zone == "player":
            return {"vitality": "heart", "mobility": "boot",
                    "precision": "target"}.get(branch["key"], "rune")
        key = branch["key"]
        known = {
            "pierce": "arrow", "ricochet": "bounce", "ballistics": "target",
            "swift": "bolt", "small": "bullet", "economist": "coin",
            "buckshot": "pellets", "demolition": "bomb", "siege": "target",
            "dust": "burst",
            # Энергопушка: заряд, гибкость, площадь, накопитель.
            "overdrive": "bolt", "flex": "burst",
            "resonance": "target", "capacitor": "shield",
        }
        if key in known:
            return known[key]
        return ("blade", "burst", "shield")[branch_index % 3]

    def _draw_glyph(self, screen, glyph, cx, cy, size, color):
        w = max(1, int(size * 0.32))
        s = size
        if glyph == "arrow":
            pygame.draw.line(screen, color, (cx - s, cy), (cx + s, cy), w)
            pygame.draw.lines(screen, color, False,
                              [(cx + s * 0.2, cy - s * 0.7),
                               (cx + s, cy), (cx + s * 0.2, cy + s * 0.7)], w)
        elif glyph == "bounce":
            pygame.draw.lines(screen, color, False,
                              [(cx - s, cy + s * 0.6), (cx - s * 0.2, cy - s * 0.6),
                               (cx + s * 0.4, cy + s * 0.2), (cx + s, cy - s * 0.5)], w)
        elif glyph == "target":
            pygame.draw.circle(screen, color, (int(cx), int(cy)), int(s), w)
            pygame.draw.line(screen, color, (cx - s * 1.2, cy), (cx + s * 1.2, cy), 1)
            pygame.draw.line(screen, color, (cx, cy - s * 1.2), (cx, cy + s * 1.2), 1)
        elif glyph == "bolt":
            pygame.draw.polygon(screen, color, [
                (cx + s * 0.15, cy - s), (cx - s * 0.65, cy + s * 0.12),
                (cx - s * 0.02, cy + s * 0.12), (cx - s * 0.2, cy + s),
                (cx + s * 0.72, cy - s * 0.18), (cx + s * 0.08, cy - s * 0.18)])
        elif glyph == "bullet":
            pygame.draw.circle(screen, color, (int(cx - s * 0.4), int(cy - s * 0.35)), max(1, int(s * 0.3)))
            pygame.draw.circle(screen, color, (int(cx + s * 0.45), int(cy - s * 0.35)), max(1, int(s * 0.3)))
            pygame.draw.circle(screen, color, (int(cx), int(cy + s * 0.45)), max(1, int(s * 0.3)))
        elif glyph == "coin":
            pygame.draw.circle(screen, color, (int(cx), int(cy)), int(s), w)
            pygame.draw.circle(screen, color, (int(cx), int(cy)), max(1, int(s * 0.45)), 1)
        elif glyph == "pellets":
            for ox, oy in ((-0.55, -0.35), (0.45, -0.38), (-0.2, 0.45),
                           (0.62, 0.38), (-0.72, 0.35)):
                pygame.draw.circle(screen, color, (int(cx + s * ox), int(cy + s * oy)),
                                   max(1, int(s * 0.22)))
        elif glyph == "bomb":
            pygame.draw.circle(screen, color, (int(cx), int(cy + s * 0.25)), int(s * 0.72), w)
            pygame.draw.line(screen, color, (cx + s * 0.38, cy - s * 0.42),
                             (cx + s * 0.78, cy - s), w)
        elif glyph == "blade":
            pygame.draw.line(screen, color, (cx - s * 0.7, cy + s * 0.8),
                             (cx + s * 0.65, cy - s * 0.85), w)
            pygame.draw.line(screen, color, (cx - s * 0.9, cy + s * 0.3),
                             (cx - s * 0.1, cy + s * 0.95), w)
        elif glyph == "burst":
            for angle in (-2.2, -1.1, -0.15, 0.9, 2.0):
                pygame.draw.line(screen, color, (cx, cy),
                                 (cx + math.cos(angle) * s,
                                  cy + math.sin(angle) * s), w)
            pygame.draw.circle(screen, color, (int(cx), int(cy)), max(1, int(s * 0.25)))
        elif glyph == "shield":
            pygame.draw.polygon(screen, color, [
                (cx, cy - s), (cx + s * 0.82, cy - s * 0.45),
                (cx + s * 0.55, cy + s * 0.72), (cx, cy + s),
                (cx - s * 0.55, cy + s * 0.72), (cx - s * 0.82, cy - s * 0.45)], w)
        elif glyph == "heart":
            pygame.draw.circle(screen, color, (int(cx - s * 0.4), int(cy - s * 0.2)), max(1, int(s * 0.45)))
            pygame.draw.circle(screen, color, (int(cx + s * 0.4), int(cy - s * 0.2)), max(1, int(s * 0.45)))
            pygame.draw.polygon(screen, color, [(cx - s * 0.9, cy), (cx + s * 0.9, cy),
                                                (cx, cy + s)])
        elif glyph == "boot":
            pygame.draw.lines(screen, color, False,
                              [(cx - s, cy + s * 0.25), (cx - s * 0.1, cy + s * 0.25),
                               (cx - s * 0.1, cy - s * 0.85)], w)
            pygame.draw.lines(screen, color, False,
                              [(cx - s * 0.1, cy + s * 0.25), (cx + s, cy + s * 0.25),
                               (cx + s, cy + s * 0.7)], w)
        else:
            pygame.draw.circle(screen, color, (int(cx), int(cy)), int(s * 0.8), w)
            pygame.draw.circle(screen, color, (int(cx), int(cy)), max(1, int(s * 0.2)))

    def _draw_player_glyph(self, screen, cx, cy, size, color):
        s = size
        pygame.draw.circle(screen, color, (int(cx), int(cy - s * 0.45)),
                           max(2, int(s * 0.32)), 2)
        pygame.draw.lines(screen, color, False,
                          [(cx - s * 0.65, cy + s * 0.7),
                           (cx - s * 0.25, cy - s * 0.05),
                           (cx, cy + s * 0.38),
                           (cx + s * 0.25, cy - s * 0.05),
                           (cx + s * 0.65, cy + s * 0.7)], 2)

    def _draw_weapon_glyph(self, screen, key, cx, cy, size, color):
        s = size
        w = max(1, int(size * 0.16))
        if key == "pistol":
            pygame.draw.rect(screen, color, (cx - s * 0.6, cy - s * 0.22,
                                             s * 1.25, s * 0.34), w, border_radius=2)
            pygame.draw.lines(screen, color, False,
                              [(cx - s * 0.15, cy + s * 0.1),
                               (cx - s * 0.32, cy + s * 0.85),
                               (cx + s * 0.12, cy + s * 0.85)], w)
        elif key == "shotgun":
            pygame.draw.line(screen, color, (cx - s * 0.85, cy - s * 0.25),
                             (cx + s * 0.95, cy - s * 0.25), w + 1)
            pygame.draw.line(screen, color, (cx - s * 0.75, cy + s * 0.08),
                             (cx + s * 0.3, cy + s * 0.08), w)
            pygame.draw.line(screen, color, (cx - s * 0.5, cy - s * 0.25),
                             (cx - s * 0.8, cy + s * 0.4), w)
        elif key == "sniper":
            pygame.draw.line(screen, color, (cx - s, cy + s * 0.12),
                             (cx + s, cy + s * 0.12), w)
            pygame.draw.rect(screen, color, (cx - s * 0.22, cy - s * 0.63,
                                             s * 0.52, s * 0.28), 1, border_radius=2)
            pygame.draw.line(screen, color, (cx + s * 0.25, cy - s * 0.1),
                             (cx + s * 0.52, cy - s * 0.72), w)
        elif key == "cannon":
            # Пушка: ствол-катушка и ядро заряда перед дулом.
            pygame.draw.rect(screen, color, (cx - s * 0.85, cy - s * 0.26,
                                             s * 1.25, s * 0.52), 1,
                             border_radius=3)
            for ring in range(3):
                pygame.draw.line(
                    screen, color,
                    (cx - s * 0.5 + ring * s * 0.28, cy - s * 0.26),
                    (cx - s * 0.5 + ring * s * 0.28, cy + s * 0.26), w)
            pygame.draw.circle(screen, color, (int(cx + s * 0.66), int(cy)),
                               max(2, int(s * 0.24)), 1)
        elif key == "knife":
            pygame.draw.polygon(screen, color, [
                (cx - s * 0.9, cy + s * 0.7), (cx + s * 0.7, cy - s * 0.65),
                (cx + s * 0.85, cy - s * 0.9), (cx + s * 0.52, cy - s * 0.28)], 2)
            pygame.draw.line(screen, color, (cx - s * 0.7, cy + s * 0.8),
                             (cx - s * 0.35, cy + s * 0.35), w)
        elif key == "machete":
            pygame.draw.polygon(screen, color, [
                (cx - s * 0.8, cy + s * 0.9), (cx + s * 0.55, cy - s * 0.45),
                (cx + s * 0.95, cy - s * 0.9), (cx + s * 0.22, cy + s * 0.2)], 2)
            pygame.draw.line(screen, color, (cx - s * 0.85, cy + s * 0.85),
                             (cx - s * 0.35, cy + s * 0.4), w)
        elif key == "katana":
            pygame.draw.lines(screen, color, False, [
                (cx - s * 0.65, cy + s * 0.85), (cx + s * 0.2, cy - s * 0.1),
                (cx + s * 0.65, cy - s * 0.48), (cx + s * 0.92, cy - s * 0.87)], 2)
            pygame.draw.line(screen, color, (cx - s * 0.72, cy + s * 0.75),
                             (cx - s * 0.95, cy + s * 0.98), w)
        elif key == "hammer":
            pygame.draw.line(screen, color, (cx - s * 0.55, cy + s * 0.95),
                             (cx + s * 0.25, cy - s * 0.2), w + 1)
            pygame.draw.rect(screen, color, (cx + s * 0.05, cy - s * 0.78,
                                             s * 0.82, s * 0.42), 2, border_radius=2)
        elif key == "shovel":
            pygame.draw.line(screen, color, (cx - s * 0.55, cy + s * 0.95),
                             (cx + s * 0.25, cy - s * 0.15), w + 1)
            pygame.draw.polygon(screen, color, [
                (cx + s * 0.06, cy - s * 0.2), (cx + s * 0.82, cy - s * 0.72),
                (cx + s * 0.98, cy - s * 0.38), (cx + s * 0.3, cy + s * 0.18)], 2)
        elif key == "shield":
            pygame.draw.polygon(screen, color, [
                (cx, cy - s), (cx + s * 0.82, cy - s * 0.45),
                (cx + s * 0.55, cy + s * 0.72), (cx, cy + s),
                (cx - s * 0.55, cy + s * 0.72), (cx - s * 0.82, cy - s * 0.45)], 2)
            pygame.draw.circle(screen, color, (int(cx), int(cy)), max(2, int(s * 0.3)), 1)
        else:
            pygame.draw.circle(screen, color, (int(cx), int(cy)), int(s * 0.7), 2)

    # ------------------------------------------------------------ HUD
    def _draw_category_titles(self, screen, game):
        if self.zoom < 0.45:
            return
        left_x, left_y = self.layout.category_center("melee")[0], 96
        right_x, right_y = self.layout.category_center("firearm")[0], 96
        for x, y, cat in ((left_x, left_y, "melee"),
                          (right_x, right_y, "firearm")):
            color = CATEGORY_COLORS[cat]
            self._text_world(screen, CATEGORY_LABELS[cat], x, y, 19, color)
            self._text_world(screen, CATEGORY_SUBTITLES[cat], x, y + 24, 11,
                             self._shade(color, 0.68))
            sx, sy = self.screen(x, y + 40)
            pygame.draw.line(screen, self._shade(color, 0.35),
                             (sx - 140 * self.zoom, sy),
                             (sx + 140 * self.zoom, sy), 1)

    def _draw_top(self, screen, game):
        pygame.draw.rect(screen, PANEL, (0, 0, WIDTH, self.TOP))
        pygame.draw.line(screen, (44, 66, 82), (0, self.TOP - 1), (WIDTH, self.TOP - 1), 1)
        self._text(screen, self.big, "ДРЕВО ГЛУБИНЫ", (221, 242, 236), pos=(22, 10))
        self._text(screen, self.tiny, f"ЕДИНАЯ ДОСКА НАВЫКОВ · СЕКТОР {game.depth:02d}",
                   (113, 169, 168), pos=(24, 45))
        # три быстрых прыжка по категориям
        chips = (
            ("1", "ГЕРОЙ", "player"),
            ("2", "СТВОЛ", "firearm"),
            ("3", "БЛИЖНИЙ", "melee"),
        )
        x = 340
        self._chips = []
        for key, label, cat in chips:
            active = (self.focus_zone == "player" and cat == "player") or (
                cat != "player" and category_of(self.focus_zone) == cat)
            color = GOLD if active else (122, 140, 162)
            rect = pygame.Rect(x, 16, 86, 30)
            pygame.draw.rect(screen, (18, 25, 37), rect, border_radius=6)
            pygame.draw.rect(screen, color if active else (43, 54, 69),
                             rect, 1, border_radius=6)
            self._text(screen, self.tiny, key, color, pos=(rect.x + 8, rect.y + 7))
            self._text(screen, self.tiny, label, color, pos=(rect.x + 23, rect.y + 7))
            self._chips.append((rect, cat))
            x += 92
        focus = zone_name(self.focus_zone)
        self._text(screen, self.small, f"ФОКУС: {focus}", (150, 177, 190),
                   pos=(x + 10, 21))
        # кошелёк
        value = str(game.money)
        vw = self.font.size(value)[0]
        self._text(screen, self.font, value, GOLD,
                   pos=(WIDTH - 24 - vw, 18))
        pygame.draw.circle(screen, (120, 88, 28), (WIDTH - 35 - vw, 31), 9)
        pygame.draw.circle(screen, GOLD, (WIDTH - 36 - vw, 30), 7)

    def _draw_minimap(self, screen, game, rows):
        rect = self._mini
        pygame.draw.rect(screen, (8, 12, 21), rect, border_radius=7)
        pygame.draw.rect(screen, (48, 66, 84), rect, 1, border_radius=7)
        self._text(screen, self.tiny, "КАРТА", (116, 156, 166),
                   pos=(rect.x + 8, rect.y + 4))
        inner = self._mini_inner()
        sx = inner.w / self.layout.board_w
        sy = inner.h / self.layout.board_h
        # регионы
        for zone in MELEE_ORDER + RANGED_ORDER:
            wx, wy = self.layout.root(zone)
            px = inner.x + wx * sx
            py = inner.y + wy * sy
            color = zone_color(zone)
            pygame.draw.circle(screen, self._shade(color, 0.24),
                               (int(px), int(py)),
                               max(4, int(self.layout.zone_extents[zone] * sx)), 1)
            pygame.draw.circle(screen, color if zone == self.focus_zone else
                               self._shade(color, 0.72),
                               (int(px), int(py)), 3 if zone == self.focus_zone else 2)
        player_x, player_y = self.layout.root("player")
        px = inner.x + player_x * sx
        py = inner.y + player_y * sy
        pygame.draw.circle(screen, GOLD, (int(px), int(py)), 4)
        # выбранный узел
        selected = self._selected_row(rows)
        if selected is not None:
            wx, wy = self.layout.node_pos(selected["zone"], selected["node"]["id"])
            pygame.draw.circle(screen, WHITE,
                               (int(inner.x + wx * sx), int(inner.y + wy * sy)), 2)
        # видимая область
        half_w = self.VIEW.w / (2.0 * self.zoom) * sx
        half_h = self.VIEW.h / (2.0 * self.zoom) * sy
        cx = inner.x + self.camera[0] * sx
        cy = inner.y + self.camera[1] * sy
        view = pygame.Rect(int(cx - half_w), int(cy - half_h),
                           max(3, int(half_w * 2)), max(3, int(half_h * 2)))
        pygame.draw.rect(screen, (224, 216, 176), view, 1)
        self._text(screen, self.tiny, f"{int(self.zoom * 100)}%",
                   (128, 160, 170), pos=(rect.right - 40, rect.y + 4))

    def _state_text(self, row, game):
        state = row["state"]
        if state == "owned":
            return "ИЗУЧЕНО", GOOD
        if state == "prev":
            return "ЗАКРЫТО: НУЖНЫ СОСЕДНИЕ НАВЫКИ", (184, 190, 204)
        if state == "excluded":
            return "ВЫБРАНА ДРУГАЯ АЛЬТЕРНАТИВА", BAD
        if state == "depth":
            requirement = skill_tree.cross_branch_requirement(
                row["weapon"], row["branch"], row["node"])
            if requirement is not None:
                needed, current = requirement
                return (f"НУЖНА ГЛУБИНА ОСНОВЫ {needed} (СЕЙЧАС {current})",
                        (184, 190, 204))
            return "ТОЛЬКО ОСНОВНАЯ ВЕТВЬ", (184, 190, 204)
        if state == "tokens":
            toll = skill_tree.cross_branch_toll(
                row["weapon"], row["branch"], row["node"])
            if skill_tree.can_pay_cross_toll(
                    game.player, row["weapon"], row["branch"], row["node"]):
                if game.money < row["price"]:
                    return f"НЕ ХВАТАЕТ {row['price'] - game.money}", LACK
                return f"ЖЕТОН ШКОЛЫ: {toll} · ENTER СПИШЕТ", (232, 170, 236)
            return f"НУЖЕН ЖЕТОН ШКОЛЫ: {toll}", (208, 140, 220)
        if state == "unequipped":
            return "ОРУЖИЕ НЕ ЭКИПИРОВАНО", (208, 170, 106)
        if state == "training":
            missing = skill_tree.missing_training(game.player, row["node"])
            if missing and skill_tree.can_cover_training(game.player, row["node"]):
                if game.money < row["price"]:
                    return f"НЕ ХВАТАЕТ {row['price'] - game.money}", LACK
                return "ПОДГОТОВКА: ENTER СПИШЕТ ЖЕТОН", GOLD
            names = ", ".join(
                f"{skill_tree.training_name(key)} {have}/{need}"
                for key, need, have, _ in missing)
            return f"НУЖНА ПОДГОТОВКА: {names}", (208, 170, 106)
        if game.money < row["price"]:
            return f"НЕ ХВАТАЕТ {row['price'] - game.money}", LACK
        return f"ЦЕНА: {row['price']}", GOLD

    def _draw_info(self, screen, game, rows):
        rect = pygame.Rect(0, HEIGHT - self.INFO_H, WIDTH, self.INFO_H)
        pygame.draw.rect(screen, (7, 11, 19), rect)
        pygame.draw.line(screen, (49, 68, 84), (0, rect.y), (WIDTH, rect.y), 1)
        row = self._selected_row(rows)
        if row is None:
            self._text(screen, self.font, "Выберите узел на доске", DIM,
                       center=(WIDTH // 2, rect.y + 46))
            self._draw_hint(screen, rect)
            return
        node, branch, zone = row["node"], row["branch"], row["zone"]
        color = zone_color(zone)
        branch_color = skill_board.BoardLayout.branch_color(zone, row["branch_index"])
        self._text(screen, self.mid, node["name"], WHITE, pos=(24, rect.y + 12))
        path = f"{zone_name(zone)} · {branch['name']} · уровень {node['tier']}"
        if node.get("role"):
            path += f" · {node['role']}"
        self._text(screen, self.tiny, path, self._shade(color, 0.86),
                   pos=(26, rect.y + 44))
        status, status_color = self._state_text(row, game)
        status = self._fit(self.small, status, 520)
        sw = self.small.size(status)[0]
        self._text(screen, self.small, status, status_color,
                   pos=(WIDTH - 24 - sw, rect.y + 16))
        if row["state"] == "ok":
            left = game.money - row["price"]
            self._text(screen, self.tiny, f"после покупки: {left} монет",
                       (132, 148, 164) if left >= 0 else LACK,
                       pos=(WIDTH - 26 - self.tiny.size(f'после покупки: {left} монет')[0],
                            rect.y + 44))
        self._text(screen, self.small, self._fit(self.small, node["desc"], 690),
                   (171, 184, 202), pos=(26, rect.y + 70))

        preview = []
        if row["kind"] == "player":
            if row["state"] == "ok":
                preview = skill_tree.preview_player_node(game.player, node)
        elif row["state"] == "ok" and row["weapon"] is not None:
            preview = skill_tree.preview_node(row["weapon"], branch, node)
        if preview:
            # строка эффектов занимает всю ширину панели: ниже неё только
            # подсказка управления, поэтому не режем её на середине.
            self._draw_effect_line(screen, preview, 26, rect.y + 96, WIDTH - 26)
        elif row["state"] == "prev":
            if row["kind"] == "player":
                prev_names = [n["name"] for n in branch["nodes"]
                              if n["id"] in skill_tree.prerequisites(branch, node)
                              and n["id"] not in game.player.skill_nodes]
            else:
                prev_names = skill_tree.missing_prerequisites(
                    row["weapon"], branch, node) if row["weapon"] else []
            if prev_names:
                text = "Сначала изучите: " + ", ".join(prev_names)
            else:
                text = "Сначала изучите соседние навыки"
            self._text(screen, self.small, self._fit(self.small, text, 760),
                       (150, 162, 180), pos=(26, rect.y + 96))
        elif row["state"] == "excluded":
            partner = (skill_tree.choice_partner(row["weapon"], node)
                       if row["weapon"] is not None else None)
            text = ("Эта ветвь уже выбрала: "
                    + (partner["name"] if partner else "другую доктрину"))
            self._text(screen, self.small, self._fit(self.small, text, 760),
                       BAD, pos=(26, rect.y + 96))
        elif row["state"] == "depth":
            main = next((b["name"] for b in skill_tree.branches_of(row["weapon"])
                         if b["key"] == row["weapon"].main_branch), "основная")
            requirement = skill_tree.cross_branch_requirement(
                row["weapon"], branch, node)
            if requirement is not None:
                needed, current = requirement
                text = (f"Вторая ветвь: нужна глубина {needed} в основной "
                        f"«{main}» (сейчас {current}).")
            else:
                text = f"Сначала выберите и развивайте основную ветвь: {main}"
            self._text(screen, self.small, self._fit(self.small, text, 760),
                       (150, 162, 180), pos=(26, rect.y + 96))
        elif row["state"] == "tokens":
            toll = skill_tree.cross_branch_toll(row["weapon"], branch, node)
            names = ", ".join(
                skill_tree.training_name(key)
                for key in skill_tree.token_keys_for(row["weapon"].key))
            have = skill_tree.token_count(game.player, row["weapon"].key)
            affordable = skill_tree.can_pay_cross_toll(
                game.player, row["weapon"], branch, node)
            text = (f"Вторая ветвь открыта, нужен жетон школы: {toll} "
                    f"(есть {have}). Принимаются: {names}")
            if affordable:
                text += (" · не хватает монет" if game.money < row["price"]
                         else " · Enter спишет жетон")
            # Список родственных школ длинный; мелкая строка на всю
            # ширину панели читается лучше, чем обрезанный «Снайперская...».
            self._text(screen, self.tiny, self._fit(self.tiny, text, WIDTH - 52),
                       (232, 170, 236) if affordable else (208, 140, 220),
                       pos=(26, rect.y + 98))
        elif row["state"] == "unequipped":
            self._text(screen, self.small,
                       "Это отдельное древо оружия. Купите и экипируйте его в магазине.",
                       (150, 162, 180), pos=(26, rect.y + 96))
        elif row["state"] == "owned":
            self._text(screen, self.small, "Навык уже работает.", (126, 188, 146),
                       pos=(26, rect.y + 96))
        if row["state"] == "training":
            missing = skill_tree.missing_training(game.player, node)
            if missing and skill_tree.can_cover_training(game.player, node):
                related = []
                for key, _, _, _ in missing:
                    related.extend(skill_tree.training_name(token_key)
                                   for token_key in skill_tree.token_keys_for(key)
                                   if token_key != key)
                text = ("Жетон тренировки будет списан: "
                        + ", ".join(skill_tree.training_name(key)
                                    for key, _, _, _ in missing))
                if related:
                    text += " (подойдёт и родственный: " + ", ".join(related) + ")"
                color = GOLD
            else:
                text = ("Подготовка: "
                        + ", ".join(
                            f"{skill_tree.training_name(key)} {have}/{need}"
                            for key, need, have, _ in missing)
                        + " — изучите навыки школы или купите жетон "
                          "(родственные школы тоже принимаются)")
                color = (208, 170, 106)
            self._text(screen, self.tiny, self._fit(self.tiny, text, WIDTH - 52),
                       color, pos=(26, rect.y + 120))
        self._draw_hint(screen, rect)

    def _draw_effect_line(self, screen, preview, x, y, max_x):
        x += self._text(screen, self.small, "Эффект:", (140, 154, 174), pos=(x, y)) + 10
        for item in preview:
            text = f"{item['label']} {item['before']} -> {item['after']}"
            color = GOOD if item["better"] else BAD
            if x + self.small.size(text)[0] > max_x:
                self._text(screen, self.small, "...", TEXT_DIM, pos=(x, y))
                return
            x += self._text(screen, self.small, text, color, pos=(x, y)) + 24

    def _draw_hint(self, screen, rect):
        hint = ("WASD / перетаскивание — двигать доску    колесо — масштаб    "
                "Tab — зона    1 / 2 / 3 — прыжок    двойной клик / Enter — изучить    T / Y / E / Esc — выход")
        self._text(screen, self.tiny, self._fit(self.tiny, hint, WIDTH - 48),
                   (112, 132, 152), pos=(24, rect.bottom - 25))

    def _draw_tooltip(self, screen, rows):
        if self.hover_key is None or self.hover_key == self.selected_key:
            return
        row = self._row_by_key(rows, self.hover_key)
        if row is None:
            return
        mx, my = pygame.mouse.get_pos()
        name = self._fit(self.small, row["node"]["name"], 230)
        zone = zone_name(row["zone"])
        state = row["state"]
        state_text = {
            "owned": "изучено",
            "prev": "закрыто",
            "excluded": "другая доктрина",
            "depth": "закрыто",
            "tokens": "нужен жетон",
            "unequipped": "нужно оружие",
            "training": "нужна подготовка",
        }.get(state)
        if state_text is None:
            state_text = f"{row['price']} монет"
        lines = (name, f"{zone} · {state_text}")
        width = max(self.small.size(lines[0])[0], self.tiny.size(lines[1])[0]) + 22
        height = 48
        x = max(8, min(WIDTH - width - 8, mx + 16))
        y = max(self.TOP + 8, min(HEIGHT - self.INFO_H - height - 8, my - 56))
        box = pygame.Rect(x, y, width, height)
        pygame.draw.rect(screen, (11, 16, 26), box, border_radius=6)
        pygame.draw.rect(screen, self._shade(zone_color(row["zone"]), 0.7),
                         box, 1, border_radius=6)
        self._text(screen, self.small, lines[0], WHITE, pos=(x + 11, y + 6))
        self._text(screen, self.tiny, lines[1], (148, 164, 182), pos=(x + 11, y + 27))

    def _draw_message(self, screen):
        if self.message_timer <= 0.0 or not self.message:
            return
        font = self.small
        text = self._fit(font, self.message, 660)
        width = font.size(text)[0] + 30
        box = pygame.Rect(0, 0, width, 30)
        box.center = (WIDTH // 2, self.TOP + 22)
        pulse = 0.75 + 0.25 * math.sin(pygame.time.get_ticks() / 160.0)
        pygame.draw.rect(screen, (9, 15, 22), box, border_radius=7)
        pygame.draw.rect(screen, tuple(int(c * pulse) for c in self.message_color),
                         box, 1, border_radius=7)
        self._text(screen, font, text, self.message_color,
                   center=box.center)

    def _draw_cursor(self, screen):
        """Стрелка-указатель доски: системный курсор скрыт во всей игре."""
        mx, my = pygame.mouse.get_pos()
        points = (
            (mx, my),
            (mx + 14, my + 12),
            (mx + 8, my + 14),
            (mx + 12, my + 22),
            (mx + 8, my + 24),
            (mx + 4, my + 16),
            (mx, my + 20),
        )
        pygame.draw.polygon(screen, (239, 244, 250), points)
        pygame.draw.lines(screen, (7, 11, 18), True, points, 2)
        # тёплая искра у острия связывает курсор с золотой доской
        pygame.draw.line(screen, GOLD, (mx + 1, my + 2), (mx + 4, my + 5), 1)

    # ------------------------------------------------------------ ГЛАВНЫЙ ВЫЗОВ
    def draw(self, screen, game):
        self._tick()
        rows = self.rows(game)
        self._ensure_selection(rows)
        self._update_hover(game)
        self._draw_background(screen, game)
        self._draw_player_tree(screen, rows)
        for zone in MELEE_ORDER + RANGED_ORDER:
            self._draw_weapon_tree(screen, zone, rows)
        self._draw_category_titles(screen, game)
        self._draw_all_nodes(screen, game, rows)
        self._draw_branch_labels(screen, rows)
        self._draw_top(screen, game)
        self._draw_minimap(screen, game, rows)
        self._draw_info(screen, game, rows)
        self._draw_tooltip(screen, rows)
        self._draw_message(screen)
        self._draw_cursor(screen)
