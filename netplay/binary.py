"""Бинарный протокол: кадр u32-длина + u8-тип + payload.

JSON остаётся отладочным режимом (``--net-debug``): он читается глазами,
но на горячем пути (20 снимков в секунду × 4 гостя) строит сотни словарей
и строк, которые тут же становятся мусором.

Здесь всё наоборот:
  * сборка идёт в заранее выделенный ``bytearray`` — никакой конкатенации
    байтов и промежуточных словарей;
  * числа квантуются (позиция 1/16 px, угол 1/65536 оборота, HP 1/8);
  * статические поля сущности (kind, radius, color, max_hp) едут один раз
    в сообщении ``spawn``, а снимок несёт только id и меняющиеся числа.

Раскладка снимка (little-endian)::

    seq u32, seed q, depth u16, zone u8, state u8, local_pid u8,
    flags u8, tick f32
    players u8:  pid u8, x i32, y i32, angle u16, hp u16, max_hp u16,
                 flags u8, money i32, ammo u16, loaded u16, rev u16,
                 score u32, kills u16, speed u16 (1/8 px/s)
    enemies u16: id u32, x i32, y i32, angle u16, hp u16, flags u8,
                 windup u8, charge u8
    bullets u16: id u32, x i32, y i32, vx i16, vy i16, charge u8
    drops u16:   id u32, x i32, y i32
    beacons u8:  index u8, x i32, y i32, state u8, progress u16
    shots u16:   id u32, x i32, y i32, vx i16, vy i16
    opened u16:  chunk_x i16, chunk_y i16

``shots`` — снаряды дальних врагов (``game.enemy_shots``). Они не пули
игрока: урон и полёт считает хост, гостю нужны позиция, скорость и
радиус, чтобы снаряд был виден и читался как угроза.
"""

import json
import struct

from . import protocol

# ---------------------------------------------------------------- ТИПЫ КАДРОВ
T_JSON = 0          # обычное сообщение в JSON (hello/welcome/start/notice/…)
T_SPAWN = 1         # дескрипторы новых сущностей
T_SNAPSHOT = 2      # только состояния известных id
T_DESPAWN = 3       # id ушедших сущностей
T_PROGRESS = 4      # полная прогрессия героя по изменению (rev)
T_INPUT = 5         # ввод гостя, ~30 байт (с позицией героя) вместо ~120
T_SOUND = 6         # звуки игроков: pid, ключ, позиция, громкость
T_EVENT = 7         # разовые визуальные события: взрывы, удары врагов

ZONES = ("dark", "medium", "cozy")
_ZONE_INDEX = {name: index for index, name in enumerate(ZONES)}
STATES = ("playing", "shop", "paused", "descent", "tree", "game_over",
          "title", "online", "settings", "difficulty")
_STATE_INDEX = {name: index for index, name in enumerate(STATES)}

ACTIONS = protocol.ACTION_KEYS_ORDER
_ACTION_BITS = {name: 1 << index for index, name in enumerate(ACTIONS)}

# Флаги сущностей в снимке.
F_ALIVE = 1 << 0
F_BURROWED = 1 << 1
F_WARNING = 1 << 2
F_ELITE = 1 << 3
F_BOSS = 1 << 4
F_LIFT = 1 << 5

POS_SCALE = 16.0        # 1/16 px
VEL_SCALE = 4.0         # 1/4 px в секунду
HP_SCALE = 8.0          # 1/8 hp
ANGLE_SCALE = 65536.0 / 6.283185307179586

# Звуки игроков. Список фиксирован: по сети едет u8-индекс, а не строка.
# Новый звук = новый ключ в конце (старые индексы не двигать!). Должен
# совпадать с soundbank.HEAR_RADIUS — это проверяет тест.
SOUND_KEYS = (
    "shoot", "shotgun", "sniper", "lightning", "spit_charge",
    "swing", "dash", "reload", "empty", "throw", "hurt", "heal",
    "pickup", "explosion", "shield", "artifact",
)
_SOUND_INDEX = {name: index for index, name in enumerate(SOUND_KEYS)}
SOUND_RADIUS = 1600.0
SOUND_MAX_EVENTS = 32

# Разовые события мира. Снимок описывает СОСТОЯНИЕ, а взрыв или удар
# врага живут доли секунды: к следующему снимку от них остаётся только
# урон в HP. Гость должен увидеть сам момент, поэтому событие едет
# отдельным кадром (взрыв — радиус и цвет, удар — позиция).
EVENT_KINDS = ("explosion", "enemy_attack")
_EVENT_INDEX = {name: index for index, name in enumerate(EVENT_KINDS)}

_FRAME = struct.Struct("!I")


# ---------------------------------------------------------------- СБОРКА
class Writer:
    """Буфер сборки без перевыделений на каждом кадре."""

    __slots__ = ("buf",)

    def __init__(self, capacity=4096):
        # capacity — это резерв на будущее, а не данные. bytearray(capacity)
        # создал бы capacity нулевых байт, и каждый кадр уезжал бы с мусорным
        # префиксом длиной в резерв.
        self.buf = bytearray()

    def reset(self):
        del self.buf[:]

    def _need(self, size):
        if len(self.buf) < size:
            self.buf.extend(b"\x00" * (size - len(self.buf)))

    def pack(self, fmt, *values):
        size = struct.calcsize(fmt)
        start = len(self.buf)
        self._need(start + size)
        struct.pack_into(fmt, self.buf, start, *values)

    def text(self, value):
        """Строка один раз (в дескрипторе): u8-длина + utf-8."""
        raw = str(value or "")[:48].encode("utf-8")
        if len(raw) > 255:
            raw = raw[:255]
        self.pack("<B", len(raw))
        start = len(self.buf)
        self._need(start + len(raw))
        self.buf[start:start + len(raw)] = raw

    def u8(self, value):
        self.pack("<B", int(value) & 0xFF)

    def u16(self, value):
        self.pack("<H", max(0, min(65535, int(value))))

    def u32(self, value):
        self.pack("<I", max(0, min(0xFFFFFFFF, int(value))))

    def i32(self, value):
        self.pack("<i", max(-0x80000000, min(0x7FFFFFFF, int(value))))

    def i16(self, value):
        self.pack("<h", max(-0x8000, min(0x7FFF, int(value))))

    def f32(self, value):
        self.pack("<f", float(value))

    def frame(self, kind):
        """Превращает накопленный payload в кадр (u32 длина + u8 тип)."""
        body = self.buf
        return (struct.pack("!I", len(body) + 1) + bytes((kind,))
                + bytes(body))


def pos(value):
    return int(round(float(value) * POS_SCALE))


def hp(value):
    return max(0, min(65535, int(round(float(value) * HP_SCALE))))


def radius(value):
    return max(0, min(65535, int(round(float(value) * HP_SCALE))))


def angle(value):
    raw = int(round((float(value) % 6.283185307179586) * ANGLE_SCALE))
    return raw & 0xFFFF


def velocity(value):
    return max(-0x8000, min(0x7FFF, int(round(float(value) * VEL_SCALE))))


def ratio(value, scale=1000.0):
    return max(0, min(65535, int(round(float(value) * scale))))


def _color(writer, color):
    if color is None:
        writer.u8(255)
        writer.u8(255)
        writer.u8(255)
        return
    try:
        red, green, blue = (int(c) for c in tuple(color)[:3])
    except (TypeError, ValueError):
        red, green, blue = 255, 255, 255
    writer.u8(max(0, min(255, red)))
    writer.u8(max(0, min(255, green)))
    writer.u8(max(0, min(255, blue)))


# ---------------------------------------------------------------- СПАВН
def encode_spawn(world, known_descriptors):
    """Дескрипторы для новых id: поля, которые не меняются.

    ``known_descriptors`` — списки (player, enemy, bullet, drop, shot), по
    которым уже отправлены дескрипторы. В кадр попадают только новые.
    Пятый список необязателен: старые вызовы с четырьмя работают как есть.
    """
    writer = Writer(512)
    groups = list(known_descriptors)
    while len(groups) < 5:
        groups.append(())
    players, enemies, bullets, drops, shots = groups[:5]
    writer.u8(len(players))
    for key, player in players:
        writer.u8(int(key) & 0xFF)
        writer.text(getattr(player, "name", "Игрок"))
        writer.u16(hp(getattr(player, "max_hp", 100.0)))
        _color(writer, getattr(getattr(player, "firearm", None), "glow_color",
                               None))
    writer.u16(len(enemies))
    for key, enemy in enemies:
        writer.u32(int(key))
        writer.text(type(enemy).__name__)
        writer.u16(radius(getattr(enemy, "radius", 18.0)))
        writer.u16(hp(getattr(enemy, "max_hp", 1.0)))
        _color(writer, getattr(enemy, "color", None))
        flags = 0
        if getattr(enemy, "elite", False):
            flags |= F_ELITE
        if getattr(enemy, "is_boss", False):
            flags |= F_BOSS
        writer.u8(flags)
    writer.u16(len(bullets))
    for key, bullet in bullets:
        writer.u32(int(key))
        writer.u16(radius(getattr(bullet, "radius", 3.0)))
        writer.text(getattr(bullet, "style", "bullet"))
        _color(writer, getattr(bullet, "color", None))
    writer.u16(len(drops))
    for key, drop in drops:
        writer.u32(int(key))
        writer.text(getattr(drop, "sprite_name", "coin") or "coin")
        _color(writer, getattr(drop, "glow_color", None))
    writer.u16(len(shots))
    for key, shot in shots:
        writer.u32(int(key))
        writer.u16(radius(getattr(shot, "radius", 7.0)))
    return writer.frame(T_SPAWN)


def decode_spawn(body):
    view = memoryview(body)
    offset = 0

    def take(fmt):
        nonlocal offset
        value = struct.unpack_from(fmt, view, offset)
        offset += struct.calcsize(fmt)
        return value

    def text():
        nonlocal offset
        (size,) = take("<B")
        raw = bytes(view[offset:offset + size]).decode("utf-8", "replace")
        offset += size
        return raw

    def color():
        nonlocal offset
        red, green, blue = take("<BBB")
        offset += 0
        return None if red == 255 and green == 255 and blue == 255 else (
            red, green, blue)

    (count,) = take("<B")
    players = []
    for _ in range(count):
        pid = take("<B")[0]
        name = text()
        max_hp = take("<H")[0] / HP_SCALE
        take("<BBB")
        players.append((pid, name, max_hp))
    (count,) = take("<H")
    enemies = []
    for _ in range(count):
        eid = take("<I")[0]
        kind = text()
        rad = take("<H")[0] / HP_SCALE
        max_hp = take("<H")[0] / HP_SCALE
        col = take("<BBB")
        col = None if col == (255, 255, 255) else col
        flags = take("<B")[0]
        enemies.append((eid, kind, rad, max_hp, col, flags))
    (count,) = take("<H")
    bullets = []
    for _ in range(count):
        bid = take("<I")[0]
        rad = take("<H")[0] / HP_SCALE
        style = text()
        col = take("<BBB")
        col = None if col == (255, 255, 255) else col
        bullets.append((bid, rad, style, col))
    (count,) = take("<H")
    drops = []
    for _ in range(count):
        did = take("<I")[0]
        sprite = text()
        col = take("<BBB")
        col = None if col == (255, 255, 255) else col
        drops.append((did, sprite, col))
    (count,) = take("<H")
    shots = []
    for _ in range(count):
        sid = take("<I")[0]
        rad = take("<H")[0] / HP_SCALE
        shots.append((sid, rad))
    return {"t": "spawn", "_bin": True, "players": players,
            "enemies": enemies, "bullets": bullets, "drops": drops,
            "shots": shots}


# ---------------------------------------------------------------- СНИМОК
def encode_snapshot(writer, header, players, enemies, bullets, drops,
                    beacons, shots=(), opened=()):
    """Пишет снимок в переданный Writer (переиспользуется между гостями)."""
    writer.reset()
    seq, seed, depth, zone, state, local_pid, flags, tick = header
    writer.pack("<IqHBBBBf", int(seq), int(seed), int(depth),
                _ZONE_INDEX.get(zone, 0), _STATE_INDEX.get(state, 0),
                int(local_pid), int(flags), float(tick))
    writer.u8(len(players))
    for (pid, x, y, ang, cur_hp, max_hp, pflags, money, ammo, loaded,
         rev, score, kills, speed) in players:
        writer.pack("<BiiHHHBiHHHIHH", int(pid), pos(x), pos(y), angle(ang),
                    hp(cur_hp), hp(max_hp), int(pflags) & 0xFF, int(money),
                    max(0, min(65535, int(ammo))), max(0, min(65535, int(loaded))),
                    max(0, min(65535, int(rev))), max(0, int(score)),
                    max(0, min(65535, int(kills))),
                    max(0, min(65535, int(round(float(speed) * 8.0)))))
    writer.u16(len(enemies))
    for raw in enemies:
        eid, x, y, ang, cur_hp, eflags = raw[:6]
        windup = raw[6] if len(raw) > 6 else 0
        charge = raw[7] if len(raw) > 7 else 0
        writer.pack("<IiiHHBBB", int(eid), pos(x), pos(y), angle(ang),
                    hp(cur_hp), int(eflags) & 0xFF,
                    max(0, min(255, int(windup))) & 0xFF,
                    max(0, min(255, int(charge))) & 0xFF)
    writer.u16(len(bullets))
    for bid, x, y, vx, vy, charge in bullets:
        writer.pack("<Iii hhB", int(bid), pos(x), pos(y), velocity(vx),
                    velocity(vy), int(charge * 255) & 0xFF)
    writer.u16(len(drops))
    for did, x, y in drops:
        writer.pack("<Iii", int(did), pos(x), pos(y))
    writer.u8(len(beacons))
    for index, x, y, bstate, progress in beacons:
        writer.pack("<BiiBH", int(index) & 0xFF, pos(x), pos(y),
                    int(bstate) & 0xFF, ratio(progress))
    writer.u16(len(shots))
    for raw in shots:
        sid, x, y, vx, vy = raw[:5]
        writer.pack("<Iii hh", int(sid), pos(x), pos(y), velocity(vx),
                    velocity(vy))
    writer.u16(len(opened))
    for site in opened:
        cx, cy = site[0], site[1]
        writer.pack("<hh", max(-32768, min(32767, int(cx))),
                    max(-32768, min(32767, int(cy))))
    return writer.frame(T_SNAPSHOT)


def decode_snapshot(body):
    view = memoryview(body)
    offset = 0

    def take(fmt):
        nonlocal offset
        values = struct.unpack_from(fmt, view, offset)
        offset += struct.calcsize(fmt)
        return values

    (seq, seed, depth, zone_index, state_index, local_pid, flags,
     tick) = take("<IqHBBBBf")
    players = []
    (count,) = take("<B")
    for _ in range(count):
        (pid, x, y, ang, cur_hp, max_hp, pflags, money, ammo, loaded, rev,
         score, kills, speed) = take("<BiiHHHBiHHHIHH")
        players.append((pid, x / POS_SCALE, y / POS_SCALE,
                        ang / ANGLE_SCALE, cur_hp / HP_SCALE,
                        max_hp / HP_SCALE, pflags, money, ammo, loaded, rev,
                        score, kills, speed / 8.0))
    enemies = []
    (count,) = take("<H")
    for _ in range(count):
        (eid, x, y, ang, cur_hp, eflags, windup,
         charge) = take("<IiiHHBBB")
        enemies.append((eid, x / POS_SCALE, y / POS_SCALE,
                        ang / ANGLE_SCALE, cur_hp / HP_SCALE, eflags,
                        windup / 255.0, charge / 255.0))
    bullets = []
    (count,) = take("<H")
    for _ in range(count):
        (bid, x, y, vx, vy, charge) = take("<Iii hhB")
        bullets.append((bid, x / POS_SCALE, y / POS_SCALE,
                        vx / VEL_SCALE, vy / VEL_SCALE, charge / 255.0))
    drops = []
    (count,) = take("<H")
    for _ in range(count):
        (did, x, y) = take("<Iii")
        drops.append((did, x / POS_SCALE, y / POS_SCALE))
    beacons = []
    (count,) = take("<B")
    for _ in range(count):
        (index, x, y, bstate, progress) = take("<BiiBH")
        beacons.append((index, x / POS_SCALE, y / POS_SCALE, bstate,
                        progress / 1000.0))
    shots = []
    (count,) = take("<H")
    for _ in range(count):
        (sid, x, y, vx, vy) = take("<Iii hh")
        shots.append((sid, x / POS_SCALE, y / POS_SCALE,
                      vx / VEL_SCALE, vy / VEL_SCALE))
    opened = []
    (count,) = take("<H")
    for _ in range(count):
        (cx, cy) = take("<hh")
        opened.append((cx, cy))
    return {
        "t": "snapshot", "_bin": True, "seq": seq, "seed": seed,
        "depth": depth, "zone": ZONES[zone_index] if zone_index < len(ZONES)
        else "medium",
        "state": STATES[state_index] if state_index < len(STATES) else "",
        "local_pid": local_pid, "lift_open": bool(flags & F_LIFT),
        "tick": tick, "players": players, "enemies": enemies,
        "bullets": bullets, "drops": drops, "shots": shots,
        "opened": opened, "beacons": beacons,
    }


# ---------------------------------------------------------------- DESPAWN
def encode_despawn(players, enemies, bullets, drops, shots=()):
    writer = Writer(64)
    writer.u8(len(players))
    for pid in players:
        writer.u8(pid)
    for group in (enemies, bullets, drops, shots):
        writer.u16(len(group))
        for entity_id in group:
            writer.u32(entity_id)
    return writer.frame(T_DESPAWN)


def decode_despawn(body):
    view = memoryview(body)
    offset = 0

    def take(fmt):
        nonlocal offset
        values = struct.unpack_from(fmt, view, offset)
        offset += struct.calcsize(fmt)
        return values

    (count,) = take("<B")
    players = [take("<B")[0] for _ in range(count)]
    groups = []
    for _ in range(4):
        (count,) = take("<H")
        groups.append([take("<I")[0] for _ in range(count)])
    return {"t": "despawn", "_bin": True, "players": players,
            "enemies": groups[0], "bullets": groups[1], "drops": groups[2],
            "shots": groups[3]}


# ---------------------------------------------------------------- PROGRESS
def encode_progress(pid, rev, state):
    """Прогрессия едет только при изменении: pid + rev + JSON состояния."""
    writer = Writer(640)
    writer.u8(int(pid))
    writer.u16(int(rev))
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8")
    writer.u32(len(raw))
    start = len(writer.buf)
    writer._need(start + len(raw))
    writer.buf[start:start + len(raw)] = raw
    return writer.frame(T_PROGRESS)


def decode_progress(body):
    view = memoryview(body)
    pid, rev, size = struct.unpack_from("<BH I", view, 0)
    raw = bytes(view[7:7 + size])
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    return {"t": "progress", "_bin": True, "pid": pid, "rev": rev,
            "data": data if isinstance(data, dict) else {}}


# ---------------------------------------------------------------- ВВОД
def encode_input(seq, move, aim, aim_pos, fire, melee, actions,
                 position=None):
    """Ввод гостя. ``position`` — где его герой находится у себя.

    Клиент — владелец позиции своего героя: хост только принимает её и
    рассылает дальше. Это убирает сверку/откаты у гостя и снимает с
    хоста симуляцию движения чужих героев (приоритет — отзывчивость,
    а не защита от подмены координат).
    """
    writer = Writer(32)
    flags = (1 if fire else 0) | (2 if melee else 0)
    if position is not None:
        flags |= 4
    bits = 0
    for action in actions:
        bits |= _ACTION_BITS.get(action, 0)
    px, py = position if position is not None else (0.0, 0.0)
    writer.pack("<BHhhHiiiiB", flags, int(seq) & 0xFFFF,
                max(-1000, min(1000, int(round(move[0] * 1000)))),
                max(-1000, min(1000, int(round(move[1] * 1000)))),
                angle(aim), pos(aim_pos[0]), pos(aim_pos[1]),
                pos(px), pos(py), bits & 0xFF)
    return writer.frame(T_INPUT)


def decode_input(body):
    """Ввод приходит уже в безопасных диапазонах: NaN/строк сюда не попасть."""
    (flags, seq, dx, dy, ang, aim_x, aim_y, px, py,
     bits) = struct.unpack_from("<BHhhHiiiiB", body, 0)
    actions = [name for name in ACTIONS if bits & _ACTION_BITS[name]]
    return {
        "t": "input", "_bin": True, "seq": seq,
        "move": (dx / 1000.0, dy / 1000.0),
        "aim": ang / ANGLE_SCALE,
        "aim_x": aim_x / POS_SCALE, "aim_y": aim_y / POS_SCALE,
        "pos": ((px / POS_SCALE, py / POS_SCALE) if flags & 4 else None),
        "fire": bool(flags & 1), "melee": bool(flags & 2),
        "actions": actions,
    }


# ---------------------------------------------------------------- ЗВУКИ
def encode_sounds(events, focus=None, radius=SOUND_RADIUS):
    """Кадр звуков игроков для одного гостя.

    ``events`` — (pid, name, x, y, volume). По сети едет только позиция и
    базовая громкость: затухание и панораму каждый клиент считает сам.
    Если ``focus`` задан, события дальше ``radius`` не отправляются —
    гость всё равно ничего не услышит.
    """
    writer = Writer(64)
    count_at = len(writer.buf)
    writer.u8(0)
    written = 0
    fx, fy = focus if focus is not None else (None, None)
    radius2 = float(radius) * float(radius)
    for pid, name, x, y, volume in events:
        key = _SOUND_INDEX.get(name)
        if key is None:
            continue
        if fx is not None:
            dx = float(x) - fx
            dy = float(y) - fy
            if dx * dx + dy * dy > radius2:
                continue
        writer.pack("<BBiiB", int(pid) & 0xFF, key, pos(x), pos(y),
                    max(0, min(255, int(round(float(volume) * 255.0)))))
        written += 1
        if written >= SOUND_MAX_EVENTS:
            break
    if written == 0:
        return None
    writer.buf[count_at] = written
    return writer.frame(T_SOUND)


def decode_sounds(body):
    view = memoryview(body)
    offset = 0
    (count,) = struct.unpack_from("<B", view, offset)
    offset += 1
    size = struct.calcsize("<BBiiB")
    items = []
    for _ in range(count):
        pid, key, x, y, level = struct.unpack_from("<BBiiB", view, offset)
        offset += size
        if key >= len(SOUND_KEYS):
            continue
        items.append((pid, SOUND_KEYS[key], x / POS_SCALE, y / POS_SCALE,
                      level / 255.0))
    return {"t": "sounds", "_bin": True, "items": items}


# ---------------------------------------------------------------- СОБЫТИЯ
def encode_events(events, focus=None, radius=SOUND_RADIUS):
    """Кадр разовых визуальных событий (взрывы, удары врагов)."""
    writer = Writer(48)
    count_at = len(writer.buf)
    writer.u8(0)
    written = 0
    fx, fy = focus if focus is not None else (None, None)
    radius2 = float(radius) * float(radius)
    for kind, x, y, size, color in events:
        key = _EVENT_INDEX.get(kind)
        if key is None:
            continue
        if fx is not None:
            dx = float(x) - fx
            dy = float(y) - fy
            if dx * dx + dy * dy > radius2:
                continue
        red, green, blue = color or (255, 255, 255)
        writer.pack("<BiiHBBB", key, pos(x), pos(y),
                    max(0, min(65535, int(round(size)))),
                    int(red) & 0xFF, int(green) & 0xFF, int(blue) & 0xFF)
        written += 1
        if written >= 24:
            break
    if written == 0:
        return None
    writer.buf[count_at] = written
    return writer.frame(T_EVENT)


def decode_events(body):
    view = memoryview(body)
    (count,) = struct.unpack_from("<B", view, 0)
    offset = 1
    size = struct.calcsize("<BiiHBBB")
    items = []
    for _ in range(count):
        kind, x, y, radius, red, green, blue = struct.unpack_from(
            "<BiiHBBB", view, offset)
        offset += size
        if kind >= len(EVENT_KINDS):
            continue
        color = None if (red, green, blue) == (255, 255, 255) \
            else (red, green, blue)
        items.append((EVENT_KINDS[kind], x / POS_SCALE, y / POS_SCALE,
                      float(radius), color))
    return {"t": "events", "_bin": True, "items": items}


# ---------------------------------------------------------------- РАЗБОР
_DECODERS = {
    T_SPAWN: decode_spawn,
    T_SNAPSHOT: decode_snapshot,
    T_DESPAWN: decode_despawn,
    T_PROGRESS: decode_progress,
    T_INPUT: decode_input,
    T_SOUND: decode_sounds,
    T_EVENT: decode_events,
}


def decode(kind, body):
    decoder = _DECODERS.get(kind)
    if decoder is None:
        raise protocol.ProtocolError(f"неизвестный тип кадра: {kind}")
    try:
        return decoder(body)
    except (struct.error, ValueError, IndexError) as exc:
        raise protocol.ProtocolError("повреждённый бинарный кадр") from exc
