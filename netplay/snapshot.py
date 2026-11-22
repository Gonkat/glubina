"""Снимок авторитетного мира: что вообще нужно гостю.

Две части сущности:

  * дескриптор — неизменные поля (kind, radius, color, max_hp, elite, boss,
    sprite, glow). Уезжает ОДИН раз, когда сущность впервые попадает
    в интерес гостя (``spawn``);
  * состояние — id и меняющиеся числа (x, y, angle, hp, флаги). Едет
    каждый тик, только для уже известных id.

Геометрия сектора в снимок НЕ входит: мир детерминирован по seed, клиент
строит чанки локально тем же кодом. В шапке только seed, глубина и тип
локации — их смена пересобирает мир.

``collect()`` обходит мир ОДИН раз на всех гостей: массивы состояний потом
фильтруются по интересу каждого гостя, а не собираются заново.

``build()`` — прежний полный JSON-снимок: он остался отладочным режимом
(--net-debug) и ориентиром для тестов, в бою не используется.
"""

from . import protocol
from .binary import F_ALIVE, F_BOSS, F_BURROWED, F_ELITE, F_LIFT, F_WARNING


def _weapon_state(weapon):
    """Срез ветви оружия: узлы, моды и фактический урон."""
    if weapon is None:
        return None
    return {
        "key": weapon.key,
        "nodes": sorted(weapon.nodes),
        "mods": dict(weapon.mods),
        "main_branch": weapon.main_branch,
        "level": int(weapon.upgrade_level),
        "damage": round(float(weapon.spec.get("damage", 0.0)), 2),
    }


def progress_state(player):
    """Полная прогрессия героя — для сообщения progress (по изменению)."""
    return {
        "skill_nodes": sorted(player.skill_nodes),
        "skill_mods": dict(player.skill_mods),
        "tokens": dict(player.weapon_tokens),
        "training": dict(player.weapon_training),
        "tree": {
            key: {"nodes": list(state.get("nodes", ())),
                  "mods": dict(state.get("mods", {})),
                  "main_branch": state.get("main_branch")}
            for key, state in player.weapon_tree_state.items()
        },
        "firearm": _weapon_state(player.firearm),
        "melee": _weapon_state(player.melee),
        "items": dict(getattr(player.equipment, "items", {})),
    }


def progress_signature(player):
    """Дешёвый признак изменения прогрессии (без сборки словарей).

    Считается каждый тик у хоста: только длины и ключи, никаких копий.
    Любая покупка меняет хотя бы один из счётчиков, ключ оружия или
    уровень улучшения — этого достаточно, чтобы понять «пора слать».
    """
    firearm = player.firearm
    melee = player.melee
    equipment = getattr(player, "equipment", None)
    return (
        len(player.skill_nodes), len(player.skill_mods),
        len(player.weapon_tokens), len(player.weapon_training),
        len(player.weapon_tree_state),
        getattr(firearm, "key", ""), int(getattr(firearm, "upgrade_level", 0)),
        len(getattr(firearm, "nodes", ()) or ()),
        len(getattr(firearm, "mods", ()) or ()),
        getattr(melee, "key", ""), int(getattr(melee, "upgrade_level", 0)),
        len(getattr(melee, "nodes", ()) or ()),
        len(getattr(melee, "mods", ()) or ()),
        len(getattr(equipment, "items", ()) or ()),
    )


# ------------------------------------------------------------------ СБОР
class EntityIds:
    """Стабильные u32-идентификаторы сущностей для сети.

    ``id(obj)`` — это адрес в 64 битах: в u32 он не влезает и может
    переиспользоваться. Хост выдаёт каждому объекту свой номер и помнит
    его, пока объект жив; новый объект по тому же адресу получает новый
    номер (проверка «это тот же объект»).
    """

    __slots__ = ("_by_object", "_next")

    def __init__(self):
        self._by_object = {}
        self._next = 1

    def key(self, obj):
        ident = id(obj)
        entry = self._by_object.get(ident)
        if entry is not None and entry[1] is obj:
            return entry[0]
        value = self._next
        self._next = value + 1 if value < 0xFFFFFFFE else 1
        self._by_object[ident] = [value, obj]
        return value

    def prune(self, limit=4096):
        """Не даём таблице расти бесконечно на долгой вылазке."""
        if len(self._by_object) <= limit:
            return
        for ident in list(self._by_object)[:len(self._by_object) // 2]:
            self._by_object.pop(ident, None)

    def clear(self):
        self._by_object.clear()


class WorldState:
    """Срез мира на тик: массивы построены один раз для всех гостей."""

    __slots__ = ("seq", "seed", "depth", "zone", "state", "lift_open", "tick",
                 "players", "enemies", "bullets", "drops", "shots",
                 "opened", "beacons")

    def __init__(self):
        self.seq = 0
        self.seed = 0
        self.depth = 1
        self.zone = "medium"
        self.state = ""
        self.lift_open = False
        self.tick = 0.0
        # каждый элемент — (объект, кортеж состояния) для дескриптора/чисел
        self.players = []
        self.enemies = []
        self.bullets = []
        self.drops = []
        self.shots = []
        self.opened = []
        self.beacons = []


def _player_row(player):
    equipment = getattr(player, "equipment", None)
    firearm = player.firearm
    return (int(player.pid), float(player.x), float(player.y),
            float(player.angle), float(player.hp), float(player.max_hp),
            F_ALIVE if player.alive else 0,
            int(getattr(player, "money", 0)),
            int(getattr(equipment, "ammo", 0)) if equipment else 0,
            int(getattr(firearm, "loaded", 0)) if firearm else 0,
            int(getattr(player, "score", 0)),
            int(getattr(player, "kills", 0)),
            # Текущая скорость героя: клиент предсказывает движение ею,
            # а не константой PLAYER_SPEED. Иначе баффы/замедления/рывок
            # дают постоянное расхождение и «резинку».
            float(getattr(player, "speed", 0.0)))


def _enemy_row(enemy, key=None):
    flags = 0
    if getattr(enemy, "elite", False):
        flags |= F_ELITE
    if getattr(enemy, "is_boss", False):
        flags |= F_BOSS
    if getattr(enemy, "burrowed", False):
        flags |= F_BURROWED
    if getattr(enemy, "warning", False):
        flags |= F_WARNING
    # Телеграфы атак: доля замаха и доля заряда плевка. Клиент без них
    # не может показать, что враг "сейчас ударит" — он видел только
    # неподвижную фигурку и получал урон "из ниоткуда".
    windup = 0.0
    total = float(getattr(enemy, "windup_total", 0.34) or 0.34)
    if getattr(enemy, "windup_timer", 0.0) > 0.0:
        windup = max(0.0, min(1.0, float(enemy.windup_timer) / total))
    charge = 0.0
    charge_total = float(getattr(enemy, "charge_total", 0.0) or 0.0)
    if charge_total > 0.0 and getattr(enemy, "charge_timer", 0.0) > 0.0:
        charge = max(0.0, min(1.0,
                             float(enemy.charge_timer) / charge_total))
    return (key if key is not None else 0, float(enemy.x), float(enemy.y),
            float(enemy.angle), float(enemy.hp), flags,
            int(round(windup * 255.0)), int(round(charge * 255.0)))


def _bullet_row(bullet, key=0):
    return (key, float(bullet.x), float(bullet.y),
            float(getattr(bullet, "vx", 0.0)),
            float(getattr(bullet, "vy", 0.0)),
            float(getattr(bullet, "charge", 0.0)))


def _drop_row(drop, key=0):
    return (key, float(drop.x), float(drop.y))


def _shot_row(shot, key=0):
    """Снаряд врага: позиция, скорость и радиус — этого хватает для вида."""
    return (key, float(shot.x), float(shot.y),
            float(getattr(shot, "vx", 0.0)),
            float(getattr(shot, "vy", 0.0)))


def _net_tick(game):
    """Монотонные часы для интерполяции, а не игровое ``elapsed``.

    ``elapsed`` растёт на dt кадра и теряет время на рывках (dt clamp),
    из-за чего шкала снимков уезжала от реального времени и гость
    периодически «догонял» хоста. Часы хоста от этого не зависят.
    """
    clock = getattr(game, "net_clock", None)
    if clock is not None:
        return float(clock())
    return float(getattr(game, "elapsed", 0.0))


def collect(game, ids=None):
    """Один проход по миру: состояние для снимка (без JSON и словарей).

    ``ids`` — реестр ``EntityIds``: сетевой номер сущности (u32), а не
    адрес объекта в памяти.
    """
    if ids is None:
        ids = game.net_ids if getattr(game, "net_ids", None) is not None \
            else EntityIds()
    world = WorldState()
    world.seq = game.net_seq
    world.seed = int(game.world.seed)
    world.depth = int(game.depth)
    world.zone = game.zone_key
    world.state = game.state
    world.tick = _net_tick(game)
    world.lift_open = bool(getattr(game.descent, "all_active", False))
    render = game.render_players if game.net_role == "host" else game.players
    world.players = [(player, _player_row(player)) for player in render]
    world.enemies = [(enemy, _enemy_row(enemy, ids.key(enemy)))
                     for enemy in game.enemies if enemy.alive]
    world.bullets = [(bullet, _bullet_row(bullet, ids.key(bullet)))
                     for bullet in game.bullets if bullet.alive]
    world.drops = [(drop, _drop_row(drop, ids.key(drop)))
                   for drop in game.drops if drop.alive]
    world.shots = [(shot, _shot_row(shot, ids.key(shot)))
                   for shot in getattr(game, "enemy_shots", ())
                   if shot.alive]
    ids.prune()
    # Открытые сундуки — общее состояние мира: сундук, вскрытый другим
    # игроком, должен остаться открытым и на моём экране.
    opened = getattr(getattr(game, "exploration", None), "opened", ())
    world.opened = [tuple(site) for site in opened][:512]
    if hasattr(game.descent, "beacon_states"):
        world.beacons = [
            (int(state.get("index", 0)), float(state.get("x", 0.0)),
             float(state.get("y", 0.0)),
             0x00 if state.get("state") is None
             else int(_beacon_code(state.get("state"))),
             float(state.get("progress", 0.0)))
            for state in game.descent.beacon_states()
        ]
    return world


_BEACON_CODES = {"idle": 0, "charging": 1, "active": 2, "done": 3}
_BEACON_NAMES = ("idle", "charging", "active", "done")


def _beacon_code(state):
    if isinstance(state, int):
        return max(0, min(3, state))
    return _BEACON_CODES.get(str(state), 0)


def beacon_name(code):
    return _BEACON_NAMES[code] if 0 <= code < len(_BEACON_NAMES) else "idle"


def snapshot_header(world, seq, local_pid):
    flags = F_LIFT if world.lift_open else 0
    return (seq, world.seed, world.depth, world.zone, world.state,
            local_pid, flags, world.tick)


# ------------------------------------------------------------------ JSON
def _player_state(player):
    weapon = player.equipment.get("firearm") if player.equipment else None
    equipment = player.equipment
    return {
        "pid": int(player.pid),
        "name": player.name,
        "x": round(player.x, 1),
        "y": round(player.y, 1),
        "angle": round(player.angle, 3),
        "hp": round(player.hp, 1),
        "max_hp": round(player.max_hp, 1),
        "alive": bool(player.alive),
        "money": int(getattr(player, "money", 0)),
        "score": int(getattr(player, "score", 0)),
        "kills": int(getattr(player, "kills", 0)),
        "weapon": getattr(weapon, "key", "") if weapon is not None else "",
        "loaded": int(getattr(weapon, "loaded", 0)) if weapon else 0,
        "ammo": int(getattr(equipment, "ammo", 0)) if equipment else 0,
        "progress": progress_state(player),
    }


def _enemy_state(enemy):
    return {
        "id": id(enemy),
        "kind": type(enemy).__name__,
        "x": round(enemy.x, 1),
        "y": round(enemy.y, 1),
        "angle": round(enemy.angle, 3),
        "hp": round(enemy.hp, 1),
        "max_hp": round(enemy.max_hp, 1),
        "radius": round(enemy.radius, 1),
        "color": list(enemy.color) if enemy.color else None,
        "elite": bool(getattr(enemy, "elite", False)),
        "boss": bool(getattr(enemy, "is_boss", False)),
        "burrowed": bool(getattr(enemy, "burrowed", False)),
        "windup": round(float(getattr(enemy, "windup_timer", 0.0)), 2),
        "charge": round(float(getattr(enemy, "charge_timer", 0.0)), 2),
    }


def _bullet_state(bullet):
    return {
        "id": id(bullet),
        "x": round(bullet.x, 1),
        "y": round(bullet.y, 1),
        "vx": round(bullet.vx, 1),
        "vy": round(bullet.vy, 1),
        "radius": round(bullet.radius, 1),
        "style": getattr(bullet, "style", "bullet"),
        "color": list(getattr(bullet, "color", (255, 215, 120))),
        "charge": round(float(getattr(bullet, "charge", 0.0)), 2),
    }


def _drop_state(drop):
    return {
        "id": id(drop),
        "x": round(drop.x, 1),
        "y": round(drop.y, 1),
        "sprite": drop.sprite_name or "coin",
        "glow": list(getattr(drop, "glow_color", (255, 200, 100))),
    }


def _shot_state(shot):
    return {
        "id": id(shot),
        "x": round(shot.x, 1),
        "y": round(shot.y, 1),
        "vx": round(getattr(shot, "vx", 0.0), 1),
        "vy": round(getattr(shot, "vy", 0.0), 1),
        "radius": round(getattr(shot, "radius", 7.0), 1),
    }


def _beacon_state(beacon):
    return {
        "index": beacon.index,
        "x": round(beacon.x, 1),
        "y": round(beacon.y, 1),
        "state": beacon.state,
        "progress": round(beacon.progress, 3),
    }


def build(game):
    """Полный JSON-снимок для отладочного режима (--net-debug)."""
    render = game.render_players if game.net_role == "host" else game.players
    return {
        "t": "snapshot",
        "seq": game.net_seq,
        "tick": round(_net_tick(game), 2),
        "seed": int(game.world.seed),
        "depth": int(game.depth),
        "zone": game.zone_key,
        "state": game.state,
        "players": [_player_state(p) for p in render],
        "enemies": [_enemy_state(e) for e in game.enemies if e.alive],
        "bullets": [_bullet_state(b) for b in game.bullets if b.alive],
        "drops": [_drop_state(d) for d in game.drops if d.alive],
        "shots": [_shot_state(s) for s in getattr(game, "enemy_shots", ())
                  if s.alive],
        "opened": [list(site) for site in
                   getattr(getattr(game, "exploration", None), "opened", ())],
        "beacons": (game.descent.beacon_states()
                    if hasattr(game.descent, "beacon_states") else []),
        "lift_open": bool(getattr(game.descent, "all_active", False)),
    }


def apply_beacons(game, states):
    """Переносит состояние маяков на локально построенный сектор."""
    by_index = {beacon.index: beacon for beacon in game.descent.beacons}
    for index, x, y, code, progress in states:
        beacon = by_index.get(index)
        if beacon is None:
            continue
        beacon.state = beacon_name(code)
        beacon.progress = protocol.clamp(progress, 0.0, 1.0)
        beacon.linked = beacon.state == "charging"
