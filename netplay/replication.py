"""Репликация под конкретного гостя: интерес, spawn/despawn, снимок.

Гость видит ~2×2 чанка (один чанк — 1024 px). Всё, что дальше, — это
трафик и работа впустую: гость не симулирует, ему нечем пользоваться
дальними числами. Хост продолжает симулировать весь мир — режется только
ОТПРАВКА.

Гистерезис: сущность появилась в 1400 px — пришёл дескриптор, ушла за
1700 px — уезжает despawn. Порог «на выход» больше, чтобы сущность на
границе не мигала каждый тик. Снаряды живут доли секунды, им хватает
900/1100 px.

Сущность, пропавшая из мира без явного despawn (умерла, подобрана),
считается мёртвой только после трёх снимков подряд без её id — это
защита от одиночного «пропуска» в кадре.
"""

from . import binary
from .binary import F_BOSS

INTEREST_RADIUS = 1400.0
INTEREST_LEAVE = 1700.0
BULLET_RADIUS = 900.0
BULLET_LEAVE = 1100.0
SILENCE_LIMIT = 3

_ENTER2 = INTEREST_RADIUS * INTEREST_RADIUS
_LEAVE2 = INTEREST_LEAVE * INTEREST_LEAVE
_BULLET_ENTER2 = BULLET_RADIUS * BULLET_RADIUS
_BULLET_LEAVE2 = BULLET_LEAVE * BULLET_LEAVE


class ClientReplication:
    """Что гость уже знает и что ему нужно отправить в этом тике."""

    __slots__ = ("local_pid", "_enemies", "_bullets", "_drops", "_shots",
                 "_players", "spawned_players", "spawned_enemies",
                 "spawned_bullets", "spawned_drops", "spawned_shots",
                 "interest", "listen")

    def __init__(self, local_pid=1, interest=True):
        self.local_pid = int(local_pid)
        self.interest = interest
        self._enemies = {}   # id -> [miss, object]
        self._bullets = {}
        self._drops = {}
        self._shots = {}
        self._players = {}   # pid -> object
        self.spawned_players = []
        self.spawned_enemies = []
        self.spawned_bullets = []
        self.spawned_drops = []
        self.spawned_shots = []
        self.listen = True   # выключено на паузе: не шлём состояния зря

    def reset(self):
        self._enemies.clear()
        self._bullets.clear()
        self._drops.clear()
        self._shots.clear()
        self._players.clear()
        self._clear_spawned()

    def _clear_spawned(self):
        self.spawned_players.clear()
        self.spawned_enemies.clear()
        self.spawned_bullets.clear()
        self.spawned_drops.clear()
        self.spawned_shots.clear()

    # ------------------------------------------------------------ СБОРКА
    def frames(self, world, seq, writer, rev_for):
        """Собирает кадры для одного гостя.

        Возвращает ``(despawn_frame, spawn_frame, snapshot_frame)``;
        despawn/spawn — None, если ничего не изменилось.
        """
        focus_x, focus_y = self._focus(world)
        self._clear_spawned()
        players = []
        enemies = []
        bullets = []
        drops = []
        shots = []
        gone_players = []
        gone_enemies = []
        gone_bullets = []
        gone_drops = []
        gone_shots = []

        # --- игроки: всегда все, их немного
        seen_pids = set()
        for player, row in world.players:
            pid = row[0]
            seen_pids.add(pid)
            if pid not in self._players:
                self._players[pid] = player
                self.spawned_players.append((pid, player))
            players.append((pid, row[1], row[2], row[3], row[4], row[5],
                            row[6], row[7], row[8], row[9], rev_for(pid),
                            row[10], row[11], row[12]))
        for pid in list(self._players):
            if pid in seen_pids:
                continue
            del self._players[pid]
            gone_players.append(pid)

        # --- враги: близкие + боссы всегда
        self._select(world.enemies, self._enemies, focus_x, focus_y,
                     _ENTER2, _LEAVE2, enemies, gone_enemies,
                     self.spawned_enemies, always=self._enemy_always,
                     row_x=1, row_y=2)

        # --- снаряды: они живут доли секунды, радиус меньше
        self._select(world.bullets, self._bullets, focus_x, focus_y,
                     _BULLET_ENTER2, _BULLET_LEAVE2, bullets, gone_bullets,
                     self.spawned_bullets, always=None, row_x=1, row_y=2)

                # --- дропы: как обычные сущности интереса
        self._select(world.drops, self._drops, focus_x, focus_y,
                     _ENTER2, _LEAVE2, drops, gone_drops,
                     self.spawned_drops, always=None, row_x=1, row_y=2)

        # --- снаряды врагов: гость должен видеть плевки и их полёт
        self._select(world.shots, self._shots, focus_x, focus_y,
                     _BULLET_ENTER2, _BULLET_LEAVE2, shots, gone_shots,
                     self.spawned_shots, always=None, row_x=1, row_y=2)

        despawn = None
        if gone_players or gone_enemies or gone_bullets or gone_drops \
                or gone_shots:
            despawn = binary.encode_despawn(gone_players, gone_enemies,
                                            gone_bullets, gone_drops,
                                            gone_shots)
        spawn = None
        if self.spawned_players or self.spawned_enemies or \
                self.spawned_bullets or self.spawned_drops or \
                self.spawned_shots:
            spawn = binary.encode_spawn(world, (
                self.spawned_players, self.spawned_enemies,
                self.spawned_bullets, self.spawned_drops,
                self.spawned_shots))
        header = (seq, world.seed, world.depth, world.zone, world.state,
                  self.local_pid, binary.F_LIFT if world.lift_open else 0,
                  world.tick)
        snapshot = binary.encode_snapshot(writer, header, players, enemies,
                                          bullets, drops, world.beacons,
                                          shots, world.opened)
        return despawn, spawn, snapshot

    @staticmethod
    def _enemy_always(row):
        return bool(row[5] & F_BOSS)

    def _focus(self, world):
        for player, row in world.players:
            if row[0] == self.local_pid:
                return row[1], row[2]
        if world.players:
            row = world.players[0][1]
            return row[1], row[2]
        return 0.0, 0.0

    def _select(self, entries, known, fx, fy, enter2, leave2, out, gone,
                spawned, always, row_x, row_y):
        """Один проход по массиву состояний с гистерезисом и «тишиной»."""
        seen = set()
        for obj, row in entries:
            entity_id = row[0]
            seen.add(entity_id)
            dx = row[row_x] - fx
            dy = row[row_y] - fy
            distance2 = dx * dx + dy * dy
            entry = known.get(entity_id)
            if entry is None:
                if not self.interest or (always is not None and always(row)) \
                        or distance2 <= enter2:
                    known[entity_id] = [0, obj]
                    spawned.append((entity_id, obj))
                    out.append(row)
                continue
            entry[0] = 0
            if not self.interest or (always is not None and always(row)) \
                    or distance2 <= leave2:
                out.append(row)
            else:
                del known[entity_id]
                gone.append(entity_id)
        for entity_id, entry in list(known.items()):
            if entity_id in seen:
                continue
            entry[0] += 1
            if entry[0] >= SILENCE_LIMIT:
                del known[entity_id]
                gone.append(entity_id)


class ProgressTracker:
    """Прогрессия по изменению: rev растёт только при реальной покупке."""

    def __init__(self):
        self._signature = {}
        self._rev = {}
        self._dirty = set()

    def reset(self):
        self._signature.clear()
        self._rev.clear()
        self._dirty.clear()

    def rev(self, pid):
        return self._rev.get(pid, 0)

    def mark_dirty(self, pid):
        self._dirty.add(pid)

    def invalidate(self):
        """Прислать прогрессию всем заново, не сбрасывая rev.

        Нужно после смены сектора: клиент пересобрал зеркало и потерял
        оружие/навыки, а сигнатура у хоста при этом не менялась. Счётчик
        rev продолжает расти — иначе клиент отбросил бы кадр как старый.
        """
        self._signature.clear()
        self._dirty.clear()

    def poll(self, players, progress_state):
        """Возвращает кадры progress для изменившихся героев.

        Вызывается на тике хоста: длины/ключи вместо полной сборки
        прогрессии. Изменение подтверждается сборкой состояния — только
        тогда, когда оно действительно есть.
        """
        frames = []
        for player in players:
            pid = int(getattr(player, "pid", 0))
            if pid <= 0:
                continue
            signature = _signature_of(player)
            previous = self._signature.get(pid)
            if previous is None or signature != previous or pid in self._dirty:
                self._signature[pid] = signature
                self._dirty.discard(pid)
                rev = self._rev.get(pid, 0) + 1
                self._rev[pid] = rev
                frames.append(binary.encode_progress(
                    pid, rev, progress_state(player)))
        return frames

    def forget(self, pid):
        self._signature.pop(pid, None)
        self._rev.pop(pid, None)
        self._dirty.discard(pid)


def _signature_of(player):
    from .snapshot import progress_signature
    return progress_signature(player)
