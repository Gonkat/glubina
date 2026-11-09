"""
ДРЕВО ЭНЕРГОПУШКИ — ДАННЫЕ И ВСТАВКА.

Пушка не усиливает себя «ещё одним процентом урона». Её дерево меняет
САМ ПРИНЦИП ВЫСТРЕЛА:

    Овердрайв  — полный заряд становится вдвое сильнее, но ранний
                 отпуск отменяет выстрел. Ставка на терпение.
    Гибкий     — разрешает стрелять недозарядом (с 8%), но с ×0.7
                 урона. Ставка на темп и мобильность.
    Резонанс   — площадь, замедление, уязвимость и цепные взрывы.
                 Ставка на толпу, а не на одну цель.
    Накопитель — скорость заряда, магазин, экономика и движение.
                 Ставка на удобство и ресурс.

Почему ветви не «лучше/хуже», а разные:
  * Овердрайв и Гибкий взаимно исключают tier-2: купив «Полный импульс»,
    нельзя взять «Аварийный разряд», и наоборот;
  * tier-3 узлы требуют СОСЕДНИЙ узел другой ветви и подготовку школы
    (снайперка / дробовик / молот). Жетон тренировки закрывает подготовку,
    если оружия ещё нет — это тот же механизм, что у «Арсенала» пистолета;
  * tier-5 — пары взаимоисключающих доктрин, по одной на ветвь;
  * tier-3+ в чужой ветви закрыты общим правилом основной специализации
    (skill_tree.node_state), поэтому «всё сразу» не собирается.

Все числа читает Firearm.resolve_shot / charge-механика в weapons.py,
а правила покупки — skill_tree.py. Новых классов оружия нет.
"""

CANNON_TREE = {
    "key": "cannon",
    "name": "ЭНЕРГОПУШКА",
    "branches": (
        {
            "key": "overdrive",
            "name": "Овердрайв",
            "nodes": (
                {
                    "id": "cannon_o1",
                    "name": "Форсированный контур",
                    "tier": 1,
                    "cost": 160,
                    "desc": "заряд на 15% быстрее; вход в ветвь полного импульса",
                    "apply": {"charge_time_mul": 0.85},
                    "role": "ОСНОВА",
                },
                {
                    "id": "cannon_o2",
                    "name": "Полный импульс",
                    "tier": 2,
                    "cost": 300,
                    "desc": "стрельба только на 100%: урон и хитбокс x2, взрыв +25%; ранний отпуск отменяет заряд",
                    "requires": ("cannon_o1",),
                    "excludes": ("cannon_f1", "cannon_f2"),
                    "mods": {
                        "full_only": 1,
                        "full_damage_mul": 1.0,
                        "full_radius_mul": 1.0,
                        "full_blast_mul": 0.25,
                    },
                    "role": "РАЗВИЛКА",
                },
                {
                    "id": "cannon_o3",
                    "name": "Критическая масса",
                    "tier": 3,
                    "cost": 470,
                    "desc": "полный снаряд пробивает +2 цели, взрыв +16; нужна подготовка снайперки",
                    "requires": ("cannon_o2", "cannon_a1"),
                    "training": ("sniper", 1),
                    "hybrid": True,
                    "mods": {"full_pierce": 2, "full_blast_add": 16},
                    "role": "ГИБРИД",
                },
                {
                    "id": "cannon_o4",
                    "name": "Термоядерный заряд",
                    "tier": 4,
                    "cost": 690,
                    "desc": "полный выстрел: урон +25%, взрыв +30, +1 пробитие; заряд на 12% дольше",
                    "requires": ("cannon_o3",),
                    "apply": {"charge_time_mul": 1.12},
                    "mods": {
                        "full_damage_mul": 0.25,
                        "full_blast_add": 30,
                        "full_pierce": 1,
                    },
                    "role": "КЛЮЧЕВОЕ",
                },
                {
                    "id": "cannon_o5a",
                    "name": "Сингулярность",
                    "tier": 5,
                    "cost": 940,
                    "lane": -1,
                    "desc": "полный взрыв +45, оглушает 0.8 с и замедляет на 2 с",
                    "requires": ("cannon_o4",),
                    "excludes": ("cannon_o5b",),
                    "mods": {
                        "full_blast_add": 45,
                        "blast_stun": 0.8,
                        "explosion_slow": 2.0,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
                {
                    "id": "cannon_o5b",
                    "name": "Импульсный таран",
                    "tier": 5,
                    "cost": 920,
                    "lane": 1,
                    "desc": "полный снаряд +3 пробития и +320 отбрасывания, но взрыв -30%",
                    "requires": ("cannon_o4",),
                    "excludes": ("cannon_o5a",),
                    "mods": {
                        "full_pierce": 3,
                        "knockback": 320,
                        "full_blast_mul": -0.30,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
            ),
        },
        {
            "key": "flex",
            "name": "Гибкий разряд",
            "nodes": (
                {
                    "id": "cannon_f1",
                    "name": "Аварийный разряд",
                    "tier": 1,
                    "cost": 150,
                    "desc": "стрельба с 8% заряда, но недозаряд: -30% урона и -20% хитбокса",
                    "excludes": ("cannon_o2",),
                    "mods": {
                        "partial_unlock": 1,
                        "partial_damage_mul": -0.30,
                        "partial_radius_mul": -0.20,
                    },
                    "role": "ОСНОВА",
                },
                {
                    "id": "cannon_f2",
                    "name": "Стабильный контур",
                    "tier": 2,
                    "cost": 285,
                    "desc": "заряд на 18% быстрее; штраф недозаряда -20% вместо -30%, полный выстрел -10%",
                    "requires": ("cannon_f1",),
                    "excludes": ("cannon_o2",),
                    "apply": {"charge_time_mul": 0.82},
                    "mods": {
                        "full_damage_mul": -0.10,
                        "partial_damage_mul": 0.10,
                    },
                    "role": "РАЗВИЛКА",
                },
                {
                    "id": "cannon_f3",
                    "name": "Импульсный возврат",
                    "tier": 3,
                    "cost": 440,
                    "desc": "недозаряд с шансом 35% возвращает патрон магазина; нужна подготовка дробовика",
                    "requires": ("cannon_f2", "cannon_c1"),
                    "training": ("shotgun", 1),
                    "hybrid": True,
                    "mods": {"partial_refund_chance": 0.35},
                    "role": "ГИБРИД",
                },
                {
                    "id": "cannon_f4",
                    "name": "Свободный поток",
                    "tier": 4,
                    "cost": 620,
                    "desc": "недозаряд -30% отката, полный выстрел -5% урона",
                    "requires": ("cannon_f3",),
                    "mods": {
                        "partial_cooldown_cut": 0.30,
                        "full_damage_mul": -0.05,
                    },
                    "role": "КЛЮЧЕВОЕ",
                },
                {
                    "id": "cannon_f5a",
                    "name": "Шквал плазмы",
                    "tier": 5,
                    "cost": 880,
                    "lane": -1,
                    "desc": "недозаряд выпускает 3 снаряда по 45% урона веером",
                    "requires": ("cannon_f4",),
                    "excludes": ("cannon_f5b",),
                    "mods": {
                        "partial_pellets": 2,
                        "partial_pellet_damage_mul": -0.55,
                        "partial_spread_deg": 10.0,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
                {
                    "id": "cannon_f5b",
                    "name": "Точный разряд",
                    "tier": 5,
                    "cost": 860,
                    "lane": 1,
                    "desc": "недозаряд +25% урона и +10% хитбокса, но заряд на 10% дольше",
                    "requires": ("cannon_f4",),
                    "excludes": ("cannon_f5a",),
                    "apply": {"charge_time_mul": 1.10},
                    "mods": {
                        "partial_damage_mul": 0.25,
                        "partial_radius_mul": 0.10,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
            ),
        },
        {
            "key": "resonance",
            "name": "Резонанс",
            "nodes": (
                {
                    "id": "cannon_a1",
                    "name": "Широкий резонатор",
                    "tier": 1,
                    "cost": 155,
                    "desc": "радиус взрыва +16, прямой урон -8%",
                    "mods": {"blast_radius_add": 16, "shot_damage_mul": -0.08},
                    "role": "ОСНОВА",
                },
                {
                    "id": "cannon_a2",
                    "name": "Ионная цепь",
                    "tier": 2,
                    "cost": 290,
                    "desc": "взрыв замедляет на 1.5 с и делает цели уязвимее на 15%",
                    "requires": ("cannon_a1",),
                    "mods": {
                        "explosion_slow": 1.5,
                        "explosion_vulnerable": 0.15,
                        "blast_radius_add": 8,
                    },
                    "role": "РАЗВИЛКА",
                },
                {
                    "id": "cannon_a3",
                    "name": "Резонансный контур",
                    "tier": 3,
                    "cost": 465,
                    "desc": "полный взрыв +20% и оглушает 0.4 с; нужна подготовка молота",
                    "requires": ("cannon_a2", "cannon_o1"),
                    "training": ("hammer", 1),
                    "hybrid": True,
                    "mods": {"full_blast_mul": 0.20, "blast_stun": 0.4},
                    "role": "ГИБРИД",
                },
                {
                    "id": "cannon_a4",
                    "name": "Плазменный шторм",
                    "tier": 4,
                    "cost": 650,
                    "desc": "убийство пушкой даёт вторичный взрыв r=55; взрыв делает цели уязвимее",
                    "requires": ("cannon_a3",),
                    "mods": {"cascade": 55, "explosion_vulnerable": 0.10},
                    "role": "КЛЮЧЕВОЕ",
                },
                {
                    "id": "cannon_a5a",
                    "name": "Гравитационная воронка",
                    "tier": 5,
                    "cost": 900,
                    "lane": -1,
                    "desc": "взрыв шире на 14 и замедляет на 2.5 с",
                    "requires": ("cannon_a4",),
                    "excludes": ("cannon_a5b",),
                    "mods": {"blast_radius_add": 14, "explosion_slow": 2.5},
                    "role": "АЛЬТЕРНАТИВА",
                },
                {
                    "id": "cannon_a5b",
                    "name": "Цепная реакция",
                    "tier": 5,
                    "cost": 900,
                    "lane": 1,
                    "desc": "каскад r=75 и 2 осколка; взрыв делает цели уязвимее",
                    "requires": ("cannon_a4",),
                    "excludes": ("cannon_a5a",),
                    # «Плазменный шторм» уже даёт r=55; +20 доводит
                    # каскад ровно до обещанных r=75, а не складывает 55+75.
                    "mods": {
                        "cascade": 20,
                        "cascade_shrapnel": 2,
                        "explosion_vulnerable": 0.10,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
            ),
        },
        {
            "key": "capacitor",
            "name": "Накопитель",
            "nodes": (
                {
                    "id": "cannon_c1",
                    "name": "Подвижный контур",
                    "tier": 1,
                    "cost": 145,
                    "desc": "при зарядке скорость +12%, полный выстрел -5% урона",
                    "mods": {"charge_move_bonus": 0.12, "full_damage_mul": -0.05},
                    "role": "ОСНОВА",
                },
                {
                    "id": "cannon_c2",
                    "name": "Аварийный накопитель",
                    "tier": 2,
                    "cost": 265,
                    "desc": "недозаряд -15% отката; ещё +8% скорости при зарядке",
                    "requires": ("cannon_c1",),
                    "mods": {
                        "partial_cooldown_cut": 0.15,
                        "charge_move_bonus": 0.08,
                    },
                    "role": "РАЗВИЛКА",
                },
                {
                    "id": "cannon_c3",
                    "name": "Ёмкий накопитель",
                    "tier": 3,
                    "cost": 435,
                    "desc": "магазин +2, перезарядка -15%, заряд на 10% дольше",
                    "requires": ("cannon_c1",),
                    "apply": {
                        "magazine_add": 2,
                        "reload_time_mul": 0.85,
                        "charge_time_mul": 1.10,
                    },
                    "role": "ГИБРИД",
                },
                {
                    "id": "cannon_c4",
                    "name": "Трофейный конденсатор",
                    "tier": 4,
                    "cost": 610,
                    "desc": "убийства с шансом 35% возвращают патрон; прямой урон -5%",
                    "requires": ("cannon_c3",),
                    "mods": {
                        "refund_kill_chance": 0.35,
                        "refund_kill_amount": 1,
                        "shot_damage_mul": -0.05,
                    },
                    "role": "КЛЮЧЕВОЕ",
                },
                {
                    "id": "cannon_c5a",
                    "name": "Бесконечный цикл",
                    "tier": 5,
                    "cost": 880,
                    "lane": -1,
                    "desc": "перезарядка -30%, шанс 30% не потратить патроны перезарядки",
                    "requires": ("cannon_c4",),
                    "excludes": ("cannon_c5b",),
                    "apply": {"reload_time_mul": 0.70},
                    "mods": {"refund_reload": 0.30},
                    "role": "АЛЬТЕРНАТИВА",
                },
                {
                    "id": "cannon_c5b",
                    "name": "Стационарный реактор",
                    "tier": 5,
                    "cost": 900,
                    "lane": 1,
                    "desc": "стоя заряд +40%, на ходу -15%, полный выстрел +10%",
                    "requires": ("cannon_c4",),
                    "excludes": ("cannon_c5a",),
                    "mods": {
                        "still_charge_speed": 0.40,
                        "moving_charge_speed": -0.15,
                        "full_damage_mul": 0.10,
                    },
                    "role": "АЛЬТЕРНАТИВА",
                },
            ),
        },
    ),
}


def inject_cannon_tree(skill_trees):
    """Добавляет дерево пушки, проверяя все ссылки на узлы.

    Функция идемпотентна: повторный импорт не создаёт дубликатов.
    """
    if "cannon" in skill_trees:
        return skill_trees
    # Сначала собираем ВСЕ id: гибрид может ссылаться на узел соседней
    # ветви, объявленный ниже (например, «Критическая масса» -> «Широкий
    # резонатор»). Проверка «уже добавлен» здесь была бы ложной ошибкой.
    all_ids = {node["id"] for branch in CANNON_TREE["branches"]
               for node in branch["nodes"]}
    branches = []
    for branch in CANNON_TREE["branches"]:
        nodes = []
        for source in branch["nodes"]:
            node = dict(source)
            node.setdefault("mods", {})
            for requirement in node.get("requires", ()):
                if requirement not in all_ids:
                    raise ValueError(
                        f"cannon: неизвестная зависимость {requirement!r}")
            node["requires"] = tuple(node.get("requires", ()))
            nodes.append(node)
        branches.append(dict(branch, nodes=tuple(nodes)))
    skill_trees["cannon"] = dict(CANNON_TREE, branches=tuple(branches))
    return skill_trees
