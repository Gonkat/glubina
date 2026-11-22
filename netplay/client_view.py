"""Клиентское представление мира.

Клиент НЕ симулирует игру: он строит ту же геометрию сектора из seed и
проигрывает снимки хоста. Здесь нет ни урона, ни добычи — только объекты
для отрисовки.

Что изменилось ради фризов и «ощущения»:

  * зеркальный объект создаётся ОДИН раз на ``spawn`` (дескриптор), а
    снимок только пишет в него числа — никаких Enemy(...)/Player(...) из
    каждого кадра и никаких словарей на сущность;
  * позиции интерполируются с ПОДСТРАИВАЕМОЙ задержкой: ровный канал —
    ~1.5 интервала снимка (~25 мс), джиттер — буфер расширяется сам;
  * буфер опустел — экстраполяция не дальше 50 мс, потом позиция стоит;
  * свой герой двигается локально (предсказание ввода) и мягко
    подтягивается к хосту; ошибка > 200 px (спуск, респаун) — перенос;
  * прогноз идёт со скоростью ЗЕРКАЛА (артефакт/бафф/навык) и через
    ``world.resolve_circle``: стены у клиента те же, что у хоста;
  * сущность, пропавшая из снимков без ``despawn``, удаляется после трёх
    снимков тишины.
"""

import math

from settings import BULLET_LIFETIME, DASH_COOLDOWN, DASH_SPEED, DASH_TIME, PLAYER_SPEED
from enemies import Bomber, Brute, Enemy, Runner, Spitter, Stalker, Tank
from bosses import BurrowWorm
from player import Player
import soundbank

from projectiles import Bullet, Casing, EnemyShot, MuzzleFlash, Spark

from . import protocol
from .binary import F_ALIVE, F_BOSS, F_BURROWED, F_ELITE, F_WARNING
from .fx import ClientFx

# Шаг снимков хоста. От него считаются все пороги буфера.
SNAPSHOT_INTERVAL = 1.0 / protocol.SNAPSHOT_HZ
# Задержка отрисовки чужих сущностей: от 1.2 до 8 интервалов снимка.
# Стартуем с двух интервалов, дальше буфер подстраивается сам: на
# гигабитной LAN это ~25-35 мс, на плохом Wi-Fi вырастает до 250 мс.
MIN_INTERP_DELAY = SNAPSHOT_INTERVAL * 1.5
MAX_INTERP_DELAY = SNAPSHOT_INTERVAL * 8.0
INTERP_DELAY = SNAPSHOT_INTERVAL * 2.0
# Пустой буфер: дальше этого предсказывать нельзя.
MAX_EXTRAPOLATE = SNAPSHOT_INTERVAL * 3.0
# Скачок позиции больше этого — телепорт (спуск, респаун), а не «проезд».
SNAP_DISTANCE = 200.0
# Локальное предсказание своего героя.
PREDICT_SNAP = 200.0
# Мёртвая зона сверки. Снимок хоста описывает прошлое, поэтому ошибка
# считается НЕ «здесь и сейчас», а между позицией хоста и тем, где
# предсказание было в тот же момент (см. _local_position_at). После
# такой сверки мёртвой зоне остаётся только шум квантования — иначе она
# маскировала бы настоящий дрейф.
PREDICT_DEADZONE = 4.0
# Максимальная скорость «подтягивания» к хосту: игрок видит скольжение
# на пару пикселей за кадр, а не рывок назад.
CORRECTION_SPEED = 320.0
HISTORY_LEN = 8
# Насколько долго после предсказанного рывка не спорим с хостом: он узнаёт
# о нажатии на половину RTT позже, и его снимок это время описывает ещё
# «до рывка». Сверка в этом окне тянула бы героя назад.
DASH_GRACE = DASH_TIME + 0.25
# Шаг анимации чужих героев: фаза ходьбы растёт от пройденного пути, а не
# от времени — иначе персонаж «скользит» без шага, когда стоит, и дёргает
# ногами, когда стоит на месте.
WALK_PHASE_PER_PX = 0.045
# Сколько помним собственную предсказанную траекторию (в кадрах).
LOCAL_HISTORY_LEN = 64
# Вспышка выстрела, уже показанная локально, гасит дубль из снимка.
LOCAL_FLASH_DIST = 120.0
LOCAL_FLASH_LIFE = 0.5
SILENCE_LIMIT = 3
# Насколько часы хоста могут разойтись с клиентскими, прежде чем переякорить
# таймлайн. Хост, простоявший в паузе/на загрузке, не должен заставлять
# клиента догонять реальность секундами.
MAX_TICK_SKEW = 0.75
# Насколько снимок может «отстать» от текущего кадра, прежде чем считать
# это фризом. Дальше переякориваем таймлайн: лучше подрезать задержку,
# чем показывать гостю две секунды прошедшего боя ускоренной перемоткой.
MAX_SNAPSHOT_LAG = 0.35


def apply_progress(player, data):
    """Переносит прогрессию героя из сообщения progress в зеркало.

    Это НЕ источник истины: цены и проверки всё равно делает хост.
    Зеркало нужно, чтобы доска навыков у клиента показывала реальные
    купленные узлы и уровни, а не пустой герой. Вызывается только при
    смене rev, а не 20 раз в секунду.
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

    # Скорость зеркала пересобирается из тех же модов: иначе предсказание
    # своего героя на клиенте шло бы на голой PLAYER_SPEED, отставало от
    # хоста у любого «быстрого» билда и постоянно подтягивалось назад.
    refresh = getattr(player, "refresh_speed", None)
    if refresh is not None:
        refresh()


ENEMY_CLASSES = {
    "Enemy": Enemy, "Runner": Runner, "Spitter": Spitter,
    "Bomber": Bomber, "Tank": Tank, "Stalker": Stalker, "Brute": Brute,
    "BurrowWorm": BurrowWorm,
}


class MirrorMixin:
    """Общие поля зеркала: история позиций и ревизия прогрессии."""

    __slots__ = ()


class MirrorDrop:
    """Предмет на полу: клиенту нужен только спрайт и позиция."""

    wobble = 3
    pickup_range = 0

    def __init__(self, x, y, sprite="coin", glow=None):
        self.x = float(x)
        self.y = float(y)
        self.history = []
        self.sprite_name = sprite
        self.glow_color = tuple(glow or (255, 200, 100))
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
        self.shots = {}       # id -> EnemyShot (плевки дальних врагов)
        self.drops = {}       # id -> MirrorDrop
        self.local_pid = None
        self.local_input = (0.0, 0.0)
        # Держим ли курок: у зарядного оружия хост даёт бонус к скорости,
        # и предсказание без него отставало бы и подтягивалось назад.
        self.local_fire = False
        # Клиент — владелец позиции своего героя. Тогда сверка с хостом
        # отключается целиком: это и есть приоритет отзывчивости над
        # защитой от подмены координат.
        self.local_authoritative = False
        self._clock = 0.0
        # Подстраиваемая задержка отрисовки (см. _adapt_interp).
        self.interp_delay = INTERP_DELAY
        # Оценка «возраста» позиции хоста в снимке: половина RTT плюс
        # интервал снимков. Нужна мёртвой зоне предсказания, чтобы героя
        # не тянуло назад на эту самую задержку.
        self.input_latency = SNAPSHOT_INTERVAL
        # Половина RTT: насколько снимок «старше» момента, когда мы его
        # приняли. Нужна и сверке предсказания, и курсору интерполяции.
        self.net_latency = 0.0
        self.predict_error = 0.0
        self.snapshot_age = 0.0
        self._newest = 0.0
        # Своя предсказанная траектория: (время клиента, x, y). По ней
        # ищется «где я был, когда хост делал этот снимок» — без этого
        # сверка тянула героя назад на половину RTT.
        self._local_history = []
        # Выстрелы, уже показанные локально: (время, x, y).
        self._local_flashes = []
        self._local_loaded = None
        self._last_local_flash = -1.0
        # Когда был предсказан последний рывок (окно «не спорим с хостом»).
        self._dash_started = -10.0
        # Когда последний раз менялось направление ввода (старт/разворот/
        # остановка): в это окно хост ещё живёт старым движением.
        self._input_changed_at = -10.0
        # История позиций живёт по ЧАСАМ ХОСТА (tick из снимка), а не по
        # времени прихода: пачка снимков после рывка хоста больше не
        # схлопывает таймлайн в одну точку.
        self._tick_offset = None
        self._progress_rev = {}
        self._pending_progress = {}
        self._kinds = {}       # id -> имя класса: нужно эффектам смерти
        self._silence = {}
        self._last_seq = -1
        self.stats = {"snapshots": 0, "spawns": 0, "despawns": 0}

    # ------------------------------------------------------------ СОБЫТИЯ
    def apply_spawn(self, message):
        """Дескрипторы новых сущностей: создать зеркало один раз."""
        for pid, name, max_hp in message.get("players", ()):
            player = self.players.get(pid)
            if player is None:
                player = Player(0.0, 0.0)
                player.pid = pid
                player.is_local = pid == self.local_pid
                self.players[pid] = player
            player.name = name
            player.max_hp = max(1.0, max_hp)
            player.hp = player.max_hp
            # Прогрессия могла прийти раньше дескриптора (она идёт отдельным
            # кадром): применяем, когда зеркало уже существует.
            pending = self._pending_progress.pop(pid, None)
            if pending is not None:
                apply_progress(player, pending)
        for eid, kind, rad, max_hp, color, flags in message.get("enemies", ()):
            if eid in self.enemies:
                continue
            klass = ENEMY_CLASSES.get(kind, Enemy)
            try:
                enemy = klass(0.0, 0.0)
            except TypeError:
                enemy = Enemy(0.0, 0.0)
            enemy.pid = eid
            enemy.radius = max(1.0, rad)
            enemy.max_hp = max(1.0, max_hp)
            enemy.hp = enemy.max_hp
            if color is not None:
                enemy.color = tuple(color)
            enemy.elite = bool(flags & F_ELITE)
            enemy.is_boss = bool(flags & F_BOSS)
            enemy.history = []
            self.enemies[eid] = enemy
            self._kinds[eid] = kind
        for bid, rad, style, color in message.get("bullets", ()):
            if bid in self.bullets:
                continue
            bullet = Bullet(0.0, 0.0, 0.0, damage=0.0, speed=1.0,
                            radius=float(rad), style=style,
                            color=tuple(color or (255, 215, 120)))
            bullet.pid = bid
            self.bullets[bid] = bullet
        for did, sprite, color in message.get("drops", ()):
            if did in self.drops:
                continue
            self.drops[did] = MirrorDrop(0.0, 0.0, sprite, color)
        for sid, rad in message.get("shots", ()):
            if sid in self.shots:
                continue
            # Снаряд врага: тот же класс, что у хоста, — рисуется и светит
            # один в один. Урон и столкновения остаются за хостом.
            shot = EnemyShot(0.0, 0.0, 0.0)
            shot.pid = sid
            shot.radius = max(1.0, float(rad))
            shot.history = []
            self.shots[sid] = shot
        self.stats["spawns"] += 1

    def _kind_of(self, entity_id):
        return self._kinds.get(entity_id, "Enemy")

    def apply_despawn(self, message):
        for pid in message.get("players", ()):
            self.players.pop(pid, None)
            self._progress_rev.pop(pid, None)
        for eid in message.get("enemies", ()):
            self.enemies.pop(eid, None)
            self._silence.pop(eid, None)
            self._kinds.pop(eid, None)
        for bid in message.get("bullets", ()):
            self.bullets.pop(bid, None)
        for did in message.get("drops", ()):
            self.drops.pop(did, None)
        for sid in message.get("shots", ()):
            self.shots.pop(sid, None)
        self.stats["despawns"] += 1

    def apply_progress_message(self, message):
        pid = int(message.get("pid", 0))
        rev = int(message.get("rev", 0))
        if rev <= self._progress_rev.get(pid, -1):
            return
        self._progress_rev[pid] = rev
        player = self.players.get(pid)
        if player is not None:
            apply_progress(player, message.get("data"))
        else:
            self._pending_progress[pid] = message.get("data")

    # ------------------------------------------------------------ СНИМОК
    def receive(self, snap):
        """Принимает снимок состояния (бинарный разбор — кортежи)."""
        seq = int(snap.get("seq", 0))
        if seq <= self._last_seq:
            return
        self._last_seq = seq
        self.stats["snapshots"] += 1
        game = self.game
        seed = int(snap.get("seed", 0))
        depth = int(snap.get("depth", 1))
        zone = snap.get("zone", game.zone_key)
        if game.world.seed != seed or getattr(game, "depth", 1) != depth:
            game.rebuild_client_world(seed, depth, zone)
            self.reset_mirrors()
        elif game.zone_key != zone:
            game.zone_key = zone

        self.local_pid = int(snap.get("local_pid", self.local_pid))
        now = self._snapshot_time(snap)
        self._newest = max(self._newest, now)
        self._apply_players(snap.get("players", ()), now)
        self._apply_enemies(snap.get("enemies", ()), now)
        self._apply_bullets(snap.get("bullets", ()), now)
        self._apply_shots(snap.get("shots", ()), now)
        self._apply_drops(snap.get("drops", ()), now)
        self._apply_opened(snap.get("opened", ()))
        self._apply_beacons(snap.get("beacons", ()))
        # Эффекты — по кортежам снимка, без промежуточных словарей.
        self.fx.apply_rows(snap.get("players", ()), snap.get("enemies", ()),
                           snap.get("bullets", ()), self.local_pid,
                           self._kind_of)

        player = self.players.get(self.local_pid)
        if player is not None:
            game.player = player
            game.players = list(self.players.values())
            game.players.sort(key=lambda item: item.pid)
        self._rebuild_lists()

    def _snapshot_time(self, snap):
        """Момент, который описывает снимок, в шкале клиента.

        ``tick`` — время хоста на момент сборки мира. Снимок дошёл до нас
        примерно на половину RTT позже, поэтому поправка часов вычитает
        эту задержку: иначе позиция хоста считалась бы «сегодняшней»,
        сверка предсказания видела бы постоянное отставание и тянула
        героя назад (тем сильнее, чем быстрее билд и больше пинг).

        Поправка не скачет от джиттера: снимок за снимком дрейф гасится
        медленно, а переякорь — только на настоящем прыжке часов хоста
        (пауза, загрузка, перезапуск).
        """
        tick = float(snap.get("tick", 0.0) or 0.0)
        if tick <= 0.0:
            return self._clock
        latency = max(0.0, min(0.2, float(getattr(self, "net_latency", 0.0))))
        sample = self._clock - latency - tick
        if self._tick_offset is None:
            self._tick_offset = sample
            return tick + sample
        drift = sample - self._tick_offset
        if abs(drift) > MAX_TICK_SKEW:
            # Часы хоста прыгнули: переякориваем шкалу и чистим историю.
            self._tick_offset = sample
            self._clear_history()
            return tick + sample
        self._tick_offset += drift * 0.02
        now = tick + self._tick_offset
        if now < self._clock - MAX_SNAPSHOT_LAG:
            # Хост стоял (пауза/загрузка/дескент), либо свой фриз: старый
            # снимок уже не «немного в прошлом», а безнадёжно устарел.
            now = self._clock - self.interp_delay
            self._tick_offset = now - tick
            self._clear_history()
        return now

    def _clear_history(self):
        """Сбрасывает точки интерполяции у всех зеркал (после переякоря)."""
        mirrors = (list(self.players.values()) + list(self.enemies.values())
                   + list(self.drops.values()))
        for mirror in mirrors:
            history = getattr(mirror, "history", None)
            if history:
                history.clear()
        # Шкала переякорена: старый «новейший» снимок больше не опора.
        self._newest = 0.0
        self._local_history.clear()

    def reset_mirrors(self):
        self.fx.reset()
        self.players.clear()
        self.enemies.clear()
        self.bullets.clear()
        self.shots.clear()
        self.drops.clear()
        self._silence.clear()
        self._progress_rev.clear()
        self._pending_progress.clear()
        self._kinds.clear()
        self._last_seq = -1
        self._tick_offset = None
        self._newest = 0.0
        self._local_history.clear()
        self._local_flashes.clear()
        self._local_loaded = None
        self._last_local_flash = -1.0
        self._dash_started = -10.0
        self._input_changed_at = -10.0
        self.local_fire = False

    def _apply_beacons(self, states):
        from . import snapshot as snapshot_module
        snapshot_module.apply_beacons(self.game, states)

    def _apply_players(self, rows, now):
        for row in rows:
            (pid, x, y, angle, cur_hp, max_hp, flags, money, ammo, loaded,
             rev, score, kills, speed) = row
            player = self.players.get(pid)
            if player is None:
                player = Player(x, y)
                player.pid = pid
                player.is_local = pid == self.local_pid
                self.players[pid] = player
            player.is_local = pid == self.local_pid
            player.angle = float(angle)
            player.max_hp = max(1.0, float(max_hp))
            player.hp = float(cur_hp)
            player.money = int(money)
            player.score = int(score)
            player.kills = int(kills)
            # Скорость — из снимка: баффы, замедления и заряд пушки
            # предсказываются ровно так же, как их считает хост.
            player.speed = max(1.0, float(speed or PLAYER_SPEED))
            player.alive = bool(flags & F_ALIVE)
            player.equipment.ammo = int(ammo)
            weapon = player.firearm
            if weapon is not None:
                # Хост выстрелил — снимок уменьшил магазин. Вспышку в этот
                # момент рисуем сами: пуля в снимке появится на RTT позже.
                if (player.is_local and self._local_loaded is not None
                        and int(loaded) < self._local_loaded
                        and self._clock - self._last_local_flash > 0.06):
                    self.present_local_shot(player)
                weapon.loaded = int(loaded)
            if player.is_local:
                # Свой герой: предсказание + сверка с хостом на одном моменте
                # времени. host_time — момент снимка в шкале клиента.
                self._local_loaded = int(loaded)
                player.host_x, player.host_y = float(x), float(y)
                player.host_time = now
                if not getattr(player, "predicted", False):
                    player.x, player.y = float(x), float(y)
                    player.predicted = True
                    self._local_history.clear()
                    self._local_history.append((now, player.x, player.y))
                elif math.hypot(player.x - x, player.y - y) > PREDICT_SNAP:
                    player.x, player.y = float(x), float(y)
                    self._local_history.clear()
                    self._local_history.append((now, player.x, player.y))
            else:
                self._remember(player, now, x, y)

    def _apply_enemies(self, rows, now):
        seen = set()
        for row in rows:
            eid, x, y, angle, cur_hp, flags = row[:6]
            windup = row[6] if len(row) > 6 else 0.0
            charge = row[7] if len(row) > 7 else 0.0
            enemy = self.enemies.get(eid)
            if enemy is None:
                enemy = Enemy(x, y)
                enemy.pid = eid
                enemy.history = []
                self.enemies[eid] = enemy
            seen.add(eid)
            enemy.angle = float(angle)
            enemy.hp = float(cur_hp)
            enemy.hp_show_timer = 1.0   # снимок сам решает, когда гаснуть
            enemy.burrowed = bool(flags & F_BURROWED)
            enemy.warning = bool(flags & F_WARNING)
            enemy.elite = bool(flags & F_ELITE)
            enemy.is_boss = bool(flags & F_BOSS)
            # Телеграф атаки — часть картины боя: без него удар врага
            # приходит "из ниоткуда" уже после того, как он случился.
            total = float(getattr(enemy, "windup_total", 0.34) or 0.34)
            enemy.windup_timer = windup * total
            charge_total = float(getattr(enemy, "charge_total", 0.0) or 0.0)
            if charge_total > 0.0:
                enemy.charge_timer = charge * charge_total
                enemy.fire_angle = float(angle)
            self._remember(enemy, now, x, y)
        self._sweep(self.enemies, seen)

    def _apply_opened(self, sites):
        """Общие вскрытые сундуки: состояние мира, а не личное."""
        opened = getattr(getattr(self.game, "exploration", None), "opened",
                         None)
        if opened is None:
            return
        current = set(opened)
        for site in sites:
            try:
                current.add(tuple(site))
            except TypeError:
                continue
        opened.clear()
        opened.update(current)

    def _apply_shots(self, rows, now):
        """Снаряды врагов: позиция и скорость; летят между снимками сами."""
        seen = set()
        for sid, x, y, vx, vy in rows:
            shot = self.shots.get(sid)
            if shot is None:
                angle = math.atan2(vy, vx)
                shot = EnemyShot(x, y, angle)
                shot.pid = sid
                shot.history = []
                self.shots[sid] = shot
                # Плевок родился: искры у «рта» и звук, не дожидаясь хоста.
                for _ in range(3):
                    self.game.effects.append(Spark(
                        x, y, angle, (150, 246, 190), 120))
                soundbank.play_remote("enemy_shot", x, y, 0.4)
            seen.add(sid)
            shot.vx = float(vx)
            shot.vy = float(vy)
            self._remember(shot, now, x, y)
        self._sweep(self.shots, seen)

    def _apply_bullets(self, rows, now):
        seen = set()
        for bid, x, y, vx, vy, charge in rows:
            bullet = self.bullets.get(bid)
            if bullet is None:
                bullet = Bullet(x, y, 0.0, damage=0.0, speed=1.0,
                                radius=3.0)
                bullet.pid = bid
                bullet.history = []
                self.bullets[bid] = bullet
            seen.add(bid)
            bullet.vx = float(vx)
            bullet.vy = float(vy)
            bullet.life = BULLET_LIFETIME
            bullet.charge = float(charge)
            # Пули тоже идут через историю: локальная интеграция со
            # "сбросом" на позицию снимка давала шаг назад каждый тик —
            # на быстрой пуле это читалось как дрожание.
            self._remember(bullet, now, x, y)
        self._sweep(self.bullets, seen)

    def _apply_drops(self, rows, now):
        seen = set()
        for did, x, y in rows:
            drop = self.drops.get(did)
            if drop is None:
                drop = MirrorDrop(x, y)
                self.drops[did] = drop
            seen.add(did)
            self._remember(drop, now, x, y)
        self._sweep(self.drops, seen)

    def _sweep(self, mirrors, seen):
        """Удаление по «тишине»: пропал из 3 снимков подряд — убираем."""
        for entity_id in list(mirrors):
            if entity_id in seen:
                self._silence.pop(entity_id, None)
                continue
            misses = self._silence.get(entity_id, 0) + 1
            if misses >= SILENCE_LIMIT:
                self._silence.pop(entity_id, None)
                mirrors.pop(entity_id, None)
            else:
                self._silence[entity_id] = misses

    def _remember(self, mirror, now, x, y):
        """История позиций для интерполяции (телепорт её сбрасывает)."""
        history = getattr(mirror, "history", None)
        if history is None:
            history = mirror.history = []
        x = float(x)
        y = float(y)
        if history and math.hypot(history[-1][1] - x,
                                  history[-1][2] - y) > SNAP_DISTANCE:
            history.clear()
        history.append((now, x, y))
        if len(history) > HISTORY_LEN:
            del history[0]

    # ------------------------------------------------------------ КАДР
    def _adapt_interp(self):
        """Подстраивает задержку отрисовки под фактический джиттер канала.

        Мерим не время прихода пакетов (оно врёт пачками на кадре), а
        запас буфера: насколько последний снимок опережает то время,
        которое мы рисуем. Запас меньше интервала — вот-вот упрёмся в
        пустоту, добавляем; запас с большим избытком — поджимаем.
        """
        if self._newest <= 0.0:
            return
        # Точки истории датированы моментом съёмки, а не прихода: курсор
        # тоже отсчитываем «как будто сейчас на хосте».
        lead = self._newest - (self._render_time())
        if lead < SNAPSHOT_INTERVAL * 0.9:
            # Буфер на исходе: шаг вверх мелкий, но частый — задержка не
            # скачет, а успевает за ростом джиттера.
            self.interp_delay = min(MAX_INTERP_DELAY,
                                    self.interp_delay + SNAPSHOT_INTERVAL * 0.15)
        elif lead > SNAPSHOT_INTERVAL * 1.15:
            if self.interp_delay > MIN_INTERP_DELAY:
                # Сжимаем медленно: редкий провал не должен возвращать
                # задержку каждую секунду обратно вверх.
                self.interp_delay = max(MIN_INTERP_DELAY,
                                        self.interp_delay - 0.0002)

    def update(self, dt):
        game = self.game
        self._clock += dt
        self._adapt_interp()
        self.snapshot_age = max(0.0, self._clock - self._newest)
        target_time = self._render_time() - self.interp_delay
        local = self.players.get(self.local_pid)
        for pid, player in self.players.items():
            if player is local:
                self._predict_local(player, dt)
            else:
                self._animate_remote(player, target_time)
            player.melee_swing_timer = max(
                0.0, getattr(player, "melee_swing_timer", 0.0) - dt)
            weapon = player.firearm
            if weapon is not None:
                weapon.update(dt)
        for enemy in self.enemies.values():
            self._interpolate(enemy, target_time)
            enemy.anim_phase += dt * 6.0
            enemy.hurt_timer = max(0.0, enemy.hurt_timer - dt)
        for bullet in self.bullets.values():
            self._interpolate(bullet, target_time)
        for shot in self.shots.values():
            # Плевки интерполируются так же, как враги: рывков от 20 Гц нет.
            self._interpolate(shot, target_time)
        for drop in self.drops.values():
            self._interpolate(drop, target_time)
            drop.update_view(dt, game.elapsed)
        # Эффекты живут и обновляются на клиенте: сервер их не присылает.
        for effect in game.effects:
            effect.update(dt, game)
        game.effects = [effect for effect in game.effects if effect.alive]
        self.fx.update(dt)
        self._rebuild_lists()

    def _render_time(self):
        """«Сейчас» в шкале снимков: клиентские часы минус половина RTT."""
        return self._clock - float(getattr(self, "net_latency", 0.0))

    def _animate_remote(self, player, target_time):
        """Интерполяция чужого героя + анимация шага по пройденному пути.

        Раньше зеркало меняло только x/y: ``walk_phase`` оставался нулём,
        и персонаж ехал по полу без шага — это и читалось как «скольжение».
        """
        prev_x, prev_y = player.x, player.y
        self._interpolate(player, target_time)
        dx = player.x - prev_x
        dy = player.y - prev_y
        distance = math.hypot(dx, dy)
        if distance > 0.01:
            player.move_dir = (dx / distance, dy / distance)
            player.walk_phase = getattr(player, "walk_phase", 0.0) + \
                distance * WALK_PHASE_PER_PX
        else:
            player.move_dir = (0.0, 0.0)

    def present_swing(self, pid, angle=None):
        """Хост ударил ближним боем — показываем замах его зеркалу.

        Урон и кулдаун остаются у хоста; клиенту нужен только визуал,
        иначе замах гостя видит один хост (свой рывок оружия клиент не
        симулирует).
        """
        player = self.players.get(int(pid))
        if player is None:
            return
        player.melee_swing_timer = 0.22
        player.melee_swing_angle = float(player.angle if angle is None else angle)

    def present_local_melee(self, angle=None):
        """Свой удар виден сразу по нажатию, а не через RTT от хоста.

        Хост всё равно решает, попал ли удар и когда откат: здесь только
        дуга замаха и кулдаун для картинки. Без этого гость бил "в воздух":
        анимация появлялась лишь на звуке от хоста (и с задержкой).
        """
        player = self.players.get(self.local_pid)
        if player is None or not player.alive:
            return
        weapon = player.melee
        attack = getattr(weapon, "attack", None)
        if attack is not None:
            if getattr(attack, "is_passive", False):
                return
            if getattr(attack, "cooldown", 0.0) > 0.0:
                return
            attack.cooldown = float(getattr(attack, "spec", {}).get(
                "cooldown", 0.0) or 0.0)
        self.present_swing(self.local_pid, angle)

    def _rebuild_lists(self):
        """Списки для отрисовки — только когда состав действительно менялся."""
        game = self.game
        enemies = self.enemies
        if len(game.enemies) != len(enemies):
            game.enemies = list(enemies.values())
        bullets = self.bullets
        if len(game.bullets) != len(bullets):
            game.bullets = list(bullets.values())
        drops = self.drops
        if len(game.drops) != len(drops):
            game.drops = list(drops.values())
        shots = self.shots
        current = getattr(game, "enemy_shots", None)
        if current is None or len(current) != len(shots):
            game.enemy_shots = list(shots.values())
        game.grenades = []

    def set_local_input(self, dx, dy):
        previous = getattr(self, "local_input", (0.0, 0.0))
        if (abs(dx - previous[0]) > 1e-6 or abs(dy - previous[1]) > 1e-6):
            # Ввод изменился: хост увидит это через половину RTT плюс тик.
            # До этого его снимок описывает СТАРОЕ движение, и сверка
            # ошибочно тормозила бы старт/разворот.
            self._input_changed_at = getattr(self, "_clock", 0.0)
        self.local_input = (dx, dy)

    def set_local_fire(self, held):
        self.local_fire = bool(held)

    def request_dash(self):
        """Рывок по нажатию: гость не ждёт подтверждения хоста.

        Хост всё равно проверит кулдаун и применит рывок к своей копии.
        Если он откажет (например, кулдаун ещё не прошёл), расхождение
        окажется больше мёртвой зоны и мягко сгладится.
        """
        player = self.players.get(self.local_pid)
        if player is None or not player.alive:
            return
        if getattr(player, "dash_timer", 0.0) > 0.0:
            return                      # уже в рывке — второй не начинаем
        dx, dy = self.local_input
        if not (dx or dy):
            dx, dy = math.cos(player.angle), math.sin(player.angle)
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        player.dash_dir = (dx / length, dy / length)
        player.dash_timer = DASH_TIME
        player.dash_cd = DASH_COOLDOWN
        self._dash_started = self._clock

    def _predict_local(self, player, dt):
        player.dash_cd = max(0.0, getattr(player, "dash_cd", 0.0) - dt)
        if not player.alive:
            # Павший герой ничего не предсказывает: рисуем позицию хоста.
            player.x = getattr(player, "host_x", player.x)
            player.y = getattr(player, "host_y", player.y)
            if not getattr(self, "local_authoritative", False):
                self._record_local(player)
            return
        # Скорость — у зеркала, а не голый PLAYER_SPEED: артефакт, бафф
        # сектора и навык скорости меняют её у хоста. На базовой скорости
        # прогноз отставал тем сильнее, чем быстрее билд, и клиент всё
        # время «догонял» сам себя.
        speed = float(getattr(player, "speed", 0.0) or PLAYER_SPEED)
        world = getattr(self.game, "world", None)
        # Анимация шага читает move_dir: без него зеркало «скользит» —
        # hero двигается, а ноги/покачивание стоят.
        player.move_dir = (player.dash_dir if getattr(player, "dash_timer", 0.0) > 0.0
                           else self.local_input)
        if getattr(player, "dash_timer", 0.0) > 0.0:
            # Рывок предсказываем теми же константами, что и хост: иначе
            # после каждого рывка герой «отматывается» на ~120 px назад.
            # И той же геометрией — один сдвиг и однократное разрешение
            # стен, как в Player.update: иначе у стены диагональный рывок
            # уезжал не туда, и хост возвращал героя.
            player.dash_timer = max(0.0, player.dash_timer - dt)
            step = DASH_SPEED * dt
            if world is not None:
                player.x, player.y = world.resolve_circle(
                    player.x + player.dash_dir[0] * step,
                    player.y + player.dash_dir[1] * step, player.radius)
            else:
                player.x += player.dash_dir[0] * step
                player.y += player.dash_dir[1] * step
            player.walk_phase = getattr(player, "walk_phase", 0.0) + dt * 24.0
        else:
            dx, dy = self.local_input
            if dx or dy:
                length = math.hypot(dx, dy)
                if length > 1.0:
                    dx, dy = dx / length, dy / length
                # «Подвижный контур» зарядного оружия — свойство билда:
                # хост применяет его в те же кадры, когда держим курок.
                move_scale = 1.0
                weapon = player.firearm
                if (weapon is not None and getattr(self, "local_fire", False)
                        and getattr(weapon, "uses_charge", False)):
                    move_scale += float(weapon.mod("charge_move_bonus", 0.0))
                # Двигаем по осям и через те же стены, что у хоста: без этого
                # предсказанный герой проходил сквозь стену, хост возвращал
                # его, и в бою у стены получался рывок назад.
                player.x += dx * speed * dt * move_scale
                if world is not None:
                    player.x, player.y = world.resolve_circle(
                        player.x, player.y, player.radius)
                player.y += dy * speed * dt * move_scale
                if world is not None:
                    player.x, player.y = world.resolve_circle(
                        player.x, player.y, player.radius)
                player.walk_phase = getattr(player, "walk_phase", 0.0) + dt * 10.0
        if getattr(self, "local_authoritative", False):
            # Позиция уже истина: историю не пишем, дрейф не считаем,
            # героя никуда не тянем. Экономит кадр и убирает "резинку".
            self.predict_error = 0.0
            return
        self._record_local(player)
        host_x = getattr(player, "host_x", player.x)
        host_y = getattr(player, "host_y", player.y)
        host_time = getattr(player, "host_time", None)
        # Сверка по ОДНОМУ моменту времени: позиция хоста в снимке — это
        # прошлое (половина RTT плюс тик), поэтому сравнивать её с текущим
        # предсказанием нельзя: честный бег выглядел бы «отставанием» и
        # героя тянуло бы назад тем сильнее, чем быстрее билд. Берём, где
        # предсказание было в момент снимка, — это и есть настоящий дрейф.
        base = (self._local_position_at(host_time)
                if host_time is not None else None)
        if base is None:
            # Нет точки отсчёта (историю только что сбросили): молчим, а
            # не тянем героя к устаревшему снимку — иначе каждый переякорь
            # давал бы рывок назад.
            return
        error_x, error_y = host_x - base[0], host_y - base[1]
        error = math.hypot(error_x, error_y)
        self.predict_error = error
        if error <= PREDICT_DEADZONE:
            return
        if error > PREDICT_SNAP:
            player.x, player.y = host_x, host_y
            self._local_history.clear()
            self._record_local(player)
            return
        # Предсказанный рывок: хост узнаёт о нажатии на половину RTT
        # позже и в это время в снимках ещё «до рывка». Сверка в этом
        # окне отматывала бы героя назад — ждём, пока хост догонит.
        if (getattr(player, "dash_timer", 0.0) > 0.0
                or self._clock - getattr(self, "_dash_started", -10.0)
                < DASH_GRACE):
            return
        # Только что изменился ввод: снимок ещё не может его содержать.
        # Это не дрейф, а честная задержка доставки — не спорим.
        input_age = self._clock - getattr(self, "_input_changed_at", -10.0)
        if input_age < getattr(self, "net_latency", 0.0) * 2.0 + \
                SNAPSHOT_INTERVAL * 2.0:
            return
        # Тянем не «к снимку», а к исправленной траектории: сдвиг тот же,
        # что и настоящий дрейф, и он гасится за ~0.15 с.
        # Гасим ~20% дрейфа за кадр, но не быстрее CORRECTION_SPEED:
        # 40 px уходят за ~0.15 с плавным скольжением, а не рывком.
        step = min(error * min(1.0, 12.0 * dt), CORRECTION_SPEED * dt)
        scale = step / max(error, 1e-6)
        shift_x = error_x * scale
        shift_y = error_y * scale
        player.x += shift_x
        player.y += shift_y
        # Сдвигаем и собственную историю: она — эталон для сверки, и без
        # этого один и тот же дрейф вычитался бы из каждого следующего
        # снимка (коррекция копилась бы и героя вело бы за хостом).
        history = getattr(self, "_local_history", None)
        if history:
            for index in range(len(history)):
                at, hx, hy = history[index]
                history[index] = (at, hx + shift_x, hy + shift_y)
        if world is not None:
            player.x, player.y = world.resolve_circle(
                player.x, player.y, player.radius)

    def _record_local(self, player):
        """Запоминает предсказанную позицию: по ней сверяемся с хостом."""
        history = getattr(self, "_local_history", None)
        if history is None:
            history = self._local_history = []
        history.append((getattr(self, "_clock", 0.0), player.x, player.y))
        if len(history) > LOCAL_HISTORY_LEN:
            del history[0]

    def _local_position_at(self, when):
        """Где предсказание было в момент ``when`` (линейно между кадрами)."""
        history = getattr(self, "_local_history", None)
        if not history:
            return None
        if when <= history[0][0]:
            return history[0][1], history[0][2]
        if when >= history[-1][0]:
            return history[-1][1], history[-1][2]
        for index in range(len(history) - 1, 0, -1):
            t1, x1, y1 = history[index]
            t0, x0, y0 = history[index - 1]
            if t0 <= when <= t1:
                span = t1 - t0
                factor = 0.0 if span <= 0 else (when - t0) / span
                return x0 + (x1 - x0) * factor, y0 + (y1 - y0) * factor
        return history[-1][1], history[-1][2]

    # -------------------------------------------------- МГНОВЕННЫЙ ВЫСТРЕЛ
    def present_local_shot(self, player=None):
        """Вспышка и гильза в кадре нажатия, не дожидаясь хоста.

        Урон, патроны и откат по-прежнему считает хост: здесь только
        картинка, которая иначе приходила бы на RTT+тик позже.
        """
        player = self.players.get(self.local_pid) if player is None else player
        if player is None or not player.alive:
            return
        weapon = player.firearm
        offset = float(getattr(weapon, "muzzle_offset", 16.0) or 16.0)
        angle = float(player.angle)
        x = player.x + math.cos(angle) * offset
        y = player.y + math.sin(angle) * offset
        effects = self.game.effects
        effects.append(MuzzleFlash(x, y, angle))
        if not getattr(weapon, "uses_charge", False):
            effects.append(Casing(x, y, angle))
        player.flash_timer = max(getattr(player, "flash_timer", 0.0), 0.05)
        self._last_local_flash = self._clock
        self._local_flashes.append((self._clock, x, y))
        if len(self._local_flashes) > 8:
            del self._local_flashes[0]

    def consume_local_flash(self, x, y):
        """Гасит дубль вспышки, если этот выстрел уже показан локально."""
        if not self._local_flashes:
            return False
        now = self._clock
        self._local_flashes = [item for item in self._local_flashes
                               if now - item[0] <= LOCAL_FLASH_LIFE]
        limit2 = LOCAL_FLASH_DIST * LOCAL_FLASH_DIST
        for index, (_at, fx, fy) in enumerate(self._local_flashes):
            if (fx - x) ** 2 + (fy - y) ** 2 <= limit2:
                del self._local_flashes[index]
                return True
        return False
    @staticmethod
    def _interpolate(mirror, target_time):
        history = getattr(mirror, "history", None)
        if not history:
            return
        if len(history) == 1 or target_time <= history[0][0]:
            mirror.x, mirror.y = history[0][1], history[0][2]
            return
        if target_time >= history[-1][0]:
            last = history[-1]
            if len(history) < 2:
                mirror.x, mirror.y = last[1], last[2]
                return
            previous = history[-2]
            span = last[0] - previous[0]
            ahead = target_time - last[0]
            if span <= 0.0 or ahead > MAX_EXTRAPOLATE:
                mirror.x, mirror.y = last[1], last[2]
                return
            factor = ahead / span
            mirror.x = last[1] + (last[1] - previous[1]) * factor
            mirror.y = last[2] + (last[2] - previous[2]) * factor
            return
        for index in range(len(history) - 1, 0, -1):
            t1, x1, y1 = history[index]
            t0, x0, y0 = history[index - 1]
            if t0 <= target_time <= t1:
                span = t1 - t0
                factor = 0.0 if span <= 0 else (target_time - t0) / span
                mirror.x = x0 + (x1 - x0) * factor
                mirror.y = y0 + (y1 - y0) * factor
                return

    # ------------------------------------------------------------ JSON (отладка)
    def apply(self, snap):
        """Совместимость: полный JSON-снимок в отладочном режиме."""
        if snap.get("_bin"):
            self.receive(snap)
            return
        game = self.game
        seed = int(snap.get("seed", 0))
        depth = int(snap.get("depth", 1))
        zone = snap.get("zone", game.zone_key)
        if game.world.seed != seed or getattr(game, "depth", 1) != depth:
            game.rebuild_client_world(seed, depth, zone)
            self.reset_mirrors()
        elif game.zone_key != zone:
            game.zone_key = zone
        self.local_pid = snap.get("local_pid", self.local_pid)
        self._ensure_players(snap.get("players", ()))
        self._ensure_enemies(snap.get("enemies", ()))
        self._ensure_bullets(snap.get("bullets", ()))
        self._ensure_drops(snap.get("drops", ()))
        for state in snap.get("enemies", ()):
            enemy = self.enemies.get(int(state["id"]))
            if enemy is not None:
                enemy.max_hp = float(state.get("max_hp", enemy.max_hp))
                enemy.color = tuple(state.get("color") or enemy.color or ())
        self._json_apply_state(snap)
        for state in snap.get("players", ()):
            apply_progress(self.players.get(int(state.get("pid", 0))),
                           state.get("progress"))
        states = snap.get("beacons", ())
        if states and isinstance(states[0], dict):
            by_index = {beacon.index: beacon
                        for beacon in game.descent.beacons}
            for state in states:
                beacon = by_index.get(state.get("index"))
                if beacon is None:
                    continue
                beacon.state = state.get("state", beacon.state)
                beacon.progress = protocol.clamp(state.get("progress"), 0.0, 1.0)
                beacon.linked = beacon.state == "charging"
        self.fx.apply(snap)
        player = self.players.get(self.local_pid)
        if player is not None:
            game.player = player
            game.players = list(self.players.values())
        self._rebuild_lists()

    def _ensure_players(self, states):
        for state in states:
            pid = int(state.get("pid", 0))
            if pid <= 0 or pid in self.players:
                continue
            player = Player(float(state.get("x", 0.0)),
                            float(state.get("y", 0.0)))
            player.pid = pid
            player.is_local = pid == self.local_pid
            self.players[pid] = player

    def _ensure_enemies(self, states):
        for state in states:
            eid = int(state.get("id", 0))
            self.apply_spawn({"enemies": [(
                eid, state.get("kind", "Enemy"),
                float(state.get("radius", 18.0)),
                float(state.get("max_hp", 1.0)), state.get("color"),
                (F_ELITE if state.get("elite") else 0)
                | (F_BOSS if state.get("boss") else 0))]})

    def _ensure_bullets(self, states):
        for state in states:
            bid = int(state.get("id", 0))
            self.apply_spawn({"bullets": [(
                bid, float(state.get("radius", 3.0)),
                state.get("style", "bullet"), state.get("color"))]})

    def _ensure_drops(self, states):
        for state in states:
            did = int(state.get("id", 0))
            self.apply_spawn({"drops": [(
                did, state.get("sprite", "coin"), state.get("glow"))]})

    def _json_apply_state(self, snap):
        now = self._snapshot_time(snap)
        for state in snap.get("players", ()):
            player = self.players.get(int(state.get("pid", 0)))
            if player is None:
                continue
            row = (int(state.get("pid", 0)), float(state.get("x", 0.0)),
                   float(state.get("y", 0.0)),
                   float(state.get("angle", 0.0)),
                   float(state.get("hp", 0.0)),
                   float(state.get("max_hp", 100.0)),
                   F_ALIVE if state.get("alive", True) else 0,
                   int(state.get("money", 0)), int(state.get("ammo", 0)),
                   int(state.get("loaded", 0)), 0,
                   int(state.get("score", 0)), int(state.get("kills", 0)),
                   float(state.get("speed", PLAYER_SPEED)))
            self._apply_players([row], now)
        for state in snap.get("enemies", ()):
            flags = ((F_BURROWED if state.get("burrowed") else 0)
                     | (F_ELITE if state.get("elite") else 0)
                     | (F_BOSS if state.get("boss") else 0))
            self._apply_enemies([(int(state.get("id", 0)),
                                  float(state.get("x", 0.0)),
                                  float(state.get("y", 0.0)),
                                  float(state.get("angle", 0.0)),
                                  float(state.get("hp", 0.0)), flags)], now)
        for state in snap.get("bullets", ()):
            self._apply_bullets([(int(state.get("id", 0)),
                                  float(state.get("x", 0.0)),
                                  float(state.get("y", 0.0)),
                                  float(state.get("vx", 0.0)),
                                  float(state.get("vy", 0.0)),
                                  float(state.get("charge", 0.0)))],
                                self._clock)
        for state in snap.get("drops", ()):
            self._apply_drops([(int(state.get("id", 0)),
                                float(state.get("x", 0.0)),
                                float(state.get("y", 0.0)))], now)
