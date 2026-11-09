"""
ДАННЫЕ артефактов — два слота по GDD: активный (клавиша F) и пассивный.

Как и в weapon_data.py: здесь только цифры и имена.
Поведение живёт в classes файла artifacts.py — потому что артефакты
МЕНЯЮТ ПОВЕДЕНИЕ (скорость, урон, способности), а не только числа.
"""
ARTIFACTS = {
    # ------------------------------------------------- ПАССИВНЫЕ
    "boots": {
        "name": "Сапоги-скороходы",
        "cost": 300,
        "rarity": "необычное",
        "slot": "passive",
        "speed_mult": 1.25,      # множитель скорости героя
    },
    "armor": {
        "name": "Кираса",
        "cost": 350,
        "rarity": "необычное",
        "slot": "passive",
        "damage_taken": 0.70,    # доля получаемого урона
    },
    "amulet": {
        "name": "Амулет жизни",
        "cost": 420,
        "rarity": "редкое",
        "slot": "passive",
        "hp_bonus": 35,          # к максимуму HP (и сразу лечит на столько)
    },
    "fang": {
        "name": "Клык монстра",
        "cost": 460,
        "rarity": "редкое",
        "slot": "passive",
        "damage_mult": 1.15,     # множитель урона всего оружия
    },
    # ------------------------------------------------- АКТИВНЫЕ (клавиша F)
    "dash": {
        "name": "Фантомный шаг",
        "cost": 260,
        "rarity": "обычное",
        "slot": "active",
        "cooldown": 4.0,
        "distance": 190,         # px — куда и как далеко
        "time": 0.16,            # секунд — за сколько пролетает
    },
    "nova": {
        "name": "Энергетическая волна",
        "cost": 520,
        "rarity": "редкое",
        "slot": "active",
        "cooldown": 12.0,
        "radius": 175,
        "damage": 45,
        "knockback": 650,
    },
    "shield": {
        "name": "Щит доблести",
        "cost": 480,
        "rarity": "редкое",
        "slot": "active",
        "cooldown": 25.0,
        "duration": 2.5,         # секунд полной неуязвимости
    },
    # ------------------------------------------------- ЭПИЧЕСКИЕ / ЛЕГЕНДАРНЫЕ (M7)
    # Уникальное поведение = отдельные классы в artifacts.py.
    # save_cooldown/heal/targets — параметры, всё настраиваемо.
    "devourer": {
        "name": "Пожиратель",
        "cost": 780,
        "rarity": "эпическое",
        "slot": "passive",
        "heal": 2,               # HP за каждое убийство (вампиризм)
    },
    "heart": {
        "name": "Сердце титана",
        "cost": 950,
        "rarity": "легендарное",
        "slot": "passive",
        "save_cooldown": 60.0,   # секунд между спасениями от смерти
    },
    "thunder": {
        "name": "Громовержец",
        "cost": 1000,
        "rarity": "легендарное",
        "slot": "active",
        "cooldown": 15.0,
        "targets": 3,            # сколько ближайших врагов бьёт молния
        "range": 420,            # дальность удара (px)
        "damage": 55,
    },
}

ALL_KEYS = tuple(ARTIFACTS)
PASSIVE_KEYS = tuple(k for k, s in ARTIFACTS.items() if s["slot"] == "passive")
ACTIVE_KEYS = tuple(k for k, s in ARTIFACTS.items() if s["slot"] == "active")
