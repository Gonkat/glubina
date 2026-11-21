"""Клиентское представление мира.

Клиент НЕ симулирует игру: он строит ту же геометрию сектора из seed
и проигрывает снимки хоста. Поэтому здесь нет ни урона, ни добычи —
только объекты для отрисовки и сглаживание позиций между снимками
(снимки приходят 20 раз в секунду, кадров — до 144).

Сглаживание сделано «догонянием» цели, а не буфером с задержкой:
клиент видит свежее состояние, а расхождение гасится за доли секунды.
Для кооператива этого достаточно; предсказание своего героя —
следующий шаг, когда появятся замеры задержки.
"""

import math

from settings import BULLET_LIFETIME
from enemies import Bomber, Brute, Enemy, Runner, Spitter, Stalker, Tank
from bosses import BurrowWorm
from player import Player
from projectiles import Bullet

from .fx import ClientFx

def apply_progress(player, data):
    """Переносит прогрессию героя из снимка в зеркального Player.

    Это НЕ источник истины: цены и проверки всё равно делает хост.
    Зеркало нужно, чтобы доска навыков у клиента показывала реальные
    купленные узлы и уровни, а не пустой герой.
    """
    if not isinstance(data, dict):
        return
    player.skill_nodes = set(data.get("skill_nodes") or ())
    player.skill_mods = dict(data.get("skill_mods") or {})
    player.weapon_tokens = dict(data.get("tokens") or {})
    player.weapon_training = dict(data.get("training") or {})
    tree = {}
    for key, state in (data.get("tree") or {}).items():
        if not isinstance(state, dict):
            continue
        tree[key] = {
            "nodes": tuple(state.get("nodes") or ()),
            "mods": dict(state.get("mods") or {}),
            "main_branch": state.get("main_branch"),
        }
    player.weapon_tree_state = tree

    for slot, switch in (("firearm", "switch_firearm"),
                         ("melee", "switch_melee")):
        state = data.get(slot)
        if not isinstance(state, dict) or not state.get("key"):
            continue
        key = state["key"]
        weapon = player.equipment.get(slot)
        if weapon is None or weapon.key != key:
            try:
                getattr(player, switch)(key)
            except (KeyError, ValueError):
                continue
            weapon = player.equipment.get(slot)
        if weapon is None:
            continue
        nodes = list(state.get("nodes") or ())
        weapon.nodes = set(nodes)
        weapon.node_order = nodes
        weapon.mods = dict(state.get("mods") or {})
        weapon.main_branch = state.get("main_branch")
        weapon.upgrade_level = int(state.get("level", 0))
        if "damage" in state:
            weapon.spec["damage"] = float(state["damage"])

    items = data.get("items")
    if isinstance(items, dict):
        player.equipment.items = {
            str(key): int(value) for key, value in items.items()
            if isinstance(value, int) and not isinstance(value, bool)}


ENEMY_CLASSES = {
    "Enemy": Enemy, "Runner": Runner, "Spitter": Spitter,
    "Bomber": Bomber, "Tank": Tank, "Stalker": Stalker, "Brute": Brute,
    "BurrowWorm": BurrowWorm,
}

# Сглаживание: доля пути до цели за секунду. 14 — быстро, но без рывков.
SMOOTH_RATE = 14.0
# Враги «телепортируются» только при большом расхождении (респавн, спуск).
SNAP_DISTANCE = 260.0


class MirrorDrop:
    """Предмет на полу: клиенту нужен только спрайт и позиция."""

    wobble = 3
    pickup_range = 0

    def __init__(self, state):
        self.x = state["x"]
        self.y = state["y"]
        self.target = (self.x, self.y)
        self.sprite_name = state.get("sprite", "coin")
        self.glow_color = tuple(state.get("glow") or (255, 200, 100))
        self.bob_phase = (self.x * 0.01 + self.y * 0.013) % math.tau
        self.lift = 0.0
        self.alive = True

    def update_view(self, dt, elapsed):
        self.lift = math.sin(elapsed * 5.0 + self.bob_phase) * self.wobble

    def draw(self, screen, camera):
        from spritebank import get
        surf = get(self.sprite_name)
        x, y = camera.to_screen(self.x, self.y)
        screen.blit(surf, surf.get_rect(center=(x, y + self.lift)))

    def draw_glow(self, screen, camera, time=0.0):
        import visuals
        x, y = camera.to_screen(self.x, self.y)
        pulse = 0.72 + 0.28 * math.sin(time * 4.0 + self.bob_phase)
        visuals.glow(screen, x, y + self.lift, 18, self.glow_color,
                     int(62 * pulse))


class ClientView:
    """Держит зеркальные объекты и применяет к ним снимки."""

    def __init__(self, game):
        self.game = game
        self.fx = ClientFx(game)
        self.players = {}     # pid -> Player
        self.enemies = {}     # id -> Enemy
        self.bullets = {}     # id -> Bullet
        self.drops = {}       # id -> MirrorDrop
        self.local_pid = None
        self._entity_seq = 0

    # ------------------------------------------------------------ СНИМОК
    def apply(self, snap):
        game = self.game
        seed = int(snap.get("seed", 0))
        depth = int(snap.get("depth", 1))
        zone = snap.get("zone", game.zone_key)
        if game.world.seed != seed or getattr(game, "depth", 1) != depth:
            game.rebuild_client_world(seed, depth, zone)
            # Сущности прошлого сектора не должны «переехать» в новый.
            self.fx.reset()
            self.players.clear()
            self.enemies.clear()
            self.bullets.clear()
            self.drops.clear()
        elif game.zone_key != zone:
            game.zone_key = zone

        self.local_pid = snap.get("local_pid", self.local_pid)
        self._apply_players(snap.get("players", []))
        self._apply_enemies(snap.get("enemies", []))
        self._apply_bullets(snap.get("bullets", []))
        self._apply_drops(snap.get("drops", []))

        from netplay import snapshot as snapshot_module
        snapshot_module.apply_beacons(game, snap.get("beacons", []))
        # Визуальные события (вспышки, цифры урона, частицы) — локально.
        self.fx.apply(snap)

        player = self.players.get(self.local_pid)
        if player is not None:
            game.player = player
            # HUD читает деньги/очки/убийства у локального героя.
            game.players = list(self.players.values())

    def _apply_players(self, states):
        seen = set()
        for state in states:
            pid = int(state.get("pid", 0))
            if pid <= 0:
                continue
            seen.add(pid)
            player = self.players.get(pid)
            if player is None:
                player = Player(state["x"], state["y"])
                player.pid = pid
                player.is_local = pid == self.local_pid
                self.players[pid] = player
            self._set_target(player, state["x"], state["y"])
            player.angle = float(state.get("angle", 0.0))
            player.max_hp = max(1.0, float(state.get("max_hp", 100.0)))
            player.hp = float(state.get("hp", player.max_hp))
            player.money = int(state.get("money", 0))
            player.score = int(state.get("score", 0))
            player.kills = int(state.get("kills", 0))
            player.name = str(state.get("name", "Игрок"))[:16]
            alive = bool(state.get("alive", True))
            if alive and not player.alive:
                player.alive = True
            elif not alive:
                player.alive = False
            player.equipment.ammo = int(state.get("ammo", 0))
            key = state.get("weapon") or "pistol"
            current = player.firearm
            if (current is None or getattr(current, "key", "") != key) and alive:
                try:
                    player.switch_firearm(key)
                except (KeyError, ValueError):
                    pass
            apply_progress(player, state.get("progress"))
            weapon = player.firearm
            if weapon is not None:
                weapon.loaded = int(state.get("loaded", weapon.loaded))
        for pid in list(self.players):
            if pid not in seen:
                self.players.pop(pid, None)

    def _apply_enemies(self, states):
        seen = set()
        for state in states:
            eid = int(state.get("id", 0))
            enemy = self.enemies.get(eid)
            if enemy is None:
                klass = ENEMY_CLASSES.get(state.get("kind"), Enemy)
                enemy = klass(state["x"], state["y"])
                enemy.pid = eid
                self.enemies[eid] = enemy
            seen.add(eid)
            self._set_target(enemy, state["x"], state["y"])
            enemy.angle = float(state.get("angle", 0.0))
            enemy.radius = max(1.0, float(state.get("radius", enemy.radius)))
            enemy.max_hp = max(1.0, float(state.get("max_hp", 1.0)))
            enemy.hp = float(state.get("hp", enemy.max_hp))
            enemy.hp_show_timer = 1.0   # снимок сам решает, когда гаснуть
            enemy.elite = bool(state.get("elite"))
            enemy.is_boss = bool(state.get("boss"))
            enemy.burrowed = bool(state.get("burrowed", False))
            color = state.get("color")
            if isinstance(color, list) and len(color) >= 3:
                enemy.color = tuple(int(c) for c in color[:3])
        for eid in list(self.enemies):
            if eid not in seen:
                self.enemies.pop(eid, None)

    def _apply_bullets(self, states):
        seen = set()
        for state in states:
            bid = int(state.get("id", 0))
            bullet = self.bullets.get(bid)
            if bullet is None:
                bullet = Bullet(state["x"], state["y"], 0.0, damage=0.0,
                                speed=1.0,
                                radius=float(state.get("radius", 3.0)),
                                style=state.get("style", "bullet"),
                                color=tuple(state.get("color") or
                                            (255, 215, 120)))
                bullet.pid = bid
                self.bullets[bid] = bullet
            seen.add(bid)
            bullet.x = float(state["x"])
            bullet.y = float(state["y"])
            bullet.vx = float(state.get("vx", 0.0))
            bullet.vy = float(state.get("vy", 0.0))
            bullet.life = BULLET_LIFETIME
            bullet.charge = float(state.get("charge", 0.0))
        for bid in list(self.bullets):
            if bid not in seen:
                self.bullets.pop(bid, None)

    def _apply_drops(self, states):
        seen = set()
        for state in states:
            did = int(state.get("id", 0))
            drop = self.drops.get(did)
            if drop is None:
                drop = MirrorDrop(state)
                self.drops[did] = drop
            seen.add(did)
            drop.target = (float(state["x"]), float(state["y"]))
            drop.sprite_name = state.get("sprite", drop.sprite_name)
            drop.glow_color = tuple(state.get("glow") or drop.glow_color)
        for did in list(self.drops):
            if did not in seen:
                self.drops.pop(did, None)

    @staticmethod
    def _set_target(obj, x, y):
        obj.target = (float(x), float(y))
        if not hasattr(obj, "x"):
            obj.x, obj.y = obj.target
            return
        if math.hypot(obj.x - x, obj.y - y) > SNAP_DISTANCE:
            obj.x, obj.y = obj.target

    # ------------------------------------------------------------ КАДР
    def update(self, dt):
        game = self.game
        blend = min(1.0, SMOOTH_RATE * dt)
        for player in self.players.values():
            self._smooth(player, blend)
            weapon = player.firearm
            if weapon is not None:
                weapon.update(dt)
        for enemy in self.enemies.values():
            self._smooth(enemy, blend)
            enemy.anim_phase += dt * 6.0
            enemy.hurt_timer = max(0.0, enemy.hurt_timer - dt)
        for bullet in self.bullets.values():
            bullet.x += bullet.vx * dt
            bullet.y += bullet.vy * dt
        for drop in self.drops.values():
            drop.update_view(dt, game.elapsed)
        # Эффекты живут и обновляются на клиенте: сервер их не присылает.
        for effect in game.effects:
            effect.update(dt, game)
        game.effects = [effect for effect in game.effects if effect.alive]
        self.fx.update(dt)
        game.enemies = list(self.enemies.values())
        game.bullets = list(self.bullets.values())
        game.drops = list(self.drops.values())
        game.grenades = []
        game.enemy_shots = []

    @staticmethod
    def _smooth(obj, blend):
        tx, ty = getattr(obj, "target", (obj.x, obj.y))
        obj.x += (tx - obj.x) * blend
        obj.y += (ty - obj.y) * blend
        # Наклон шага для отрисовки: клиент не знает ввода, но видит,
        # что герой сместился.
        if abs(tx - obj.x) + abs(ty - obj.y) > 0.5:
            obj.walk_phase = getattr(obj, "walk_phase", 0.0) + 0.15
