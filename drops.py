"""
Добыча с монстров: монеты, патроны, гранаты.

ШАНСЫ и КОЛИЧЕСТВА лежат в таблицах `drops` классов монстров —
здесь только розыгрыш и подбор. Баланс правится в enemies.py.

Отрисовка (M8): общий draw в базе + спрайт из assets/sprites/{sprite_name}.png.
Подклассу достаточно объявить sprite_name — рисовать самому не нужно.
"""
import math
import random

import soundbank
import spritebank

from artifact_data import ALL_KEYS
from artifacts import create_artifact
from game_object import GameObject
from projectiles import FloatingText
import visuals
from utils import distance


class Drop(GameObject):
    """
    Предмет на полу: слегка покачивается, притягивается к герою
    на близкой дистанции и подбирается касанием.

    Подклассы реализуют apply(game) — ЧТО конкретно даёт предмет.
    """

    pickup_range = 112      # с этого расстояния предмет летит к герою
    wobble = 3              # амплитуда покачивания (px)
    sprite_name = None      # файл assets/sprites/{name}.png (у подклассов)
    glow_color = (255, 200, 100)

    def __init__(self, x, y):
        super().__init__(x, y)
        self.bob_phase = random.uniform(0, math.tau)
        self.pickup_delay = 0.35   # не подбирается мгновенно на месте драки
        self.lift = 0.0            # текущий сдвиг по Y для отрисовки

    def draw(self, screen, camera):
        """Один общий рисунок для всех предметов: спрайт + покачивание."""
        x, y = camera.to_screen(self.x, self.y)
        surf = spritebank.get(self.sprite_name)
        screen.blit(surf, surf.get_rect(center=(x, y + self.lift)))

    def draw_glow(self, screen, camera, time=0.0):
        """Мягкий блик поверх темноты: лут находят глазами, а не на ощупь."""
        x, y = camera.to_screen(self.x, self.y)
        pulse = 0.72 + 0.28 * math.sin(time * 4.0 + self.bob_phase)
        visuals.glow(screen, x, y + self.lift, 18, self.glow_color,
                     int(62 * pulse))

    def update(self, dt, game):
        if self.pickup_delay > 0.0:
            self.pickup_delay -= dt
            return
        player = game.player
        dist = distance(self.x, self.y, player.x, player.y)

        if dist < self.pickup_range:            # примагничивание
            dx = player.x - self.x
            dy = player.y - self.y
            length = math.hypot(dx, dy) or 1.0
            speed = 240.0 * dt
            self.x += dx / length * min(speed, dist)
            self.y += dy / length * min(speed, dist)
            dist = distance(self.x, self.y, player.x, player.y)

        if dist < player.radius + 12:           # подбор
            if self.apply(game):
                self.kill()

        # покачивание при отрисовке (запоминаем здесь, draw не знает про время)
        self.lift = math.sin(game.elapsed * 5.0 + self.bob_phase) * self.wobble

    def apply(self, game):
        """Что даёт предмет. True — предмет потрачен/подобран."""
        raise NotImplementedError(
            f"{type(self).__name__} должен реализовать apply()"
        )


class CoinDrop(Drop):
    """Монета → деньги (в M5 на них будут магазины и улучшения)."""

    sprite_name = "coin"
    glow_color = (255, 202, 90)

    def __init__(self, x, y, value):
        super().__init__(x, y)
        self.value = value

    def apply(self, game):
        game.money += self.value
        game.effects.append(FloatingText(self.x, self.y - 8, f"+{self.value}",
                                         (255, 212, 105), 17, 44.0))
        soundbank.play("coin")
        return True


class AmmoDrop(Drop):
    """Боезапас → ОБЩИЙ пул единиц (M11: калибров больше нет)."""

    sprite_name = "ammo"
    glow_color = (180, 208, 240)

    def __init__(self, x, y, amount):
        super().__init__(x, y)
        self.amount = amount

    def apply(self, game):
        game.player.equipment.add_ammo(self.amount)
        game.effects.append(FloatingText(self.x, self.y - 8, f"+{self.amount} патр.",
                                         (210, 226, 246), 15, 44.0))
        soundbank.play("pickup")
        return True


class GrenadeDrop(Drop):
    """Граната → расходник в инвентаре (клавиша Q)."""

    sprite_name = "grenade"
    glow_color = (250, 170, 90)

    def __init__(self, x, y, amount=1):
        super().__init__(x, y)
        self.amount = amount

    def apply(self, game):
        game.player.equipment.add_item("grenade", self.amount)
        soundbank.play("pickup")
        return True


class HealDrop(Drop):
    """Аптечка → расходник в инвентаре (клавиша G лечит)."""

    sprite_name = "medkit"
    glow_color = (140, 240, 180)

    def __init__(self, x, y, amount=1):
        super().__init__(x, y)
        self.amount = amount

    def apply(self, game):
        game.player.equipment.add_item("medkit", self.amount)
        soundbank.play("pickup")
        return True


class ArtifactDrop(Drop):
    """
    Артефакт с пола: подбирается — сразу встаёт в свой слот.
    Старый артефакт того же слота продаётся за тот же процент
    компенсации, что и оружие (единое экономическое правило).
    """

    sprite_name = "artifact"
    glow_color = (202, 134, 255)

    def __init__(self, x, y, artifact_key):
        super().__init__(x, y)
        self.artifact_key = artifact_key

    def apply(self, game):
        player = game.player
        artifact = create_artifact(self.artifact_key)
        old = player.equipment.get(artifact.slot)
        if old is not None:
            old.on_unequip(player)            # снять статы старого
            game.money += old.refund_value()  # и вернуть % вложенного
        player.equipment.equip(artifact.slot, artifact)
        artifact.on_equip(player)             # включить статы нового
        soundbank.play("artifact")
        return True


def roll_drops(enemy):
    """
    Розыгрыш по таблице enemy.drops: каждая строка — независимый бросок.
    Из одного монстра может упасть несколько предметов или ничего.
    """
    result = []
    for entry in enemy.drops:
        if random.random() >= entry.get("chance", 0.0):
            continue
        amount = random.randint(entry.get("min", 1), entry.get("max", 1))
        if amount <= 0:
            continue
        x = enemy.x + random.uniform(-8, 8)
        y = enemy.y + random.uniform(-8, 8)
        kind = entry.get("type")
        if kind == "coin":
            result.append(CoinDrop(x, y, amount))
        elif kind == "ammo":
            # M11: без типа — таблицы дропа больше не знают про калибры
            result.append(AmmoDrop(x, y, amount))
        elif kind == "grenade":
            result.append(GrenadeDrop(x, y, amount))
        elif kind == "heal":
            result.append(HealDrop(x, y, amount))
        elif kind == "artifact":
            # ключ указанного артефакта или случайный — настраивается строкой
            key = entry.get("key") or random.choice(ALL_KEYS)
            result.append(ArtifactDrop(x, y, key))
        else:
            raise ValueError(f"Неизвестный тип дропа: {kind!r}")
    return result
