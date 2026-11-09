"""
РАСШИРЕНИЕ ДРЕВ ОРУЖИЯ: НОВЫЕ ВЕТВИ И МАСТЕРСТВО.

Базовые древа описывают 3–5 ветвей по 4–9 узлов. Этот слой доводит
КАЖДУЮ ветвь до 20 узлов и добавляет каждому оружию новые ветви, чтобы
у него было 5–6 самостоятельных стратегий.

Почему мастерские узлы не продолжают tier 5 напрямую:
  * tier 5 у классических ветвей — ПАРА взаимоисключающих доктрин;
  * tier 6 у пистолета — ещё одна пара, продолжающая выбор;
  * если бы мастерство требовало «предыдущий tier», вторая альтернатива
    навсегда отрезала бы свой путь.
Поэтому общая мастерская цепочка начинается от tier 4 (или от
единственного финального узла ветви без развилки). Доктрины остаются
боковыми стилями, а мастерство — общей длинной лестницей ветви.

Связи ветвей:
  * 12-й и 18-й узлы каждой ветви требуют первый узел соседней ветви;
  * это не блокирует старт: соседний tier 1 всегда доступен;
  * такие узлы помечены hybrid и стоят на 15% дороже.

Все эффекты используют существующие ключи mods. Новый универсальный
ключ только один — damage_mul для мастерства (читается weapons.py и
attacks.py). Новых классов оружия и снарядов нет.
"""

MAX_BRANCH_NODES = 20

# Цена новой ветви привязана к базовой цене оружия, а не к одной
# константе: иначе «Дуэлянт» за 130 стоил бы как половина пистолетной
# ветви, а новая ветвь пушки — как две старые. Доли задают четыре
# авторских узла; мастерство начинается не ниже последнего из них.
NEW_BRANCH_SEED_FRACTIONS = (1.0, 1.5, 2.2, 2.8)
NEW_BRANCH_MASTERY_FLOOR = 240
NEW_BRANCH_MASTERY_GROWTH = 0.03

# Названия ступеней мастерства. Их много, потому что ветвь длинная;
# префикс ветви в UI отделяет «Закалку» одной ветви от другой.
RANKS = (
    "Закалка", "Калибровка", "Насечка", "Стабилизация", "Усиление",
    "Фокусировка", "Разгон", "Уплотнение", "Точность", "Мощь",
    "Экономия", "Перегрузка", "Резонанс", "Синергия", "Полировка",
    "Автоматика", "Охлаждение", "Импульс", "Совершенство", "Апофеоз",
)

# Шаг эффекта за одну мастерскую ступень. Значения подобраны так, чтобы
# 12–15 ступеней давали заметный, но не абсурдный прирост.
MASTERY_STEPS = {
    "damage_mul": 0.015,
    "shot_damage_mul": 0.025,
    "pierce_add": 1,
    "wall_pen": 1,
    "ricochets": 1,
    "homing": 1,
    "enemy_bounce": 1,
    "explode": 6,
    "cascade": 6,
    "knockback": 25,
    "growth": 0.03,
    "bounce_growth": 0.04,
    "close_bonus": 0.03,
    "alternating_bonus": 0.03,
    "refund_reload": 0.025,
    "refund_kill_chance": 0.025,
    "refund_kill_amount": 1,
    "bleed": 0.02,
    "bleed_spread": 0.02,
    "bleed_spread_radius": 4,
    "explosion_bleed": 0.02,
    "impact_slow": 0.12,
    "impact_slow_radius": 5,
    "explosion_slow": 0.12,
    "explosion_vulnerable": 0.015,
    "full_damage_mul": 0.03,
    "full_radius_mul": 0.02,
    "full_blast_add": 4,
    "full_pierce": 1,
    "blast_radius_add": 4,
    "blast_stun": 0.04,
    "partial_damage_mul": 0.025,
    "partial_radius_mul": 0.02,
    "partial_cooldown_cut": 0.025,
    "charge_speed_add": 0.025,
    "charge_move_bonus": 0.02,
    "still_charge_speed": 0.025,
    "moving_charge_speed": 0.02,
    "steady_bonus": 0.03,
    "aim_mark": 0.03,
    "mark_vulnerable": 0.02,
    "opening_bonus": 0.03,
    "first_strike_bonus": 0.03,
    "dash_strike_bonus": 0.03,
    "moving_bonus": 0.02,
    "kill_heal": 0.4,
    "kill_invuln": 0.025,
    "leech": 0.012,
    "execute": 0.03,
    "execute_threshold": 0.015,
    "splash": 0.03,
    "splash_radius_add": 4,
    "impact_stun": 0.03,
    "close_stun": 0.02,
    "close_stun_range": 5,
    "echo_damage": 0.03,
    "low_hp_bonus": 0.03,
    "low_hp_threshold": 0.01,
    "combo_bonus": 0.005,
    "shield_guard": 0.01,
    "retaliate_damage": 2.5,
    "retaliate_radius": 4,
    "aura_heal": 0.25,
    "pull_radius": 5,
    "pull_force": 10,
    "dust_damage_add": 0.003,
    "dust_slow_add": 0.008,
    "dust_radius_add": 4,
    "stagger": 0.03,
    "double": 0.02,
    "resonance_bonus": 0.025,
    "resonance_radius": 0.02,
    "epicenter_damage": 0.03,
    "shock_slow": 0.08,
    "fissure_slow": 0.03,
    "cascade_shrapnel": 1,
    "scatter_damage_mul": 0.03,
    "lance_pierce_add": 1,
    "lance_wall_pen_add": 1,
    "hammer_radius_add": 3,
    "hammer_stun": 0.03,
    "hammer_stun_range": 10,
    "bleed_add": 0.02,
    # --- новые школы (M16) ---
    "disc_return_damage": 0.03,
    "disc_range_add": 8,
    "disc_recall_speed": 0.02,
    "disc_catch_refund": 0.01,
    "chain_jumps": 1,
    "chain_range_add": 8,
    "chain_damage_mul": 0.03,
    "chain_falloff_add": 0.02,
    "heat_damage_bonus": 0.02,
    "heat_gain_add": 0.02,
    "heat_cool_add": 0.02,
    "vent_blast_add": 1,
    "vent_radius_add": 3,
    "vent_slow": 0.05,
    "vent_self_damage_add": 0.2,
    "vent_time_mul": -0.02,
}

# Эти ключи — переключатели и «события», а не накопительные числа.
# Складывать их на каждой ступени нельзя: выйдет стрельба раз в 30
# выстрелов или вечный разлом.
NON_SCALING = {
    "full_only", "partial_unlock", "mode_switch", "rapid",
    "variable_handle", "fissure", "volley_every", "volley_count",
    "quake_rings", "alternating_cooldown_mul", "impact_slow_factor",
    "scatter_spread_add", "reload_time_mul", "magazine_add",
    "ammo_cost_add", "charge_time_mul", "spread_deg_mul",
    # Переходы дуги и затухание — событие, а не «+1 каждый tier»:
    # иначе мастерство превратило бы цепь в бесконечную молнию.
    "chain_jumps", "chain_falloff_add", "vent_time_mul",
}

PERCENT_MODS = {
    "damage_mul", "shot_damage_mul", "growth", "bounce_growth",
    "close_bonus", "alternating_bonus", "refund_reload",
    "refund_kill_chance", "bleed",
    "bleed_spread", "explosion_bleed", "explosion_vulnerable",
    "full_damage_mul", "full_radius_mul", "partial_damage_mul",
    "partial_radius_mul", "partial_cooldown_cut", "charge_speed_add",
    "charge_move_bonus", "still_charge_speed", "moving_charge_speed",
    "steady_bonus", "aim_mark", "mark_vulnerable", "opening_bonus",
    "first_strike_bonus", "dash_strike_bonus", "moving_bonus", "leech",
    "execute", "execute_threshold", "splash", "echo_damage",
    "low_hp_bonus", "low_hp_threshold", "combo_bonus", "shield_guard",
    "dust_damage_add", "dust_slow_add", "stagger", "double",
    "resonance_bonus", "resonance_radius", "epicenter_damage",
    "fissure_slow", "scatter_damage_mul", "bleed_add",
    "disc_return_damage", "disc_recall_speed", "disc_catch_refund",
    "chain_damage_mul", "heat_damage_bonus", "heat_gain_add",
    "heat_cool_add", "vent_time_mul", "vent_slow",
}

TIME_MODS = {
    "impact_slow", "explosion_slow", "impact_stun", "close_stun",
    "kill_invuln", "blast_stun", "hammer_stun",
}

EFFECT_LABELS = {
    "damage_mul": "урон", "shot_damage_mul": "урон выстрела",
    "pierce_add": "пробитие", "wall_pen": "сквозь стены",
    "ricochets": "рикошет", "homing": "наведение",
    "enemy_bounce": "рикошет от врага", "explode": "взрыв",
    "cascade": "каскад", "knockback": "отбрасывание",
    "growth": "рост урона", "bounce_growth": "рост на рикошете",
    "close_bonus": "урон в упор",
    "alternating_bonus": "тяжёлый выстрел",
    "refund_reload": "возврат перезарядки",
    "refund_kill_chance": "возврат за убийство",
    "refund_kill_amount": "патроны за убийство", "bleed": "кровотечение",
    "bleed_spread": "разнос крови", "bleed_spread_radius": "радиус крови",
    "explosion_bleed": "кровь от взрыва", "impact_slow": "замедление",
    "impact_slow_radius": "радиус замедления",
    "explosion_slow": "замедление взрывом",
    "explosion_vulnerable": "уязвимость от взрыва",
    "full_damage_mul": "урон полного заряда",
    "full_radius_mul": "хитбокс полного заряда",
    "full_blast_add": "взрыв полного заряда", "full_pierce": "пробитие заряда",
    "blast_radius_add": "радиус взрыва", "blast_stun": "оглушение взрыва",
    "partial_damage_mul": "урон недозаряда",
    "partial_radius_mul": "хитбокс недозаряда",
    "partial_cooldown_cut": "откат недозаряда",
    "charge_speed_add": "скорость заряда",
    "charge_move_bonus": "скорость при заряде",
    "still_charge_speed": "заряд на месте",
    "moving_charge_speed": "заряд на ходу", "steady_bonus": "стоя на месте",
    "aim_mark": "метка", "mark_vulnerable": "уязвимость метки",
    "opening_bonus": "удар в замах", "first_strike_bonus": "первый удар",
    "dash_strike_bonus": "удар после рывка", "moving_bonus": "удар на ходу",
    "kill_heal": "лечение за убийство", "kill_invuln": "неуязвимость за убийство",
    "leech": "вампиризм", "execute": "казнь",
    "execute_threshold": "порог казни", "splash": "урон по площади",
    "splash_radius_add": "радиус площади", "impact_stun": "оглушение",
    "close_stun": "оглушение в упор", "close_stun_range": "радиус оглушения",
    "echo_damage": "эхо-удар", "low_hp_bonus": "урон при низком HP",
    "low_hp_threshold": "порог низкого HP", "combo_bonus": "рост серии",
    "shield_guard": "защита щитом", "retaliate_damage": "ответный удар",
    "retaliate_radius": "радиус ответа", "aura_heal": "лечение ауры",
    "pull_radius": "радиус притяжения", "pull_force": "сила притяжения",
    "dust_damage_add": "урон пыли", "dust_slow_add": "замедление пылью",
    "dust_radius_add": "радиус пыли", "stagger": "отбрасывание",
    "double": "двойной удар", "resonance_bonus": "резонанс",
    "resonance_radius": "радиус резонанса", "epicenter_damage": "эпицентр",
    "shock_slow": "замедление волной", "fissure_slow": "замедление разломом",
    "cascade_shrapnel": "осколки", "scatter_damage_mul": "урон картечи",
    "lance_pierce_add": "пробитие копья",
    "lance_wall_pen_add": "стены копья",
    "hammer_radius_add": "радиус молота", "hammer_stun": "оглушение молота",
    "hammer_stun_range": "дальность оглушения", "bleed_add": "кровотечение надреза",
    "disc_return_damage": "урон на возврате",
    "disc_range_add": "дальность диска",
    "disc_recall_speed": "скорость подзыва",
    "disc_catch_refund": "патрон за поимку",
    "chain_jumps": "переходы дуги", "chain_range_add": "дальность дуги",
    "chain_damage_mul": "урон цепи",
    "chain_falloff_add": "затухание цепи",
    "heat_damage_bonus": "урон от нагрева", "heat_gain_add": "нагрев",
    "heat_cool_add": "остывание", "vent_blast_add": "урон сброса",
    "vent_radius_add": "радиус сброса", "vent_slow": "замедление сброса",
    "vent_self_damage_add": "урон сброса герою",
    "vent_time_mul": "длительность сброса",
}


def _fmt_effect(key, value):
    if key in PERCENT_MODS:
        return f"{value:+.0%}"
    if key in TIME_MODS:
        return f"{value:+.2f}с"
    if key in ("refund_kill_amount", "cascade_shrapnel", "pierce_add",
               "wall_pen", "ricochets", "homing", "enemy_bounce",
               "full_pierce", "lance_pierce_add", "lance_wall_pen_add"):
        return f"{int(round(value)):+d}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):+d}"
    return f"{value:+g}"


def _effect_desc(mods):
    parts = []
    for key, value in mods.items():
        if key in ("damage_mul",) and value == 0.0:
            continue
        parts.append(f"{EFFECT_LABELS.get(key, key)} {_fmt_effect(key, value)}")
    return ", ".join(parts[:2])


def _recipe(skill_trees, weapon_key, branch):
    """(signature, secondary) из уже существующих mods ветви."""
    keys = []
    for node in branch["nodes"]:
        for key in node.get("mods", {}):
            if (key in MASTERY_STEPS and key not in NON_SCALING
                    and key not in keys):
                keys.append(key)
    if len(keys) >= 2:
        return keys[0], keys[1]
    if weapon_key in ("pistol", "shotgun", "sniper", "cannon"):
        fallback = ("shot_damage_mul", "damage_mul")
    else:
        fallback = ("damage_mul", "execute")
    if keys:
        return keys[0], (fallback[1] if keys[0] != fallback[1] else fallback[0])
    return fallback


def _mastery_mods(signature, secondary, ordinal):
    mods = {"damage_mul": MASTERY_STEPS["damage_mul"]}
    if ordinal % 2 == 1:
        mods[signature] = mods.get(signature, 0.0) + MASTERY_STEPS[signature]
    if ordinal % 3 == 0:
        mods[secondary] = mods.get(secondary, 0.0) + MASTERY_STEPS[secondary]
    return mods


def _mastery_cost(base, tier, growth=0.22):
    return int(round(base * (1.0 + growth * max(0, tier - 5))))


def _branch_entry(branch):
    """Первый узел ветви, доступный без подготовки и без requires."""
    for node in branch["nodes"]:
        if node["tier"] == 1 and not node.get("requires") and not node.get("training"):
            return node
    return branch["nodes"][0]


def _append_mastery(weapon_key, branch):
    nodes = list(branch["nodes"])
    if len(nodes) >= MAX_BRANCH_NODES:
        return branch
    needed = MAX_BRANCH_NODES - len(nodes)
    max_tier = max(int(node["tier"]) for node in nodes)
    # Единственный финальный узел (метла/арсенал) — естественный вход.
    last = [node for node in nodes if int(node["tier"]) == max_tier]
    tier4 = [node for node in nodes if int(node["tier"]) == 4]
    if len(last) == 1 and max_tier <= 5:
        anchor = last[0]
    elif tier4:
        anchor = tier4[0]
    else:
        anchor = nodes[0]
    signature, secondary = _recipe(None, weapon_key, branch)
    base = min(int(node["cost"]) for node in nodes if int(node["tier"]) == 1)
    first = True
    for ordinal in range(1, needed + 1):
        tier = max_tier + ordinal
        mods = _mastery_mods(signature, secondary, ordinal)
        node_id = f"{weapon_key}_{branch['key']}_m{tier}"
        desc = f"мастерство ветви: {_effect_desc(mods)}"
        node = {
            "id": node_id,
            "name": f"{branch['name']}: {RANKS[(ordinal - 1) % len(RANKS)]}",
            "tier": tier,
            "cost": _mastery_cost(base, tier),
            "desc": desc,
            "mods": mods,
            "lane": 0.25 if ordinal % 2 else -0.25,
            "role": "МАСТЕРСТВО",
        }
        # Первый мастерский узел не должен требовать доктрину tier 5:
        # иначе вторая альтернатива останется без продолжения.
        if first:
            node["requires"] = (anchor["id"],)
            first = False
        nodes.append(node)
    branch = dict(branch)
    branch["nodes"] = tuple(nodes)
    return branch


# --------------------------------------------------------------- НОВЫЕ ВЕТВИ
# Четыре «семени» задают характер ветви; дальше 16 ступеней мастерства
# автоматически усиливают её подпись. Это не случайные проценты: каждая
# ветвь — отдельная стратегия, а не клон уже существующей.
NEW_BRANCHES = {
    "pistol": (
        {
            "key": "duelist", "name": "Дуэлянт",
            "signature": ("alternating_bonus", 0.03),
            "secondary": ("steady_bonus", 0.03),
            "seeds": (
                ("Стойка дуэлянта", "стоя на месте урон +12%",
                 {"steady_bonus": 0.12}),
                ("Первый ход", "тяжёлый выстрел в очереди +18%",
                 {"alternating_bonus": 0.18}),
                ("Прицельная пауза", "метка цели +15%",
                 {"aim_mark": 0.15}),
                ("Выстрел в упор", "в ближнем бою +18%",
                 {"close_bonus": 0.18}),
            ),
        },
    ),
    "disc": (
        {
            "key": "satellite", "name": "Спутник",
            "signature": ("disc_return_damage", 0.03),
            "secondary": ("disc_range_add", 8),
            "seeds": (
                ("Парный диск", "урон на возврате +12%",
                 {"disc_return_damage": 0.12}),
                ("Дальняя орбита", "дальность диска +25",
                 {"disc_range_add": 25}),
                ("Метка спутника", "метка цели +12%",
                 {"aim_mark": 0.12}),
                ("Возврат в руку", "10% шанс вернуть патрон при поимке",
                 {"disc_catch_refund": 0.10}),
            ),
        },
    ),
    "arc": (
        {
            "key": "conduit", "name": "Проводник",
            "signature": ("chain_range_add", 8),
            "secondary": ("chain_damage_mul", 0.03),
            "seeds": (
                ("Дальний разряд", "дальность перехода +20",
                 {"chain_range_add": 20}),
                ("Усиленный мост", "урон цепи +10%",
                 {"chain_damage_mul": 0.10}),
                ("Ионная метка", "помеченная цель уязвима на 5%",
                 {"mark_vulnerable": 0.05}),
                ("Экономия дуги", "10% патрона за убийство",
                 {"refund_kill_chance": 0.10}),
            ),
        },
    ),
    "cutter": (
        {
            "key": "impulse", "name": "Импульс",
            "signature": ("heat_damage_bonus", 0.02),
            "secondary": ("shot_damage_mul", 0.025),
            "seeds": (
                ("Быстрый нагрев", "нагрев +8% — пик раньше",
                 {"heat_gain_add": 0.08}),
                ("Термостойкость", "сброс ранит героя на 2 меньше",
                 {"vent_self_damage_add": -2.0}),
                ("Отвод тепла", "остывание +10%",
                 {"heat_cool_add": 0.10}),
                ("Плазменная кромка", "урон выстрела +8%",
                 {"shot_damage_mul": 0.08}),
            ),
        },
    ),
    "cannon": (
        {
            "key": "siege", "name": "Осадный контур",
            "signature": ("full_blast_add", 3),
            "secondary": ("impact_slow", 0.10),
            "seeds": (
                ("Тяжёлый снаряд", "отбрасывание +60",
                 {"knockback": 60}),
                ("Сейсмический заряд", "радиус взрыва +6",
                 {"blast_radius_add": 6}),
                ("Шоковый импульс", "взрыв оглушает 0.08 с",
                 {"blast_stun": 0.08}),
                ("Разрыв брони", "уязвимость от взрыва +4%",
                 {"explosion_vulnerable": 0.04}),
            ),
        },
    ),
    "sniper": (
        {
            "key": "bombard", "name": "Осада",
            "signature": ("pierce_add", 1),
            "secondary": ("shot_damage_mul", 0.02),
            "seeds": (
                ("Разрывной сердечник", "попадание даёт взрыв r=12",
                 {"explode": 12}),
                ("Бронебойная насечка", "пуля пробивает ещё 1 блок стены",
                 {"wall_pen": 1}),
                ("Тяжёлый удар", "замедляет цель на 0.3 с",
                 {"impact_slow": 0.3, "impact_slow_radius": 20}),
                ("Цепной разрыв", "убийство даёт вторичный взрыв r=8",
                 {"cascade": 8}),
            ),
        },
        {
            "key": "hunter", "name": "Охотник",
            "signature": ("mark_vulnerable", 0.02),
            "secondary": ("steady_bonus", 0.03),
            "seeds": (
                ("Метка зверя", "метка цели +15%",
                 {"aim_mark": 0.15}),
                ("Уязвимый след", "помеченная цель получает +5%",
                 {"mark_vulnerable": 0.05}),
                ("Твёрдая стойка", "стоя на месте урон +10%",
                 {"steady_bonus": 0.10}),
                ("Добивание", "пробитая цель уязвима +6%",
                 {"pierce_vulnerable": 0.06}),
            ),
        },
    ),
    "shotgun": (
        {
            "key": "dragon", "name": "Дракон",
            "signature": ("explosion_bleed", 0.02),
            "secondary": ("bleed", 0.02),
            "seeds": (
                ("Поджиг", "взрыв вызывает кровотечение 12%",
                 {"explosion_bleed": 0.12}),
                ("Кровавый веер", "дробины кровоточат 5%",
                 {"bleed": 0.05}),
                ("Пламенный след", "взрыв замедляет на 0.3 с",
                 {"explosion_slow": 0.3}),
                ("Разнос огня", "смерть разносит кровь r=12",
                 {"bleed_spread": 0.10, "bleed_spread_radius": 12}),
            ),
        },
        {
            "key": "bulwark", "name": "Бастион",
            "signature": ("knockback", 15),
            "secondary": ("close_bonus", 0.025),
            "seeds": (
                ("Толчок", "отбрасывание +50",
                 {"knockback": 50}),
                ("Оглушающий залп", "в упор оглушает 0.06 с",
                 {"close_stun": 0.06, "close_stun_range": 240}),
                ("Плотный контакт", "в упор урон +10%",
                 {"close_bonus": 0.10}),
                ("Замедление", "попадание замедляет на 0.4 с",
                 {"impact_slow": 0.4, "impact_slow_radius": 15}),
            ),
        },
    ),
    "knife": (
        {
            "key": "shadow", "name": "Тень",
            "signature": ("dash_strike_bonus", 0.03),
            "secondary": ("first_strike_bonus", 0.03),
            "seeds": (
                ("Удар из-под руки", "первый удар +12%",
                 {"first_strike_bonus": 0.12}),
                ("Рывок в спину", "удар после рывка +12%",
                 {"dash_strike_bonus": 0.12}),
                ("Уход в тень", "убийство даёт 0.06 с неуязвимости",
                 {"kill_invuln": 0.06}),
                ("Скользящий шаг", "удар на ходу +8%",
                 {"moving_bonus": 0.08}),
            ),
        },
        {
            "key": "venom", "name": "Яд",
            "signature": ("bleed", 0.02),
            "secondary": ("leech", 0.012),
            "seeds": (
                ("Отравленный клинок", "кровотечение 6%",
                 {"bleed": 0.06}),
                ("Заражение", "смерть разносит кровь r=10",
                 {"bleed_spread": 0.10, "bleed_spread_radius": 10}),
                ("Кровопийца", "вампиризм 2.5%",
                 {"leech": 0.025}),
                ("Жажда", "удар по раненому лечит +0.5 HP",
                 {"bleed_heal": 0.5}),
            ),
        },
    ),
    "machete": (
        {
            "key": "whirlwind", "name": "Вихрь",
            "signature": ("combo_bonus", 0.006),
            "secondary": ("double", 0.02),
            "seeds": (
                ("Разгон", "серия даёт +1% урона, предел +2",
                 {"combo_bonus": 0.01, "combo_max": 2}),
                ("Двойной разрез", "шанс повторного удара 6%",
                 {"double": 0.06}),
                ("Широкий круг", "урон по площади 6%, радиус +4",
                 {"splash": 0.06, "splash_radius_add": 4}),
                ("Инерция", "отбрасывание +5%",
                 {"stagger": 0.05}),
            ),
        },
        {
            "key": "butcher", "name": "Мясник",
            "signature": ("execute", 0.03),
            "secondary": ("bleed", 0.02),
            "seeds": (
                ("Глубокая рана", "кровотечение 6%",
                 {"bleed": 0.06}),
                ("Порог казни", "порог казни +3%",
                 {"execute_threshold": 0.03}),
                ("Казнь", "урон по раненым +8%",
                 {"execute": 0.08}),
                ("Сытость", "убийство лечит +0.5 HP",
                 {"kill_heal": 0.5}),
            ),
        },
    ),
    "katana": (
        {
            "key": "iaido", "name": "Иайдо",
            "signature": ("first_strike_bonus", 0.03),
            "secondary": ("echo_damage", 0.02),
            "seeds": (
                ("Первый выхват", "первый удар +15%",
                 {"first_strike_bonus": 0.15}),
                ("Мгновенный шаг", "удар после рывка +12%",
                 {"dash_strike_bonus": 0.12}),
                ("Эхо клинка", "эхо-удар 8%",
                 {"echo_damage": 0.08}),
                ("Двойной разрез", "шанс повторного удара 8%",
                 {"double": 0.08}),
            ),
        },
        {
            "key": "samurai", "name": "Самурай",
            "signature": ("low_hp_bonus", 0.03),
            "secondary": ("leech", 0.012),
            "seeds": (
                ("Дух воина", "при низком HP урон +12%, порог +3%",
                 {"low_hp_bonus": 0.12, "low_hp_threshold": 0.03}),
                ("Стальная стойка", "стоя на месте урон +8%",
                 {"steady_bonus": 0.08}),
                ("Последний вздох", "убийство лечит +0.5 HP",
                 {"kill_heal": 0.5}),
                ("Рассечение", "удар оглушает 0.05 с",
                 {"impact_stun": 0.05}),
            ),
        },
    ),
    "hammer": (
        {
            "key": "resonance", "name": "Резонанс",
            "signature": ("resonance_bonus", 0.025),
            "secondary": ("epicenter_damage", 0.03),
            "seeds": (
                ("Отклик", "повторный удар +8%",
                 {"resonance_bonus": 0.08}),
                ("Широкий резонанс", "радиус резонанса +5%",
                 {"resonance_radius": 0.05}),
                ("Эпицентр", "урон в центре +12%",
                 {"epicenter_damage": 0.12}),
                ("Повторный удар", "каждый удар даёт лишнюю волну",
                 {"quake_rings": 1}),
            ),
        },
        {
            "key": "control", "name": "Контроль",
            "signature": ("shock_slow", 0.08),
            "secondary": ("impact_stun", 0.025),
            "seeds": (
                ("Вязкая волна", "замедление волной 0.3 с",
                 {"shock_slow": 0.3}),
                ("Оглушение", "удар оглушает 0.06 с",
                 {"impact_stun": 0.06}),
                ("Притяжение", "удар притягивает врагов r=15",
                 {"pull_radius": 15, "pull_force": 15}),
                ("Разлом", "удар оставляет замедляющий разлом",
                 {"fissure": 1, "fissure_slow": 0.3}),
            ),
        },
    ),
    "shovel": (
        {
            "key": "gardener", "name": "Садовник",
            "signature": ("dust_damage_add", 0.003),
            "secondary": ("leech", 0.012),
            "seeds": (
                ("Питательная пыль", "урон пыли +0.4%, замедление +1%",
                 {"dust_damage_add": 0.004, "dust_slow_add": 0.01}),
                ("Широкий след", "радиус пыли +8",
                 {"dust_radius_add": 8}),
                ("Сбор урожая", "вампиризм 2%",
                 {"leech": 0.02}),
                ("Полевая медицина", "убийство лечит +0.5 HP",
                 {"kill_heal": 0.5}),
            ),
        },
    ),
    "shield": (
        {
            "key": "bastion", "name": "Бастион",
            "signature": ("shield_guard", 0.012),
            "secondary": ("retaliate_damage", 2),
            "seeds": (
                ("Крепкая стойка", "получаемый урон -3%",
                 {"shield_guard": 0.03}),
                ("Шипы", "ответный удар +8",
                 {"retaliate_damage": 8}),
                ("Ответный круг", "радиус ответа +8",
                 {"retaliate_radius": 8}),
                ("Тяжёлый контакт", "отбрасывание +6%",
                 {"stagger": 0.06}),
            ),
        },
        {
            "key": "pulse", "name": "Пульс",
            "signature": ("aura_heal", 0.2),
            "secondary": ("leech", 0.012),
            "seeds": (
                ("Лечебная аура", "аура лечит +0.5 HP",
                 {"aura_heal": 0.5}),
                ("Живой контакт", "вампиризм 2%",
                 {"leech": 0.02}),
                ("Замедляющий контакт", "контакт замедляет на 0.3 с",
                 {"impact_slow": 0.3}),
                ("Волна", "урон по площади 5%",
                 {"splash": 0.05}),
            ),
        },
    ),
}


def _new_branch(weapon_key, spec, base_cost):
    """Новая ветвь: четыре авторских узла + 16 мастерских.

    Цены растут от базовой стоимости оружия. Полная ветвь выходит
    примерно на уровне старых 20-узловых цепочек, а не в 2–4 раза
    дороже: мастерство должно быть доступной целью забега.
    """
    base_cost = max(1, int(base_cost))
    seed_costs = tuple(round(base_cost * fraction)
                       for fraction in NEW_BRANCH_SEED_FRACTIONS)
    seeds = spec["seeds"]
    nodes = []
    for tier, (name, desc, mods) in enumerate(seeds, 1):
        nodes.append({
            "id": f"{weapon_key}_{spec['key']}_{tier}",
            "name": name,
            "tier": tier,
            "cost": seed_costs[tier - 1],
            "desc": desc,
            "mods": dict(mods),
            "role": "ОСНОВА" if tier == 1 else "РАЗВИТИЕ",
        })
    signature = spec["signature"][0]
    secondary = spec["secondary"][0]
    mastery_base = max(NEW_BRANCH_MASTERY_FLOOR, seed_costs[-1])
    for tier in range(5, MAX_BRANCH_NODES + 1):
        ordinal = tier - 4
        mods = _mastery_mods(signature, secondary, ordinal)
        node = {
            "id": f"{weapon_key}_{spec['key']}_{tier}",
            "name": f"{spec['name']}: {RANKS[(tier - 5) % len(RANKS)]}",
            "tier": tier,
            "cost": _mastery_cost(mastery_base, tier,
                                  NEW_BRANCH_MASTERY_GROWTH),
            "desc": f"мастерство ветви: {_effect_desc(mods)}",
            "mods": mods,
            "lane": 0.25 if ordinal % 2 else -0.25,
            "role": "МАСТЕРСТВО",
        }
        nodes.append(node)
    return {"key": spec["key"], "name": spec["name"], "nodes": tuple(nodes)}


def _add_cross_links(weapon_key, branches):
    """12-й и 18-й узлы требуют первый узел соседней ветви."""
    if len(branches) < 2:
        return
    entries = [_branch_entry(branch) for branch in branches]
    for bi, branch in enumerate(branches):
        nodes = list(branch["nodes"])
        if len(nodes) < MAX_BRANCH_NODES:
            continue
        # «Пыльный след» намеренно независим от специализации метлы:
        # не превращаем его в заложника чужой ветви.
        if branch.get("independent"):
            continue
        # Ищем доступный вход соседней ветви. Нельзя связывать ветвь
        # с узлом, который она сама исключает (например, «Овердрайв»
        # требует «Полный импульс», а тот закрывает «Аварийный разряд»).
        branch_ids = {node["id"] for node in nodes}
        branch_excludes = set()
        for node in nodes:
            branch_excludes.update(node.get("excludes", ()))

        def compatible(candidate):
            if candidate.get("training"):
                return False
            if candidate["id"] in branch_excludes:
                return False
            if any(req in branch_ids for req in candidate.get("excludes", ())):
                return False
            return True

        linked = None
        if len(branches) > 1:
            for step in range(1, len(branches)):
                candidate = entries[(bi + step) % len(branches)]
                if compatible(candidate):
                    linked = candidate
                    break
        if linked is None:
            linked = entries[(bi + 1) % len(branches)]
        for index in (11, 17):
            node = nodes[index]
            previous = nodes[index - 1]
            node["requires"] = (previous["id"], linked["id"])
            node["hybrid"] = True
            node["desc"] = (
                f"{node['desc']} · связка с «{linked['name']}»"
            )
        branch = dict(branch)
        branch["nodes"] = tuple(nodes)
        branches[bi] = branch


def inject_expanded_trees(skill_trees):
    """Расширяет все древа до 5–6 ветвей и 20 узлов в каждой.

    Идемпотентен: повторный вызов видит готовые цепочки и ничего не
    дублирует. Сначала добавляются новые ветви, затем все ветви (включая
    новые) получают мастерство и межветвевые связи.
    """
    for weapon_key, specs in NEW_BRANCHES.items():
        tree = skill_trees.get(weapon_key)
        if tree is None:
            continue
        branches = list(tree["branches"])
        existing_keys = {branch["key"] for branch in branches}
        existing_bases = [min(int(node["cost"]) for node in branch["nodes"]
                              if int(node["tier"]) == 1)
                          for branch in branches
                          if any(int(node["tier"]) == 1
                                 for node in branch["nodes"])]
        base_cost = min(existing_bases) if existing_bases else 130
        for spec in specs:
            if spec["key"] in existing_keys:
                continue
            branches.append(_new_branch(weapon_key, spec, base_cost))
        tree["branches"] = tuple(branches)

    for weapon_key, tree in skill_trees.items():
        branches = []
        for branch in tree["branches"]:
            if len(branch["nodes"]) < MAX_BRANCH_NODES:
                branch = _append_mastery(weapon_key, branch)
            branches.append(branch)
        _add_cross_links(weapon_key, branches)
        tree["branches"] = tuple(branches)
    return skill_trees
