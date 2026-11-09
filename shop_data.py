"""
Правила магазинов и ассортимент хранятся отдельно от игровой логики.
Новый тип магазина добавляется записью в SHOP_TYPES и настройкой его
вероятности в settings.py.
"""
import random

from artifact_data import ARTIFACTS
from settings import (
    SHOP_PRICE_MULTIPLIER_RANGE,
    SHOP_SPAWN_CHANCES,
    SHOP_STOCK_COUNTS,
    UPGRADE_BONUS,
)
from weapon_data import (AMMO_NAME, FIREARMS, GUARANTEED_FIREARMS, MELEE,
                         PROTOTYPE_FIREARMS, TOKEN_KEYS)

# Жетоны тренировки продаются в оружейном магазине. Цена выше обычного
# насадка: это способ обойти необходимость покупать чужое оружие.
# Теперь жетон есть у каждой школы, включая пистолет и энергопушку:
# жетоны нужны не только для подготовки, но и для углубления второй ветви.
TRAINING_TOKEN_PRICES = {
    "pistol": 200,
    "shotgun": 240,
    "sniper": 290,
    "cannon": 310,
    "hammer": 260,
    "knife": 180,
    "machete": 210,
    "katana": 270,
    "shovel": 190,
    "shield": 230,
    "disc": 250,
    "arc": 270,
    "cutter": 290,
}

SHOP_TYPES = {
    "weapons": {
        "name": "ОРУЖЕЙНЫЙ МАГАЗИН",
        "color": (224, 84, 72),
        "chance": SHOP_SPAWN_CHANCES.get("weapons", 0),
        "pools": {
            "firearm": tuple(
                {"kind": "firearm", "key": key}
                for key, spec in FIREARMS.items()
                if spec["cost"] > 0
                and key not in GUARANTEED_FIREARMS
                and key not in PROTOTYPE_FIREARMS
            ),
            # Стартовый пистолет нельзя «потерять» навсегда: после ухода
            # в дробовик игрок должен иметь возможность вернуться к
            # универсальному оружию и его ветви «Арсенал».
            "sidearm": (
                {"kind": "firearm", "key": "pistol", "price": 80},
            ),
            # Энергопушка — гарантированная точка входа в новую ветвь.
            # Она не зависит от случайного пула firearm и всегда лежит
            # на витрине; базовая цена фиксирована, как у возврата пистолета.
            "cannon": (
                {"kind": "firearm", "key": "cannon", "price": 380},
            ),
            # Прототипы новых школ: диск, дуга и резак. В витрине всегда
            # лежат 2-3 из них, поэтому билд не зависит от случайного
            # пула, но и не выдаётся бесплатно.
            "prototype": tuple(
                {"kind": "firearm", "key": key,
                 "price": FIREARMS[key]["cost"]}
                for key in PROTOTYPE_FIREARMS
            ),
            "melee": tuple(
                {"kind": "melee", "key": key}
                for key, spec in MELEE.items() if spec["cost"] > 0
            ),
            "token": tuple(
                {"kind": "token", "key": key,
                 "price": TRAINING_TOKEN_PRICES[key]}
                for key in TOKEN_KEYS
            ),
        },
    },
    "supplies": {
        "name": "МАГАЗИН ПРИПАСОВ",
        "color": (80, 164, 232),
        "chance": SHOP_SPAWN_CHANCES.get("supplies", 0),
        "pools": {
            # M11: один ресурс — «боезапас» (цена за единицу ≈ 1.7 монеты)
            "ammo": (
                {"kind": "ammo", "key": "ammo", "pack": 30, "price": 40},
            ),
            "consumable": (
                {"kind": "consumable", "key": "grenade", "name": "Граната",
                 "pack": 1, "price": 40},
            ),
        },
    },
    "artifacts": {
        "name": "МАГАЗИН АРТЕФАКТОВ",
        "color": (178, 104, 230),
        "chance": SHOP_SPAWN_CHANCES.get("artifacts", 0),
        "pools": {
            "artifact": tuple(
                {"kind": "artifact", "key": key} for key in ARTIFACTS
            ),
        },
    },
}


def generate_shop_inventory(store_type, rng=None):
    """Создаёт ограниченный ассортимент и фиксирует случайные цены."""
    if store_type not in SHOP_TYPES:
        raise ValueError(f"Неизвестный тип магазина: {store_type!r}")
    rng = rng or random

    inventory = []
    for kind, pool in SHOP_TYPES[store_type]["pools"].items():
        if not pool:
            continue
        minimum, maximum = SHOP_STOCK_COUNTS[kind]
        count = min(rng.randint(minimum, maximum), len(pool))
        for source in rng.sample(pool, count):
            offer = dict(source)
            base_price = _base_price(offer)
            multiplier = rng.uniform(*SHOP_PRICE_MULTIPLIER_RANGE)
            offer["base_price"] = base_price
            offer["price"] = max(1, round(base_price * multiplier))
            inventory.append(offer)
    return inventory


def _base_price(offer):
    kind = offer["kind"]
    if kind == "firearm":
        return offer.get("price", FIREARMS[offer["key"]]["cost"])
    if kind == "melee":
        return offer.get("price", MELEE[offer["key"]]["cost"])
    if kind == "artifact":
        return ARTIFACTS[offer["key"]]["cost"]
    if kind == "token":
        return TRAINING_TOKEN_PRICES.get(offer["key"], offer["price"])
    return offer["price"]


def _slot_table(kind):
    """Таблица weapon_data для вида оружия: 'firearm' → FIREARMS и т.д."""
    return FIREARMS if kind == "firearm" else MELEE


def upgrade_offers(game, price_multiplier=1.0):
    """
    Линейная прокачка (+25% урона за уровень) осталась у БЛИЖНЕГО БОЯ:
    это быстрый способ поднять урон, пока ветви оружия покупаются на
    общей доске навыков (skill_tree_ui, T / Y).
    """
    offers = []
    weapon = game.player.melee
    if weapon is not None:
        price = max(1, round(weapon.upgrade_cost() * price_multiplier))
        offers.append({
            "kind": "upgrade",
            "weapon": weapon,
            "price": price,
        })
    return offers


def _artifact_in_slot(game, key):
    """Экипированный артефакт ДРУГОГО ключа в том же слоте (или None)."""
    spec = ARTIFACTS[key]
    slot = ("active_artifact" if spec["slot"] == "active"
            else "passive_artifact")
    current = game.player.equipment.get(slot)
    if current is not None and current.key != key:
        return current
    return None


def offer_refund(game, offer):
    """
    Сколько вернётся при замене: огнестрельное — только за улучшения,
    ближний бой и артефакты — по прежнему правилу. Процент настраивается.
    Для неэкипированного ключа — 0.
    """
    if offer["kind"] in ("firearm", "melee"):
        current = game.player.equipment.get(offer["kind"])
        if current is not None and current.key != offer["key"]:
            if offer["kind"] == "firearm":
                return current.upgrade_refund_value()
            return current.refund_value()
        return 0
    if offer["kind"] == "artifact":
        current = _artifact_in_slot(game, offer["key"])
        return current.refund_value() if current else 0
    return 0


def offer_rarity(game, offer):
    """
    Редкость предмета для подсветки строки в UI (M7).
    Патроны/улучшения редкости не имеют → None.
    """
    kind = offer["kind"]
    if kind in ("firearm", "melee"):
        return _slot_table(kind)[offer["key"]]["rarity"]
    if kind == "artifact":
        return ARTIFACTS[offer["key"]]["rarity"]
    if kind == "token":
        spec = FIREARMS.get(offer["key"]) or MELEE[offer["key"]]
        return spec["rarity"]
    return None


def offer_view(game, offer):
    """
    (название, цена, пояснение) — превращение ДАННЫХ в строку для UI.
    Показывает возврат за старое оружие прямо в пояснении — игрок
    видит полную «сделку», а не только ценник.
    """
    kind = offer["kind"]
    if kind in ("firearm", "melee"):
        spec = _slot_table(kind)[offer["key"]]
        if kind == "firearm":
            if offer["key"] == "cannon":
                note = ("удерживайте ЛКМ: заряд 1.15с · урон 46→97 · "
                        "взрыв и хитбокс растут")
            elif offer["key"] == "disc":
                note = ("ЛКМ — заброс, повторный ЛКМ — подзыв; "
                        "возврат бьёт +55%")
            elif offer["key"] == "arc":
                note = ("цепь: попадание перескакивает на 3 цели, "
                        "урон затухает до 72%")
            elif offer["key"] == "cutter":
                note = ("нагрев: до +85% урона, перегрев бьёт по герою "
                        "и блокирует ствол")
            else:
                note = (f"урон {spec['damage']} · {spec['magazine']} патр. · "
                        f"{1.0 / max(0.01, spec['cooldown']):.1f} выстр./с")
        else:
            note = (f"урон {spec['damage']} · откат {spec['cooldown']:.2f}с · "
                    f"{spec['rarity']}")
        refund = offer_refund(game, offer)
        if refund:
            note += f"; старое вернёт +{refund}"
        return spec["name"], offer["price"], note
    if kind == "token":
        spec = FIREARMS.get(offer["key"]) or MELEE[offer["key"]]
        have = game.player.weapon_training.get(offer["key"], 0)
        if have >= 3:
            note = "максимум · жетон для второй ветви"
        else:
            note = "жетон подготовки +1"
        return f"Жетон: {spec['name']}", offer["price"], note
    if kind == "ammo":
        return (f"{AMMO_NAME} x{offer['pack']}",
                offer["price"], "единый запас для всего оружия")
    if kind == "consumable":
        return (f"{offer['name']} x{offer['pack']}",
                offer["price"], "расходник, Q — бросок")
    if kind == "upgrade":
        weapon = offer["weapon"]
        if not weapon.is_upgradable:
            return f"{weapon.name}: МАКС", 0, "улучшений больше нет"
        nxt = weapon.damage * (1.0 + UPGRADE_BONUS)
        return (f"{weapon.name} -> ур. {weapon.upgrade_level + 1}",
                offer["price"],
                f"урон {weapon.damage:.0f} -> {nxt:.0f}")
    if kind == "artifact":
        spec = ARTIFACTS[offer["key"]]
        if spec["slot"] == "active":
            if "targets" in spec:
                note = (f"молния по {spec['targets']} врагам, "
                        f"кулдаун {spec['cooldown']:.0f}с")
            else:
                note = f"активный (F), кулдаун {spec['cooldown']:.0f}с"
        else:
            note = "пассивный"
            if "speed_mult" in spec:
                note += f", скорость x{spec['speed_mult']}"
            if "damage_taken" in spec:
                note += f", урон x{spec['damage_taken']}"
            if "hp_bonus" in spec:
                note += f", +{spec['hp_bonus']} HP"
            if "damage_mult" in spec:
                note += f", урон всего x{spec['damage_mult']}"
            if "heal" in spec:
                note += f", вампиризм +{spec['heal']} HP"
            if "save_cooldown" in spec:
                note += (f", спасает от смерти "
                         f"раз в {spec['save_cooldown']:.0f}с")
        refund = offer_refund(game, offer)
        if refund:
            note += f"; старый вернёт +{refund}"
        return spec["name"], offer["price"], note
    raise ValueError(f"Неизвестный вид товара: {kind!r}")
