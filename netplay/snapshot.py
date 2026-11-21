"""Снимок авторитетного мира: сериализация и применение.

Снимок — это ПОЛНОЕ состояние видимых сущностей на момент тика.
Дельта-сжатие не вводим: на 4 игроках JSON-снимок заметно меньше
сетевого бюджета, а полное состояние исключает рассинхрон «потерял
одну дельту — мир разъехался». Позиции округляются, чтобы не гонять
бессмысленные знаки после запятой.

Геометрия сектора в снимок НЕ входит: мир детерминирован по seed,
клиент строит чанки локально тем же кодом (`world.World`). В снимке
только seed, глубина и тип локации — их смена пересобирает мир.
"""

from . import protocol


def _weapon_state(weapon):
    """Срез ветви оружия: узлы, моды и фактический урон.

    Без этого клиент не мог бы показать доску навыков своего героя:
    интерфейс читает купленные узлы и уровень улучшения у оружия.
    """
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


def _progress_state(player):
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
        "progress": _progress_state(player),
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


def _beacon_state(beacon):
    return {
        "index": beacon.index,
        "x": round(beacon.x, 1),
        "y": round(beacon.y, 1),
        "state": beacon.state,
        "progress": round(beacon.progress, 3),
    }


def build(game):
    """Полный снимок мира для клиентов."""
    render = game.render_players if game.net_role == "host" else game.players
    return {
        "t": "snapshot",
        "seq": game.net_seq,
        "tick": round(game.elapsed, 2),
        "seed": int(game.world.seed),
        "depth": int(game.depth),
        "zone": game.zone_key,
        "state": game.state,
        "players": [_player_state(p) for p in render],
        "enemies": [_enemy_state(e) for e in game.enemies if e.alive],
        "bullets": [_bullet_state(b) for b in game.bullets if b.alive],
        "drops": [_drop_state(d) for d in game.drops if d.alive],
        "beacons": (game.descent.beacon_states()
                    if hasattr(game.descent, "beacon_states") else []),
        "lift_open": bool(getattr(game.descent, "all_active", False)),
    }


def apply_beacons(game, states):
    """Переносит состояние маяков на локально построенный сектор."""
    by_index = {beacon.index: beacon for beacon in game.descent.beacons}
    for state in states or ():
        beacon = by_index.get(state.get("index"))
        if beacon is None:
            continue
        beacon.state = state.get("state", beacon.state)
        beacon.progress = protocol.clamp(state.get("progress"), 0.0, 1.0)
        beacon.linked = beacon.state == "charging"
