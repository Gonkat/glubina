"""
ОПИСАНИЯ оружия — это ДАННЫЕ, а не код.

Главное правило п.8 GDD: «добавление нового оружия не требует
переписывания боевой системы». Здесь это достигается тем, что
новое оружие = новый СЛОВАРЬ, а не новый класс.

Редкость: "обычное" | "необычное" | "редкое" | "эпическое" | "легендарное"
"""

# ---------------------------------------------------------------- ОГНЕСТРЕЛЬНОЕ
# Слот firearm — одновременно доступно только ОДНО из четырёх.
# Пистолет — универсал, пушка — заряжаемый «тяжёлый» ствол.
FIREARMS = {
    "pistol": {
        "name": "Пистолет",
        "cost": 0,
        "rarity": "обычное",
        # M11: патроны ОДИН ресурс (боезапас), аmmo_cost — сколько
        # единиц забирает ПЕРЕЗАРЯДКА одного патрона в магазин
        "ammo_cost": 1,
        "damage": 25,
        "cooldown": 0.22,       # секунд между выстрелами
        "sound": "shoot",       # звук выстрела — файл в assets/sounds/ (M8)
        "reload_time": 1.0,     # секунд на перезарядку
        "magazine": 12,
        "pellets": 1,           # сколько пуль за один выстрел
        "spread_deg": 0.0,      # разброс в градусах
        "bullet_speed": 640,    # px/сек
        "bullet_radius": 4,
        "pierce": 0,            # сколько врагов пуля задевает, не умирая
        "barrel_len": 34,       # как рисуется ствол (px)
        "barrel_w": 6,
    },
    "shotgun": {
        "name": "Дробовик",
        "cost": 240,
        "rarity": "необычное",
        "ammo_cost": 3,        # дробовой выстрел «весит» 3 единицы
        "damage": 12,
        "cooldown": 0.75,
        "sound": "shotgun",
        "reload_time": 1.6,
        "magazine": 6,
        "pellets": 7,
        "spread_deg": 22,
        "bullet_speed": 560,
        "bullet_radius": 3,
        "pierce": 0,
        "barrel_len": 40,
        "barrel_w": 9,
    },
    "sniper": {
        "name": "Снайперская винтовка",
        "cost": 620,
        "rarity": "редкое",
        "ammo_cost": 4,        # выстрел снайперки — 4 единицы
        "damage": 90,
        "cooldown": 1.1,
        "sound": "sniper",
        "reload_time": 2.0,
        "magazine": 5,
        "pellets": 1,
        "spread_deg": 0.0,
        "bullet_speed": 1100,
        "bullet_radius": 5,
        "pierce": 2,            # пробивает двоих и летит дальше
        "barrel_len": 50,
        "barrel_w": 4,
    },
    # ---------------------------------------------------------- ЭНЕРГОПУШКА
    # Особое оружие: не «ещё один пистолет», а заряжаемый выстрел.
    # Пока ЛКМ удерживается, под героем растёт шкала; при отпускании
    # снаряд получает масштаб от накопленного заряда. Параметры ниже
    # читает Firearm (weapons.py), поэтому отдельного класса нет.
    "cannon": {
        "name": "Энергопушка",
        "short_name": "ЭНЕРГОПУШКА",
        "cost": 380,
        "rarity": "редкое",
        "ammo_cost": 2,
        "damage": 46,
        "cooldown": 0.45,
        "sound": "sniper",
        "reload_time": 1.8,
        "magazine": 5,
        "pellets": 1,
        "spread_deg": 0.0,
        "bullet_speed": 620,
        "bullet_radius": 7,
        "pierce": 0,
        "barrel_len": 46,
        "barrel_w": 11,
        # --- заряд ---
        "charge_time": 1.15,       # секунд до 100%
        "min_charge": 0.35,        # ниже — безопасная отмена, без выстрела
        "charge_min_damage": 0.50, # множитель урона на нуле
        "charge_max_damage": 2.10, # множитель урона на 100%
        "charge_max_radius": 25,   # радиус хитбокса снаряда на 100%
        "charge_blast_min": 24,    # радиус взрыва на нуле
        "charge_blast_max": 64,    # радиус взрыва на 100%
        "charge_power_min": 0.80,  # множитель урона взрыва
        "charge_power_max": 1.10,
        "charge_sound": "sniper",
        "charge_start_sound": "spit_charge",
        "charge_full_sound": "lightning",
        "projectile_style": "plasma",
        "projectile_color": (112, 232, 255),
        "shake": 2.4,
    },
    # ------------------------------------------------------ МАГНИТНЫЙ ДИСК
    # Оружие УПРАВЛЯЕМОЙ ТРАЕКТОРИИ: снаряд улетает на конечную дистанцию
    # и возвращается к герою. Пока он в полёте, ЛКМ не стреляет, а
    # ПОДЗЫВАЕТ диск — игрок сам решает, когда закончить проход.
    # Обратный проход бьёт сильнее и заново может задеть тех же врагов.
    # Двигаясь, игрок «рулит» возвратом: диск летит к нему.
    "disc": {
        "name": "Магнитный диск",
        "short_name": "ДИСК",
        "cost": 340,
        "rarity": "редкое",
        "ammo_cost": 1,
        # 40 по одной цели и 62 на возврате: одиночная цель слабее
        # пистолета, но два прохода по двум целям — уже выгоднее.
        "damage": 40,
        "cooldown": 0.62,
        "sound": "shoot",
        "reload_time": 1.5,
        "magazine": 6,
        "pellets": 1,
        "spread_deg": 0.0,
        "bullet_speed": 560,
        "bullet_radius": 9,
        "pierce": 1,
        "barrel_len": 38,
        "barrel_w": 12,
        # --- возврат ---
        "returning": True,
        "return_range": 300,        # px полёта до автовозврата
        "return_speed_mul": 1.25,   # авто-возврат чуть быстрее заброса
        "return_damage_mul": 0.55,  # +55% урона на обратном проходе
        "recall_speed_mul": 1.9,    # ручной подзыв резко ускоряет диск
        "catch_refund": 0.0,        # шанс вернуть патрон при поимке
        "projectile_style": "disc",
        "projectile_color": (255, 196, 96),
        "shake": 1.6,
    },
    # ------------------------------------------------------- ДУГОВАЯ ПУШКА
    # Оружие ЦЕПНЫХ АТАК: попадание перескакивает на ближние цели дугой.
    # Одиночная цель получает меньше, чем у пистолета, но группа из трёх-
    # четырёх врагов — заметно больше: сила зависит от плотности толпы.
    "arc": {
        "name": "Дуговая пушка",
        "short_name": "ДУГА",
        "cost": 400,
        "rarity": "редкое",
        "ammo_cost": 1,
        "damage": 28,
        "cooldown": 0.5,
        "sound": "lightning",
        "reload_time": 1.4,
        "magazine": 8,
        "pellets": 1,
        "spread_deg": 0.0,
        "bullet_speed": 720,
        "bullet_radius": 5,
        "pierce": 0,
        "barrel_len": 42,
        "barrel_w": 8,
        # --- цепь ---
        "chain_jumps": 3,           # сколько ПЕРЕХОДОВ после попадания
        "chain_range": 170,         # px на каждый переход
        "chain_falloff": 0.72,      # множитель урона на каждом переходе
        "projectile_style": "arc",
        "projectile_color": (150, 190, 255),
        "shake": 1.2,
    },
    # ---------------------------------------------------- ПЛАЗМЕННЫЙ РЕЗАК
    # Оружие РИСКА И НАГРАДЫ: каждый выстрел греет контур. Чем горячее
    # ствол, тем сильнее выстрел, но на 100% происходит ПРИНУДИТЕЛЬНЫЙ
    # СБРОС: короткая блокировка, толчок по врагам и немного урона герою.
    # Игрок сам выбирает: остывать заранее или «дожать» горячую очередь.
    "cutter": {
        "name": "Плазменный резак",
        "short_name": "РЕЗАК",
        "cost": 440,
        "rarity": "редкое",
        "ammo_cost": 1,
        "damage": 30,
        "cooldown": 0.26,
        "sound": "shoot",
        "reload_time": 1.5,
        "magazine": 10,
        "pellets": 1,
        "spread_deg": 0.0,
        "bullet_speed": 780,
        "bullet_radius": 4,
        "pierce": 1,
        "barrel_len": 40,
        "barrel_w": 7,
        # --- тепло ---
        "heat_per_shot": 0.18,     # шесть выстрелов до сброса
        "heat_cool": 0.42,         # единиц тепла в секунду
        "heat_cool_delay": 0.35,   # пауза перед остыванием
        "heat_damage_bonus": 0.85, # +85% урона на пике нагрева
        "vent_time": 1.15,         # блокировка после сброса
        "vent_self_damage": 7.0,   # цена ошибки
        "vent_radius": 105,
        "vent_blast": 30.0,
        "vent_knockback": 220.0,
        "projectile_style": "cutter",
        "projectile_color": (255, 128, 96),
        "shake": 1.4,
    },
}

# Новые стволы не входят в случайную витрину, но и не «гарантированы»
# поимённо: в оружейном магазине всегда лежит 2-3 прототипа из этой
# тройки. Так билд на новом оружии не зависит от удачи, а витрина
# не превращается в каталог из восьми пушек.
PROTOTYPE_FIREARMS = ("disc", "arc", "cutter")

# Какие стволы гарантированно лежат в каждом оружейном магазине.
# Это не случайный ассортимент: игрок всегда может купить точку входа
# в новую ветвь, даже если ему не выпал нужный магазин у старта.
GUARANTEED_FIREARMS = ("pistol", "cannon")

# ---------------------------------------------------------------- БОЕПРИПАСЫ
# M11: ОДИН ресурс — «боезапас» (GDD п.5, экономика патронов).
# Так выпад 12ga никогда не пропадает зря: у игрока нет «чужих» калибров.
# Сколько единиц тратит выстрел — атрибут оружия (spec["ammo_cost"]).
AMMO_NAME = "Боезапас"
START_AMMO = 80              # стартовый запас единиц (≈80 выстрелов пистолета)

# ---------------------------------------------------------------- ОРУЖИЕ БЛИЖНЕГО БОЯ
# "attack" выбирает МЕХАНИКУ атаки (класс из attacks.py), остальное — числа.
#  arc_slash — рубящий удар по дуге (Тип 1)
#  delayed   — удар с задержкой существования зоны (Тип 2)
#  shockwave — расходящаяся ударная волна (Тип 3)
#  aura      — пассивная контактная аура (Тип 4)
MELEE = {
    "knife": {
        "name": "Нож",
        "cost": 0,
        "upgrade_cost": 40,
        "rarity": "обычное",
        "attack": "delayed",
        "damage": 18,
        "cooldown": 0.32,
        "reach": 78,          # дальность зоны поражения (px)
        "arc_deg": 26,        # ширина зоны (градусов)
        "windup": 0.05,       # задержка перед появлением зоны
        "hitbox_time": 0.1,   # сколько живёт зона после появления
        "knockback": 90,
        "color": (225, 230, 240),
    },
    "machete": {
        "name": "Мачете",
        "cost": 220,
        "upgrade_cost": 70,
        "rarity": "обычное",
        "attack": "arc_slash",
        "damage": 30,
        "cooldown": 0.5,
        "reach": 96,
        "arc_deg": 45,        # полный угол замаха
        "swing_time": 0.26,   # длительность всего замаха
        "blade_deg": 18,      # толщина «лезвия» (как широкая зона удара)
        "knockback": 170,
        "color": (210, 215, 225),
    },
    "katana": {
        "name": "Катана",
        "cost": 520,
        "upgrade_cost": 110,
        "rarity": "редкое",
        "attack": "delayed",
        "damage": 45,
        "cooldown": 0.55,
        "reach": 135,
        "arc_deg": 34,
        "windup": 0.08,
        "hitbox_time": 0.45,  # главное преимущество катаны — живая зона
        "knockback": 230,
        "color": (190, 225, 255),
    },
    "hammer": {
        "name": "Молот",
        "cost": 500,
        "upgrade_cost": 100,
        "rarity": "редкое",
        "attack": "shockwave",
        "damage": 55,
        "cooldown": 1.0,
        "radius": 125,        # радиус локального эпицентра
        "handle_base": 95,
        "handle_min": 48,
        "handle_max": 235,
        "wave_time": 0.35,    # сколько волна расширяется
        "knockback": 420,
        "color": (255, 160, 70),
    },
    "shovel": {
        "name": "Метла",
        "cost": 300,
        "upgrade_cost": 60,
        "rarity": "необычное",
        "attack": "arc_slash",
        "damage": 22,
        "cooldown": 0.65,
        "reach": 112,
        "dust_damage": 0.015,
        "dust_duration": 2.4,
        "dust_stack_cap": 1,
        "dust_slow": 0.10,
        "arc_deg": 75,        # та же механика, что у мачете, но шире и медленнее
        "swing_time": 0.4,
        "blade_deg": 26,
        "knockback": 300,
        "color": (180, 200, 170),
    },
    "shield": {
        "name": "Щит",
        "cost": 380,
        "upgrade_cost": 90,
        "rarity": "необычное",
        "attack": "aura",
        "damage": 8,          # слабый контактный урон
        "cooldown": 0,         # пассивно — отката нет
        "radius": 88,
        "tick": 0.55,          # как часто бьёт по одному врагу
        "knockback": 160,
        "color": (255, 214, 96),
    },
}

# ---------------------------------------------------------------- РЕЖИМЫ ПИСТОЛЕТА
# Пистолет — универсал: его ветвь «Арсенал» (skill_pistol.py) открывает
# насадки, которые в ОСЛАБЛЕННОМ виде повторяют механики других школ.
# Профиль — чистые ДАННЫЕ, поэтому новый режим не требует нового класса.
#
# Поля:
#   source        — чьё оружие копируется (для бонусов подготовки);
#   rounds        — сколько патронов магазина стоит ОДИН выстрел;
#   damage_mul    — множитель урона базовой пули пистолета;
#   pellets       — сколько дробин вместо spec["pellets"];
#   spread_deg    — конус вместо spec["spread_deg"];
#   pierce/wall_pen/explode/knockback/bleed — добавки к параметрам пули;
#   cooldown_mul  — расплата за мощь режима;
#   training_*    — бонус за глубокую подготовку исходного оружия.
PISTOL_MODES = {
    "standard": {
        "name": "Точечный",
        "short": "ТОЧКА",
        "rounds": 1,
        "color": (112, 208, 242),
        "desc": "одиночный точный выстрел без штрафов",
    },
    "scatter": {
        "name": "Картечь",
        "short": "КАРТЕЧЬ",
        "source": "shotgun",
        "rounds": 2,
        "sound": "shotgun",
        "shake": 1.8,
        "damage_mul": 0.38,
        "pellets": 3,
        "spread_deg": 16.0,
        "cooldown_mul": 1.12,
        "knockback": 30.0,
        "explode_cap": 20.0,
        "color": (248, 180, 92),
        "desc": "3 дробины по 38% урона; ближний бой, 2 патрона",
    },
    "lance": {
        "name": "Копьё",
        "short": "КОПЬЁ",
        "source": "sniper",
        "rounds": 2,
        "sound": "sniper",
        "shake": 2.6,
        "damage_mul": 1.75,
        "pierce": 2,
        "wall_pen": 1,
        "bullet_speed_mul": 1.2,
        "cooldown_mul": 1.8,
        "color": (174, 154, 255),
        "desc": "тяжёлая пуля: +2 пробития, 1 блок стены, 2 патрона",
    },
    "hammer": {
        "name": "Молот",
        "short": "МОЛОТ",
        "source": "hammer",
        "rounds": 3,
        "sound": "shoot",
        "shake": 3.2,
        "damage_mul": 1.15,
        "explode": 45.0,
        "knockback": 220.0,
        "cooldown_mul": 2.0,
        "color": (255, 166, 78),
        "desc": "взрыв r=45 и отбрасывание; 3 патрона",
    },
    "bleed": {
        "name": "Надрез",
        "short": "НАДРЕЗ",
        "source": "knife",
        "rounds": 1,
        "sound": "shoot",
        "shake": 1.1,
        "damage_mul": 0.85,
        "bleed": 0.45,
        "cooldown_mul": 1.05,
        "color": (234, 152, 92),
        "desc": "пули вызывают кровотечение; дешёвый режим",
    },
    # Новый режим для нового оружия: пистолет получает собственный
    # заряжаемый плазменный выстрел. Это не копия пушки 1-в-1: заряд
    # короче, снаряд легче, а цена — два патрона. Все параметры читает
    # та же charge-механика Firearm, поэтому отдельного класса нет.
    "plasma": {
        "name": "Плазма",
        "short": "ПЛАЗМА",
        "source": "cannon",
        "rounds": 2,
        "sound": "sniper",
        "shake": 2.8,
        "damage_mul": 0.95,
        "bullet_speed_mul": 1.10,
        "cooldown_mul": 1.35,
        "color": (112, 232, 255),
        "desc": "удержание ЛКМ: короткий заряд, плазменный взрыв; 2 патрона",
        "charge_time": 0.85,
        "min_charge": 0.25,
        "charge_min_damage": 0.55,
        "charge_max_damage": 1.85,
        "charge_max_radius": 18,
        "charge_blast_min": 10,
        "charge_blast_max": 48,
        "charge_power_min": 0.75,
        "charge_power_max": 1.05,
        "charge_sound": "sniper",
        "charge_start_sound": "spit_charge",
        "charge_full_sound": "lightning",
        "projectile_style": "plasma",
        "projectile_color": (112, 232, 255),
    },
}

PISTOL_MODE_ORDER = ("standard", "scatter", "lance", "hammer", "bleed",
                     "plasma")

# Какой узел древа открывает режим. Идентификаторы — часть сохранения
# прогресса, поэтому они не меняются при балансных правках.
PISTOL_MODE_NODES = {
    "scatter": "pistol_x_scatter",
    "lance": "pistol_x_lance",
    "hammer": "pistol_x_hammer",
    "bleed": "pistol_x_bleed",
    "plasma": "pistol_p1",
}

# Исторический список источников режимов «Арсенала». Магазин жетонов
# теперь использует TOKEN_KEYS, чтобы охватить все десять школ.
PISTOL_SOURCE_WEAPONS = ("shotgun", "sniper", "hammer", "knife", "cannon")

# ------------------------------------------------------------ ЖЕТОНЫ ШКОЛ
# Жетон — это не «валюта одного ствола». Школы образуют родственные
# группы: картечь/взрыв, точность/энергия, удар/щит, клинок. Поэтому
# жетон дробовика может закрыть подготовку пушки, а жетон снайперки —
# подготовку пистолетного «Копья» или плазменной ветви.
TOKEN_KEYS = tuple((*FIREARMS, *MELEE))
TOKEN_NAMES = {key: spec["name"]
               for key, spec in {**FIREARMS, **MELEE}.items()}

TOKEN_FAMILIES = {
    "scatter": ("shotgun", "cannon"),
    "precision": ("sniper", "cannon", "pistol", "arc"),
    "impact": ("hammer", "shovel", "shield"),
    "edge": ("knife", "machete", "katana"),
    "orbit": ("disc", "arc"),
    "heat": ("cutter", "cannon"),
}

TOKEN_SUBSTITUTES = {
    "shotgun": ("shotgun", "cannon"),
    "cannon": ("cannon", "shotgun", "sniper"),
    "sniper": ("sniper", "pistol", "cannon"),
    "pistol": ("pistol", "sniper", "cannon"),
    "hammer": ("hammer", "shovel", "shield"),
    "shovel": ("shovel", "hammer", "shield"),
    "shield": ("shield", "hammer", "shovel"),
    "knife": ("knife", "machete", "katana"),
    "machete": ("machete", "knife", "katana"),
    "katana": ("katana", "knife", "machete"),
    # Новое оружие принимает жетоны родственных школ: диск — метательное
    # и энергетическое, дуга — точность и пистолет, резак — пушку.
    "disc": ("disc", "cannon", "shotgun"),
    "arc": ("arc", "sniper", "pistol"),
    "cutter": ("cutter", "cannon", "sniper"),
}

# В финале M5 оружие меняется ТОЛЬКО через магазин (shop_data.py):
# тестовые словари переключателей удалены. Для юнит-тестов остались
# методы Player.switch_firearm/switch_melee — они принимают ключи выше.
#
# Энергопушка не входит в случайный пул: она лежит в гарантированной
# витрине (GUARANTEED_FIREARMS), иначе её ветвь зависела бы от удачи.
