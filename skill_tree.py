"""
Ветви развития оружия и героя — ПРАВИЛА (M11/M12).

Три подхода к ограничениям (A: жёсткая специализация, B: мягкая,
C: гибрид) сводятся здесь к трём функциям-проверкам:

  1. ПОРЯДОК:  узел N покупается после своих requires. Для старых узлов
               это tier N-1 своей ветви; у поздних доктрин могут быть
               ещё и соседние навыки из другой ветви.
  2. ЦЕНА:     tier 1 любой ветви — базовая; tier 2+ в ОСНОВНОЙ ветви —
               базовая, в остальных — xOTHER_BRANCH_COST_MUL (вариант B:
               «первое улучшение другой ветви доступно, дальше дорого»).
               Гибридный узел с чужим requires дороже на HYBRID_COST_MUL.
  3. ГЛУБИНА:  tier 3+ вне основной ветви открывается по глубине
               основной (tier 3 после tier 3, tier 5 после tier 5).
               Tier 4+ дополнительно стоит жетоны школы: вторая ветвь
               становится доступной позже, но не остаётся навсегда
               заблокированной.
  4. ВЫБОР:    tier 5 каждой ветви — две доктрины. Купив одну, игрок
               навсегда закрывает вторую (excludes), поэтому финал
               ветви — это стиль, а не ещё одна строка бонусов.

Основная ветвь фиксируется первым настоящим навыком — выбор имеет вес,
но tier 1 любой ветви всегда по базовой цене. Узлы-входы (no_main,
например «Полевой устав» пистолета) специализацию не фиксируют.

Данные узлов — skill_data.py / skill_capstones.py / skill_pistol.py;
применение модификаторов — здесь же.
"""
from skill_data import PLAYER_TREE, SKILL_TREES
from settings import (CROSS_BRANCH_DEPTHS, CROSS_BRANCH_MAX_TOKENS,
                      CROSS_BRANCH_TOKEN_COSTS, HYBRID_COST_MUL,
                      OTHER_BRANCH_COST_MUL)
from weapon_data import (FIREARMS, MELEE, PISTOL_MODES,
                         TOKEN_SUBSTITUTES)


# Имена школ для условий «подготовка другого оружия». Один узел чужого
# древа или жетон тренировки считаются одним уровнем подготовки.
_WEAPON_NAMES = {key: spec["name"] for key, spec in {**FIREARMS, **MELEE}.items()}


def training_level(player, weapon_key):
    """Сколько подготовки накоплено по школе оружия (0 — не открыта)."""
    if player is None:
        return 0
    return int(getattr(player, "weapon_training", {}).get(weapon_key, 0))


def token_keys_for(weapon_key):
    """Жетоны каких школ принимаются вместо подготовки этой школы."""
    return TOKEN_SUBSTITUTES.get(weapon_key, (weapon_key,))


def token_count(player, weapon_key):
    """Суммарное число подходящих жетонов (свои + родственные)."""
    if player is None:
        return 0
    tokens = getattr(player, "weapon_tokens", {})
    return sum(int(tokens.get(key, 0)) for key in token_keys_for(weapon_key))


def _spend_tokens(player, weapon_key, amount):
    """Списывает жетоны, начиная с точной школы, затем родственные."""
    if player is None:
        return False
    remaining = max(0, int(amount))
    for key in token_keys_for(weapon_key):
        if remaining <= 0:
            break
        have = int(player.weapon_tokens.get(key, 0))
        take = min(have, remaining)
        if take:
            player.weapon_tokens[key] = have - take
            remaining -= take
    return remaining == 0


def training_requirement(node):
    """(школа, уровень) или None — читает необязательное поле training."""
    requirement = node.get("training")
    if not requirement:
        return None
    weapon_key, level = requirement
    return weapon_key, int(level)


def training_name(weapon_key):
    return _WEAPON_NAMES.get(weapon_key, weapon_key)


def missing_training(player, node):
    """Недостающая подготовка: (школа, нужно, есть, жетонов у игрока)."""
    requirement = training_requirement(node)
    if requirement is None:
        return []
    weapon_key, needed = requirement
    have = training_level(player, weapon_key)
    if have >= needed:
        return []
    tokens = token_count(player, weapon_key)
    return [(weapon_key, needed, have, tokens)]


def can_cover_training(player, node):
    """Хватит ли жетонов, чтобы закрыть все недостающие условия."""
    missing = missing_training(player, node)
    if not missing:
        return True
    if player is None:
        return False
    return all(tokens >= needed - have
               for _, needed, have, tokens in missing)


def _pay_training(player, node):
    """Списывает жетоны и превращает их в уровни подготовки."""
    missing = missing_training(player, node)
    if not missing or not can_cover_training(player, node):
        return False
    for weapon_key, needed, have, _ in missing:
        spend = needed - have
        if not _spend_tokens(player, weapon_key, spend):
            return False
        player.add_weapon_training(weapon_key, spend)
    return True


def tree_of(weapon):
    """Дерево оружия или None (для ключа без древа)."""
    return SKILL_TREES.get(weapon.key)


# ------------------------------------------------------------ ДРЕВО ГЕРОЯ
def player_branches():
    """Ветви общего древа героя (одна доска с оружейными древами)."""
    return PLAYER_TREE["branches"]


def find_player_node(node_id):
    """(ветвь, узел) общего древа по id — или (None, None)."""
    for branch in player_branches():
        for node in branch["nodes"]:
            if node["id"] == node_id:
                return branch, node
    return None, None


def player_node_state(player, branch, node):
    """
    Состояние узла героя. У общего древа нет «основной ветви»: любая
    ветвь развивается до конца, но только по цепочке tier 1 → tier 5.
    """
    if node["id"] in player.skill_nodes:
        return "owned"
    if any(req not in player.skill_nodes for req in prerequisites(branch, node)):
        return "prev"
    return "ok"


def player_node_price(player, branch, node):
    """Цена узла героя: без наценки «чужой ветви», это общая прокачка."""
    return node["cost"]


def buy_player_node(player, branch, node, paid):
    """
    Покупка узла героя. Эффекты складываются в player.skill_mods:
      * *_mul — перемножаются (например, −6% и −12% урона);
      * остальные — складываются (регенерация, бонусы урона и т.п.);
      * hp_add сразу увеличивает максимум и текущее здоровье.
    """
    if player_node_state(player, branch, node) != "ok":
        raise ValueError(f"Узел героя {node['id']!r} нельзя купить сейчас")
    player.skill_nodes.add(node["id"])
    for key, value in node.get("mods", {}).items():
        if key.endswith("_mul"):
            player.skill_mods[key] = player.skill_mods.get(key, 1.0) * value
        else:
            player.skill_mods[key] = player.skill_mods.get(key, 0.0) + value
        if key == "hp_add":
            player.max_hp += value
            player.hp += value
    player.refresh_speed()
    return paid


def branches_of(weapon):
    tree = tree_of(weapon)
    return tree["branches"] if tree else ()


def find_node(weapon, node_id):
    """(ветвь, узел) по id — или (None, None)."""
    for branch in branches_of(weapon):
        for node in branch["nodes"]:
            if node["id"] == node_id:
                return branch, node
    return None, None


def branch_depth(weapon, branch):
    """Самый глубокий купленный tier этой ветви (0 — ничего не куплено)."""
    return max((int(node["tier"]) for node in branch["nodes"]
                if node["id"] in weapon.nodes), default=0)


def main_branch_depth(weapon):
    """Глубина основной ветви — ключ к мастерству остальных ветвей."""
    if weapon.main_branch is None:
        return 0
    for branch in branches_of(weapon):
        if branch["key"] == weapon.main_branch:
            return branch_depth(weapon, branch)
    return 0


def cross_branch_requirement(weapon, branch, node):
    """
    (нужная глубина, текущая глубина) для tier 3+ вне основной ветви.

    Это и есть «позднее открытие»: чтобы нырнуть в чужую ветвь, основная
    должна быть не мельче того же tier. Tier 3 открывается после tier 3
    основы, tier 5 — после tier 5, и так далее. Независимые ветви
    (например, пыль метлы) не подчиняются этому правилу.
    """
    if (node["tier"] < 3 or branch.get("independent", False)
            or weapon.main_branch in (None, branch["key"])):
        return None
    # Глубина требуется только до tier 6. Дальше ветви растут
    # мастерством, а не «ещё одним уровнем допуска»: иначе короткая
    # ветвь-основа делала бы длинную чужую ветвь недостижимой.
    needed = CROSS_BRANCH_DEPTHS.get(node["tier"], 6)
    current = main_branch_depth(weapon)
    if current < needed:
        return needed, current
    return None


def cross_branch_toll(weapon, branch, node):
    """
    Сколько жетонов стоит углубление второй ветви (0 — не требуется).

    Tier 3 открывается бесплатно после tier 3 основы; tier 4/5/6 требуют
    жетоны. Это ограничивает «собрать все ветви сразу» и даёт жетонам
    применение за пределами подготовки чужой школы.
    """
    if (weapon.main_branch in (None, branch["key"])
            or branch.get("independent", False)
            or cross_branch_requirement(weapon, branch, node) is not None):
        return 0
    return int(CROSS_BRANCH_TOKEN_COSTS.get(
        node["tier"], min(CROSS_BRANCH_MAX_TOKENS,
                           max(0, int(node["tier"]) - 3))))


def can_pay_cross_toll(player, weapon, branch, node):
    toll = cross_branch_toll(weapon, branch, node)
    return toll <= 0 or token_count(player, weapon.key) >= toll


def _pay_cross_toll(player, weapon, branch, node):
    toll = cross_branch_toll(weapon, branch, node)
    if toll <= 0:
        return True
    return _spend_tokens(player, weapon.key, toll)


def node_state(weapon, branch, node, player=None):
    """
    Состояние узла для UI и покупки:
      "owned"    — уже куплен;
      "excluded" — выбрана другая доктрина этой пары;
      "prev"     — не куплены обязательные соседние навыки;
      "depth"    — глубина второй ветви ещё не открыта основной;
      "training" — нужна подготовка другой школы (жетон закроет);
      "tokens"   — нужен жетон школы для tier 4+ второй ветви;
      "ok"       — можно купить.

    Независимые ветви могут проходить все уровни, не становясь основной.
    """
    if node["id"] in weapon.nodes:
        return "owned"
    if any(other in weapon.nodes for other in node.get("excludes", ())):
        return "excluded"
    if any(req not in weapon.nodes for req in prerequisites(branch, node)):
        return "prev"
    if cross_branch_requirement(weapon, branch, node) is not None:
        return "depth"
    if missing_training(player, node):
        return "training"
    if cross_branch_toll(weapon, branch, node) > 0:
        return "tokens"
    return "ok"


def node_price(weapon, branch, node):
    """Цена узла: tier 1 и основная ветвь — база, иначе x1.75."""
    base = node["cost"]
    if node.get("hybrid"):
        base = round(base * HYBRID_COST_MUL)
    if node["tier"] == 1:
        return base
    if weapon.main_branch in (None, branch["key"]):
        return base
    return round(base * OTHER_BRANCH_COST_MUL)


def buy(weapon, branch, node, paid, player=None):
    """
    Покупка узла: фиксирует основную ветвь (первая покупка),
    записывает id в weapon.nodes и ПРИМЕНЯЕТ эффекты:
      * apply — один раз мутирует spec этого экземпляра (как M5);
      * mods  — складываются в weapon.mods (dict), их читают
                resolve_shot/попадание — комбинации бесплатны.
    Подготовка другой школы закрывается жетоном, если её уровень ещё
    не набран. Деньги списывает магазин — оружие о деньгах не знает.
    """
    state = node_state(weapon, branch, node, player)
    if state == "training":
        if not _pay_training(player, node):
            raise ValueError(f"Узел {node['id']!r}: не хватает подготовки")
        state = node_state(weapon, branch, node, player)
    if state == "tokens":
        if not _pay_cross_toll(player, weapon, branch, node):
            raise ValueError(f"Узел {node['id']!r}: нужен жетон школы")
        # Оплата уже произошла; повторный node_state снова вернул бы
        # "tokens", потому что сам факт наличия платы — не состояние узла.
        state = "ok"
    if state != "ok":
        raise ValueError(f"Узел {node['id']!r} нельзя купить сейчас")
    # Узел-вход (например, «Полевой устав» пистолета) не фиксирует
    # специализацию: основную ветвь выбирает первый настоящий навык.
    if (weapon.main_branch is None and not node.get("no_main")
            and not branch.get("independent", False)):
        weapon.main_branch = branch["key"]
    weapon.nodes.add(node["id"])
    weapon.node_order.append(node["id"])
    for key, value in node.get("apply", {}).items():
        _apply_spec(weapon.spec, key, value)
    for key, value in node.get("mods", {}).items():
        weapon.mods[key] = weapon.mods.get(key, 0) + value
    weapon.invested += paid
    # Подготовка переживает смену оружия: она живёт на герое, а не на
    # экземпляре. Поэтому пистолетные условия другого оружия остаются
    # достижимыми даже после продажи дробовика.
    if player is not None:
        player.add_weapon_training(weapon.key, 1)
        player.remember_weapon_tree(weapon)
    return paid


def _apply_spec(spec, key, value):
    """'damage_mul' -> spec['damage'] *= value; 'spread_add' -> +=."""
    if key.endswith("_mul"):
        base = key[:-4]
        spec[base] = spec[base] * value
    elif key.endswith("_add"):
        base = key[:-4]
        spec[base] = spec[base] + value
    else:
        base = key
        spec[key] = value
    if base == "pellets":
        # дробины — целые (range()), после умножений округляем
        spec["pellets"] = max(1, int(round(spec["pellets"])))


# ------------------------------------------------------------ ПРЕДПРОСМОТР ДЛЯ UI
_SPEC_LABELS = {
    "damage": "Урон", "cooldown": "Откат", "magazine": "Магазин",
    "pellets": "Дробь", "spread_deg": "Разброс", "ammo_cost": "Цена выстрела",
    "reach": "Дальность", "radius": "Радиус", "arc_deg": "Дуга",
    "tick": "Частота", "hitbox_time": "Зона", "windup": "Замах",
    "reload_time": "Перезарядка", "bullet_speed": "Скорость пули",
    # Энергопушка: заряд — такая же характеристика, как урон или откат.
    "charge_time": "Время заряда", "charge_max_damage": "Урон на 100%",
    "charge_max_radius": "Хитбокс на 100%", "charge_blast_max": "Взрыв на 100%",
}
_LOWER_IS_BETTER = {"cooldown", "spread_deg", "ammo_cost", "tick", "windup",
                    "reload_time", "charge_time"}
_TIME_KEYS = {"cooldown", "tick", "windup", "hitbox_time", "reload_time",
              "charge_time", "impact_stun", "close_stun", "impact_slow",
              "mark_duration", "echo_delay", "fissure_slow", "kill_invuln",
              "retaliate_cd", "aura_heal_interval", "hammer_stun",
              "dust_duration", "blast_stun"}

_MOD_LABELS = {
    "pierce_add": "Пробитие", "wall_pen": "Сквозь стены", "ricochets": "Рикошет",
    "homing": "Наведение", "enemy_bounce": "Рикошет от врага",
    "growth": "Рост урона", "explode": "Взрыв", "cascade": "Каскад",
    "knockback": "Отбрасывание", "close_bonus": "В упор",
    "refund_reload": "Возврат патронов", "refund_kill_chance": "Возврат за убийство",
    "aim_mark": "Метка", "aim_full_mul": "Полный прицел", "stable_mul": "Стабилизация",
    "bleed": "Кровотечение", "double": "Двойной удар", "leech": "Вампиризм",
    "execute": "Казнь", "splash": "По площади", "stagger": "Оглушение",
    "epicenter_damage": "Эпицентр", "shock_slow": "Замедление",
    "dust_damage": "Урон пыли", "dust_damage_add": "Урон пыли",
    "dust_stack_cap_add": "Слои пыли", "dust_radius_add": "Радиус пыли",
    "dust_duration": "Длительность пыли", "dust_slow": "Замедление пылью",
    "dust_slow_add": "Замедление пылью",
    "variable_handle": "Дистанция удара",
    # --- поздние доктрины ---
    "volley_every": "Залп каждые", "volley_count": "Пули залпа",
    "volley_damage_mul": "Урон залпа", "volley_spread_deg": "Веер залпа",
    "alternating_bonus": "Тяжёлый выстрел", "alternating_cooldown_mul": "Лёгкий откат",
    "bounce_growth": "Рост на рикошете", "shot_damage_mul": "Урон выстрела",
    "bleed_spread": "Разнос кровотечения", "bleed_spread_radius": "Радиус крови",
    "explosion_bleed": "Кровь от взрыва", "explosion_slow": "Замедление взрывом",
    "cascade_shrapnel": "Осколки", "close_stun": "Оглушение в упор",
    "close_stun_range": "Радиус оглушения", "impact_slow": "Замедление удара",
    "impact_slow_factor": "Сила замедления", "impact_slow_radius": "Радиус замедления",
    "pierce_vulnerable": "Уязвимость от пробоя", "bounced_bonus": "После рикошета",
    "bounced_mark": "Метка после рикошета", "mark_vulnerable": "Уязвимость метки",
    "mark_duration": "Длительность метки", "steady_bonus": "Стоя на месте",
    "steady_pierce": "Пробитие стоя", "opening_bonus": "Удар в брешь",
    "opening_bleed": "Кровь в брешь", "execute_threshold": "Порог казни",
    "combo_every": "Серия каждые", "combo_double": "Двойной серийный",
    "dash_strike_bonus": "Удар после рывка", "moving_bonus": "Удар на ходу",
    "bleed_heal": "Лечение от раны", "kill_heal": "Лечение за убийство",
    "kill_invuln": "Неуязвимость за убийство", "splash_radius_add": "Радиус площади",
    "combo_bonus": "Рост серии", "combo_max": "Предел серии",
    "impact_stun": "Оглушение удара", "first_strike_bonus": "Первый удар",
    "first_strike_bleed": "Кровь первого удара", "echo_damage": "Эхо-удар",
    "echo_delay": "Задержка эха", "low_hp_bonus": "Урон при низком HP",
    "low_hp_threshold": "Порог низкого HP", "resonance_bonus": "Резонанс",
    "resonance_radius": "Радиус резонанса", "quake_rings": "Волны землетрясения",
    "fissure": "Разлом", "fissure_slow": "Замедление разломом",
    "handle_max_add": "Дальность рукояти", "pull_radius": "Радиус притяжения",
    "pull_force": "Сила притяжения", "shield_guard": "Защита щитом",
    "retaliate_damage": "Ответный удар", "retaliate_radius": "Радиус ответа",
    "retaliate_cd": "Перезарядка ответа", "aura_heal": "Лечение ауры",
    "aura_heal_interval": "Интервал лечения",
    # --- ветвь «Арсенал» пистолета ---
    "scatter_pellets_add": "Дробины картечи",
    "scatter_spread_add": "Разброс картечи",
    "scatter_damage_mul": "Урон картечи",
    "lance_pierce_add": "Пробитие копья",
    "lance_wall_pen_add": "Стены копья",
    "hammer_radius_add": "Радиус молота",
    "hammer_stun": "Оглушение молота",
    "hammer_stun_range": "Дальность оглушения",
    "bleed_add": "Кровотечение надреза",
    # --- плазменная ветвь пистолета ---
    "charge_speed_add": "Скорость заряда",
    # --- энергопушка ---
    "full_only": "Только 100%",
    "full_damage_mul": "Полный урон",
    "full_radius_mul": "Полный хитбокс",
    "full_blast_mul": "Полный взрыв",
    "full_blast_add": "Взрыв полного заряда",
    "full_pierce": "Пробитие полного заряда",
    "partial_unlock": "Стрельба недозарядом",
    "partial_damage_mul": "Урон недозаряда",
    "partial_radius_mul": "Хитбокс недозаряда",
    "partial_pellets": "Снаряды недозаряда",
    "partial_pellet_damage_mul": "Урон каждого снаряда",
    "partial_spread_deg": "Веер недозаряда",
    "partial_refund_chance": "Возврат патрона",
    "partial_cooldown_cut": "Откат недозаряда",
    "explosion_vulnerable": "Уязвимость от взрыва",
    "blast_radius_add": "Радиус взрыва",
    "blast_stun": "Оглушение взрыва",
    "charge_move_bonus": "Скорость при заряде",
    "still_charge_speed": "Заряд на месте",
    "moving_charge_speed": "Заряд на ходу",
    # --- мастерство ветвей (20-ступенчатые цепочки) ---
    "damage_mul": "Урон",
}
_PERCENT_MODS = {"damage_mul", "growth", "close_bonus", "refund_reload",
                 "refund_kill_chance",
                 "aim_mark", "bleed", "double", "leech", "execute", "splash",
                 "stagger", "epicenter_damage", "alternating_bonus",
                 "bounce_growth", "shot_damage_mul", "bleed_spread",
                 "explosion_bleed", "pierce_vulnerable", "bounced_bonus",
                 "bounced_mark", "mark_vulnerable", "steady_bonus",
                 "opening_bonus", "opening_bleed", "execute_threshold",
                 "combo_double", "dash_strike_bonus", "moving_bonus",
                 "first_strike_bonus", "first_strike_bleed", "echo_damage",
                 "low_hp_bonus", "low_hp_threshold", "combo_bonus",
                 "resonance_bonus", "resonance_radius", "shield_guard",
                 "volley_damage_mul", "scatter_damage_mul", "bleed_add",
                 "dust_damage", "dust_damage_add", "dust_slow",
                 "dust_slow_add", "full_damage_mul", "full_radius_mul",
                 "full_blast_mul", "partial_damage_mul",
                 "partial_radius_mul", "partial_pellet_damage_mul",
                 "partial_refund_chance", "partial_cooldown_cut",
                 "explosion_vulnerable", "charge_move_bonus",
                 "still_charge_speed", "moving_charge_speed",
                 "charge_speed_add"}
# Меньше — лучше для этих механик: превью не должно красить -4° в красный.
_LOWER_IS_BETTER_MODS = {"scatter_spread_add"}


def _fmt(key, value):
    if key in _TIME_KEYS:
        return f"{value:.2f}с"
    if key in _PERCENT_MODS:
        return f"{value:+.0%}" if value else "0%"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.2f}"
    return f"{value:g}" if isinstance(value, float) else str(value)


def preview_node(weapon, branch, node):
    """
    «Что изменится» для выбранного узла: список (label, before, after, better).
    Считается по тем же полям spec/mods, которые реально применяет buy(),
    поэтому окно не может показать одно, а купить другое.
    """
    preview = []
    if node.get("mode"):
        mode = PISTOL_MODES.get(node["mode"])
        if mode is not None:
            preview.append({"label": "Режим", "before": "нет",
                            "after": mode["name"], "better": True})
    if node.get("mods", {}).get("mode_switch"):
        preview.append({"label": "Управление", "before": "нет",
                        "after": "V", "better": True})
    spec = weapon.spec
    applied = dict(spec)
    for key, value in node.get("apply", {}).items():
        _apply_spec(applied, key, value)
    seen = set()
    for key in node.get("apply", {}):
        base = key[:-4] if key.endswith(("_mul", "_add")) else key
        if base in seen or base not in _SPEC_LABELS:
            continue
        seen.add(base)
        before, after = spec.get(base), applied.get(base)
        if before is None or after is None or before == after:
            continue
        better = after < before if base in _LOWER_IS_BETTER else after > before
        preview.append({"label": _SPEC_LABELS[base], "before": _fmt(base, before),
                        "after": _fmt(base, after), "better": better})

    for key, value in node.get("mods", {}).items():
        label = _MOD_LABELS.get(key)
        if label is None:
            continue
        before = float(weapon.mods.get(key, 0.0))
        after = before + value
        if key in ("full_only", "partial_unlock"):
            preview.append({"label": label,
                            "before": "да" if before else "нет",
                            "after": "да", "better": True})
            continue
        # процентные механики красивее показывать как «нет → +20%»
        before_text = _fmt(key, before) if before else "нет"
        after_text = _fmt(key, after) if after else "нет"
        better = (after < before if key in _LOWER_IS_BETTER_MODS
                  else after >= before)
        preview.append({"label": label, "before": before_text,
                        "after": after_text, "better": better})
    return preview[:4]


_PLAYER_MOD_LABELS = {
    "hp_add": "Здоровье",
    "damage_taken_mul": "Получаемый урон",
    "regen_add": "Регенерация",
    "heal_add": "Лечение",
    "speed_add": "Скорость",
    "dash_cd_mul": "Перезарядка рывка",
    "dash_invuln_add": "Неуязвимость рывка",
    "damage_add": "Урон оружия",
    "fire_rate_mul": "Откат выстрела",
    "loot_add": "Монеты",
    "execute_add": "Урон по раненым",
}
_PLAYER_REDUCTIONS = {"damage_taken_mul", "fire_rate_mul", "dash_cd_mul"}


def preview_player_node(player, node):
    """
    Предпросмотр узла героя в тех же единицах, что читает player.py.
    Показывает совокупный результат (например, −6% → −17% урона),
    а не только число конкретного узла.
    """
    preview = []
    for key, value in node.get("mods", {}).items():
        label = _PLAYER_MOD_LABELS.get(key)
        if label is None:
            continue
        if key == "hp_add":
            before = int(player.max_hp)
            after = int(player.max_hp + value)
            before_text, after_text, better = str(before), str(after), True
        elif key in _PLAYER_REDUCTIONS:
            current = player.skill_mods.get(key, 1.0)
            after_value = current * value
            before_text = f"-{(1.0 - current):.0%}" if current < 0.999 else "нет"
            after_text = f"-{(1.0 - after_value):.0%}"
            better = after_value < current
        elif key in ("regen_add", "dash_invuln_add"):
            current = player.skill_mods.get(key, 0.0)
            suffix = "с" if key == "dash_invuln_add" else "/с"
            before_text = f"+{current:.2f}{suffix}" if current else "нет"
            after_text = f"+{current + value:.2f}{suffix}"
            better = True
        else:
            current = player.skill_mods.get(key, 0.0)
            before_text = f"+{current:.0%}" if current else "нет"
            after_text = f"+{current + value:.0%}"
            better = True
        preview.append({"label": label, "before": before_text,
                        "after": after_text, "better": better})
    return preview[:4]


def _node_at(branch, tier):
    for node in branch["nodes"]:
        if node["tier"] == tier:
            return node["id"]
    return None


def prerequisites(branch, node):
    """
    Обязательные узлы: явный requires (поздние доктрины) или предыдущий
    tier той же ветви. Возвращает кортеж id, чтобы UI мог показать,
    какие именно соседи мешают покупке.
    """
    explicit = tuple(node.get("requires", ()))
    if explicit:
        return explicit
    if node["tier"] > 1:
        prev_id = _node_at(branch, node["tier"] - 1)
        return (prev_id,) if prev_id is not None else ()
    return ()


def node_names_by_id(weapon):
    """id -> имя узла, для подсказок «сначала изучите ...»."""
    return {node["id"]: node["name"]
            for branch in branches_of(weapon) for node in branch["nodes"]}


def missing_prerequisites(weapon, branch, node):
    """Имена ещё не купленных обязательных узлов (для инфопанели)."""
    names = node_names_by_id(weapon)
    return [names.get(req, req) for req in prerequisites(branch, node)
            if req not in weapon.nodes]


def choice_partner(weapon, node):
    """Парный узел-альтернатива или None."""
    for branch in branches_of(weapon):
        for other in branch["nodes"]:
            if other["id"] in node.get("excludes", ()):
                return other
    return None
