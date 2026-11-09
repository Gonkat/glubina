"""
Окно магазина: список слева, карточка товара справа.

Почему так: в старом окне всё было одной строкой текста — игрок не видел,
что именно покупает и насколько новое оружие лучше текущего. Теперь
слева выбор, справа — иконка, цена, описание и сравнение характеристик
с экипированным оружием. Ввод остался клавиатурным, но стал нагляднее.
"""
import math

import pygame

import soundbank
import spritebank
import visuals
from artifact_data import ARTIFACTS
from artifacts import create_artifact
from settings import HEIGHT, RARITY_COLORS, TEXT_COLOR, TEXT_DIM, WIDTH
from shop_data import (
    offer_rarity,
    offer_refund,
    offer_view,
    upgrade_offers,
)
from weapon_data import AMMO_NAME, FIREARMS, MELEE
from weapons import create_weapon

PANEL = (16, 21, 31)
EDGE = (64, 82, 108)
GOLD = (255, 208, 112)
GREEN = (134, 226, 154)
RED = (238, 110, 100)
DIM = (144, 156, 178)


# ------------------------------------------------------------ ОБРАБОТЧИКИ ПОКУПОК
def _buy_weapon(game, kind, offer):
    """Общая логика покупки оружия: замена слота + компенсация за старое."""
    player = game.player
    current = player.equipment.get(kind)
    price = offer["price"]
    key = offer["key"]
    if current is not None and current.key == key:
        return False, "Это оружие уже у тебя"
    if current is None:
        refund = 0
    elif kind == "firearm":
        refund = current.upgrade_refund_value()
    else:
        refund = current.refund_value()
    if game.money + refund < price:
        return False, f"Не хватает {price - game.money - refund}"
    game.money += refund - price
    weapon = create_weapon(key)
    player.restore_weapon_tree(weapon)
    player.equipment.equip(kind, weapon)
    note = f", старое продано за {refund}" if current is not None else ""
    return True, f"Куплено: {weapon.name}{note}"


def buy_firearm(game, offer):
    return _buy_weapon(game, "firearm", offer)


def buy_melee(game, offer):
    return _buy_weapon(game, "melee", offer)


def buy_ammo(game, offer):
    if game.money < offer["price"]:
        return False, f"Не хватает {offer['price'] - game.money}"
    game.money -= offer["price"]
    game.player.equipment.add_ammo(offer["pack"])
    return True, f"Куплено: {AMMO_NAME} x{offer['pack']}"


def buy_token(game, offer):
    """Жетон тренировки: развитие школы без покупки самого оружия."""
    if game.money < offer["price"]:
        return False, f"Не хватает {offer['price'] - game.money}"
    key = offer["key"]
    spec = FIREARMS.get(key) or MELEE[key]
    # Даже при максимальной подготовке жетон не бесполезен: он платит
    # за tier 4+ второй ветви (см. skill_tree.cross_branch_toll).
    game.money -= offer["price"]
    game.player.add_weapon_token(key, 1)
    return True, (f"Жетон: {spec['name']} · в запасе "
                  f"{game.player.weapon_token_count(key)} · подготовка узла "
                  f"или плата за вторую ветвь")


def buy_consumable(game, offer):
    if game.money < offer["price"]:
        return False, f"Не хватает {offer['price'] - game.money}"
    game.money -= offer["price"]
    game.player.equipment.add_item(offer["key"], offer["pack"])
    return True, f"Куплено: {offer['name']} x{offer['pack']}"


def buy_upgrade(game, offer):
    weapon = offer["weapon"]
    if not weapon.is_upgradable:
        return False, f"{weapon.name}: предел улучшений"
    cost = offer["price"]
    if game.money < cost:
        return False, f"Не хватает {cost - game.money}"
    game.money -= cost
    weapon.upgrade(cost)
    return True, (f"{weapon.name}: ур. {weapon.upgrade_level}, "
                  f"урон {weapon.damage:.0f}")


def buy_artifact(game, offer):
    """
    Артефакт встаёт в свой слот (активный или пассивный).
    Старый артефакт этого слота продаётся за тот же %, что и оружие,
    и СРАЗУ снимает свои статы с героя (on_unequip).
    """
    player = game.player
    artifact = create_artifact(offer["key"])
    current = player.equipment.get(artifact.slot)
    if current is not None and current.key == artifact.key:
        return False, "Этот артефакт уже у тебя"
    refund = current.refund_value() if current is not None else 0
    price = offer["price"]
    if game.money + refund < price:
        return False, f"Не хватает {price - game.money - refund}"
    game.money += refund - price
    if current is not None:
        current.on_unequip(player)
    player.equipment.equip(artifact.slot, artifact)
    artifact.on_equip(player)
    note = f", старый продан за {refund}" if current is not None else ""
    return True, f"Куплено: {artifact.name}{note}"


BUY_HANDLERS = {
    "firearm": buy_firearm,
    "melee": buy_melee,
    "ammo": buy_ammo,
    "token": buy_token,
    "consumable": buy_consumable,
    "upgrade": buy_upgrade,
    "artifact": buy_artifact,
}


class ShopUI:
    """Отвечает только за окно магазина: ввод и отрисовку."""

    PANEL = pygame.Rect((WIDTH - 860) // 2, 74, 860, 632)
    ROW_H = 52

    def __init__(self):
        self.font = visuals.font(24)
        self.font_small = visuals.font(19)
        self.font_big = visuals.font(34)
        self.active_shop = None
        self.cursor = 0
        self.message = ""
        self.message_timer = 0.0
        self._last_tick = 0
        self.overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.overlay.fill((5, 7, 13, 214))

    # ------------------------------------------------------------ УПРАВЛЕНИЕ
    def open(self, shop):
        self.active_shop = shop
        self.cursor = 0
        self.message = ""
        self._last_tick = pygame.time.get_ticks()

    def _items(self, game):
        if self.active_shop is None:
            return []
        items = list(self.active_shop.inventory)
        if self.active_shop.store_type == "weapons":
            mult = self.active_shop.upgrade_price_multiplier
            items.extend(upgrade_offers(game, mult))
        return items

    def handle_event(self, event, game):
        if event.type != pygame.KEYDOWN:
            return
        items = self._items(game)
        if event.key in (pygame.K_w, pygame.K_UP):
            self.cursor = (self.cursor - 1) % max(1, len(items))
            soundbank.play("ui_move")
        elif event.key in (pygame.K_s, pygame.K_DOWN):
            self.cursor = (self.cursor + 1) % max(1, len(items))
            soundbank.play("ui_move")
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.buy(game)

    def buy(self, game):
        items = self._items(game)
        if not items:
            return
        self.cursor = min(self.cursor, len(items) - 1)
        offer = items[self.cursor]
        handler = BUY_HANDLERS.get(offer["kind"])
        if handler is None:
            raise ValueError(f"Нет обработчика для {offer['kind']!r}")
        ok, self.message = handler(game, offer)
        soundbank.play("buy" if ok else "error")
        self.message_timer = 3.4
        if ok:
            # после покупки список мог измениться (улучшение/замена) — курсор
            # не должен «прыгнуть» на другой товар
            self.cursor = min(self.cursor, max(0, len(self._items(game)) - 1))

    # ------------------------------------------------------------ ИКОНКИ
    @staticmethod
    def _fit(font, text, width):
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text + "…"

    def _weapon_sprite(self, key, size):
        base = spritebank.try_get(f"weapons/{key}")
        if base is None:
            return None
        w, h = base.get_size()
        scale = min(size / max(1, w), size / max(1, h))
        return pygame.transform.smoothscale(base, (max(1, int(w * scale)),
                                                   max(1, int(h * scale))))

    def _icon(self, screen, offer, center, size=36):
        kind = offer["kind"]
        cx, cy = center
        if kind in ("firearm", "melee", "upgrade"):
            key = offer.get("key")
            if kind == "upgrade":
                key = offer["weapon"].key
            sprite = self._weapon_sprite(key, size)
            if sprite is not None:
                screen.blit(sprite, sprite.get_rect(center=center))
                return
            if kind == "upgrade":
                pygame.draw.polygon(screen, GREEN, [
                    (cx, cy - 10), (cx + 10, cy), (cx + 4, cy),
                    (cx + 4, cy + 9), (cx - 4, cy + 9), (cx - 4, cy),
                    (cx - 10, cy),
                ])
                return
        if kind == "artifact":
            color = RARITY_COLORS.get(ARTIFACTS[offer["key"]]["rarity"],
                                      (196, 144, 255))
            pts = [(cx, cy - size // 2), (cx + size // 2, cy),
                   (cx, cy + size // 2), (cx - size // 2, cy)]
            pygame.draw.polygon(screen, (30, 22, 44), pts)
            pygame.draw.polygon(screen, color, pts, 2)
            pygame.draw.polygon(screen, (240, 224, 255),
                                [(cx, cy - 7), (cx + 6, cy), (cx, cy + 4),
                                 (cx - 6, cy)])
            return
        if kind == "token":
            # жетон школы: шестиугольник в цвете оружия + внутренний ромб
            spec = FIREARMS.get(offer["key"]) or MELEE[offer["key"]]
            color = RARITY_COLORS.get(spec["rarity"], (120, 134, 158))
            r = size * 0.42
            pts = [(cx + math.cos(a) * r, cy + math.sin(a) * r)
                   for a in (math.pi / 6 + i * math.pi / 3 for i in range(6))]
            pygame.draw.polygon(screen, (18, 24, 34), pts)
            pygame.draw.polygon(screen, color, pts, 2)
            pygame.draw.polygon(screen, color, [
                (cx, cy - r * 0.5), (cx + r * 0.5, cy),
                (cx, cy + r * 0.5), (cx - r * 0.5, cy)], 1)
            return
        if kind == "ammo":
            surf = spritebank.get_scaled("ammo", (size, size))
        elif kind == "consumable":
            name = "grenade" if offer.get("key") == "grenade" else "medkit"
            surf = spritebank.get_scaled(name, (size, size))
        else:
            surf = None
        if surf is not None:
            screen.blit(surf, surf.get_rect(center=center))
        else:
            pygame.draw.circle(screen, (120, 130, 150), center, size // 3)

    # ------------------------------------------------------------ ОТРИСОВКА
    def _tick(self):
        now = pygame.time.get_ticks()
        if self._last_tick:
            self.message_timer = max(0.0, self.message_timer - (now - self._last_tick) / 1000.0)
        self._last_tick = now

    def draw(self, screen, game):
        self._tick()
        screen.blit(self.overlay, (0, 0))
        panel = self.PANEL
        pygame.draw.rect(screen, PANEL, panel, border_radius=14)
        pygame.draw.rect(screen, EDGE, panel, 2, border_radius=14)

        shop = self.active_shop
        accent = shop.color if shop else TEXT_COLOR
        pygame.draw.rect(screen, (24, 31, 44), (panel.x, panel.y, panel.w, 70),
                         border_radius=14)
        pygame.draw.rect(screen, (24, 31, 44), (panel.x, panel.y + 40, panel.w, 30))
        visuals.text(screen, (shop.name if shop else "МАГАЗИН"),
                     (panel.x + 24, panel.y + 18), 32, accent)
        # кошелёк: монета слева от суммы, сумма прижата к правому краю
        value = str(game.money)
        value_w = visuals.text_width(value, 28)
        visuals.text(screen, value, (panel.right - 26, panel.y + 16),
                     28, GOLD, align="right")
        coin_x = panel.right - 26 - value_w - 20
        pygame.draw.circle(screen, (146, 106, 30), (coin_x, panel.y + 30), 10)
        pygame.draw.circle(screen, GOLD, (coin_x - 1, panel.y + 28), 8)

        items = self._items(game)
        self.cursor = min(self.cursor, max(0, len(items) - 1))
        list_rect = pygame.Rect(panel.x + 18, panel.y + 84, 472, panel.h - 154)
        detail = pygame.Rect(list_rect.right + 14, list_rect.y, 330, panel.h - 154)
        pygame.draw.rect(screen, (19, 25, 36), list_rect, border_radius=10)
        pygame.draw.rect(screen, (50, 62, 82), list_rect, 1, border_radius=10)
        pygame.draw.rect(screen, (19, 25, 36), detail, border_radius=10)
        pygame.draw.rect(screen, (50, 62, 82), detail, 1, border_radius=10)

        self._draw_list(screen, game, items, list_rect)
        self._draw_current_loadout(screen, game, list_rect)
        self._draw_detail(screen, game, items, detail)

        footer = (f"W/S — выбор    Enter — купить    E/ESC — выйти    "
                  f"[{self.cursor + 1}/{len(items)}]")
        visuals.text(screen, footer, (panel.x + 26, panel.bottom - 46), 17, DIM)
        if self.message_timer > 0.0 and self.message:
            success = not any(word in self.message for word in
                              ("Не хватает", "уже", "предел", "Нет"))
            visuals.text(screen, self.message,
                         (panel.centerx + 40, panel.bottom - 46), 18,
                         GREEN if success else RED, align="center")

    def _draw_list(self, screen, game, items, rect):
        # нижние 94 px заняты сводкой «сейчас в руках» — строки не заезжают под неё
        visible = max(1, (rect.h - 94) // self.ROW_H)
        start = max(0, min(self.cursor - visible // 2, len(items) - visible))
        if not items:
            visuals.text(screen, "Прилавок пуст", (rect.centerx, rect.y + 34),
                         22, DIM, align="center")
            return
        for i in range(start, min(len(items), start + visible)):
            offer = items[i]
            name, price, note = offer_view(game, offer)
            refund = offer_refund(game, offer)
            selected = i == self.cursor
            row = pygame.Rect(rect.x + 6, rect.y + 6 + (i - start) * self.ROW_H,
                              rect.w - 12, self.ROW_H - 4)
            rarity = offer_rarity(game, offer)
            accent = RARITY_COLORS.get(rarity, (120, 134, 158))
            if selected:
                pygame.draw.rect(screen, (33, 43, 59), row, border_radius=8)
                pygame.draw.rect(screen, accent, row, 1, border_radius=8)
            else:
                pygame.draw.rect(screen, (24, 31, 43), row, border_radius=8)
            pygame.draw.rect(screen, accent, (row.x + 6, row.y + 9, 3, row.h - 18),
                             border_radius=2)
            self._icon(screen, offer, (row.x + 34, row.centery), 28)

            affordable = game.money + refund >= price
            equipped = self._is_equipped(game, offer)
            color = (120, 128, 142) if equipped else (
                (226, 234, 246) if affordable else (126, 128, 140))
            visuals.text(screen, self._fit(visuals.font(21), name, row.w - 150),
                         (row.x + 58, row.y + 7), 21, color)
            note_text = "уже экипировано" if equipped else note
            visuals.text(screen, self._fit(visuals.font(15), note_text, row.w - 150),
                         (row.x + 58, row.y + 28), 15,
                         GREEN if equipped else (DIM if affordable else (104, 106, 120)))
            if equipped:
                visuals.text(screen, "✓", (row.right - 14, row.y + 10), 22, GREEN,
                             align="right")
            else:
                price_color = GOLD if affordable else (160, 100, 80)
                visuals.text(screen, str(price), (row.right - 14, row.y + 10), 21,
                             price_color, align="right")
                if not affordable:
                    visuals.text(screen, f"не хватает {price - game.money - refund}",
                                 (row.right - 14, row.y + 30), 13, RED, align="right")

    @staticmethod
    def _is_equipped(game, offer):
        kind = offer["kind"]
        if kind not in ("firearm", "melee", "artifact"):
            return False
        slot = kind
        if kind == "artifact":
            spec = ARTIFACTS[offer["key"]]
            slot = "active_artifact" if spec["slot"] == "active" else "passive_artifact"
        current = game.player.equipment.get(slot)
        return current is not None and getattr(current, "key", None) == offer["key"]

    def _draw_current_loadout(self, screen, game, list_rect):
        """Маленькая сводка «что уже в руках» — контекст для сравнения."""
        rect = pygame.Rect(list_rect.x + 10, list_rect.bottom - 78,
                           list_rect.w - 20, 66)
        pygame.draw.rect(screen, (16, 22, 31), rect, border_radius=8)
        pygame.draw.rect(screen, (44, 56, 74), rect, 1, border_radius=8)
        visuals.text(screen, "СЕЙЧАС В РУКАХ", (rect.x + 12, rect.y + 8), 13, DIM)
        firearm = game.player.equipment.get("firearm")
        melee = game.player.equipment.get("melee")
        line1 = (f"{firearm.name} · урон {firearm.damage:.0f}"
                 if firearm is not None else "нет оружия")
        if firearm is not None and getattr(firearm, "has_modes", False):
            line1 += f" · {firearm.mode_name}"
        line2 = (f"{melee.name} · урон {melee.damage:.0f}"
                 if melee is not None else "нет оружия ближнего боя")
        visuals.text(screen, self._fit(visuals.font(16), line1, rect.w - 160),
                     (rect.x + 12, rect.y + 26), 16, (200, 212, 232))
        visuals.text(screen, f"патроны {game.player.equipment.ammo_count()}",
                     (rect.right - 12, rect.y + 27), 15, GOLD, align="right")
        visuals.text(screen, self._fit(visuals.font(15), line2, rect.w - 24),
                     (rect.x + 12, rect.y + 45), 15, (150, 162, 184))

    def _draw_detail(self, screen, game, items, rect):
        if not items:
            return
        offer = items[min(self.cursor, len(items) - 1)]
        name, price, note = offer_view(game, offer)
        rarity = offer_rarity(game, offer)
        accent = RARITY_COLORS.get(rarity, (140, 154, 178))
        refund = offer_refund(game, offer)

        # шапка карточки
        self._icon(screen, offer, (rect.x + 40, rect.y + 40), 46)
        visuals.text(screen, name, (rect.x + 76, rect.y + 18), 21,
                     TEXT_COLOR if rarity is None else accent)
        if rarity:
            visuals.text(screen, rarity.upper(), (rect.x + 76, rect.y + 44),
                         14, accent)
        visuals.text(screen, self._fit(visuals.font(16), note, rect.w - 36),
                     (rect.x + 18, rect.y + 78), 16, DIM)

        y = rect.y + 112
        pygame.draw.line(screen, (46, 58, 76), (rect.x + 16, y),
                         (rect.right - 16, y), 1)
        y += 14
        kind = offer["kind"]
        if kind in ("firearm", "melee"):
            self._draw_weapon_compare(screen, game, kind, offer, rect, y)
        elif kind == "upgrade":
            weapon = offer["weapon"]
            visuals.text(screen, "ПРОКАЧКА БЛИЖНЕГО БОЯ", (rect.x + 18, y), 15, DIM)
            y += 26
            visuals.text(screen, f"Урон {weapon.damage:.0f}",
                         (rect.x + 18, y), 19, TEXT_COLOR)
            visuals.text(screen, f"→ {weapon.damage * 1.25:.0f}",
                         (rect.x + 150, y), 19, GREEN)
            y += 26
            visuals.text(screen, f"Уровень {weapon.upgrade_level} → "
                                 f"{weapon.upgrade_level + 1}",
                         (rect.x + 18, y), 17, DIM)
        elif kind == "token":
            key = offer["key"]
            spec = FIREARMS.get(key) or MELEE[key]
            have = game.player.weapon_training.get(key, 0)
            if have >= 3:
                # При максимальной подготовке жетон не «пропадает»:
                # он платит за tier 4+ второй ветви.
                visuals.text(screen, "ПОДГОТОВКА МАКСИМАЛЬНА",
                             (rect.x + 18, y), 15, DIM)
                y += 26
                visuals.text(screen, "жетон нужен второй ветви",
                             (rect.x + 18, y), 19, GREEN)
                y += 30
                visuals.text(screen, "Tier 4 / 5 / 6 вне основной:",
                             (rect.x + 18, y), 16, DIM)
                y += 24
                visuals.text(screen, "1 / 2 / 3 жетона школы",
                             (rect.x + 18, y), 19, TEXT_COLOR)
                y += 28
                visuals.text(screen, "Подойдут жетоны родственных",
                             (rect.x + 18, y), 15, DIM)
                visuals.text(screen, "школ.", (rect.x + 18, y + 18),
                             15, DIM)
            else:
                visuals.text(screen, "ПОДГОТОВКА ШКОЛЫ",
                             (rect.x + 18, y), 15, DIM)
                y += 26
                visuals.text(screen, "+1 при покупке навыка",
                             (rect.x + 18, y), 19, GREEN)
                y += 30
                visuals.text(screen, self._fit(visuals.font(17),
                                               f"«{spec['name']}»",
                                               rect.w - 36),
                             (rect.x + 18, y), 17, TEXT_COLOR)
                y += 24
                visuals.text(screen, f"сейчас: {have}", (rect.x + 18, y),
                             16, DIM)
                y += 24
                visuals.text(screen, "Спишется при покупке зависимого",
                             (rect.x + 18, y), 15, DIM)
                visuals.text(screen, "навыка; родственные жетоны тоже",
                             (rect.x + 18, y + 18), 15, DIM)
                visuals.text(screen, "принимаются.", (rect.x + 18, y + 36),
                             15, DIM)
        elif kind == "ammo":
            visuals.text(screen, "ОБЩИЙ БОЕЗАПАС", (rect.x + 18, y), 15, DIM)
            y += 26
            visuals.text(screen, f"+{offer['pack']} единиц", (rect.x + 18, y),
                         24, GREEN)
            y += 32
            visuals.text(screen, "Один ресурс для всего оружия:",
                         (rect.x + 18, y), 15, DIM)
            visuals.text(screen, "не бывает «чужих» патронов.",
                         (rect.x + 18, y + 18), 15, DIM)
        elif kind == "consumable":
            visuals.text(screen, "РАСХОДНИК", (rect.x + 18, y), 15, DIM)
            y += 26
            visuals.text(screen, f"+{offer['pack']} шт.", (rect.x + 18, y), 24, GREEN)
            y += 32
            hint = ("Q — бросок, взрыв по площади" if offer["key"] == "grenade"
                    else "G — восстановить 50 HP")
            visuals.text(screen, hint, (rect.x + 18, y), 16, DIM)
        elif kind == "artifact":
            spec = ARTIFACTS[offer["key"]]
            visuals.text(screen, "АКТИВНЫЙ · F" if spec["slot"] == "active"
                         else "ПАССИВНЫЙ", (rect.x + 18, y), 15,
                         (198, 144, 255) if spec["slot"] == "active" else (134, 226, 154))
            y += 26
            current = game.player.equipment.get(
                "active_artifact" if spec["slot"] == "active" else "passive_artifact")
            if current is not None and current.key == offer["key"]:
                visuals.text(screen, "Уже экипирован", (rect.x + 18, y), 18,
                             (160, 166, 184))
            else:
                visuals.text(screen, "Заменит текущий артефакт слота",
                             (rect.x + 18, y), 16, DIM)

        # цена и возврат
        price_y = rect.bottom - 92
        pygame.draw.line(screen, (46, 58, 76), (rect.x + 16, price_y - 12),
                         (rect.right - 16, price_y - 12), 1)
        equipped = self._is_equipped(game, offer)
        affordable = game.money + refund >= price
        if equipped:
            visuals.text(screen, "УЖЕ ЭКИПИРОВАНО", (rect.x + 18, price_y + 4),
                         20, GREEN)
            if refund:
                visuals.text(screen, f"замена вернёт +{refund}",
                             (rect.x + 18, price_y + 34), 15, DIM)
            return
        visuals.text(screen, "ЦЕНА", (rect.x + 18, price_y), 14, DIM)
        visuals.text(screen, str(price), (rect.right - 18, price_y - 4), 28,
                     GOLD if affordable else RED, align="right")
        if refund:
            visuals.text(screen, f"старое вернёт +{refund}",
                         (rect.x + 18, price_y + 30), 15, GREEN)
        if not affordable:
            visuals.text(screen, f"не хватает {price - game.money - refund}",
                         (rect.right - 18, price_y + 30), 14, RED, align="right")
        elif offer["kind"] in ("firearm", "melee", "artifact"):
            visuals.text(screen, "Enter — купить и заменить",
                         (rect.right - 18, price_y + 30), 14, DIM, align="right")
        elif offer["kind"] == "token":
            visuals.text(screen, "Enter — купить жетон",
                         (rect.right - 18, price_y + 30), 14, DIM, align="right")

    def _draw_weapon_compare(self, screen, game, kind, offer, rect, y):
        table = FIREARMS if kind == "firearm" else MELEE
        spec = table[offer["key"]]
        current = game.player.equipment.get(kind)
        current_spec = current.spec if current is not None else None
        rows = []
        if kind == "firearm":
            rows = (
                ("Урон", "damage", True, "{:.0f}"),
                ("Темп", None, True, None),
                ("Магазин", "magazine", True, "{:.0f}"),
                ("Дробь", "pellets", True, "{:.0f}"),
                ("Разброс", "spread_deg", False, "{:.1f}°"),
                ("Перезарядка", "reload_time", False, "{:.2f}с"),
            )
        else:
            rows = (
                ("Урон", "damage", True, "{:.0f}"),
                ("Откат", "cooldown", False, "{:.2f}с"),
                ("Дальность", "reach", True, "{:.0f}"),
                ("Дуга", "arc_deg", True, "{:.0f}°"),
                ("Тип", None, True, None),
            )
        visuals.text(screen, "СРАВНЕНИЕ", (rect.x + 18, y), 15, DIM)
        visuals.text(screen, "БЫЛО / СТАНЕТ", (rect.right - 18, y), 14, DIM,
                     align="right")
        y += 24
        for label, key, higher_better, fmt in rows:
            if key == "cooldown" or (kind == "firearm" and key is None):
                if kind == "firearm":
                    before = 1.0 / max(0.01, current_spec["cooldown"]) if current_spec else None
                    after = 1.0 / max(0.01, spec["cooldown"])
                    before_text = f"{before:.1f}/с" if before else "—"
                    after_text = f"{after:.1f}/с"
                    better = before is None or after >= before
                else:
                    before_text = "—"
                    after_text = "удар"
                    better = True
            elif key == "arc_deg" and offer["key"] == "hammer":
                before_text = "—"
                after_text = "волна"
                better = True
            elif key is None:
                before_text = "—"
                after_text = spec.get("attack", "").replace("_", " ")
                better = True
            else:
                before = current_spec.get(key) if current_spec else None
                after = spec.get(key)
                if after is None:
                    before_text = "—"
                    after_text = "—"
                    better = True
                else:
                    before_text = fmt.format(before) if before is not None else "—"
                    after_text = fmt.format(after)
                    if before is None:
                        better = True
                    elif higher_better:
                        better = after >= before
                    else:
                        better = after <= before
            visuals.text(screen, label, (rect.x + 18, y), 15, (150, 162, 184))
            visuals.text(screen, before_text, (rect.x + 150, y), 16, (120, 130, 150))
            pygame.draw.line(screen, (60, 72, 92), (rect.x + 224, y + 7),
                             (rect.x + 254, y + 7), 1)
            visuals.text(screen, after_text, (rect.x + 270, y), 16,
                         GREEN if better else RED)
            y += 24
