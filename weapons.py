"""
Классы оружия.

Здесь НЕТ классов «Пистолет», «Дробовик» — все они одинаковы по коду
и различаются только ДАННЫМИ из weapon_data.py. Это осознанный выбор:
наследование нужно там, где меняется ПОВЕДЕНИЕ, а не цифры.
"""
import math
import random

import pygame

from attacks import create_attack
import spritebank
from settings import (
    AIM_FULL_TIME,
    AIM_MARK_TIME,
    GUN_COLOR,
    MODE_SWITCH_TIME,
    SELL_RETURN_PERCENT,
    STABLE_SHOT_TIME,
    UPGRADE_BONUS,
    UPGRADE_COST_GROWTH,
    UPGRADE_MAX_LEVEL,
)
from weapon_data import (FIREARMS, MELEE, PISTOL_MODE_NODES,
                         PISTOL_MODE_ORDER, PISTOL_MODES)


class Weapon:
    """
    База любого оружия: имя, цена, редкость, характеристики.

    Характеристики лежат в self.spec как КОПИЯ словаря — улучшения (M5)
    меняют конкретный экземпляр, а не общий шаблон weapon_data.py.
    """

    slot = None   # какой слот занимает ("firearm", "melee", ...)

    def __init__(self, key, spec):
        self.key = key              # ключ в weapon_data — по нему магазин
        self.spec = dict(spec)      # КОПИЯ: прокачка правит только её
        self.name = spec["name"]
        self.cost = spec["cost"]    # базовая цена покупки
        self.rarity = spec["rarity"]
        self.upgrade_level = 0      # текущий уровень улучшения (melee, M5)
        self.invested = 0           # сколько денег вложено в улучшения/узлы
        # --- ВЕТВИ РАЗВИТИЯ (M11): дерево покупок этого экземпляра ---
        self.nodes = set()          # id купленных узлов (источник правды)
        self.node_order = []        # порядок покупок — для восстановления при смене
        self.mods = {}              # агрегированные механики: имя -> значение
        self.main_branch = None     # ключ основной ветви (фиксируется 1-й покупкой)

    def mod(self, name, default=0):
        """Значение механики из купленных узлов (0/None — не куплено)."""
        return self.mods.get(name, default)

    @property
    def damage(self):
        """Урон берётся из spec — улучшения переписывают spec['damage']"""
        return self.spec["damage"]

    # ------------------------------------------------------------ ПРОКАЧКА (M5)
    def upgrade_cost(self):
        """Цена следующего уровня: база × рост^текущий уровень."""
        base = self.spec.get("upgrade_cost", 50)
        return round(base * UPGRADE_COST_GROWTH ** self.upgrade_level)

    @property
    def is_upgradable(self):
        return self.upgrade_level < UPGRADE_MAX_LEVEL

    def upgrade(self, paid_cost=None):
        """
        Прокачка на один уровень: +урон к данным этого экземпляра.
        Возвращает СКОЛЬКО заплачено (0 — если уже максимум).
        Деньги списывает магазин — оружие о деньгах не знает.
        """
        if not self.is_upgradable:
            return 0
        cost = self.upgrade_cost() if paid_cost is None else paid_cost
        self.upgrade_level += 1
        self.invested += cost
        # важно: атаки ближнего боя читают spec["damage"] напрямую,
        # поэтому улучшение пишет именно в spec — и все бьют сильнее
        self.spec["damage"] *= 1.0 + UPGRADE_BONUS
        return cost

    # ------------------------------------------------------------ ЭКОНОМИКА (M5)
    @property
    def total_spent(self):
        """Сколько вложено в это оружие: покупка + все улучшения."""
        return self.cost + self.invested

    def refund_value(self):
        """Компенсация при замене: настраиваемый % от total_spent (GDD п.2)."""
        return round(self.total_spent * SELL_RETURN_PERCENT)

    def upgrade_refund_value(self):
        """Компенсация огнестрельного оружия только за фактические улучшения."""
        return round(self.invested * SELL_RETURN_PERCENT)


class Firearm(Weapon):
    """Огнестрельное оружие: магазин, откат, перезарядка, дробь, пробитие."""

    slot = "firearm"

    def __init__(self, key, spec):
        super().__init__(key, spec)
        # M11: калибров больше нет — только цена единицы боезапаса.
        # Цена читается из spec, поэтому поздние узлы могут её менять.
        self.loaded = spec["magazine"]     # патроны В магазине
        self.cooldown = 0.0
        self.reload_timer = 0.0
        self._reload_take = 0              # сколько патронов заберём при конце
        self.since_shot = 0.0              # секунд с последнего выстрела
        self.shot_streak = 0               # длина непрерывной серии («Разгон»)
        self.shot_count = 0                # всего спусков (для залпов)
        self.shot_parity = 0               # чётные/нечётные выстрелы («Ритм»)
        self.last_shot_heavy = False       # текущий выстрел — тяжёлый
        self.volley_ready = False          # следующий выстрел даёт залп
        # --- режимы пистолета (ветвь «Арсенал») ---
        self.mode = "standard"
        self.switch_timer = 0.0            # короткая пауза после смены режима
        # --- заряд энергопушки (M14) ---
        # 0..1 — накопленный заряд; is_charging — ЛКМ реально удерживается.
        # last_charge_ratio фиксируется в момент отпускания: resolve_shot
        # читает именно его, поэтому снаряд не зависит от следующего кадра.
        self.charge = 0.0
        self.is_charging = False
        self.charge_full = False
        self.last_charge_ratio = 0.0
        self.charge_started_at = 0.0
        # --- магнитный диск (M16): только один снаряд в полёте ---
        self.live_discs = []
        # --- плазменный резак (M16): тепло и принудительный сброс ---
        self.heat = 0.0
        self.vent_timer = 0.0
        self.vent_pending = False
        self.last_heat = 0.0
        self.sprite = self._build_sprite()

    # ------------------------------------------------------------ СОСТОЯНИЕ
    @property
    def is_reloading(self):
        return self.reload_timer > 0.0

    @property
    def magazine_size(self):
        """Ёмкость читается из spec: узлы «магазин +N» работают сразу."""
        return max(1, int(round(self.spec.get("magazine", 1))))

    # ------------------------------------------------------------ ЗАРЯД (M14)
    @property
    def uses_charge(self):
        """Заряд может жить и в spec (пушка), и в профиле режима (плазма)."""
        return self._charge_value("charge_time", 0.0) > 0.0

    def _charge_value(self, key, default):
        """Профиль режима важнее spec: пистолет не заряжается вне «Плазмы»."""
        return float(self.mode_profile.get(key, self.spec.get(key, default)))

    @property
    def charge_time(self):
        return max(0.08, self._charge_value("charge_time", 1.0))

    @property
    def charge_color(self):
        return self.mode_profile.get("projectile_color",
                                     self.spec.get("projectile_color",
                                                   (112, 232, 255)))

    @property
    def min_charge(self):
        """Порог, ниже которого базовый выстрел не происходит."""
        if self.mod("full_only"):
            return 1.0
        if self.mod("partial_unlock"):
            return 0.08
        return max(0.0, min(1.0, self._charge_value("min_charge", 0.0)))

    @property
    def charge_ratio(self):
        return max(0.0, min(1.0, self.charge))

    def begin_charge(self):
        """Начать заряд, если оружие готово. Не тратит патроны."""
        if not self.uses_charge or self.is_charging:
            return False
        if not self.can_fire:
            return False
        self.is_charging = True
        self.charge = 0.0
        self.charge_full = False
        self.last_charge_ratio = 0.0
        return True

    def advance_charge(self, dt, player=None):
        """Тик удержания. Возвращает 'full' в кадр достижения 100%."""
        if not self.is_charging or not self.uses_charge:
            return None
        rate = 1.0
        moving = False
        if player is not None:
            moving = math.hypot(*getattr(player, "move_dir", (0.0, 0.0))) > 0.1
        rate += float(self.mod("charge_speed_add", 0.0))
        if self.mod("still_charge_speed") and not moving:
            rate += float(self.mod("still_charge_speed"))
        if self.mod("moving_charge_speed") and moving:
            rate += float(self.mod("moving_charge_speed"))
        rate = max(0.35, rate)
        was_full = self.charge_full
        self.charge = min(1.0, self.charge + dt / self.charge_time * rate)
        if self.charge >= 1.0 and not was_full:
            self.charge_full = True
            return "full"
        return None

    def cancel_charge(self):
        """Прерывание без выстрела и без расхода патронов."""
        self.is_charging = False
        self.charge = 0.0
        self.charge_full = False

    def release_charge(self, player=None):
        """
        Отпускание ЛКМ. Возвращает:
          'fire'   — снаряд выпущен (параметры уже в состоянии оружия);
          'cancel' — заряд сброшен, выстрела НЕ было;
          'idle'   — нечего отпускать.

        Ранний отпуск — это именно отмена, а не «пуля в молоко»: игрок
        не теряет патрон и не получает случайный выстрел.
        """
        if not self.is_charging:
            return "idle"
        ratio = self.charge_ratio
        self.is_charging = False
        self.charge = 0.0
        self.charge_full = False
        if ratio + 1e-6 < self.min_charge:
            return "cancel"
        if not self.can_fire:
            return "cancel"
        self.last_charge_ratio = ratio
        self.consume_shot(player)
        # «Импульсный возврат»: недозаряд иногда не тратит патрон магазина.
        if (ratio < 0.999 and self.mod("partial_refund_chance")
                and random.random() < self.mod("partial_refund_chance")):
            self.loaded = min(self.magazine_size, self.loaded + 1)
        return "fire"

    @property
    def ammo_cost(self):
        """Сколько единиц боезапаса стоит один патрон магазина."""
        return self.spec.get("ammo_cost", 1)

    @property
    def muzzle_offset(self):
        """Дальность от центра героя до дула (для пули и вспышки)."""
        return self.spec.get("barrel_len", 34) - 4

    # ------------------------------------------------------------ РЕЖИМЫ (M13)
    @property
    def mode_switch_unlocked(self):
        return "pistol_x1" in self.nodes

    @property
    def available_modes(self):
        """Стандартный режим плюс купленные насадки «Арсенала»."""
        modes = ["standard"]
        for mode in PISTOL_MODE_ORDER[1:]:
            if PISTOL_MODE_NODES.get(mode) in self.nodes:
                modes.append(mode)
        return tuple(modes)

    @property
    def has_modes(self):
        return len(self.available_modes) > 1

    @property
    def mode_profile(self):
        return PISTOL_MODES.get(self.mode, PISTOL_MODES["standard"])

    @property
    def mode_name(self):
        return self.mode_profile["name"]

    @property
    def mode_color(self):
        return self.mode_profile.get("color", (112, 208, 242))

    @property
    def rounds_per_shot(self):
        """Сколько патронов магазина стоит один выстрел текущего режима."""
        return max(1, int(self.mode_profile.get("rounds", 1)))

    def cycle_mode(self):
        """Следующий открытый режим. None — если насадков ещё нет."""
        modes = self.available_modes
        if len(modes) <= 1:
            return None
        # Смена режима — это смена механики. Заряд «Плазмы» не должен
        # переехать в следующий режим и выстрелить из «Точки».
        if self.is_charging:
            self.cancel_charge()
        index = modes.index(self.mode) if self.mode in modes else 0
        self.mode = modes[(index + 1) % len(modes)]
        self.switch_timer = MODE_SWITCH_TIME
        # Смена насадка — новый ритм: не тащим в него залп и «тяжёлый»
        # выстрел от предыдущего режима.
        self.volley_ready = False
        self.last_shot_heavy = False
        self.shot_streak = 0
        return self.mode

    # ---------------------------------------------------- ДИСК (M16)
    @property
    def uses_disc(self):
        """Оружие с возвращающимся снарядом (магнитный диск)."""
        return bool(self.spec.get("returning"))

    @property
    def has_live_disc(self):
        return any(disc.alive for disc in self.live_discs)

    def track_disc(self, bullet):
        self.live_discs = [disc for disc in self.live_discs if disc.alive]
        self.live_discs.append(bullet)

    def drop_disc(self, bullet):
        self.live_discs = [disc for disc in self.live_discs if disc is not bullet]

    def recall_discs(self):
        """ЛКМ по летящему диску подзывает его, не тратя патрон."""
        recalled = False
        for disc in self.live_discs:
            if disc.alive:
                disc.recall()
                recalled = True
        return recalled

    def catch_refund_chance(self):
        return max(0.0, float(self.spec.get("catch_refund", 0.0))
                   + float(self.mod("disc_catch_refund", 0.0)))

    # ---------------------------------------------------- РЕЗАК (M16)
    @property
    def uses_heat(self):
        return float(self.spec.get("heat_per_shot", 0.0)) > 0.0

    @property
    def heat_ratio(self):
        return max(0.0, min(1.0, self.heat))

    @property
    def is_venting(self):
        return self.vent_timer > 0.0

    @property
    def heat_damage_mult(self):
        """Множитель урона от нагрева ИМЕННО прошлого спуска курка."""
        bonus = (float(self.spec.get("heat_damage_bonus", 0.0))
                 + float(self.mod("heat_damage_bonus", 0.0)))
        return 1.0 + bonus * max(0.0, min(1.0, self.last_heat))

    def vent_radius(self):
        return max(20.0, float(self.spec.get("vent_radius", 100.0))
                   + float(self.mod("vent_radius_add", 0.0)))

    def vent_blast(self):
        return max(0.0, float(self.spec.get("vent_blast", 0.0))
                   + float(self.mod("vent_blast_add", 0.0)))

    def vent_self_damage(self):
        return max(0.0, float(self.spec.get("vent_self_damage", 0.0))
                   + float(self.mod("vent_self_damage_add", 0.0)))

    def start_vent(self):
        """Принудительный сброс тепла: блокировка ствола на vent_time."""
        base = float(self.spec.get("vent_time", 1.0))
        modifier = max(0.5, 1.0 + float(self.mod("vent_time_mul", 0.0)))
        self.vent_timer = max(0.3, base * modifier)
        self.heat = 0.0
        self.vent_pending = False
        self.cooldown = max(self.cooldown, self.vent_timer)
        return self.vent_timer

    def update(self, dt):
        """Тик таймеров: откат выстрела, серия, конец перезарядки."""
        self.cooldown = max(0.0, self.cooldown - dt)
        self.switch_timer = max(0.0, self.switch_timer - dt)
        # узел мог исчезнуть только в отладке/тестах — не оставляем
        # оружие с недоступным режимом
        if self.mode not in self.available_modes:
            self.mode = "standard"
        self.since_shot += dt
        if self.since_shot > 1.0:
            self.shot_streak = 0           # серия оборвалась — «Разгон» сбросился
        if self.uses_heat:
            self.vent_timer = max(0.0, self.vent_timer - dt)
            if self.vent_timer <= 0.0 and self.since_shot >= float(
                    self.spec.get("heat_cool_delay", 0.35)):
                cool = float(self.spec.get("heat_cool", 0.0)) * max(
                    0.2, 1.0 + float(self.mod("heat_cool_add", 0.0)))
                self.heat = max(0.0, self.heat - cool * dt)
        if self.live_discs:
            self.live_discs = [disc for disc in self.live_discs if disc.alive]
        if self.is_reloading:
            self.reload_timer -= dt
            if self.reload_timer <= 0.0:
                self.loaded += self._reload_take
                self._reload_take = 0
                self.reload_timer = 0.0

    # ------------------------------------------------------------ СТРЕЛЬБА
    @property
    def can_fire(self):
        return (self.cooldown <= 0.0 and self.switch_timer <= 0.0
                and self.vent_timer <= 0.0
                and not self.is_reloading
                and self.loaded >= self.rounds_per_shot)

    def consume_shot(self, player=None):
        """Один спуск курка = столько патронов, сколько стоит режим."""
        # Нагрев фиксируется ДО выстрела: этот же множитель получит
        # снаряд, даже если ствол успеет остыть, пока пуля летит.
        self.last_heat = self.heat
        if self.uses_heat:
            gain = float(self.spec.get("heat_per_shot", 0.0)) * max(
                0.2, 1.0 + float(self.mod("heat_gain_add", 0.0)))
            self.heat = min(1.0, self.heat + gain)
            if self.heat >= 0.999:
                self.vent_pending = True
        self.loaded = max(0, self.loaded - self.rounds_per_shot)
        self.shot_count += 1
        self.shot_parity ^= 1
        self.last_shot_heavy = bool(self.mod("alternating_bonus")
                                    and self.shot_parity == 0)
        cooldown = self.spec["cooldown"] * self.mode_profile.get("cooldown_mul", 1.0)
        if self.mod("rapid"):
            # «Разгон» (ветвь Шквал): каждая пуля серии чуть быстрее
            cooldown *= 0.95 ** min(self.shot_streak, 6)
        if (self.mod("alternating_cooldown_mul")
                and not self.last_shot_heavy):
            cooldown *= self.mod("alternating_cooldown_mul", 1.0)
        if self.uses_charge and self.last_charge_ratio < 0.999:
            # «Свободный поток»: недозаряд можно выпускать чаще.
            cut = max(0.0, min(0.45, float(self.mod("partial_cooldown_cut"))))
            cooldown *= 1.0 - cut
        every = int(self.mod("volley_every", 0))
        self.volley_ready = bool(every and self.shot_count % every == 0)
        self.cooldown = cooldown
        self.shot_streak += 1
        self.since_shot = 0.0

    def resolve_shot(self, player):
        """
        Параметры СНАРЯДА одного выстрела (слой ProjectileDefinition, M11).

        Здесь складываются: база из spec, множитель пассивных
        артефактов, механики купленных узлов дерева и состояние
        прицела («Стабилизация», «Метка», «Расчёт траектории»).
        Возвращает ровно те kwargs, которые ждёт Bullet.
        """
        profile = self.mode_profile
        source = profile.get("source")
        training = 0
        if source is not None:
            training = int(getattr(player, "weapon_training", {}).get(source, 0))
        damage = self.spec["damage"] * player.damage_mult
        zoomed = getattr(player, "camera_zoom", 1.0) < 0.999
        stable_time = STABLE_SHOT_TIME
        if zoomed:
            stable_time = max(
                0.35, STABLE_SHOT_TIME
                - float(self.mod("zoom_stable_time_cut", 0.0)))
        if self.mod("stable_mul") and self.since_shot >= stable_time:
            damage *= self.mod("stable_mul")          # «Стабилизация»
        if zoomed:
            damage *= 1.0 + float(self.mod("zoom_damage_bonus", 0.0))
        damage *= 1.0 + self.mod("shot_damage_mul", 0.0)
        # «Мастерство» ветвей: универсальный множитель урона, не
        # привязанный к конкретному типу снаряда или заряду.
        damage *= 1.0 + float(self.mod("damage_mul", 0.0))
        damage *= profile.get("damage_mul", 1.0)
        if self.uses_heat:
            # Риск/награда резака: горячий ствол бьёт сильнее.
            damage *= self.heat_damage_mult
        if self.mode == "scatter":
            damage *= 1.0 + self.mod("scatter_damage_mul", 0.0)
        # --- энергопушка: заряд масштабирует урон, хитбокс и взрыв ---
        charge = 0.0
        radius = float(self.spec["bullet_radius"])
        explosion_power = 1.0
        explosion_vulnerable = float(self.mod("explosion_vulnerable", 0.0))
        if self.uses_charge:
            charge = max(0.0, min(1.0, self.last_charge_ratio))
            low_damage = self._charge_value("charge_min_damage", 0.5)
            high_damage = self._charge_value("charge_max_damage", 2.0)
            damage *= low_damage + (high_damage - low_damage) * charge
            radius_min = float(self.spec["bullet_radius"])
            radius_max = self._charge_value("charge_max_radius", radius_min)
            radius = radius_min + (radius_max - radius_min) * charge
            if charge >= 0.999:
                damage *= 1.0 + float(self.mod("full_damage_mul"))
                radius *= 1.0 + float(self.mod("full_radius_mul"))
            else:
                damage *= 1.0 + float(self.mod("partial_damage_mul"))
                radius *= 1.0 + float(self.mod("partial_radius_mul"))
                if self.mod("partial_pellets"):
                    damage *= 1.0 + float(
                        self.mod("partial_pellet_damage_mul"))
            # Подготовка пушки усиливает именно плазменный режим, а не
            # обычный пистолетный выстрел.
            if self.mode == "plasma" and training >= 3:
                damage *= 1.10
            power_min = self._charge_value("charge_power_min", 1.0)
            power_max = self._charge_value("charge_power_max", 1.0)
            explosion_power = power_min + (power_max - power_min) * charge
        if self.last_shot_heavy:
            damage *= 1.0 + self.mod("alternating_bonus", 0.0)
        moving = math.hypot(*getattr(player, "move_dir", (0.0, 0.0))) > 0.1
        if self.mod("steady_bonus") and not moving:
            damage *= 1.0 + self.mod("steady_bonus")
        if zoomed and not moving and self.mod("zoom_steady_bonus"):
            damage *= 1.0 + self.mod("zoom_steady_bonus")
        pierce = (self.spec.get("pierce", 0)
                  + int(self.mod("pierce_add"))
                  + int(getattr(player, "boon_pierce", 0))
                  + int(profile.get("pierce", 0)))
        if self.mod("steady_pierce") and not moving:
            pierce += int(self.mod("steady_pierce"))
        if self.mode == "lance":
            pierce += int(self.mod("lance_pierce_add", 0))
            if training >= 3:
                pierce += 1
        wall_pen = int(self.mod("wall_pen")) + int(profile.get("wall_pen", 0))
        if self.mode == "lance":
            wall_pen += int(self.mod("lance_wall_pen_add", 0))
        explode = float(self.mod("explode", 0.0))
        if self.uses_charge:
            blast_min = self._charge_value("charge_blast_min", 0.0)
            blast_max = self._charge_value("charge_blast_max", blast_min)
            explode = blast_min + (blast_max - blast_min) * charge
            if charge >= 0.999:
                explode *= 1.0 + float(self.mod("full_blast_mul"))
                explode += float(self.mod("full_blast_add"))
                explode += float(self.mod("blast_radius_add"))
                pierce += int(self.mod("full_pierce"))
            else:
                explode += float(self.mod("blast_radius_add"))
        if self.mode == "scatter":
            # Дробина слишком мала для полноценного взрыва: синергия с
            # «Микровзрывом» остаётся, но не превращает дробь в артиллерию.
            explode = min(explode, float(profile.get("explode_cap", 20.0)))
        elif self.mode == "hammer":
            explode = (float(profile.get("explode", 45.0))
                       + min(20.0, explode * 0.25)
                       + float(self.mod("hammer_radius_add", 0.0)))
            if training >= 3:
                explode += 8.0
        elif self.mode == "lance":
            explode = min(explode, 45.0)
        bleed = (float(self.mod("bleed", 0.0))
                 + float(profile.get("bleed", 0.0)))
        if self.mode == "bleed":
            bleed += float(self.mod("bleed_add", 0.0))
            if training >= 3:
                bleed += 0.1
        # Оглушение «Резонанса» — только в режиме молота. Иначе бонус
        # специализации протекал бы в копьё и надрез.
        close_stun = float(self.mod("close_stun", 0.0))
        close_stun_range = float(self.mod("close_stun_range", 0.0))
        if self.mode == "hammer" and self.mod("hammer_stun"):
            close_stun = max(close_stun, float(self.mod("hammer_stun")))
            close_stun_range = max(close_stun_range,
                                   float(self.mod("hammer_stun_range", 0.0)))
        # --- параметры новых школ (M16) ---
        return_range = (float(self.spec.get("return_range", 0.0))
                        + float(self.mod("disc_range_add", 0.0)))
        return_speed_mul = (float(self.spec.get("return_speed_mul", 1.0))
                            + float(self.mod("disc_return_speed", 0.0)))
        return_damage_mul = (float(self.spec.get("return_damage_mul", 0.0))
                             + float(self.mod("disc_return_damage", 0.0)))
        recall_speed_mul = (float(self.spec.get("recall_speed_mul", 1.0))
                            + float(self.mod("disc_recall_speed", 0.0)))
        chain_jumps = (int(self.spec.get("chain_jumps", 0))
                       + int(self.mod("chain_jumps")))
        chain_range = (float(self.spec.get("chain_range", 0.0))
                       + float(self.mod("chain_range_add", 0.0)))
        chain_falloff = min(0.95, float(self.spec.get("chain_falloff", 0.72))
                            + float(self.mod("chain_falloff_add", 0.0)))
        chain_damage_mul = 1.0 + float(self.mod("chain_damage_mul", 0.0))
        shot = {
            "damage": damage,
            "speed": self.spec["bullet_speed"] * profile.get("bullet_speed_mul", 1.0),
            "radius": radius,
            "pierce": max(0, pierce),
            "ricochets": int(self.mod("ricochets")),
            "wall_pen": max(0, wall_pen),
            "homing": int(self.mod("homing")),
            "enemy_bounce": int(self.mod("enemy_bounce")),
            "growth": self.mod("growth", 0.0),
            "explode": explode,
            "cascade": self.mod("cascade", 0.0),
            "knockback": (self.mod("knockback", 0.0)
                          + float(profile.get("knockback", 0.0))),
            "close_bonus": self.mod("close_bonus", 0.0),
            "refund_kill_chance": self.mod("refund_kill_chance", 0.0),
            "refund_kill_amount": int(self.mod("refund_kill_amount")),
            # поздние доктрины
            "bleed": bleed,
            "bleed_spread": self.mod("bleed_spread", 0.0),
            "bleed_spread_radius": self.mod("bleed_spread_radius", 90.0),
            "explosion_bleed": self.mod("explosion_bleed", 0.0),
            "explosion_slow": self.mod("explosion_slow", 0.0),
            "close_stun": close_stun,
            "close_stun_range": close_stun_range,
            "impact_slow": self.mod("impact_slow", 0.0),
            "impact_slow_factor": self.mod("impact_slow_factor", 0.5),
            "impact_slow_radius": self.mod("impact_slow_radius", 0.0),
            "bounce_growth": self.mod("bounce_growth", 0.0),
            "bounced_bonus": self.mod("bounced_bonus", 0.0),
            "bounced_mark": self.mod("bounced_mark", 0.0),
            "pierce_vulnerable": self.mod("pierce_vulnerable", 0.0),
            "mark_vulnerable": (self.mod("mark_vulnerable", 0.0)
                                + (self.mod("zoom_mark_vulnerable", 0.0)
                                   if zoomed else 0.0)),
            "mark_duration": (self.mod("mark_duration", 1.5)
                              + (self.mod("zoom_mark_duration_add", 0.0)
                                 if zoomed else 0.0)),
            "cascade_shrapnel": int(self.mod("cascade_shrapnel")),
            "explosion_power": explosion_power,
            "explosion_vulnerable": explosion_vulnerable,
            "explosion_color": (self.charge_color
                                if self.uses_charge else None),
            "style": self.mode_profile.get(
                "projectile_style",
                self.spec.get("projectile_style", "bullet")),
            "color": self.mode_profile.get(
                "projectile_color", self.spec.get("projectile_color")),
            "charge": charge,
            "return_range": return_range,
            "return_speed_mul": return_speed_mul,
            "return_damage_mul": return_damage_mul,
            "recall_speed_mul": recall_speed_mul,
            "catch_refund": self.catch_refund_chance(),
            "chain_jumps": chain_jumps,
            "chain_range": chain_range,
            "chain_falloff": chain_falloff,
            "chain_damage_mul": chain_damage_mul,
            "heat": self.last_heat,
            # «Резонанс»: оглушение только у полного плазменного взрыва.
            "blast_stun": (float(self.mod("blast_stun"))
                           if self.uses_charge and charge >= 0.999 else 0.0),
        }
        # «Метка» и «Расчёт траектории» — прицел держится на враге
        mark_time = AIM_MARK_TIME
        if zoomed:
            mark_time /= 1.0 + max(0.0, float(self.mod("zoom_aim_speed", 0.0)))
        if player.aim_target is not None and player.aim_time >= mark_time:
            shot["mark_id"] = id(player.aim_target)
            shot["mark_bonus"] = self.mod("aim_mark", 0.0)
            if player.aim_time >= AIM_FULL_TIME and self.mod("aim_full_mul"):
                shot["damage"] *= self.mod("aim_full_mul")
                shot["pierce"] += int(self.mod("aim_full_pierce"))
        return shot

    def volley_shot(self, shot):
        """Параметры дополнительных пуль залпа (без расхода патронов)."""
        extra = dict(shot)
        extra["damage"] *= self.mod("volley_damage_mul", 0.65)
        extra["pierce"] = max(0, extra.get("pierce", 0))
        return extra

    def shot_params(self, player=None):
        """(дробины, разброс) текущего режима с бонусами подготовки."""
        profile = self.mode_profile
        pellets = int(profile.get("pellets", self.spec["pellets"]))
        spread = float(profile.get("spread_deg", self.spec["spread_deg"]))
        if self.mode == "scatter":
            training = 0
            if player is not None:
                training = int(getattr(player, "weapon_training", {})
                               .get("shotgun", 0))
            # Глубокая подготовка дробовика даёт одну дополнительную дробину.
            pellets += 1 if training >= 2 else 0
            pellets += int(self.mod("scatter_pellets_add", 0))
            spread += float(self.mod("scatter_spread_add", 0.0))
            spread = max(6.0, spread)
            pellets = max(1, min(6, pellets))
        if self.uses_charge and self.last_charge_ratio < 0.999:
            # «Шквал плазмы»: недозаряд распадается на несколько слабых
            # сгустков. Патрон всё равно один — это альтернатива burst.
            pellets += int(self.mod("partial_pellets"))
            spread += float(self.mod("partial_spread_deg"))
            pellets = max(1, min(6, pellets))
        return max(1, pellets), max(0.0, spread)

    def shot_angles(self, base_angle, params=None):
        """
        Углы всех пуль одного выстрела.
        Дробовик разлетается по конусу, остальные бьют в точку.
        """
        pellets, spread_deg = params or (self.spec["pellets"],
                                       self.spec["spread_deg"])
        spread = math.radians(spread_deg)
        return [
            base_angle + random.uniform(-spread / 2, spread / 2)
            for _ in range(int(pellets))
        ]

    # ------------------------------------------------------------ ПЕРЕЗАРЯДКА
    def start_reload(self, equipment):
        """
        Начинает перезарядку, забирая из ОБЩЕГО пула unit'ов:
        каждый добираемый патрон стоит self.ammo_cost единиц (M11).
        Узел «Экономист» может с шансом вернуть весь расход.
        Ничего не делает, если магазин полон или боеприпасов нет.
        """
        if self.is_reloading or self.loaded >= self.magazine_size:
            return False
        need = self.magazine_size - self.loaded
        units = need * self.ammo_cost
        taken = equipment.take_ammo(units)
        if taken == 0:
            return False                      # боезапаса нет — нечем заряжать
        rounds = taken // self.ammo_cost
        if rounds == 0:
            equipment.add_ammo(taken)         # единиц не хватило даже на патрон
            return False
        leftover = taken - rounds * self.ammo_cost
        if leftover:
            # остаток единиц не «сгорает»: 10 ед. при цене 3 = 3 патрона
            # и 1 ед. обратно в запас (частичная перезарядка, M11)
            equipment.add_ammo(leftover)
        if self.mod("refund_reload") and random.random() < self.mod("refund_reload"):
            equipment.add_ammo(taken - leftover)  # «повезло» — расход вернулся
        self._reload_take = rounds
        self.reload_timer = self.spec["reload_time"]
        return True

    # ------------------------------------------------------------ ОТРИСОВКА
    def _build_sprite(self):
        """
        Спрайт ствола: PNG из assets/sprites/weapons/{key}.png (M8),
        а если файла нет — процедурная отрисовка (игра работает и без ассетов).
        """
        asset = spritebank.try_get(f"weapons/{self.key}")
        if asset is not None:
            return asset
        return self._build_proc_sprite()

    def _build_proc_sprite(self):
        """
        Процедурный ствол. Это же ИСХОДНИК для assets_gen.py —
        генератор вызывает этот метод и сохраняет результат в PNG,
        поэтому код рисунка существует в одном экземпляре.
        """
        bl = self.spec.get("barrel_len", 34)
        bw = self.spec.get("barrel_w", 6)
        if self.key == "cannon":
            # Отдельный силуэт: катушки и плазменное ядро, а не «труба».
            # Пивот остаётся в центре поверхности, поэтому ствол длиной bl
            # уходит вперёд при повороте вокруг героя.
            width = bl * 2 + 16
            height = max(26, bw + 22)
            surf = pygame.Surface((width, height), pygame.SRCALPHA)
            cx = width // 2
            cy = height // 2
            body = pygame.Rect(cx - 12, cy - bw // 2 - 2, bl + 6, bw + 4)
            pygame.draw.rect(surf, (40, 48, 62), body, border_radius=4)
            pygame.draw.rect(surf, (76, 88, 110), body, 1, border_radius=4)
            # верхняя направляющая
            pygame.draw.rect(surf, (30, 36, 48),
                             (cx - 6, cy - bw // 2 - 6, bl, 3),
                             border_radius=1)
            # катушки
            for i in range(4):
                x = cx + 6 + i * 8
                pygame.draw.line(surf, (78, 196, 210),
                                 (x, cy - bw // 2 - 1),
                                 (x, cy + bw // 2 + 1), 1)
                pygame.draw.line(surf, (152, 246, 250),
                                 (x, cy - bw // 2 + 1),
                                 (x, cy + bw // 2 - 1), 1)
            # ядро у дула
            pygame.draw.circle(surf, (66, 178, 204),
                               (cx + bl - 2, cy), max(3, bw // 2))
            pygame.draw.circle(surf, (224, 255, 255),
                               (cx + bl - 2, cy), max(1, bw // 4))
            # рукоять
            pygame.draw.rect(surf, (48, 54, 70),
                             (cx - 16, cy + 2, 9, 11), border_radius=2)
            return surf
        if self.key == "disc":
            # Дискомёт: широкие «рога» и гнездо диска на конце.
            width = bl * 2 + 16
            height = max(26, bw + 20)
            surf = pygame.Surface((width, height), pygame.SRCALPHA)
            cx, cy = width // 2, height // 2
            body = pygame.Rect(cx - 12, cy - bw // 2, bl - 4, bw)
            pygame.draw.rect(surf, (44, 40, 34), body, border_radius=3)
            pygame.draw.rect(surf, (120, 104, 74), body, 1, border_radius=3)
            tip_x = cx + bl - 6
            for sign in (-1, 1):
                pygame.draw.line(surf, (188, 156, 96),
                                 (tip_x - 10, cy),
                                 (tip_x + 4, cy + sign * (bw // 2 + 6)), 2)
            pygame.draw.circle(surf, (96, 84, 62), (tip_x, cy), 5, 2)
            pygame.draw.circle(surf, (255, 214, 132), (tip_x, cy), 2)
            pygame.draw.rect(surf, (52, 46, 38),
                             (cx - 16, cy + 2, 9, 10), border_radius=2)
            return surf
        if self.key == "arc":
            # Дуговик: два расходящихся электрода и разряд между ними.
            width = bl * 2 + 14
            height = max(28, bw + 22)
            surf = pygame.Surface((width, height), pygame.SRCALPHA)
            cx, cy = width // 2, height // 2
            body = pygame.Rect(cx - 12, cy - bw // 2, bl - 2, bw)
            pygame.draw.rect(surf, (34, 42, 58), body, border_radius=3)
            pygame.draw.rect(surf, (86, 108, 140), body, 1, border_radius=3)
            tip_x = cx + bl - 8
            for sign in (-1, 1):
                pygame.draw.line(surf, (150, 170, 200),
                                 (tip_x - 12, cy + sign * 2),
                                 (tip_x + 6, cy + sign * (bw // 2 + 7)), 2)
            pygame.draw.line(surf, (176, 214, 255),
                             (tip_x + 2, cy - bw // 2 - 5),
                             (tip_x + 2, cy + bw // 2 + 5), 1)
            pygame.draw.circle(surf, (196, 232, 255), (tip_x + 2, cy), 2)
            pygame.draw.rect(surf, (40, 48, 62),
                             (cx - 16, cy + 2, 9, 10), border_radius=2)
            return surf
        if self.key == "cutter":
            # Резак: узкий эмиттер с рёбрами радиатора.
            width = bl * 2 + 12
            height = max(24, bw + 18)
            surf = pygame.Surface((width, height), pygame.SRCALPHA)
            cx, cy = width // 2, height // 2
            body = pygame.Rect(cx - 12, cy - bw // 2, bl + 2, bw)
            pygame.draw.rect(surf, (52, 40, 36), body, border_radius=3)
            pygame.draw.rect(surf, (152, 90, 72), body, 1, border_radius=3)
            for i in range(3):
                x = cx + 4 + i * 7
                pygame.draw.line(surf, (206, 118, 92),
                                 (x, cy - bw // 2 - 4),
                                 (x, cy - bw // 2 - 1), 1)
            pygame.draw.line(surf, (255, 176, 130),
                             (cx + bl - 4, cy - 1),
                             (cx + bl + 3, cy - 1), 2)
            pygame.draw.circle(surf, (255, 190, 150), (cx + bl + 3, cy), 2)
            pygame.draw.rect(surf, (44, 38, 36),
                             (cx - 16, cy + 2, 9, 10), border_radius=2)
            return surf
        width = bl + 12
        height = max(16, bw + 10)
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        cx = width // 2
        cy = height // 2
        # ствол выступает вперёд от центра
        pygame.draw.rect(surf, GUN_COLOR,
                         (cx - 6, cy - bw // 2, bl, bw), border_radius=2)
        # рукоять позади центра
        pygame.draw.rect(surf, GUN_COLOR, (cx - 16, cy - 2, 12, 4))
        return surf


class MeleeWeapon(Weapon):
    """
    Оружие ближнего боя. Собственной атаки НЕ имеет — оно ВЛАДЕЕТ
    объектом-атакой (композиция, HAS-A), выбранным по ключу spec["attack"].
    Один и тот же MeleeWeapon обслуживает и дугу, и волну, и ауру.
    """

    slot = "melee"

    def __init__(self, key, spec):
        super().__init__(key, spec)
        # атака получает КОПИЮ САМОГО ЭКЗЕМПЛЯРА (self.spec), а не общий
        # словарь weapon_data — иначе прокачка одного меча прокачала бы все
        self.attack = create_attack(self.spec)      # ← стратегия
        self.attack.mods = self.mods
        self.sprite = self._build_sprite()
        self._display_sprite = self.sprite
        self._display_sprite_state = (
            self.upgrade_level, self.spec.get("reach", 0.0))

    def _build_sprite(self):
        """
        Спрайт в руке: PNG из assets/sprites/weapons/{key}.png (M8).
        Файла может не быть — тогда None, и в руке ничего не рисуется
        (атака-зону это не отменяет: её рисует attacks.py).
        """
        return spritebank.try_get(f"weapons/{self.key}")

    def display_sprite(self):
        """Спрайт для руки; метла постепенно увеличивается с уровнем улучшения."""
        if self.sprite is None or self.key != "shovel":
            return self.sprite
        state = (self.upgrade_level, self.spec.get("reach", 0.0))
        if self._display_sprite_state != state:
            scale = 1.0 + 0.08 * self.upgrade_level
            base_reach = MELEE[self.key]["reach"]
            handle_scale = self.spec["reach"] / base_reach
            size = (max(1, round(self.sprite.get_width() * scale * handle_scale)),
                    max(1, round(self.sprite.get_height() * scale)))
            self._display_sprite = pygame.transform.smoothscale(self.sprite, size)
            self._display_sprite_state = state
        return self._display_sprite

    @property
    def is_passive(self):
        return self.attack.is_passive

    def update(self, dt, owner, game):
        self.attack.update(dt, owner, game)

    def try_attack(self, owner, game):
        """Нажатие ПКМ. Пассивная аура самоё себя вызывать не даст."""
        self.attack.start(owner, game)

    def draw(self, overlay, camera, owner):
        self.attack.draw(overlay, camera, owner)


def create_weapon(key):
    """Фабрика: строка-ключ из weapon_data → готовое оружие любого слота."""
    if key in FIREARMS:
        return Firearm(key, FIREARMS[key])
    if key in MELEE:
        return MeleeWeapon(key, MELEE[key])
    raise ValueError(f"Неизвестное оружие: {key!r}")
