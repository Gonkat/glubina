"""
ДРЕВА НОВЫХ ШКОЛ: ДИСК, ДУГА И РЕЗАК.

Каждая школа описывает СВОЮ механику, а не «ещё один процент урона»:

    Магнитный диск — траектория. Ветви меняют дальность заброса,
        силу обратного прохода, поле взрыва и способ возврата.
    Дуговая пушка — цепь. Ветви решают, насколько далеко и сильно
        разряд перескакивает по целям, и что он оставляет после себя.
    Плазменный резак — тепло. Ветви двигают кривую «нагрев → урон»
        и цену принудительного сброса.

Здесь только ДАННЫЕ. Числа читают weapons.py (resolve_shot),
projectiles.py (Bullet) и game.py (_chain_arc); правила покупки —
skill_tree.py. Финальный слой (мастерство до 20 узлов и пятые ветви)
добавляет skill_expansion.py, поэтому таблицы ниже — базовые tier 1–5.
"""


def _node(node_id, name, tier, cost, desc, *, mods=None, apply=None,
          requires=(), excludes=(), lane=None, hybrid=False, training=None,
          role="РАЗВИТИЕ"):
    node = {
        "id": node_id,
        "name": name,
        "tier": tier,
        "cost": cost,
        "desc": desc,
        "mods": dict(mods or {}),
        "requires": tuple(requires),
        "role": role,
    }
    if apply:
        node["apply"] = dict(apply)
    if excludes:
        node["excludes"] = tuple(excludes)
    if lane is not None:
        node["lane"] = lane
    if hybrid:
        node["hybrid"] = True
    if training is not None:
        node["training"] = tuple(training)
    return node


# ============================================================ МАГНИТНЫЙ ДИСК
DISC_TREE = {
    "key": "disc",
    "name": "МАГНИТНЫЙ ДИСК",
    "branches": (
        {
            "key": "orbit",
            "name": "Орбита",
            "nodes": (
                _node("disc_o1", "Рукоять возврата", 1, 140,
                      "урон обратного прохода +15%",
                      mods={"disc_return_damage": 0.15}, role="ОСНОВА"),
                _node("disc_o2", "Дальний заброс", 2, 250,
                      "дальность полёта диска +60",
                      mods={"disc_range_add": 60},
                      requires=("disc_o1",), role="РАЗВИЛКА"),
                _node("disc_o3", "Ускоритель возврата", 3, 380,
                      "подзыв на 25% быстрее; нужна подготовка пушки",
                      mods={"disc_recall_speed": 0.25},
                      requires=("disc_o2", "disc_f1"),
                      hybrid=True, training=("cannon", 1), role="ГИБРИД"),
                _node("disc_o4", "Двойной проход", 4, 555,
                      "урон возврата +20%, дальность +40",
                      mods={"disc_return_damage": 0.20,
                            "disc_range_add": 40},
                      requires=("disc_o3",), role="КЛЮЧЕВОЕ"),
                _node("disc_o5a", "Вечный оборот", 5, 780,
                      "35% шанс вернуть патрон при поимке диска",
                      mods={"disc_catch_refund": 0.35},
                      requires=("disc_o4",), excludes=("disc_o5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("disc_o5b", "Режущая кромка", 5, 760,
                      "диск пробивает +1 цель и бьёт на возврате +10%",
                      mods={"pierce_add": 1, "disc_return_damage": 0.10},
                      requires=("disc_o4",), excludes=("disc_o5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "field",
            "name": "Поле",
            "nodes": (
                _node("disc_f1", "Магнитный удар", 1, 145,
                      "попадание даёт взрыв r=16",
                      mods={"explode": 16}, role="ОСНОВА"),
                _node("disc_f2", "Широкое поле", 2, 258,
                      "взрыв шире на 12",
                      mods={"explode": 12},
                      requires=("disc_f1",), role="РАЗВИЛКА"),
                _node("disc_f3", "Вязкое поле", 3, 388,
                      "взрыв замедляет на 0.8 с; нужна подготовка молота",
                      mods={"explosion_slow": 0.8},
                      requires=("disc_f2", "disc_t1"),
                      hybrid=True, training=("hammer", 1), role="ГИБРИД"),
                _node("disc_f4", "Притяжение поля", 4, 560,
                      "отбрасывание +160, взрыв +10",
                      mods={"knockback": 160, "explode": 10},
                      requires=("disc_f3",), role="КЛЮЧЕВОЕ"),
                _node("disc_f5a", "Гравитационный узел", 5, 790,
                      "взрыв замедляет на 1.8 с и делает цели уязвимее на 15%",
                      mods={"explosion_slow": 1.8,
                            "explosion_vulnerable": 0.15},
                      requires=("disc_f4",), excludes=("disc_f5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("disc_f5b", "Разрывное поле", 5, 775,
                      "убийство диском даёт вторичный взрыв r=45",
                      mods={"cascade": 45},
                      requires=("disc_f4",), excludes=("disc_f5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "tempo",
            "name": "Ритм",
            "nodes": (
                _node("disc_t1", "Быстрый заброс", 1, 150,
                      "откат броска -12%",
                      apply={"cooldown_mul": 0.88}, role="ОСНОВА"),
                _node("disc_t2", "Ёмкая катушка", 2, 262,
                      "магазин +2",
                      apply={"magazine_add": 2},
                      requires=("disc_t1",), role="РАЗВИЛКА"),
                _node("disc_t3", "Лёгкая перезарядка", 3, 392,
                      "перезарядка -15%",
                      apply={"reload_time_mul": 0.85},
                      requires=("disc_t2", "disc_p1"), role="ГИБРИД"),
                _node("disc_t4", "Двойная намотка", 4, 565,
                      "откат броска ещё -15%",
                      apply={"cooldown_mul": 0.85},
                      requires=("disc_t3",), role="КЛЮЧЕВОЕ"),
                _node("disc_t5a", "Экономия", 5, 800,
                      "25% шанс патрона за поимку, 20% — за убийство",
                      mods={"disc_catch_refund": 0.25,
                            "refund_kill_chance": 0.20,
                            "refund_kill_amount": 1},
                      requires=("disc_t4",), excludes=("disc_t5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("disc_t5b", "Точный бросок", 5, 780,
                      "стоя на месте урон +15%, возврат +10%",
                      mods={"steady_bonus": 0.15,
                            "disc_return_damage": 0.10},
                      requires=("disc_t4",), excludes=("disc_t5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "path",
            "name": "Траектория",
            "nodes": (
                _node("disc_p1", "Управляемый диск", 1, 155,
                      "диск отражается от стен 1 раз",
                      mods={"ricochets": 1}, role="ОСНОВА"),
                _node("disc_p2", "Второй отскок", 2, 270,
                      "ещё один отскок от стены",
                      mods={"ricochets": 1},
                      requires=("disc_p1",), role="РАЗВИЛКА"),
                _node("disc_p3", "Разгон на отскоке", 3, 400,
                      "после отскока урон +18%, отражённый удар +15%",
                      mods={"bounce_growth": 0.18, "bounced_bonus": 0.15},
                      requires=("disc_p2", "disc_o1"),
                      hybrid=True, training=("shotgun", 1), role="ГИБРИД"),
                _node("disc_p4", "Резонанс диска", 4, 570,
                      "каждое попадание усиливает следующий проход на 12%",
                      mods={"growth": 0.12},
                      requires=("disc_p3",), role="КЛЮЧЕВОЕ"),
                _node("disc_p5a", "Стальная орбита", 5, 820,
                      "два отскока и проход сквозь 1 блок стены",
                      mods={"ricochets": 2, "wall_pen": 1},
                      requires=("disc_p4",), excludes=("disc_p5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("disc_p5b", "Кровавый след", 5, 800,
                      "диск кровоточит 12%, смерть разносит кровь r=90",
                      mods={"bleed": 0.12, "bleed_spread": 0.08,
                            "bleed_spread_radius": 90},
                      requires=("disc_p4",), excludes=("disc_p5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
    ),
}


# ============================================================ ДУГОВАЯ ПУШКА
ARC_TREE = {
    "key": "arc",
    "name": "ДУГОВАЯ ПУШКА",
    "branches": (
        {
            "key": "chain",
            "name": "Дуга",
            "nodes": (
                _node("arc_c1", "Проводник", 1, 145,
                      "разряд перескакивает на +1 цель",
                      mods={"chain_jumps": 1}, role="ОСНОВА"),
                _node("arc_c2", "Широкий разряд", 2, 258,
                      "дальность перехода +40",
                      mods={"chain_range_add": 40},
                      requires=("arc_c1",), role="РАЗВИЛКА"),
                _node("arc_c3", "Ионный мост", 3, 388,
                      "урон цепи +15%, дальность +20; нужна подготовка пистолета",
                      mods={"chain_damage_mul": 0.15,
                            "chain_range_add": 20},
                      requires=("arc_c2", "arc_v1"),
                      hybrid=True, training=("pistol", 1), role="ГИБРИД"),
                _node("arc_c4", "Каскад дуг", 4, 560,
                      "ещё +1 переход, урон цепи +10%",
                      mods={"chain_jumps": 1, "chain_damage_mul": 0.10},
                      requires=("arc_c3",), role="КЛЮЧЕВОЕ"),
                _node("arc_c5a", "Гроза", 5, 790,
                      "+2 перехода и слабее затухание",
                      mods={"chain_jumps": 2, "chain_falloff_add": 0.10},
                      requires=("arc_c4",), excludes=("arc_c5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("arc_c5b", "Сфокусированный разряд", 5, 775,
                      "урон цепи +25% и выстрела +10%, но переходов меньше",
                      mods={"chain_damage_mul": 0.25,
                            "shot_damage_mul": 0.10},
                      requires=("arc_c4",), excludes=("arc_c5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "overcharge",
            "name": "Перегрузка",
            "nodes": (
                _node("arc_v1", "Фокусировка", 1, 150,
                      "урон выстрела +8%",
                      mods={"shot_damage_mul": 0.08}, role="ОСНОВА"),
                _node("arc_v2", "Пробойник", 2, 262,
                      "снаряд пробивает +1 цель",
                      mods={"pierce_add": 1},
                      requires=("arc_v1",), role="РАЗВИЛКА"),
                _node("arc_v3", "Импульс", 3, 395,
                      "урон +10%, пробитие +1",
                      mods={"shot_damage_mul": 0.10, "pierce_add": 1},
                      requires=("arc_v2", "arc_i1"), role="ГИБРИД"),
                _node("arc_v4", "Тяжёлый разряд", 4, 570,
                      "урон выстрела +14%",
                      mods={"shot_damage_mul": 0.14},
                      requires=("arc_v3",), role="КЛЮЧЕВОЕ"),
                _node("arc_v5a", "Рельсотрон", 5, 810,
                      "пробитие +2 и проход сквозь 1 блок стены",
                      mods={"pierce_add": 2, "wall_pen": 1},
                      requires=("arc_v4",), excludes=("arc_v5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("arc_v5b", "Критический разряд", 5, 790,
                      "в упор +25% и замедление на 0.3 с",
                      mods={"close_bonus": 0.25, "impact_slow": 0.3,
                            "impact_slow_radius": 25},
                      requires=("arc_v4",), excludes=("arc_v5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "ion",
            "name": "Ионизация",
            "nodes": (
                _node("arc_i1", "Ионный след", 1, 145,
                      "попадание замедляет на 0.25 с",
                      mods={"impact_slow": 0.25,
                            "impact_slow_factor": 0.7}, role="ОСНОВА"),
                _node("arc_i2", "Оглушающий разряд", 2, 260,
                      "попадание оглушает на 0.12 с",
                      mods={"impact_stun": 0.12},
                      requires=("arc_i1",), role="РАЗВИЛКА"),
                _node("arc_i3", "Уязвимость", 3, 390,
                      "пробитая цель уязвима на 10%",
                      mods={"pierce_vulnerable": 0.10},
                      requires=("arc_i2", "arc_c1"),
                      hybrid=True, training=("sniper", 1), role="ГИБРИД"),
                _node("arc_i4", "Статическое поле", 4, 560,
                      "замедление шире и сильнее",
                      mods={"impact_slow_radius": 35,
                            "impact_slow_factor": 0.5},
                      requires=("arc_i3",), role="КЛЮЧЕВОЕ"),
                _node("arc_i5a", "Паралич", 5, 800,
                      "попадание оглушает на 0.35 с",
                      mods={"impact_stun": 0.35},
                      requires=("arc_i4",), excludes=("arc_i5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("arc_i5b", "Проводимость", 5, 785,
                      "пробитая цель уязвима на 12% и получает +10% цепи",
                      mods={"pierce_vulnerable": 0.12,
                            "chain_damage_mul": 0.10},
                      requires=("arc_i4",), excludes=("arc_i5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "circuit",
            "name": "Контур",
            "nodes": (
                _node("arc_r1", "Ёмкий конденсатор", 1, 150,
                      "магазин +2",
                      apply={"magazine_add": 2}, role="ОСНОВА"),
                _node("arc_r2", "Быстрый цикл", 2, 265,
                      "откат выстрела -12%",
                      apply={"cooldown_mul": 0.88},
                      requires=("arc_r1",), role="РАЗВИЛКА"),
                _node("arc_r3", "Холодный контур", 3, 395,
                      "перезарядка -15%",
                      apply={"reload_time_mul": 0.85},
                      requires=("arc_r2", "arc_v1"), role="ГИБРИД"),
                _node("arc_r4", "Двойной контур", 4, 575,
                      "откат выстрела ещё -13%",
                      apply={"cooldown_mul": 0.87},
                      requires=("arc_r3",), role="КЛЮЧЕВОЕ"),
                _node("arc_r5a", "Бесконечная дуга", 5, 800,
                      "25% патрона за убийство и 20% — за перезарядку",
                      mods={"refund_kill_chance": 0.25,
                            "refund_kill_amount": 1,
                            "refund_reload": 0.20},
                      requires=("arc_r4",), excludes=("arc_r5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("arc_r5b", "Стойка оператора", 5, 790,
                      "стоя на месте урон +12% и +8% выстрела",
                      mods={"steady_bonus": 0.12,
                            "shot_damage_mul": 0.08},
                      requires=("arc_r4",), excludes=("arc_r5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
    ),
}


# ========================================================== ПЛАЗМЕННЫЙ РЕЗАК
CUTTER_TREE = {
    "key": "cutter",
    "name": "ПЛАЗМЕННЫЙ РЕЗАК",
    "branches": (
        {
            "key": "heat",
            "name": "Нагрев",
            "nodes": (
                _node("cut_h1", "Калибровка резака", 1, 150,
                      "урон от нагрева +15% (на пике сильнее)",
                      mods={"heat_damage_bonus": 0.15}, role="ОСНОВА"),
                _node("cut_h2", "Красная зона", 2, 262,
                      "урон от нагрева +20%",
                      mods={"heat_damage_bonus": 0.20},
                      requires=("cut_h1",), role="РАЗВИЛКА"),
                _node("cut_h3", "Термический удар", 3, 392,
                      "урон от нагрева +20%, выстрела +6%; нужна подготовка пушки",
                      mods={"heat_damage_bonus": 0.20,
                            "shot_damage_mul": 0.06},
                      requires=("cut_h2", "cut_v1"),
                      hybrid=True, training=("cannon", 1), role="ГИБРИД"),
                _node("cut_h4", "Предельный режим", 4, 565,
                      "урон от нагрева +25%",
                      mods={"heat_damage_bonus": 0.25},
                      requires=("cut_h3",), role="КЛЮЧЕВОЕ"),
                _node("cut_h5a", "Плазменный резак", 5, 800,
                      "урон от нагрева +30% и пробитие +1",
                      mods={"heat_damage_bonus": 0.30, "pierce_add": 1},
                      requires=("cut_h4",), excludes=("cut_h5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("cut_h5b", "Управляемый нагрев", 5, 780,
                      "нагрев медленнее на 15%, урон от нагрева +15%",
                      mods={"heat_damage_bonus": 0.15,
                            "heat_gain_add": -0.15},
                      requires=("cut_h4",), excludes=("cut_h5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "vent",
            "name": "Отвод",
            "nodes": (
                _node("cut_v1", "Радиатор", 1, 145,
                      "остывание +25%",
                      mods={"heat_cool_add": 0.25}, role="ОСНОВА"),
                _node("cut_v2", "Быстрый сброс", 2, 260,
                      "длительность перегрева -15%",
                      apply={"vent_time_mul": -0.15},
                      requires=("cut_v1",), role="РАЗВИЛКА"),
                _node("cut_v3", "Аварийный клапан", 3, 390,
                      "урон сброса +8",
                      mods={"vent_blast_add": 8},
                      requires=("cut_v2", "cut_b1"), role="ГИБРИД"),
                _node("cut_v4", "Контур охлаждения", 4, 560,
                      "остывание +35%, нагрев -10%",
                      mods={"heat_cool_add": 0.35,
                            "heat_gain_add": -0.10},
                      requires=("cut_v3",), role="КЛЮЧЕВОЕ"),
                _node("cut_v5a", "Тихий сброс", 5, 800,
                      "сброс почти не ранит героя",
                      mods={"vent_self_damage_add": -6.0},
                      requires=("cut_v4",), excludes=("cut_v5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("cut_v5b", "Взрывной сброс", 5, 790,
                      "сброс шире и сильнее, замедляет на 1.5 с",
                      mods={"vent_radius_add": 30,
                            "vent_blast_add": 12, "vent_slow": 1.5},
                      requires=("cut_v4",), excludes=("cut_v5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "beam",
            "name": "Луч",
            "nodes": (
                _node("cut_b1", "Острый край", 1, 150,
                      "урон выстрела +8%",
                      mods={"shot_damage_mul": 0.08}, role="ОСНОВА"),
                _node("cut_b2", "Прожигание", 2, 262,
                      "снаряд пробивает +1 цель",
                      mods={"pierce_add": 1},
                      requires=("cut_b1",), role="РАЗВИЛКА"),
                _node("cut_b3", "Непрерывный рез", 3, 392,
                      "каждое попадание усиливает следующий на 10%",
                      mods={"growth": 0.10},
                      requires=("cut_b2", "cut_h1"),
                      hybrid=True, training=("sniper", 1), role="ГИБРИД"),
                _node("cut_b4", "Перегрузка луча", 4, 565,
                      "урон +12%, пробитие +1",
                      mods={"shot_damage_mul": 0.12, "pierce_add": 1},
                      requires=("cut_b3",), role="КЛЮЧЕВОЕ"),
                _node("cut_b5a", "Испепеление", 5, 810,
                      "попадание даёт взрыв r=18 и кровь от взрыва",
                      mods={"explode": 18, "explosion_bleed": 0.15},
                      requires=("cut_b4",), excludes=("cut_b5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("cut_b5b", "Кровавый рез", 5, 790,
                      "попадание кровоточит 15%",
                      mods={"bleed": 0.15},
                      requires=("cut_b4",), excludes=("cut_b5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
        {
            "key": "flow",
            "name": "Поток",
            "nodes": (
                _node("cut_f1", "Подача", 1, 150,
                      "откат выстрела -10%",
                      apply={"cooldown_mul": 0.90}, role="ОСНОВА"),
                _node("cut_f2", "Ёмкий магазин", 2, 265,
                      "магазин +3",
                      apply={"magazine_add": 3},
                      requires=("cut_f1",), role="РАЗВИЛКА"),
                _node("cut_f3", "Быстрая замена", 3, 395,
                      "перезарядка -15%",
                      apply={"reload_time_mul": 0.85},
                      requires=("cut_f2", "cut_v1"), role="ГИБРИД"),
                _node("cut_f4", "Непрерывный поток", 4, 570,
                      "откат -10%, нагрев -10%",
                      apply={"cooldown_mul": 0.90},
                      mods={"heat_gain_add": -0.10},
                      requires=("cut_f3",), role="КЛЮЧЕВОЕ"),
                _node("cut_f5a", "Бесконечный рез", 5, 800,
                      "30% патрона за убийство",
                      mods={"refund_kill_chance": 0.30,
                            "refund_kill_amount": 1},
                      requires=("cut_f4",), excludes=("cut_f5b",),
                      lane=-1, role="АЛЬТЕРНАТИВА"),
                _node("cut_f5b", "Стационарный резак", 5, 790,
                      "стоя на месте урон +15% и остывание +20%",
                      mods={"steady_bonus": 0.15,
                            "heat_cool_add": 0.20},
                      requires=("cut_f4",), excludes=("cut_f5a",),
                      lane=1, role="АЛЬТЕРНАТИВА"),
            ),
        },
    ),
}


NEW_TREES = (DISC_TREE, ARC_TREE, CUTTER_TREE)


def inject_new_arsenal(skill_trees):
    """Добавляет три новых древа, проверяя все ссылки на узлы.

    Идемпотентна: повторный вызов не создаёт дубликатов. Требования
    проверяются по СОБРАННОМУ набору id, потому что гибридный узел может
    ссылаться на ветвь, объявленную ниже.
    """
    for tree in NEW_TREES:
        key = tree["key"]
        if key in skill_trees:
            continue
        all_ids = {node["id"] for branch in tree["branches"]
                   for node in branch["nodes"]}
        branches = []
        for branch in tree["branches"]:
            nodes = []
            for source in branch["nodes"]:
                node = dict(source)
                node.setdefault("mods", {})
                for requirement in node.get("requires", ()):
                    if requirement not in all_ids:
                        raise ValueError(
                            f"{key}: неизвестная зависимость {requirement!r}")
                for excluded in node.get("excludes", ()):
                    if excluded not in all_ids:
                        raise ValueError(
                            f"{key}: неизвестное исключение {excluded!r}")
                node["requires"] = tuple(node.get("requires", ()))
                nodes.append(node)
            branches.append(dict(branch, nodes=tuple(nodes)))
        skill_trees[key] = dict(tree, branches=tuple(branches))
    return skill_trees
