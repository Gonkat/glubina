"""
ВЕТВЬ «АРСЕНАЛ» ПИСТОЛЕТА.

Пистолет — универсальное оружие. Его четвёртая ветвь не усиливает числа,
а открывает РЕЖИМЫ ОГНЯ (V), которые в ослабленном виде повторяют
механики других школ:

    Картечь  — дробовик: несколько слабых дробин, ближний бой;
    Копьё    — снайперка: тяжёлая пробивающая пуля;
    Молот    — молот: взрыв и отбрасывание;
    Надрез   — нож: кровотечение.

Каждый режим — это компромисс: он тратит больше патронов и времени,
чем обычный выстрел, и заметно уступает исходному оружию в его нише.
Поэтому пистолет остаётся удобным «швейцарским ножом», но не заменяет
специалиста.

Зависимости:
  * режим требует подготовки исходной школы: один купленный узел её
    древа ИЛИ жетон тренировки из оружейного магазина (для случая,
    когда оружие ещё не получено);
  * tier-3 специализация требует ещё и соседний узел пистолета, поэтому
    ветви связаны, а не изолированы;
  * tier-3 доступен только если «Арсенал» — основная ветвь (общее
    правило глубины). Так игрок выбирает между классическими ветвями
    и глубокой универсальностью.

Данные лежат отдельно от правил: skill_tree.py читает поля requires,
training, mods; бой читает mods через weapons.py. Старые id не меняются.
"""

PISTOL_ARSENAL = {
    "key": "arsenal",
    "name": "Арсенал",
    "nodes": (
        {
            "id": "pistol_x1",
            "name": "Полевой устав",
            "tier": 1,
            "cost": 140,
            "desc": "V — смена режима огня; открывает насадки чужих школ",
            "mods": {"mode_switch": 1},
            "role": "ОСНОВА",
            # Сам по себе устав не выбирает специализацию: иначе дешёвый
            # вход в «Арсенал» запирал бы глубокие классические ветви.
            "no_main": True,
        },
        {
            "id": "pistol_x_scatter",
            "name": "Картечный насадок",
            "tier": 2,
            "cost": 220,
            "desc": "режим «Картечь»: 3 дробины по 38%, 2 патрона за выстрел",
            "requires": ("pistol_x1",),
            "training": ("shotgun", 1),
            "mods": {"unlock_scatter": 1},
            "mode": "scatter",
            "role": "НАСАДКА",
        },
        {
            "id": "pistol_x_lance",
            "name": "Винтовочный насадок",
            "tier": 2,
            "cost": 230,
            "desc": "режим «Копьё»: +2 пробития, 1 блок стены, 2 патрона",
            "requires": ("pistol_x1",),
            "training": ("sniper", 1),
            "mods": {"unlock_lance": 1},
            "mode": "lance",
            "role": "НАСАДКА",
        },
        {
            "id": "pistol_x_hammer",
            "name": "Ударный насадок",
            "tier": 2,
            "cost": 240,
            "desc": "режим «Молот»: взрыв r=45, отбрасывание, 3 патрона",
            "requires": ("pistol_x1",),
            "training": ("hammer", 1),
            "mods": {"unlock_hammer": 1},
            "mode": "hammer",
            "role": "НАСАДКА",
        },
        {
            "id": "pistol_x_bleed",
            "name": "Режущий патрон",
            "tier": 2,
            "cost": 210,
            "desc": "режим «Надрез»: пули кровоточат; дешёвый режим",
            "requires": ("pistol_x1",),
            "training": ("knife", 1),
            "mods": {"unlock_bleed": 1},
            "mode": "bleed",
            "role": "НАСАДКА",
        },
        {
            "id": "pistol_x_scatter3",
            "name": "Кучная картечь",
            "tier": 3,
            "cost": 380,
            "desc": "+1 дробина, уже веер, +6% урона; взрыв дробины до r=20",
            "requires": ("pistol_x_scatter", "pistol_m2"),
            "training": ("shotgun", 2),
            "hybrid": True,
            "mods": {"scatter_pellets_add": 1, "scatter_spread_add": -4.0,
                     "scatter_damage_mul": 0.06},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
        {
            "id": "pistol_x_lance3",
            "name": "Бронебойный наконечник",
            "tier": 3,
            "cost": 400,
            "desc": "+1 пробитие и +1 блок стены в режиме «Копьё»",
            "requires": ("pistol_x_lance", "pistol_m1"),
            "training": ("sniper", 2),
            "hybrid": True,
            "mods": {"lance_pierce_add": 1, "lance_wall_pen_add": 1},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
        {
            "id": "pistol_x_hammer3",
            "name": "Резонанс",
            "tier": 3,
            "cost": 400,
            "desc": "+15 к радиусу взрыва; попадание оглушает на 0.35 с",
            "requires": ("pistol_x_hammer", "pistol_e2"),
            "training": ("hammer", 2),
            "hybrid": True,
            "mods": {"hammer_radius_add": 15.0, "hammer_stun": 0.35,
                     "hammer_stun_range": 700.0},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
        {
            "id": "pistol_x_bleed3",
            "name": "Кровопуск",
            "tier": 3,
            "cost": 380,
            "desc": "+20% кровотечения; смерть разносит кровь в радиусе 80",
            "requires": ("pistol_x_bleed", "pistol_e2"),
            "training": ("knife", 2),
            "hybrid": True,
            "mods": {"bleed_add": 0.20, "bleed_spread": 0.40,
                     "bleed_spread_radius": 80.0},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
    ),
}


def inject_pistol_arsenal(skill_trees):
    """Добавляет четвёртую ветвь пистолета, не трогая прежние id."""
    tree = skill_trees["pistol"]
    branches = list(tree["branches"])
    if any(branch["key"] == "arsenal" for branch in branches):
        return skill_trees

    existing = {node["id"] for branch in branches for node in branch["nodes"]}
    nodes = []
    for source in PISTOL_ARSENAL["nodes"]:
        node = dict(source)
        node.setdefault("mods", {})
        for req in node.get("requires", ()):
            if req not in existing:
                raise ValueError(
                    f"pistol arsenal: неизвестная зависимость {req!r}")
        existing.add(node["id"])
        nodes.append(node)

    branch = dict(PISTOL_ARSENAL)
    branch["nodes"] = tuple(nodes)
    branches.append(branch)
    tree["branches"] = tuple(branches)
    return skill_trees


# Пятая ветвь — ответ на появление энергопушки. Она не копирует пушку
# целиком, а даёт пистолету заряжаемый режим «Плазма»: короткий заряд,
# два патрона за выстрел, меньший взрыв и никакой защиты от раннего
# отпускания. Это отдельная специализация, а не ещё один процент урона.
PISTOL_PLASMA = {
    "key": "plasma",
    "name": "Плазменный контур",
    "nodes": (
        {
            "id": "pistol_p1",
            "name": "Плазменный насадок",
            "tier": 1,
            "cost": 190,
            "requires": ("pistol_x1",),
            "training": ("cannon", 1),
            "desc": "V — режим «Плазма»: удержание ЛКМ заряжает выстрел; 2 патрона",
            "mode": "plasma",
            "role": "ОСНОВА",
        },
        {
            "id": "pistol_p2",
            "name": "Быстрый конденсатор",
            "tier": 2,
            "cost": 310,
            "requires": ("pistol_p1",),
            "desc": "заряд плазмы на 18% быстрее; откат после выстрела не растёт",
            "mods": {"charge_speed_add": 0.18},
            "role": "РАЗВИЛКА",
        },
        {
            "id": "pistol_p3",
            "name": "Резонансный сердечник",
            "tier": 3,
            "cost": 470,
            "requires": ("pistol_p2", "pistol_m2"),
            "training": ("cannon", 2),
            "hybrid": True,
            "desc": "+8 к радиусу взрыва и +1 пробитие полного заряда; нужна подготовка пушки 2",
            "mods": {"blast_radius_add": 8.0, "full_pierce": 1},
            "role": "ГИБРИД",
        },
        {
            "id": "pistol_p4",
            "name": "Критический контур",
            "tier": 4,
            "cost": 650,
            "requires": ("pistol_p3",),
            "desc": "полный заряд: +25% урона, +15% хитбокса и +6 к взрыву",
            "mods": {"full_damage_mul": 0.25, "full_radius_mul": 0.15,
                     "blast_radius_add": 6.0},
            "role": "КЛЮЧЕВОЕ",
        },
        {
            "id": "pistol_p5a",
            "name": "Сингулярный разряд",
            "tier": 5,
            "cost": 900,
            "lane": -1,
            "requires": ("pistol_p4",),
            "excludes": ("pistol_p5b",),
            "desc": "полный взрыв +22, оглушает 0.5 с и замедляет на 1.5 с",
            "mods": {"full_blast_add": 22.0, "blast_stun": 0.5,
                     "explosion_slow": 1.5},
            "role": "АЛЬТЕРНАТИВА",
        },
        {
            "id": "pistol_p5b",
            "name": "Плазменный таран",
            "tier": 5,
            "cost": 900,
            "lane": 1,
            "requires": ("pistol_p4",),
            "excludes": ("pistol_p5a",),
            "desc": "полный заряд: +3 пробития, +260 отбрасывания и +20% хитбокса",
            "mods": {"full_pierce": 3, "knockback": 260.0,
                     "full_radius_mul": 0.20},
            "role": "АЛЬТЕРНАТИВА",
        },
        {
            "id": "pistol_p6a",
            "name": "Гравитационный ожог",
            "tier": 6,
            "cost": 820,
            "requires": ("pistol_p5a",),
            "excludes": ("pistol_p5b",),
            "desc": "взрыв +26, оглушение +0.3 с, замедление +1 с",
            "mods": {"full_blast_add": 26.0, "blast_stun": 0.3,
                     "explosion_slow": 1.0},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
        {
            "id": "pistol_p6b",
            "name": "Копьё плазмы",
            "tier": 6,
            "cost": 820,
            "requires": ("pistol_p5b",),
            "excludes": ("pistol_p5a",),
            "desc": "полный заряд +15% урона, +1 пробитие и +120 отбрасывания",
            "mods": {"full_damage_mul": 0.15, "full_pierce": 1,
                     "knockback": 120.0},
            "role": "СПЕЦИАЛИЗАЦИЯ",
        },
    ),
}


def inject_pistol_plasma(skill_trees):
    """Добавляет пятую ветвь пистолета — плазменный режим пушки."""
    tree = skill_trees["pistol"]
    branches = list(tree["branches"])
    if any(branch["key"] == "plasma" for branch in branches):
        return skill_trees

    existing = {node["id"] for branch in branches for node in branch["nodes"]}
    nodes = []
    for source in PISTOL_PLASMA["nodes"]:
        node = dict(source)
        node.setdefault("mods", {})
        for req in node.get("requires", ()):
            if req not in existing:
                raise ValueError(
                    f"pistol plasma: неизвестная зависимость {req!r}")
        existing.add(node["id"])
        nodes.append(node)

    branch = dict(PISTOL_PLASMA)
    branch["nodes"] = tuple(nodes)
    branches.append(branch)
    tree["branches"] = tuple(branches)
    return skill_trees
