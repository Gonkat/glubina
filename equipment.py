"""
Экипировка героя: слоты и пул боеприпасов.

Правило GDD (п.2): в слоте огнестрельного оружия — ТОЛЬКО ОДНО оружие.
Покупка нового заменяет старое; старое возвращается вызывающему,
чтобы тот начислил компенсацию за улучшения (расчёт денег — в M5).
"""
from weapon_data import START_AMMO


class Equipment:
    """Владеет слотами и патронами. Не знает ни о герое, ни о монстрах."""

    SLOTS = (
        "firearm",           # огнестрельное (1 из 3)
        "melee",             # ближний бой (M3)
        "active_artifact",   # активный артефакт (M6)
        "passive_artifact",  # пассивный артефакт (M6)
        "consumables",       # расходники, например гранаты (M6)
    )

    def __init__(self, start_ammo=None):
        self.slots = {slot: None for slot in self.SLOTS}
        # M11: боезапас — ОДНО число (единицы), не словарь калибров
        self.ammo = START_AMMO if start_ammo is None else start_ammo
        self.items = {}      # расходники: имя → количество (гранаты и др.)

    # ------------------------------------------------------------ СЛОТЫ
    def equip(self, slot, weapon):
        """
        Ставит оружие в слот. Возвращает ПРЕДЫДУЩЕЕ содержимое слота
        (или None) — вызывающая сторона решает, что с ним делать.
        """
        if slot not in self.slots:
            raise ValueError(f"Неизвестный слот: {slot!r}")
        old = self.slots[slot]
        self.slots[slot] = weapon
        return old

    def get(self, slot):
        """Содержимое слота (может быть None)."""
        return self.slots.get(slot)

    # ------------------------------------------------------------ БОЕПРИПАСЫ
    def ammo_count(self):
        """Сколько единиц боезапаса в запасе (M11: один общий ресурс)."""
        return self.ammo

    def take_ammo(self, amount):
        """Забирает до amount единиц. Возвращает, сколько забрано реально."""
        taken = min(self.ammo, max(0, amount))
        self.ammo -= taken
        return taken

    def add_ammo(self, amount):
        """Добирает единицы (выпадают с монстров / покупаются в магазине)."""
        if amount > 0:
            self.ammo += amount

    # ------------------------------------------------------------ РАСХОДНИКИ
    def add_item(self, name, amount=1):
        """Кладёт расходник в инвентарь (гранаты и будущие предметы)."""
        if amount > 0:
            self.items[name] = self.items.get(name, 0) + amount

    def item_count(self, name):
        return self.items.get(name, 0)

    def use_item(self, name):
        """Тратит один предмет. False — если его нет."""
        if self.items.get(name, 0) <= 0:
            return False
        self.items[name] -= 1
        return True
