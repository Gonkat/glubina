"""
Артефакты: два слота по GDD — активный (F) и пассивный.

ДАННЫЕ лежат в artifact_data.py, здесь только ПОВЕДЕНИЕ — именно
оно отличает артефакты друг от друга, поэтому здесь классы
(наследование там, где меняется поведение, а не цифры).

Контракт, который понимают Player и магазин (duck typing):
  on_equip(owner) / on_unequip(owner) — включение/выключение статов;
  on_hurt(owner, damage) -> damage    — «броня» переписывает урон;
  on_kill(owner, game, enemy)         — реакция на убийство (вампиризм);
  on_fatal(owner, damage) -> bool     — спасение от смертельного удара;
  damage_mult                         — «клык» множит урон всего оружия;
  activate(owner, game) -> bool       — активная способность (клавиша F);
  update(dt, owner, game)             — тик кулдауна и длительных эффектов;
  refund_value()                      — компенсация при замене (как у оружия).

Событийные хуки (on_kill / on_fatal) — РАСШИРЕНИЕ M7: Player и Game
спрашивают «есть ли реакция на это событие?», а артефакт решает.
Нет артефакта или у него нет хука — база отвечает мгновенно и безвредно.
"""
import math

import soundbank
from artifact_data import ARTIFACTS
from projectiles import Explosion, Lightning, Particle
from settings import SELL_RETURN_PERCENT
from utils import distance


class Artifact:
    """База: ключ, имя, цена, вложенность и компенсация — как у Weapon."""

    def __init__(self, key):
        spec = ARTIFACTS[key]
        self.key = key
        self.spec = dict(spec)
        self.name = spec["name"]
        self.cost = spec["cost"]
        self.rarity = spec["rarity"]
        # слот Equipment, куда садится артефакт, — из данных
        self.slot = ("active_artifact" if spec["slot"] == "active"
                     else "passive_artifact")
        self.invested = 0       # артефакты не прокачиваются — но поле есть

    # ---------------------------------------------------- КОНТРАКТ (по умолчанию пусто)
    def on_equip(self, owner):
        pass

    def on_unequip(self, owner):
        pass

    def on_hurt(self, owner, damage):
        return damage

    def on_kill(self, owner, game, enemy):
        pass

    def on_fatal(self, owner, damage):
        return False            # «не спасло» — игрок сам решит, что делать

    def activate(self, owner, game):
        return False

    def update(self, dt, owner, game):
        pass

    @property
    def damage_mult(self):
        return 1.0

    # ---------------------------------------------------- ЭКОНОМИКА (как у оружия)
    @property
    def total_spent(self):
        return self.cost + self.invested

    def refund_value(self):
        return round(self.total_spent * SELL_RETURN_PERCENT)


# ================================================================ ПАССИВНЫЕ
class PassiveArtifact(Artifact):
    """Работает сам по себе, пока стоит в слоте. Вкл/выкл — статы героя."""


class Boots(PassiveArtifact):
    """Сапоги: +25% скорости. Считаем от base_speed, чтобы снятие вернуло всё."""

    def on_equip(self, owner):
        owner.speed = (owner.base_speed * self.spec["speed_mult"]
                       * getattr(owner, "boon_speed_mult", 1.0)
                       * (1.0 + owner.skill_mod("speed_add")))

    def on_unequip(self, owner):
        owner.speed = (owner.base_speed
                       * getattr(owner, "boon_speed_mult", 1.0)
                       * (1.0 + owner.skill_mod("speed_add")))


class Armor(PassiveArtifact):
    """Кираса: переписывает каждый получаемый урон (хук on_hurt)."""

    def on_hurt(self, owner, damage):
        return damage * self.spec["damage_taken"]


class Amulet(PassiveArtifact):
    """Амулет жизни: +к максимуму HP и сразу лечит на столько же."""

    def on_equip(self, owner):
        bonus = self.spec["hp_bonus"]
        owner.max_hp += bonus
        owner.heal(bonus)

    def on_unequip(self, owner):
        owner.max_hp -= self.spec["hp_bonus"]
        owner.hp = min(owner.hp, owner.max_hp)


class Fang(PassiveArtifact):
    """Клык: множитель урона. Player читает weapon.damage * damage_mult."""

    @property
    def damage_mult(self):
        return self.spec["damage_mult"]


# ==================================================== ЭПИЧЕСКИЕ / ЛЕГЕНДАРНЫЕ (M7)
class Devourer(PassiveArtifact):
    """Пожиратель: вампиризм — Game зовёт on_kill на каждое убийство."""

    def on_kill(self, owner, game, enemy):
        owner.heal(self.spec["heal"])
        # визуальный отклик — зелёная искра лечения у героя
        game.effects.append(Particle(owner.x, owner.y, (110, 240, 130)))


class Heart(PassiveArtifact):
    """
    Сердце титана: раз в save_cooldown смертельный удар оставляет 1 HP.
    Единственный пассивный артефакт, котору нужен тик таймера —
    Player обновляет ВСЕ артефакты в слотах (см. update).
    """

    def __init__(self, key):
        super().__init__(key)
        self.save_timer = 0.0

    def update(self, dt, owner, game):
        self.save_timer = max(0.0, self.save_timer - dt)

    def on_fatal(self, owner, damage):
        if self.save_timer > 0.0:
            return False         # спасение ещё «перезаряжается»
        self.save_timer = self.spec["save_cooldown"]
        return True              # Player поставит hp = 1


# ================================================================ АКТИВНЫЕ
class ActiveArtifact(Artifact):
    """Способность по F: кулдаун + делегирование конкретной силе (_power)."""

    def __init__(self, key):
        super().__init__(key)
        self.cooldown_timer = 0.0

    @property
    def ready(self):
        return self.cooldown_timer <= 0.0

    @property
    def cooldown(self):
        return self.spec["cooldown"]

    def activate(self, owner, game):
        """False — если кулдаун или способность отказалась работать."""
        if not self.ready:
            return False
        if not self._power(owner, game):
            return False
        self.cooldown_timer = self.spec["cooldown"]
        return True

    def update(self, dt, owner, game):
        self.cooldown_timer = max(0.0, self.cooldown_timer - dt)
        self._tick(dt, owner, game)

    def _power(self, owner, game):
        raise NotImplementedError(f"{type(self).__name__}: нет способности")

    def _tick(self, dt, owner, game):
        """Длительные эффекты (например, движение рывка) — по желанию."""


class Dash(ActiveArtifact):
    """Рывок: за time секунд проходит distance в направлении взгляда,
    сквозь врагов (без урона). Стены нет — resolve_circle."""

    def __init__(self, key):
        super().__init__(key)
        self.remaining = 0.0      # сколько ещё осталось пролететь

    def _power(self, owner, game):
        self.remaining = float(self.spec["distance"])
        owner.invuln_timer = max(getattr(owner, "invuln_timer", 0.0), 0.30)
        soundbank.play("dash")
        return True

    def _tick(self, dt, owner, game):
        if self.remaining <= 0.0:
            return
        speed = self.spec["distance"] / self.spec["time"]
        step = min(speed * dt, self.remaining)
        nx = owner.x + math.cos(owner.angle) * step
        ny = owner.y + math.sin(owner.angle) * step
        owner.x, owner.y = game.world.resolve_circle(nx, ny, owner.radius)
        self.remaining -= step
        game.effects.append(Particle(owner.x, owner.y, (140, 220, 255)))


class Nova(ActiveArtifact):
    """Волна вокруг героя: урон + отброс. Бьёт ТОЛЬКО врагов —
    в отличие от взрыва гранаты, герой в центре в порядке."""

    def _power(self, owner, game):
        radius = self.spec["radius"]
        for enemy in game.enemies:
            if not enemy.alive:
                continue
            d = distance(owner.x, owner.y, enemy.x, enemy.y)
            if d > radius + enemy.radius:
                continue
            scale = 1.0 - 0.5 * min(1.0, d / radius)    # ближе — больнее
            game.damage_enemy(
                enemy, self.spec["damage"] * scale,
                knockback_dir=((enemy.x - owner.x) / max(d, 1e-6),
                               (enemy.y - owner.y) / max(d, 1e-6)),
                knockback=self.spec["knockback"] * scale,
            )
        # визуал — переиспользуем Explosion (свет подхватит Game сам)
        game.effects.append(Explosion(owner.x, owner.y, radius))
        soundbank.play("explosion", 0.6)   # волна тише настоящего взрыва
        return True


class Shield(ActiveArtifact):
    """Щит: полная неуязвимость на duration секунд (hurt_timer героя)."""

    def _power(self, owner, game):
        owner.hurt_timer = max(owner.hurt_timer, self.spec["duration"])
        soundbank.play("shield")
        return True


class Thunderlord(ActiveArtifact):
    """
    Громовержец: молния бьёт ближайших врагов в радиусе range.
    Если в радиусе никого нет — способность ВОЗВРАЩАЕТ False,
    и activate() НЕ засчитывает кулдаун: свинья не должна наказывать.
    """

    def _power(self, owner, game):
        in_range = [
            enemy for enemy in game.enemies
            if enemy.alive
            and distance(owner.x, owner.y, enemy.x, enemy.y)
            <= self.spec["range"] + enemy.radius
        ]
        if not in_range:
            return False         # мимо — кулдаун не тратим
        in_range.sort(key=lambda e: distance(owner.x, owner.y, e.x, e.y))
        for enemy in in_range[: self.spec["targets"]]:
            game.damage_enemy(enemy, self.spec["damage"])
            game.effects.append(Lightning(owner.x, owner.y,
                                          enemy.x, enemy.y))
        soundbank.play("lightning", 0.8)   # ОДИН раз на активацию, не на молнию
        return True


# ================================================================ ФАБРИКА
ARTIFACT_CLASSES = {
    "boots": Boots,
    "armor": Armor,
    "amulet": Amulet,
    "fang": Fang,
    "dash": Dash,
    "nova": Nova,
    "shield": Shield,
    "devourer": Devourer,
    "heart": Heart,
    "thunder": Thunderlord,
}


def create_artifact(key):
    """Фабрика: строка-ключ из artifact_data → готовый артефакт."""
    cls = ARTIFACT_CLASSES.get(key)
    if cls is None:
        raise ValueError(f"Неизвестный артефакт: {key!r}")
    return cls(key)
