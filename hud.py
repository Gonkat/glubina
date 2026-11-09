"""
Интерфейс: титульный экран, HUD, пауза, смерть.

HUD отвечает только за отрисовку — вся логика остаётся в Game. Задача
интерфейса: игрок должен понимать, что происходит, не читая абзацы.
Поэтому здоровье, патроны, перекат, серия и взаимодействия собраны
в четыре опорные зоны по краям экрана, а центр остаётся миру.
"""
import math
import textwrap

import pygame

import soundbank
import visuals
from bosses import RECIPES
from settings import (
    DASH_COOLDOWN,
    DIFFICULTIES,
    HEIGHT,
    STATE_DIFFICULTY,
    STATE_GAME_OVER,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_SETTINGS,
    WIDTH,
)

# ---------------------------------------------------------------- ПАЛИТРА UI
PANEL = (16, 21, 31)
PANEL_EDGE = (64, 82, 108)
PANEL_LIGHT = (28, 36, 50)
TEXT = (234, 241, 250)
DIM = (144, 156, 178)
GOLD = (255, 208, 112)
GREEN = (134, 226, 154)
RED = (238, 100, 92)
CYAN = (106, 218, 212)
PURPLE = (198, 144, 255)

HINT_1 = "WASD — движение   ЛКМ — огонь / заряд   ПКМ — удар   Space — рывок"
HINT_2 = "R — перезарядка   V — режим   Q — граната   G — аптечка   F — артефакт   E — взаимодействие   T — дерево"


class HUD:
    """Только рисует. Ничего не считает и не меняет состояние игры."""

    def __init__(self):
        self.overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.overlay.fill((6, 9, 16, 226))
        self.menu_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.menu_overlay.fill((5, 7, 14, 218))
        self._title_bg = None
        self._dust = [(i * 97 % WIDTH, (i * 53) % HEIGHT,
                       (i % 5) * 0.4 + 0.3, (i % 7) * 0.11)
                      for i in range(46)]

    # ------------------------------------------------------------ ОБЩЕЕ
    @staticmethod
    def _panel(screen, rect, color=PANEL, edge=PANEL_EDGE, radius=10, alpha=240):
        surf = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        surf.fill((*color, alpha))
        pygame.draw.rect(surf, edge, surf.get_rect(), 1, border_radius=radius)
        screen.blit(surf, rect.topleft)

    # ------------------------------------------------------------ ГЛАВНЫЙ HUD
    def draw(self, screen, game):
        if game.state == STATE_GAME_OVER:
            self._draw_game_over(screen, game)
            return
        if game.state not in (STATE_PLAYING, STATE_PAUSED, STATE_SETTINGS,
                             STATE_DIFFICULTY):
            return

        self._draw_vitals(screen, game)
        self._draw_weapon(screen, game)
        self._draw_loadout(screen, game)
        self._draw_top(screen, game)
        self._draw_combo(screen, game)
        self._draw_boss_bars(screen, game)
        self._draw_compass(screen, game)
        self._draw_prompt(screen, game)
        self._draw_notice(screen, game)
        # урок управления не спорит с полосой босса: во время боя
        # приоритет у здоровья цели, а не у подсказок
        boss_active = any(getattr(e, "is_boss", False) for e in game.enemies)
        if (game.state == STATE_PLAYING and game.depth == 1
                and game.elapsed < 16 and not boss_active):
            self._draw_hints(screen, game)
        self._draw_crosshair(screen, game)

    # ------------------------------------------------------------ ЖИЗНЬ / РЫВОК
    def _draw_vitals(self, screen, game):
        player = game.player
        rect = pygame.Rect(22, HEIGHT - 148, 338, 126)
        self._panel(screen, rect)
        ratio = max(0.0, player.hp / max(1, player.max_hp))
        hp_color = GREEN if ratio > 0.55 else (240, 196, 94) if ratio > 0.28 else RED
        if ratio <= 0.28 and player.alive:
            pulse = 0.6 + 0.4 * math.sin(game.elapsed * 9)
            hp_color = tuple(int(c * pulse) for c in RED)
        visuals.text(screen, "ЗДОРОВЬЕ", (rect.x + 16, rect.y + 10), 18, DIM)
        visuals.text(screen, f"{int(player.hp)} / {int(player.max_hp)}",
                     (rect.right - 16, rect.y + 9), 20, TEXT, align="right")
        bar_rect = pygame.Rect(rect.x + 16, rect.y + 34, rect.w - 32, 15)
        visuals.bar(screen, bar_rect, ratio, hp_color, (24, 28, 38),
                    border=(8, 12, 18), segments=10)

        # перекат
        ready = player.dash_cd <= 0.0
        dash_ratio = 1.0 - player.dash_cd / DASH_COOLDOWN if player.dash_cd > 0 else 1.0
        dash_ratio = max(0.0, min(1.0, dash_ratio))
        visuals.key_badge(screen, "SPACE", rect.x + 16, rect.y + 62,
                          CYAN if ready else DIM, 16)
        visuals.text(screen, "РЫВОК", (rect.x + 82, rect.y + 64), 18,
                     CYAN if ready else DIM)
        visuals.text(screen, "готов" if ready else f"{player.dash_cd:.1f} с",
                     (rect.right - 16, rect.y + 64), 17,
                     CYAN if ready else DIM, align="right")
        visuals.bar(screen, pygame.Rect(rect.x + 16, rect.y + 86, rect.w - 32, 7),
                    dash_ratio, CYAN, (20, 27, 38))

        # артефакт / мелочь
        passive = player.equipment.get("passive_artifact")
        active = player.equipment.get("active_artifact")
        bits = []
        if passive is not None:
            bits.append(f"◆ {passive.name}")
        if active is not None:
            bits.append(f"F {active.name} " +
                        ("готов" if active.ready else f"{active.cooldown_timer:.0f}с"))
        if bits:
            visuals.text(screen, "   ".join(bits), (rect.x + 16, rect.y + 98),
                         16, (186, 198, 218))

    # ------------------------------------------------------------ ОРУЖИЕ
    def _draw_weapon(self, screen, game):
        player = game.player
        weapon = player.firearm
        rect = pygame.Rect(WIDTH - 314, HEIGHT - 148, 292, 126)
        self._panel(screen, rect)
        if weapon is None:
            visuals.text(screen, "ОРУЖИЕ НЕ ЭКИПИРОВАНО", (rect.centerx, rect.y + 40),
                         18, DIM, align="center")
            return
        reserve = player.equipment.ammo_count()
        shots = reserve // max(1, weapon.ammo_cost)
        # длинное имя не должно наезжать на «ПАТРОНЫ» справа
        label = weapon.name.upper()
        max_w = rect.w - 150
        if visuals.text_width(label, 18) > max_w:
            label = weapon.spec.get("short_name", label).upper()
        while label and visuals.text_width(label, 18) > max_w:
            label = label[:-1]
        visuals.text(screen, label, (rect.x + 16, rect.y + 9), 18, GOLD)
        visuals.text(screen, f"{weapon.loaded}", (rect.x + 16, rect.y + 30), 38,
                     TEXT if weapon.loaded else RED)
        visuals.text(screen, f"/ {shots}", (rect.x + 62, rect.y + 48), 18, DIM)
        visuals.text(screen, "ПАТРОНЫ", (rect.right - 16, rect.y + 13), 15, DIM,
                     align="right")

        # магазин точками: быстрее считать взглядом, чем читать число
        mag = max(1, weapon.magazine_size)
        pip_w = (rect.w - 32) / mag
        for i in range(mag):
            x = rect.x + 16 + i * pip_w
            if i < weapon.loaded:
                color = GOLD if weapon.loaded > mag * 0.35 else RED
            else:
                color = (44, 50, 64)
            pygame.draw.rect(screen, color, (int(x), rect.y + 78,
                                             max(2, int(pip_w) - 2), 5),
                             border_radius=2)

        if weapon.is_reloading:
            full = max(0.001, weapon.spec.get("reload_time", 1.0))
            progress = 1.0 - max(0.0, weapon.reload_timer) / full
            visuals.text(screen, "ПЕРЕЗАРЯДКА", (rect.x + 16, rect.y + 92), 16, DIM)
            visuals.bar(screen, pygame.Rect(rect.x + 124, rect.y + 95, 150, 7),
                        progress, GOLD, (20, 26, 36))
        elif weapon.loaded == 0 and shots == 0:
            # Пустой ствол — это не «ещё одна строчка», а причина бежать
            # в магазин: показываем одной ясной парой слов.
            visuals.text(screen, "ПАТРОНОВ НЕТ — ищите магазин",
                         (rect.centerx, rect.y + 92), 15, RED, align="center")
        elif weapon.loaded == 0:
            visuals.text(screen, "ПУСТО", (rect.x + 16, rect.y + 91), 16, DIM)
            visuals.text(screen, "R — ПЕРЕЗАРЯДИТЬ",
                         (rect.right - 16, rect.y + 92), 16, RED, align="right")
        else:
            melee = player.melee
            if getattr(weapon, "uses_charge", False):
                # У пушки вместо строки ближнего боя — состояние заряда.
                if weapon.is_charging:
                    percent = int(round(weapon.charge_ratio * 100))
                    if weapon.mod("full_only") and not weapon.charge_full:
                        label = f"ЗАРЯД {percent}% · ТОЛЬКО 100%"
                        color = (246, 186, 96)
                    elif weapon.charge_full:
                        label = "ПОЛНЫЙ ЗАРЯД · ОТПУСТИТЕ"
                        color = (220, 252, 255)
                    else:
                        label = f"ЗАРЯД {percent}% · ОТПУСТИТЕ"
                        color = (112, 232, 255)
                else:
                    label = f"УДЕРЖИВАЙТЕ ЛКМ · {weapon.charge_time:.2f}с"
                    if weapon.mod("full_only"):
                        label = f"ТОЛЬКО 100% · {weapon.charge_time:.2f}с"
                    color = (138, 204, 224)
                visuals.text(screen, label, (rect.x + 16, rect.y + 91), 13, color)
                # У плазменного пистолета ниже уже стоит строка режима.
                # Ближний бой там не помещается, поэтому не рисуем его
                # поверх «V · ПЛАЗМА»; у пушки строки режима нет.
                if melee is not None and not weapon.has_modes:
                    status = "аура" if melee.is_passive else "ПКМ · X"
                    visuals.text(screen, f"{melee.name} · {status}",
                                 (rect.x + 16, rect.y + 108), 12, DIM)
            elif getattr(weapon, "uses_heat", False):
                # Резак: строка показывает и нагрев, и множитель урона,
                # чтобы риск горячей очереди был виден до сброса.
                if weapon.is_venting:
                    label = f"ПЕРЕГРЕВ · {weapon.vent_timer:.1f}с"
                    color = (255, 138, 110)
                else:
                    percent = int(round(weapon.heat_ratio * 100))
                    label = (f"НАГРЕВ {percent}% · "
                             f"x{weapon.heat_damage_mult:.2f}")
                    color = ((255, 118, 96) if percent >= 70
                             else (226, 170, 140))
                visuals.text(screen, label, (rect.x + 16, rect.y + 91),
                             13, color)
            elif getattr(weapon, "uses_disc", False):
                # Диск: одна строка объясняет второе назначение ЛКМ.
                if weapon.has_live_disc:
                    label = "ЛКМ — ВОЗВРАТ ДИСКА"
                    color = (255, 216, 132)
                else:
                    label = "ЛКМ — ЗАБРОС · ПОВТОР — ПОДЗЫВ"
                    color = (198, 176, 132)
                visuals.text(screen, label, (rect.x + 16, rect.y + 91),
                             13, color)
            elif melee is not None:
                status = "аура" if melee.is_passive else (
                    f"ПКМ · X {game.active_cooldown:.0f}с" if game.active_cooldown > 0
                    else "ПКМ · X готов")
                visuals.text(screen, f"{melee.name} — {status}",
                             (rect.x + 16, rect.y + 91), 15, (186, 198, 218))
            else:
                visuals.text(screen, "R — перезарядка", (rect.x + 16, rect.y + 93),
                             15, DIM)
        # Режим «Арсенала» — отдельная строка: видно и название, и цену
        # выстрела, не отнимая места у патронов и перезарядки.
        if weapon.has_modes:
            color = weapon.mode_color
            visuals.text(screen, f"V · {weapon.mode_name.upper()}",
                         (rect.x + 16, rect.y + 108), 13, color)
            rounds = weapon.rounds_per_shot
            if rounds > 1:
                visuals.text(screen, f"{rounds} патр./выстрел",
                             (rect.right - 16, rect.y + 108), 12, DIM,
                             align="right")

    # ------------------------------------------------------------ РАСХОДНИКИ
    def _draw_loadout(self, screen, game):
        player = game.player
        rect = pygame.Rect(22, HEIGHT - 198, 470, 38)
        self._panel(screen, rect, alpha=205)
        x = rect.x + 12
        entries = [
            ("Q", f"граната ×{player.equipment.item_count('grenade')}",
             (250, 160, 94) if player.equipment.item_count("grenade") else DIM),
            ("G", f"аптечка ×{player.equipment.item_count('medkit')}",
             (160, 232, 196) if player.equipment.item_count("medkit") else DIM),
            ("B", "босс", (230, 170, 120)),
            ("T", "дерево", CYAN),
        ]
        for key, label, color in entries:
            x += visuals.key_badge(screen, key, x, rect.y + 8, color, 15) + 6
            size = visuals.text_width(label, 16)
            visuals.text(screen, label, (x, rect.y + 10), 16, color)
            x += size + 18

    # ------------------------------------------------------------ ВЕРХ
    def _draw_top(self, screen, game):
        # слева — сектор, задача и маяки: главный ориентир вылазки
        rect = pygame.Rect(22, 18, 276, 96)
        self._panel(screen, rect)
        visuals.text(screen, f"СЕКТОР {game.depth:02d}", (rect.x + 14, rect.y + 6),
                     24, GOLD)
        visuals.text(screen, f"{int(game.elapsed // 60):02d}:{int(game.elapsed % 60):02d}",
                     (rect.right - 14, rect.y + 10), 18, DIM, align="right")

        descent = game.descent
        objective = descent.objective_text(game)
        color = (126, 240, 208) if descent.all_active else (198, 210, 226)
        font_size = 14 if visuals.text_width(objective, 14) < rect.w - 28 else 12
        visuals.text(screen, objective, (rect.x + 14, rect.y + 36), font_size,
                     color)

        # три ромба-маяка: состояние видно без чтения цифр
        x = rect.x + 16
        for index, beacon in enumerate(descent.beacons):
            selected = beacon.state == "active"
            charging = beacon.state == "charging"
            base_color = (112, 242, 204) if selected else (
                GOLD if charging else (64, 76, 96))
            cx, cy = x + index * 22, rect.y + 62
            points = [(cx, cy - 7), (cx + 7, cy), (cx, cy + 7), (cx - 7, cy)]
            pygame.draw.polygon(screen, base_color if selected else (18, 24, 34),
                                points)
            pygame.draw.polygon(screen, base_color, points, 1)
            if charging:
                pygame.draw.circle(screen, (255, 236, 170), (cx, cy), 2)
        visuals.text(screen, f"МАЯКИ {descent.active_count}/{len(descent.beacons)}",
                     (rect.x + 90, rect.y + 54), 14, DIM)
        threat = len(game.enemies)
        threat_color = GREEN if threat < 8 else (240, 190, 94) if threat < 18 else RED
        visuals.text(screen, f"врагов {threat}", (rect.x + 14, rect.y + 74), 14,
                     threat_color)
        if game.boss_kills:
            visuals.text(screen, f"боссов {game.boss_kills}",
                         (rect.right - 14, rect.y + 74), 14, PURPLE,
                         align="right")

        # справа — деньги/очки/убийства
        rect = pygame.Rect(WIDTH - 262, 18, 240, 96)
        self._panel(screen, rect)
        pygame.draw.circle(screen, (150, 108, 30), (rect.x + 26, rect.y + 24), 10)
        pygame.draw.circle(screen, GOLD, (rect.x + 25, rect.y + 22), 8)
        pygame.draw.circle(screen, (255, 244, 196), (rect.x + 22, rect.y + 19), 2)
        visuals.text(screen, f"{game.money:,}".replace(",", " "),
                     (rect.x + 42, rect.y + 8), 30, GOLD)
        visuals.text(screen, f"{game.score:,}".replace(",", " "),
                     (rect.right - 16, rect.y + 12), 24, TEXT, align="right")
        visuals.text(screen, "МОНЕТЫ", (rect.x + 42, rect.y + 38), 14, DIM)
        visuals.text(screen, "ОЧКИ", (rect.right - 16, rect.y + 38), 14, DIM,
                     align="right")
        visuals.text(screen, f"Убийства {game.kills}", (rect.x + 16, rect.y + 64),
                     16, (196, 206, 224))

    # ------------------------------------------------------------ СЕРИЯ
    def _draw_combo(self, screen, game):
        if game.combo <= 0:
            return
        t = max(0.0, game.combo_timer / 4.0)
        x, y = WIDTH // 2, 22
        mult = game.combo_multiplier
        pulse = 1.0 + 0.06 * math.sin(game.elapsed * 12) if game.combo >= 5 else 1.0
        color = GOLD if game.combo >= 5 else (226, 214, 188)
        label = f"x{mult:.1f}"
        size = int(30 * pulse)
        visuals.text(screen, label, (x - 26, y), size, color, align="right")
        visuals.text(screen, f"СЕРИЯ {game.combo}", (x - 14, y + 6), 19, color)
        visuals.bar(screen, pygame.Rect(x - 100, y + 34, 200, 5), t, color,
                    (24, 28, 38))

    # ------------------------------------------------------------ БОСС
    def _draw_boss_bars(self, screen, game):
        bosses = [e for e in game.enemies if getattr(e, "is_boss", False)]
        if not bosses:
            return
        top = 96
        for index, boss in enumerate(bosses[:3]):
            name = RECIPES.get(getattr(boss, "boss_key", ""), {}).get("name", "БОСС")
            ratio = max(0.0, boss.hp / max(1, boss.max_hp))
            y = top + index * 46
            # Ширина 420 оставляет зазор до панели сектора слева:
            # полоса босса не должна прятаться под ней углом.
            panel = pygame.Rect(WIDTH // 2 - 210, y, 420, 38)
            self._panel(screen, panel, color=(24, 16, 22), edge=(120, 66, 78),
                        alpha=228)
            visuals.text(screen, name.upper(), (panel.x + 14, panel.y + 8), 18,
                         (255, 190, 170))
            visuals.text(screen, f"фаза {getattr(boss, 'phase', 1)}",
                         (panel.right - 14, panel.y + 9), 15, DIM, align="right")
            visuals.bar(screen, pygame.Rect(panel.x + 14, panel.y + 28,
                                           panel.w - 28, 6), ratio, (236, 92, 96),
                        (28, 18, 24))

    # ------------------------------------------------------------ КОМПАС
    def _draw_compass(self, screen, game):
        """Стрелки к цели сектора и к ближайшему магазину."""
        target = game.descent.compass_target()
        if target is not None:
            if hasattr(target, "index"):
                label = f"МАЯК {target.index + 1}"
                color = target.color
            else:
                label = "ЛИФТ"
                color = (104, 238, 208)
            self._compass_arrow(screen, game, target, color, label, 76, 9, 15)

        shop = None
        best = 2600 ** 2
        for candidate in game.shops:
            d = (candidate.x - game.player.x) ** 2 + (candidate.y - game.player.y) ** 2
            if d < best:
                best, shop = d, candidate
        if shop is not None and game.nearest_shop() is None:
            label = {"weapons": "ОРУЖИЕ", "supplies": "ПРИПАСЫ",
                     "artifacts": "АРТЕФАКТЫ"}.get(shop.store_type, "МАГАЗИН")
            self._compass_arrow(screen, game, shop, shop.color, label, 128, 6, 13)

    def _compass_arrow(self, screen, game, target, color, label,
                       radius, size, font_size):
        dx = target.x - game.player.x
        dy = target.y - game.player.y
        dist = math.hypot(dx, dy)
        # вблизи цель видна сама: стрелка с подписью только закрывала бы её
        if dist < 190:
            return
        px, py = game.camera.to_screen(game.player.x, game.player.y)
        angle = math.atan2(dy, dx)
        cx = px + math.cos(angle) * radius
        cy = py + math.sin(angle) * radius
        visuals.arrow(screen, cx, cy, angle, size, color, 1)
        lx = cx + math.cos(angle) * (size * 4 + 8)
        ly = cy + math.sin(angle) * (size * 4 + 8) - 8
        text_value = f"{label} · {int(dist / 32)} м"
        tw = visuals.text_width(text_value, font_size)
        panel = pygame.Rect(lx - tw // 2 - 6, ly - 2, tw + 12, 18)
        self._panel(screen, panel, color=(12, 16, 24), edge=color,
                    alpha=180, radius=5)
        visuals.text(screen, text_value, (lx, ly), font_size, color,
                     align="center")

    # ------------------------------------------------------------ ПОДСКАЗКИ
    def _near_chest(self, game):
        px, py = game.player.x, game.player.y
        for site in game.exploration.sites.values():
            if site["id"] in game.exploration.opened:
                continue
            if (site["x"] - px) ** 2 + (site["y"] - py) ** 2 < 105 ** 2:
                return site
        return None

    def _draw_prompt(self, screen, game):
        message = None
        color = GREEN
        key = "E"
        target = game.descent.nearest_interactable(game)
        if target is not None:
            if hasattr(target, "index"):
                message = f"ЗАПУСТИТЬ МАЯК {target.index + 1}"
                color = target.color
            elif target.open:
                message = f"СПУСТИТЬСЯ В СЕКТОР {target.target_depth:02d}"
                color = (104, 238, 208)
            else:
                message = (f"ЛИФТ ЗАКРЫТ · МАЯКИ "
                           f"{game.descent.active_count}/{len(game.descent.beacons)}")
                color = (150, 164, 184)
                key = None
        if message is None:
            chest = self._near_chest(game)
            shop = game.nearest_shop()
            if chest is not None:
                label = game.exploration.LABELS.get(chest["kind"], "Тайник")
                rarity = game.exploration.rarity_label(
                    game.exploration.rarity(chest)).lower()
                message = f"ОТКРЫТЬ {label.upper()} · {rarity} сундук"
                color = (255, 224, 140)
            elif shop is not None:
                message = f"ОТКРЫТЬ {shop.name}"
                color = shop.color
        if message is None:
            return
        width = visuals.text_width(message, 19) + (52 if key else 26)
        rect = pygame.Rect(WIDTH // 2 - width // 2, HEIGHT - 238, width, 34)
        self._panel(screen, rect, color=(16, 22, 30), edge=color, alpha=232)
        text_x = rect.x + 13
        if key:
            key_w = visuals.key_badge(screen, key, rect.x + 10, rect.y + 7,
                                      color, 17)
            text_x = rect.x + 10 + key_w + 10
        visuals.text(screen, message, (text_x, rect.y + 8), 19, TEXT)

    def _draw_notice(self, screen, game):
        y = HEIGHT - 286
        if game.toast_timer > 0.0 and game.toast_text:
            alpha = min(1.0, game.toast_timer / 0.4)
            text = game.toast_text
            width = visuals.text_width(text, 18) + 36
            rect = pygame.Rect(WIDTH // 2 - width // 2, y, width, 32)
            self._panel(screen, rect, color=(14, 19, 27),
                        edge=game.toast_color, alpha=int(215 * alpha))
            visuals.text(screen, text, (WIDTH // 2, y + 7), 18,
                         game.toast_color, align="center")
            y -= 38
        if game.boss_notice_timer > 0.0 and game.boss_notice:
            width = visuals.text_width(game.boss_notice, 20) + 36
            rect = pygame.Rect(WIDTH // 2 - width // 2, y, width, 34)
            self._panel(screen, rect, color=(28, 20, 18),
                        edge=(230, 150, 90), alpha=235)
            visuals.text(screen, game.boss_notice, (WIDTH // 2, y + 8), 20,
                         (255, 214, 140), align="center")

    def _draw_hints(self, screen, game):
        alpha = max(0.25, min(1.0, (16 - game.elapsed) / 4.0))
        for i, line in enumerate((HINT_1, HINT_2)):
            color = tuple(int(c * alpha) for c in DIM)
            visuals.text(screen, line, (WIDTH // 2, 112 + i * 20),
                         16, color, align="center")

    # ------------------------------------------------------------ ПРИЦЕЛ
    def _draw_crosshair(self, screen, game):
        mx, my = pygame.mouse.get_pos()
        weapon = game.player.firearm
        spread = weapon.spec.get("spread_deg", 0.0) if weapon else 0.0
        moving = game.player.move_dir[0] or game.player.move_dir[1]
        gap = 5 + spread * 0.35 + game.recoil * 8.0 + (2.0 if moving else 0.0)
        world = game.camera.to_world(mx, my)
        hot = any(e.alive and (e.x - world[0]) ** 2 + (e.y - world[1]) ** 2
                  < (e.radius + 10) ** 2 for e in game.enemies)
        color = (255, 122, 108) if hot else (156, 232, 196)
        gap = int(gap)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            start = (mx + dx * gap, my + dy * gap)
            end = (mx + dx * (gap + 6), my + dy * (gap + 6))
            pygame.draw.line(screen, (10, 14, 20), start, end, 3)
            pygame.draw.line(screen, color, start, end, 1)
        pygame.draw.circle(screen, (10, 14, 20), (mx, my), 3)
        pygame.draw.circle(screen, color, (mx, my), 1)
        # перезарядка — дуга вокруг прицела
        if weapon is not None and weapon.is_reloading:
            full = max(0.001, weapon.spec.get("reload_time", 1.0))
            progress = 1.0 - max(0.0, weapon.reload_timer) / full
            pygame.draw.arc(screen, (255, 208, 112),
                            (mx - 20, my - 20, 40, 40), -math.pi / 2,
                            -math.pi / 2 + math.tau * progress, 2)
        # хитмаркер
        if game.hitmarker_timer > 0.0:
            t = min(1.0, game.hitmarker_timer / 0.15)
            size = 9 + 3 * (1 - t)
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                pygame.draw.line(screen, (255, 240, 214),
                                 (mx + dx * 4, my + dy * 4),
                                 (mx + dx * size, my + dy * size), 2)

    # ------------------------------------------------------------ ПАУЗА
    def draw_pause_menu(self, screen, game):
        screen.blit(self.menu_overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 330, 70, 660, HEIGHT - 140)
        self._panel(screen, panel, color=(16, 21, 31), edge=(84, 100, 126), radius=16)

        if game.state == STATE_PAUSED:
            title = "ПАУЗА"
            items = ("Продолжить", "Настройки", "Сложность", "В главное меню")
            for index, item in enumerate(items):
                self._draw_menu_item(screen, item, index, game.pause_menu_index, 176)
            self._draw_controls(screen, panel)
            hint = "W/S — выбор   Enter — подтвердить   Esc — продолжить"
        elif game.state == STATE_SETTINGS:
            title = "НАСТРОЙКИ"
            video = getattr(game, "video", None)
            selected = game.settings_menu_index
            volume = int(round(soundbank.get_volume() * 100))
            volume_label = "› " if selected == 0 else ""
            renderer_label = "› " if selected == 1 else ""
            adapter_label = "› " if selected == 2 else ""
            effects_label = "› " if selected == 3 else ""
            volume_color = GOLD if selected == 0 else TEXT
            renderer_color = GOLD if selected == 1 else TEXT
            adapter_color = GOLD if selected == 2 else TEXT
            effects_color = GOLD if selected == 3 else TEXT

            visuals.text(screen, f"{volume_label}ГРОМКОСТЬ ЗВУКА",
                         (panel.centerx, 182), 21, volume_color, align="center")
            bar = pygame.Rect(panel.centerx - 170, 214, 340, 14)
            visuals.bar(screen, bar, volume / 100, GOLD, (24, 29, 40),
                        border=(8, 12, 18), segments=10)
            visuals.text(screen, f"{volume}%", (panel.centerx, 238), 18, GOLD,
                         align="center")

            mode = getattr(video, "mode", "cpu")
            requested = getattr(video, "requested_mode", mode)
            renderer = "OpenGL · GPU" if mode == "opengl" else "CPU · SDL"
            actual = getattr(video, "active_renderer", "") or "—"
            if mode != requested:
                detail = "OpenGL не запустился — используется CPU fallback."
            elif mode == "opengl":
                detail = f"Активный адаптер: {actual[:48]}"
            else:
                detail = "Совместимый режим без OpenGL."
            visuals.text(screen, f"{renderer_label}РЕНДЕР",
                         (panel.centerx, 276), 21, renderer_color, align="center")
            visuals.text(screen, renderer, (panel.centerx, 304), 19, GOLD,
                         align="center")
            visuals.text(screen, detail, (panel.centerx, 328), 15, DIM,
                         align="center")

            if video is not None:
                adapter = video.selected_adapter()
                adapter_name = adapter.name
                if adapter.device and mode == "opengl":
                    adapter_detail = f"Сейчас: {actual[:44]}"
                else:
                    adapter_detail = "Применится после перезапуска игры."
            else:
                adapter_name = "—"
                adapter_detail = ""
            visuals.text(screen, f"{adapter_label}ВИДЕОАДАПТЕР",
                         (panel.centerx, 364), 21, adapter_color, align="center")
            visuals.text(screen, adapter_name[:52], (panel.centerx, 392), 18,
                         GOLD, align="center")
            visuals.text(screen, adapter_detail, (panel.centerx, 416), 15, DIM,
                         align="center")

            effects_on = bool(getattr(video, "effects", False))
            visuals.text(screen, f"{effects_label}GPU-ЭФФЕКТЫ",
                         (panel.centerx, 452), 21, effects_color, align="center")
            visuals.text(screen, "ВКЛ · мягкое свечение" if effects_on else "ВЫКЛ",
                         (panel.centerx, 480), 18, GOLD, align="center")
            visuals.text(screen, "Финальный кадр и масштаб — на видеокарте; логика на CPU.",
                         (panel.centerx, 504), 14, DIM, align="center")

            if game.settings_notice:
                notice_lines = textwrap.wrap(game.settings_notice, width=68)[:2]
                for line_index, line in enumerate(notice_lines):
                    visuals.text(screen, line,
                                 (panel.centerx, 532 + line_index * 20),
                                 15, GOLD, align="center")
            hint = "W/S — выбор   A/D — изменить   Enter — GPU-перезапуск   Esc — назад"
        else:
            title = "СЛОЖНОСТЬ"
            keys = list(DIFFICULTIES)
            descriptions = {
                "easy": "мягче враги и реже спавн",
                "normal": "сбалансированный вызов",
                "hard": "плотнее орда, злее урон",
            }
            for index, key in enumerate(keys):
                item = DIFFICULTIES[key]["name"]
                if key == game.difficulty_key:
                    item += "   · выбрана"
                self._draw_menu_item(screen, item, index, game.difficulty_menu_index,
                                     188)
                visuals.text(screen, descriptions.get(key, ""),
                             (panel.centerx, 218 + index * 48), 15, DIM,
                             align="center")
            hint = "W/S — выбор   Enter — применить   Esc — назад"

        visuals.text(screen, title, (panel.centerx, 104), 54, TEXT, align="center")
        pygame.draw.line(screen, (76, 92, 116), (panel.centerx - 80, 146),
                         (panel.centerx + 80, 146), 2)
        visuals.text(screen, hint, (panel.centerx, panel.bottom - 54), 17, DIM,
                     align="center")

    def _draw_controls(self, screen, panel):
        x = panel.x + 34
        y = panel.y + 372
        visuals.text(screen, "УПРАВЛЕНИЕ", (x, y), 18, GOLD)
        rows = (
            ("WASD", "движение"),
            ("ЛКМ / ПКМ", "огонь или заряд / удар"),
            ("SPACE", "рывок с неуязвимостью"),
            ("R / Q / G", "перезарядка / граната / аптечка"),
            ("V", "режим огня пистолета (Арсенал)"),
            ("F / X", "артефакт / приём оружия"),
            ("E / T", "взаимодействие / дерево навыков"),
        )
        for i, (key, action) in enumerate(rows):
            yy = y + 28 + i * 26
            visuals.text(screen, key, (x, yy), 16, CYAN)
            visuals.text(screen, action, (x + 130, yy), 16, (190, 200, 218))

    def _draw_menu_item(self, screen, text, index, selected, top):
        color = GOLD if index == selected else TEXT
        y = top + index * 44
        if index == selected:
            rect = pygame.Rect(WIDTH // 2 - 190, y - 6, 380, 36)
            self._panel(screen, rect, color=(32, 42, 58), edge=GOLD, alpha=220)
            visuals.arrow(screen, rect.x + 18, y + 12, 0, 6, GOLD, 1)
        visuals.text(screen, text, (WIDTH // 2, y), 26, color, align="center")

    # ------------------------------------------------------------ СМЕРТЬ
    def _draw_game_over(self, screen, game):
        screen.blit(self.overlay, (0, 0))
        panel = pygame.Rect(WIDTH // 2 - 300, 96, 600, 560)
        self._panel(screen, panel, color=(18, 14, 20), edge=(128, 64, 74), radius=18)
        visuals.text(screen, "ВЫ ПОГИБЛИ", (WIDTH // 2, 124), 56, (255, 108, 96),
                     align="center")
        visuals.text(screen, "Тьма забрала ещё одного искателя",
                     (WIDTH // 2, 180), 18, (180, 160, 170), align="center")

        rows = (
            ("ОЧКИ", f"{game.score:,}".replace(",", " "), GOLD),
            ("УБИЙСТВА", f"{game.kills}", TEXT),
            ("ГЛУБИНА", f"СЕКТОР {game.depth:02d}", CYAN),
            ("ВРЕМЯ", f"{int(game.run_time // 60):02d}:{int(game.run_time % 60):02d}", TEXT),
            ("МОНЕТЫ", f"{game.money:,}".replace(",", " "), GOLD),
            ("ЛУЧШАЯ СЕРИЯ", f"{game.max_combo}", CYAN),
            ("ПОПАДАНИЙ", f"{game.shots_hit}", (190, 204, 224)),
            ("БОССЫ", f"{game.boss_kills}", PURPLE),
        )
        for i, (label, value, color) in enumerate(rows):
            col = i % 2
            row = i // 2
            x = panel.x + 60 + col * 270
            y = 216 + row * 46
            visuals.text(screen, label, (x, y), 15, DIM)
            visuals.text(screen, value, (x, y + 16), 26, color)

        best = max(game.best_score, game.score)
        visuals.text(screen, f"ЛУЧШИЙ РЕЗУЛЬТАТ: {best:,}".replace(",", " "),
                     (WIDTH // 2, 414), 20, GOLD, align="center")
        pygame.draw.line(screen, (90, 72, 82), (panel.x + 50, 448),
                         (panel.right - 50, 448), 1)
        visuals.text(screen, "R — новая вылазка", (WIDTH // 2, 470), 22, TEXT,
                     align="center")
        visuals.text(screen, "Esc — в главное меню", (WIDTH // 2, 508), 18, DIM,
                     align="center")
        visuals.text(screen, "деньги, серия и достижения этой вылазки сгорели",
                     (WIDTH // 2, 560), 15, (130, 120, 134), align="center")

    # ------------------------------------------------------------ ТИТУЛЬНЫЙ ЭКРАН
    def draw_title(self, screen, game):
        self._title_background(screen)
        time = pygame.time.get_ticks() / 1000.0

        # силуэты: герой слева, тень справа. Сначала свет, потом фигуры.
        visuals.glow(screen, WIDTH * 0.20, HEIGHT * 0.63, 150, (72, 210, 190), 20)
        visuals.glow(screen, WIDTH * 0.84, HEIGHT * 0.60, 190, (150, 70, 210), 16)
        player = visuals.character("player", 56, 0).copy()
        player.fill((92, 130, 140, 255), special_flags=pygame.BLEND_RGBA_MULT)
        screen.blit(player, player.get_rect(center=(WIDTH * 0.20, HEIGHT * 0.63)))
        reaper = visuals.character("boss/reaper", 116, math.pi).copy()
        reaper.fill((66, 46, 88, 255), special_flags=pygame.BLEND_RGBA_MULT)
        screen.blit(reaper, reaper.get_rect(center=(WIDTH * 0.84, HEIGHT * 0.60)))

        visual_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        visual_overlay.fill((6, 8, 16, 120))
        screen.blit(visual_overlay, (0, 0))

        # логотип
        title_y = 150
        for dx, dy, color in ((4, 6, (6, 10, 16)), (0, 0, (255, 206, 112))):
            visuals.text(screen, "ГЛУБИНА", (WIDTH // 2 + dx, title_y + dy),
                         92, color, align="center", shadow=False)
        pygame.draw.line(screen, (96, 218, 202), (WIDTH // 2 - 170, title_y + 104),
                         (WIDTH // 2 + 170, title_y + 104), 2)
        visuals.text(screen, "Т Ё М Н Ы Й   Ш У Т Е Р", (WIDTH // 2, title_y + 118),
                     20, (150, 220, 214), align="center")
        visuals.text(screen, "выживи, заработай, спустись глубже",
                     (WIDTH // 2, title_y + 154), 17, (150, 162, 186),
                     align="center")

        # меню
        items = (
            "НАЧАТЬ ВЫЛАЗКУ",
            f"СЛОЖНОСТЬ: {DIFFICULTIES[game.difficulty_key]['name'].upper()}",
            "ВЫЙТИ",
        )
        for index, item in enumerate(items):
            y = 380 + index * 58
            selected = index == game.title_index
            if selected:
                rect = pygame.Rect(WIDTH // 2 - 250, y - 8, 500, 44)
                self._panel(screen, rect, color=(25, 44, 52), edge=GOLD,
                            alpha=228, radius=8)
                visuals.arrow(screen, rect.x + 22, y + 12, 0, 7, GOLD, 1)
                visuals.text(screen, "ENTER", (rect.right - 18, y + 8), 14, GOLD,
                             align="right")
            visuals.text(screen, item, (WIDTH // 2, y), 28,
                         GOLD if selected else (224, 232, 244), align="center")

        best = max(game.best_score, 0)
        if best:
            visuals.text(screen, f"рекорд: {best}", (WIDTH // 2, 556), 17, DIM,
                         align="center")

        # управление внизу
        controls = pygame.Rect(WIDTH // 2 - 330, 598, 660, 110)
        self._panel(screen, controls, color=(12, 17, 25), edge=(54, 72, 94),
                    alpha=210)
        cols = (
            (("WASD", "движение"), ("SPACE", "рывок")),
            (("ЛКМ", "огонь / заряд"), ("ПКМ", "удар")),
            (("E", "маяк / магазин"), ("T", "дерево навыков")),
        )
        for ci, column in enumerate(cols):
            x = controls.x + 24 + ci * 218
            for ri, (key, label) in enumerate(column):
                y = controls.y + 22 + ri * 42
                visuals.key_badge(screen, key, x, y, CYAN, 15)
                visuals.text(screen, label, (x + 72, y + 2), 16, (190, 202, 220))
        visuals.text(screen, "W/S — выбор   A/D — сложность   Enter — начать",
                     (WIDTH // 2, HEIGHT - 26), 15, DIM, align="center")

    def _title_background(self, screen):
        if self._title_bg is None:
            surf = pygame.Surface((WIDTH, HEIGHT))
            for y in range(HEIGHT):
                t = y / HEIGHT
                color = (int(10 + 10 * (1 - t)), int(14 + 16 * (1 - t)),
                         int(24 + 20 * (1 - t)))
                pygame.draw.line(surf, color, (0, y), (WIDTH, y))
            # перспективная сетка пола
            horizon = int(HEIGHT * 0.62)
            for i in range(-10, 22):
                x = WIDTH // 2 + i * 90
                pygame.draw.line(surf, (18, 28, 38), (WIDTH // 2, horizon),
                                 (x, HEIGHT), 1)
            for i in range(1, 9):
                y = horizon + int((HEIGHT - horizon) * (i / 8) ** 1.7)
                pygame.draw.line(surf, (18, 28, 38), (0, y), (WIDTH, y), 1)
            # дальние колонны
            for x in (60, 190, 780, 930):
                pygame.draw.rect(surf, (14, 19, 29), (x, 260, 76, horizon - 260))
                pygame.draw.rect(surf, (24, 32, 46), (x, 260, 76, 3))
            self._title_bg = surf
        screen.blit(self._title_bg, (0, 0))

        # медленно плывущие пылинки
        time = pygame.time.get_ticks() / 1000.0
        for x, y, speed, phase in self._dust:
            yy = (y - time * (8 + speed * 8)) % HEIGHT
            xx = x + math.sin(time * 0.3 + phase * 6) * 6
            pygame.draw.circle(screen, (120, 160, 170),
                               (int(xx), int(yy)), 1)
