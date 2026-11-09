"""
ПОЗДНИЕ ВЫБОРЫ ОРУЖЕЙНЫХ ДРЕВ.

Каждая из трёх ветвей любого оружия получает на пятом уровне не один
финальный узел, а ПАРУ взаимоисключающих доктрин. Это не «ещё две цифры»:
пара меняет рисунок боя (залпы, эхо-удары, разломы, аура, экономика),
а купить можно только одну из двух.

Модуль хранит только ДАННЫЕ. Вставка узлов в SKILL_TREES выполняется
функцией inject_capstones() из skill_data.py. Там же остаются базовые
узлы, поэтому старые id (tier 1..4) не меняются.

Поля позднего узла:
    requires_extra — id соседних навыков, которые тоже нужны (гибрид);
    mods            — механики, которые читают бой и UI;
    apply           — одноразовые изменения spec (как у старых узлов).
"""
CAPSTONES = {
    # ============================================================ ПИСТОЛЕТ
    "pistol": (
        (
            {"id": "pistol_s5a", "name": "Свинцовый вихрь", "cost": 430,
             "desc": "каждый 3-й выстрел: +2 пули веером, урон 65%, без патронов",
             "mods": {"volley_every": 3, "volley_count": 2,
                      "volley_damage_mul": 0.65, "volley_spread_deg": 9}},
            {"id": "pistol_s5b", "name": "Дуэльный ритм", "cost": 470,
             "desc": "выстрелы чередуются: тяжёлый +45% урона, лёгкий -20% откат",
             "mods": {"alternating_bonus": 0.45,
                      "alternating_cooldown_mul": 0.8}},
        ),
        (
            {"id": "pistol_m5a", "name": "Рикошетный каскад", "cost": 450,
             "desc": "каждое отражение +18% урона, +2 рикошета",
             "mods": {"ricochets": 2, "bounce_growth": 0.18}},
            {"id": "pistol_m5b", "name": "Крупный калибр", "cost": 500,
             "desc": "пробой +2, взрыв r=80, урон +15%, откат +25%",
             "apply": {"cooldown_mul": 1.25},
             "mods": {"pierce_add": 2, "explode": 80,
                      "shot_damage_mul": 0.15}},
        ),
        (
            {"id": "pistol_e5a", "name": "Чистый цикл", "cost": 470,
             "desc": "перезарядка -35%, шанс вернуть весь боезапас 65%",
             "apply": {"reload_time_mul": 0.65},
             "mods": {"refund_reload": 0.1}},
            {"id": "pistol_e5b", "name": "Свинцовый налог", "cost": 530,
             "desc": "урон +35%, цена выстрела +1, убийства возвращают 3",
             "requires_extra": ("pistol_s2",),
             "apply": {"ammo_cost_add": 1},
             "mods": {"shot_damage_mul": 0.35,
                      "refund_kill_chance": 0.25,
                      "refund_kill_amount": 1}},
        ),
    ),

    # ============================================================ ДРОБОВИК
    "shotgun": (
        (
            {"id": "shotgun_c5a", "name": "Свинцовый шторм", "cost": 650,
             "desc": "каждый 3-й выстрел: +4 дробины с уроном 80%",
             "mods": {"volley_every": 3, "volley_count": 4,
                      "volley_damage_mul": 0.8, "volley_spread_deg": 8}},
            {"id": "shotgun_c5b", "name": "Кровавая картечь", "cost": 690,
             "desc": "дробины вызывают кровотечение, смерть разносит его",
             "mods": {"bleed": 0.28, "bleed_spread": 0.5,
                      "bleed_spread_radius": 90}},
        ),
        (
            {"id": "shotgun_d5a", "name": "Термитный заряд", "cost": 700,
             "desc": "взрывы поджигают и замедляют всех в радиусе",
             "mods": {"explode": 25, "explosion_bleed": 0.35,
                      "explosion_slow": 1.2}},
            {"id": "shotgun_d5b", "name": "Осколочный каскад", "cost": 740,
             "desc": "убийство взрывом рождает 4 осколка-дробины",
             "requires_extra": ("shotgun_c1",),
             "mods": {"cascade": 20, "cascade_shrapnel": 4}},
        ),
        (
            {"id": "shotgun_s5a", "name": "Осадный таран", "cost": 700,
             "desc": "в упор: +40% урона и оглушение 0.9 с",
             "mods": {"close_bonus": 0.4, "close_stun": 0.9,
                      "close_stun_range": 240}},
            {"id": "shotgun_s5b", "name": "Дымовая стена", "cost": 730,
             "desc": "попадания замедляют цель и соседей r=85",
             "requires_extra": ("shotgun_d1",),
             "mods": {"impact_slow": 1.8, "impact_slow_factor": 0.45,
                      "impact_slow_radius": 85}},
        ),
    ),

    # ============================================================ СНАЙПЕРКА
    "sniper": (
        (
            {"id": "sniper_p5a", "name": "Линия смерти", "cost": 900,
             "desc": "пробитие +2; каждая цель +35% урона следующей и уязвима",
             "mods": {"pierce_add": 2, "growth": 0.35,
                      "pierce_vulnerable": 0.25}},
            {"id": "sniper_p5b", "name": "Тяжёлый сердечник", "cost": 980,
             "desc": "урон +75%, ещё 2 блока (8 суммарно), пробитие -2, скорость -15%",
             "apply": {"damage_mul": 1.75, "bullet_speed_mul": 0.85},
             "mods": {"pierce_add": -2, "wall_pen": 2}},
        ),
        (
            {"id": "sniper_r5a", "name": "Карамболь", "cost": 940,
             "desc": "рикошет от врага +25% урона и +1 цепь",
             "mods": {"enemy_bounce": 1, "bounce_growth": 0.25,
                      "ricochets": 1}},
            {"id": "sniper_r5b", "name": "Зеркальный капкан", "cost": 980,
             "desc": "после стены +60% урона и метка уязвимости",
             "requires_extra": ("sniper_b2",),
             "mods": {"bounced_bonus": 0.6, "bounced_mark": 0.2,
                      "ricochets": 1}},
        ),
        (
            {"id": "sniper_b5a", "name": "Метка охотника", "cost": 940,
             "desc": "помеченная цель получает +25% от всех атак 2 с",
             "mods": {"mark_vulnerable": 0.25, "mark_duration": 2.0}},
            {"id": "sniper_b5b", "name": "Хладнокровие", "cost": 1000,
             "desc": "стоя на месте: +60% урона и +1 пробитие",
             "requires_extra": ("sniper_p1",),
             "mods": {"steady_bonus": 0.6, "steady_pierce": 1}},
        ),
    ),

    # ============================================================ НОЖ
    "knife": (
        (
            {"id": "knife_0_5a", "name": "Удар в брешь", "cost": 320,
             "desc": "удар по врагу в замахе +70% и кровотечение",
             "mods": {"opening_bonus": 0.7, "opening_bleed": 0.2}},
            {"id": "knife_0_5b", "name": "Казнь", "cost": 360,
             "desc": "порог казни 50%, бонус +70%",
             "mods": {"execute": 0.7, "execute_threshold": 0.15}},
        ),
        (
            {"id": "knife_1_5a", "name": "Кровавый вальс", "cost": 360,
             "desc": "каждый 3-й удар бьёт дважды на 80% и кровоточит",
             "requires_extra": ("knife_0_2",),
             "mods": {"combo_every": 3, "combo_double": 0.8,
                      "bleed": 0.1}},
            {"id": "knife_1_5b", "name": "Тень", "cost": 380,
             "desc": "удар после рывка +80%, на ходу +15%",
             "mods": {"dash_strike_bonus": 0.8, "moving_bonus": 0.15}},
        ),
        (
            {"id": "knife_2_5a", "name": "Паразит", "cost": 360,
             "desc": "вампиризм 12%; удар по раненому лечит +2 HP",
             "mods": {"leech": 0.12, "bleed_heal": 2.0}},
            {"id": "knife_2_5b", "name": "Фантом", "cost": 400,
             "desc": "убийство: +3 HP и 0.7 с неуязвимости",
             "requires_extra": ("knife_1_1",),
             "mods": {"kill_heal": 3.0, "kill_invuln": 0.7}},
        ),
    ),

    # ============================================================ МАЧЕТЕ
    "machete": (
        (
            {"id": "machete_0_5a", "name": "Кровавая жатва", "cost": 440,
             "desc": "смерть кровоточащей цели разносит кровотечение r=100",
             "mods": {"bleed": 0.1, "bleed_spread": 0.55,
                      "bleed_spread_radius": 100}},
            {"id": "machete_0_5b", "name": "Мясорубка", "cost": 480,
             "desc": "удар повторяется на 35%, дуга уже на 10%",
             "apply": {"arc_deg_mul": 0.9},
             "mods": {"double": 0.35}},
        ),
        (
            {"id": "machete_1_5a", "name": "Смертельный круг", "cost": 460,
             "desc": "урон по площади 55%, радиус +40",
             "mods": {"splash": 0.55, "splash_radius_add": 40}},
            {"id": "machete_1_5b", "name": "Вихрь", "cost": 500,
             "desc": "серия попаданий: +7% урона, до 8 стаков",
             "requires_extra": ("machete_0_1",),
             "mods": {"combo_bonus": 0.07, "combo_max": 8}},
        ),
        (
            {"id": "machete_2_5a", "name": "Палач", "cost": 460,
             "desc": "порог казни 55%, бонус +85%",
             "mods": {"execute": 0.85, "execute_threshold": 0.2}},
            {"id": "machete_2_5b", "name": "Напор", "cost": 500,
             "desc": "отбрасывание +80%, оглушение 0.5 с",
             "requires_extra": ("machete_1_1",),
             "mods": {"stagger": 0.8, "impact_stun": 0.5}},
        ),
    ),

    # ============================================================ КАТАНА
    "katana": (
        (
            {"id": "katana_0_5a", "name": "Мгновенный клинок", "cost": 520,
             "desc": "первый удар после 1 с покоя +100% и кровотечение",
             "mods": {"first_strike_bonus": 1.0,
                      "first_strike_bleed": 0.25}},
            {"id": "katana_0_5b", "name": "Стальной веер", "cost": 560,
             "desc": "удар на 360°, но урон -30%",
             "apply": {"arc_deg": 360, "damage_mul": 0.7}},
        ),
        (
            {"id": "katana_1_5a", "name": "Лунная волна", "cost": 560,
             "desc": "эхо-волна 65% по площади, радиус +45",
             "mods": {"splash": 0.65, "splash_radius_add": 45}},
            {"id": "katana_1_5b", "name": "Эхо клинка", "cost": 600,
             "desc": "через 0.25 с повторный удар на 45%",
             "requires_extra": ("katana_0_2",),
             "mods": {"echo_damage": 0.45, "echo_delay": 0.25}},
        ),
        (
            {"id": "katana_2_5a", "name": "Последний удар", "cost": 560,
             "desc": "при HP ниже 40% урон +80% и вампиризм 8%",
             "mods": {"low_hp_bonus": 0.8, "low_hp_threshold": 0.4,
                      "leech": 0.08}},
            {"id": "katana_2_5b", "name": "Стойка самурая", "cost": 600,
             "desc": "стоя на месте +45% урона, удары оглушают 0.4 с",
             "requires_extra": ("katana_1_1",),
             "mods": {"steady_bonus": 0.45, "impact_stun": 0.4}},
        ),
    ),

    # ============================================================ МОЛОТ
    "hammer": (
        (
            {"id": "hammer_0_5a", "name": "Сердце разлома", "cost": 600,
             "desc": "эпицентр +80%, радиус +15%",
             "apply": {"radius_mul": 1.15},
             "mods": {"epicenter_damage": 0.8}},
            {"id": "hammer_0_5b", "name": "Резонанс", "cost": 640,
             "desc": "повторный удар в ту же точку +30% и +10% радиус",
             "mods": {"resonance_bonus": 0.3,
                      "resonance_radius": 0.1}},
        ),
        (
            {"id": "hammer_1_5a", "name": "Землетрясение", "cost": 640,
             "desc": "каждый удар даёт 3 затухающие волны",
             "mods": {"quake_rings": 3}},
            {"id": "hammer_1_5b", "name": "Разлом", "cost": 680,
             "desc": "удары оставляют разлом, замедляющий 2 с",
             "requires_extra": ("hammer_2_1",),
             "mods": {"fissure": 1, "fissure_slow": 2.0}},
        ),
        (
            {"id": "hammer_2_5a", "name": "Оглушающая волна", "cost": 640,
             "desc": "волна замедляет 3 с и оглушает 0.5 с",
             "mods": {"shock_slow": 3.0, "impact_stun": 0.5}},
            {"id": "hammer_2_5b", "name": "Подвижная рукоять", "cost": 680,
             "desc": "удар в точку курсора, дальность +80",
             "requires_extra": ("hammer_0_1",),
             "mods": {"variable_handle": 1, "handle_max_add": 80}},
        ),
    ),

    # ============================================================ ЛОПАТА
    "shovel": (
        (
            {"id": "shovel_0_5a", "name": "Земляной таран", "cost": 460,
             "desc": "отбрасывание +80%, оглушение 0.55 с",
             "mods": {"stagger": 0.8, "impact_stun": 0.55}},
            {"id": "shovel_0_5b", "name": "Грязевой плен", "cost": 500,
             "desc": "удар замедляет цель и соседей r=75",
             "mods": {"impact_slow": 2.0, "impact_slow_factor": 0.4,
                      "impact_slow_radius": 75}},
        ),
        (
            {"id": "shovel_1_5a", "name": "Полевой лекарь", "cost": 480,
             "desc": "вампиризм 20%, убийство лечит +3",
             "mods": {"leech": 0.2, "kill_heal": 3.0}},
            {"id": "shovel_1_5b", "name": "Корни", "cost": 520,
             "desc": "удар притягивает врагов в радиусе 70",
             "requires_extra": ("shovel_2_1",),
             "mods": {"pull_radius": 70, "pull_force": 180}},
        ),
        (
            {"id": "shovel_2_5a", "name": "Обвал", "cost": 500,
             "desc": "урон по площади 60%, радиус +50",
             "mods": {"splash": 0.6, "splash_radius_add": 50}},
            {"id": "shovel_2_5b", "name": "Широкий замах", "cost": 540,
             "desc": "дуга +50%, отбрасывание +40%",
             "requires_extra": ("shovel_0_1",),
             "apply": {"arc_deg_mul": 1.5},
             "mods": {"stagger": 0.4}},
        ),
    ),

    # ============================================================ ЩИТ
    "shield": (
        (
            {"id": "shield_0_5a", "name": "Несокрушимый", "cost": 520,
             "desc": "пока щит в руках, получаемый урон -12%",
             "mods": {"shield_guard": 0.12}},
            {"id": "shield_0_5b", "name": "Отражение", "cost": 560,
             "desc": "получив урон, щит бьёт по площади r=90 (кд 2.5 с)",
             "mods": {"retaliate_damage": 35.0,
                      "retaliate_radius": 90, "retaliate_cd": 2.5}},
        ),
        (
            {"id": "shield_1_5a", "name": "Терновый венец", "cost": 540,
             "desc": "аура вызывает кровотечение 25% и бьёт по площади",
             "mods": {"bleed": 0.25, "splash": 0.25}},
            {"id": "shield_1_5b", "name": "Шипованный барьер", "cost": 580,
             "desc": "радиус ауры +25%, отбрасывание +50%",
             "requires_extra": ("shield_2_1",),
             "apply": {"radius_mul": 1.25},
             "mods": {"stagger": 0.5}},
        ),
        (
            {"id": "shield_2_5a", "name": "Живая крепость", "cost": 540,
             "desc": "вампиризм 18%, убийство лечит +3",
             "mods": {"leech": 0.18, "kill_heal": 3.0}},
            {"id": "shield_2_5b", "name": "Пульс", "cost": 580,
             "desc": "аура каждые 2 с лечит на 3 HP",
             "requires_extra": ("shield_0_1",),
             "mods": {"aura_heal": 3.0, "aura_heal_interval": 2.0}},
        ),
    ),
}


PISTOL_ADVANCEMENTS = (
    (
        {"id": "pistol_s6a", "name": "Усиленный залп", "cost": 760,
         "desc": "залп чаще и шире: +1 пуля, урон каждой 50%",
         "requires": ("pistol_s5a",),
         "excludes": ("pistol_s5b",),
         "mods": {"volley_count": 1, "volley_damage_mul": -0.15,
                  "volley_spread_deg": 3}},
        {"id": "pistol_s6b", "name": "Точная раскачка", "cost": 780,
         "desc": "тяжёлый выстрел +10%, лёгкий цикл быстрее",
         "requires": ("pistol_s5b",),
         "excludes": ("pistol_s5a",),
         "mods": {"alternating_bonus": 0.10,
                  "alternating_cooldown_mul": -0.05}},
    ),
    (
        {"id": "pistol_m6a", "name": "Расчёт рикошета", "cost": 790,
         "desc": "ещё один рикошет и +8% урона за отражение",
         "requires": ("pistol_m5a",),
         "excludes": ("pistol_m5b",),
         "mods": {"ricochets": 1, "bounce_growth": 0.08}},
        {"id": "pistol_m6b", "name": "Микрокартечь", "cost": 820,
         "desc": "3 дробины слабо взрываются веером; выстрел стоит 2 боеприпаса",
         "requires": ("pistol_m5b",),
         "excludes": ("pistol_m5a",),
         "apply": {"pellets_add": 2, "spread_deg_add": 16,
                   "damage_mul": 0.26, "ammo_cost_add": 1},
         "mods": {"explode": -120}},
    ),
    (
        {"id": "pistol_e6a", "name": "Универсальная обойма", "cost": 790,
         "desc": "перезарядка быстрее, пробой +1 и возврат за убийство +1",
         "requires": ("pistol_e5a", "pistol_s2", "pistol_m1"),
         "excludes": ("pistol_e5b",),
         "apply": {"reload_time_mul": 0.9},
         "mods": {"refund_kill_amount": 1, "pierce_add": 1}},
        {"id": "pistol_e6b", "name": "Пробой с возвратом", "cost": 820,
         "desc": "пробивной патрон рикошетит; шанс возврата +5%, ещё +1 патрон",
         "requires": ("pistol_e5b", "pistol_m1"),
         "excludes": ("pistol_e5a",),
         "mods": {"ricochets": 1, "refund_kill_chance": 0.05,
                  "refund_kill_amount": 1}},
    ),
)


def inject_capstones(skill_trees):
    """
    Добавляет по два tier-5 узла в каждую ветвь. Старые узлы и их id
    остаются нетронутыми; для каждого выбора автоматически создаются
    связи (tier 4 -> выбор) и взаимные запреты (excludes).
    """
    for weapon_key, branch_choices in CAPSTONES.items():
        tree = skill_trees[weapon_key]
        branches = list(tree["branches"])
        if len(branches) != len(branch_choices):
            raise ValueError(f"{weapon_key}: ожидалось 3 ветви")
        for bi, pair in enumerate(branch_choices):
            if len(pair) != 2:
                raise ValueError(f"{weapon_key}[{bi}]: нужна пара выборов")
            branch = dict(branches[bi])
            nodes = list(branch["nodes"])
            tier4 = next((n for n in nodes if n["tier"] == 4), None)
            if tier4 is None:
                raise ValueError(f"{weapon_key}[{bi}]: нет tier 4")
            choices = []
            for lane, spec in zip((-1, 1), pair):
                node = dict(spec)
                node["tier"] = 5
                node["lane"] = lane
                extras = tuple(node.pop("requires_extra", ()))
                node["requires"] = (tier4["id"],) + extras
                node["hybrid"] = bool(extras)
                node["role"] = "АЛЬТЕРНАТИВА"
                node.setdefault("mods", {})
                node.setdefault("apply", {})
                choices.append(node)
            choices[0]["excludes"] = (choices[1]["id"],)
            choices[1]["excludes"] = (choices[0]["id"],)
            branch["nodes"] = tuple(nodes + choices)
            branches[bi] = branch
        tree["branches"] = tuple(branches)
    return skill_trees


def inject_pistol_advancements(skill_trees):
    """Добавляет специализации tier 6, следующие за выборами пистолета tier 5."""
    tree = skill_trees["pistol"]
    branches = list(tree["branches"])
    if len(branches) != len(PISTOL_ADVANCEMENTS):
        raise ValueError("pistol: tier-6 specializations require three branches")
    existing_ids = {
        node["id"] for branch in branches for node in branch["nodes"]
    }
    for branch_index, branch in enumerate(branches):
        branch = dict(branch)
        nodes = list(branch["nodes"])
        additions = []
        for spec in PISTOL_ADVANCEMENTS[branch_index]:
            if not set(spec["requires"]).issubset(existing_ids):
                raise ValueError(
                    f"{branch['key']}: нет требования tier 6 для {spec['id']}")
            node = dict(spec)
            node["tier"] = 6
            node.setdefault("mods", {})
            node.setdefault("apply", {})
            node["role"] = "СПЕЦИАЛИЗАЦИЯ"
            additions.append(node)
        branch["nodes"] = tuple(nodes + additions)
        branches[branch_index] = branch
    tree["branches"] = tuple(branches)
    return skill_trees
