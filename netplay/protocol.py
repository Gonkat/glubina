"""Протокол кооператива: кадры, сообщения и валидация.

Транспорт — TCP. Кадр: 4 байта длины (big-endian) + UTF-8 JSON.
JSON выбран осознанно: он отлаживается глазами, не тянет зависимостей
и при 20 снимках в секунду с запасом укладывается в LAN и домашний
интернет. Если профилирование покажет нехватку — формат кадра можно
заменить на бинарный, не меняя остальную игру.

Здесь же — единственное место, где проверяются ВХОДЯЩИЕ данные:
клиент не должен уметь прислать NaN, бесконечность, строку на месте
числа или действие чаще, чем разрешено.
"""

import json
import math
import struct

PROTOCOL_VERSION = 1
DEFAULT_PORT = 32123

# MVP: 4 участника. Это не «магическое число» в коде игры — лимит
# объявлен здесь, показывается в интерфейсе и проверяется при входе.
MAX_PLAYERS = 4

SNAPSHOT_HZ = 20.0          # частота авторитетных снимков мира
INPUT_HZ = 30.0             # частота ввода клиента
MAX_FRAME_BYTES = 1 << 20   # 1 МиБ — защита от «кадра-бомбы»
MAX_NAME_LEN = 16

# Допустимые типы сообщений. Всё остальное отклоняется до обработки.
MESSAGE_TYPES = frozenset({
    "hello", "welcome", "reject", "start", "snapshot", "input",
    "bye", "ping", "pong", "notice", "buy", "buy_result", "skill",
})

ACTION_KEYS = frozenset({
    "dash", "reload", "grenade", "medkit", "artifact", "melee_ability",
    "interact", "cycle_mode",
})


class ProtocolError(ValueError):
    """Некорректное или несовместимое сообщение."""


# ------------------------------------------------------------------ КАДРЫ
def encode(message):
    """Сериализует сообщение в кадр с префиксом длины."""
    if not isinstance(message, dict):
        raise ProtocolError("сообщение должно быть объектом")
    payload = json.dumps(message, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("слишком большое сообщение")
    return struct.pack("!I", len(payload)) + payload


def read_frame(buffer):
    """Достаёт один кадр из буфера.

    Возвращает (message, rest) или (None, buffer), если данных мало.
    """
    if len(buffer) < 4:
        return None, buffer
    (size,) = struct.unpack("!I", buffer[:4])
    if size <= 0 or size > MAX_FRAME_BYTES:
        raise ProtocolError(f"недопустимая длина кадра: {size}")
    if len(buffer) < 4 + size:
        return None, buffer
    raw = buffer[4:4 + size]
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("кадр не является корректным JSON") from exc
    if not isinstance(message, dict):
        raise ProtocolError("сообщение должно быть объектом")
    return message, buffer[4 + size:]


# ------------------------------------------------------------------ ВАЛИДАЦИЯ
def sanitize_name(raw, fallback="Игрок"):
    """Имя игрока: без управляющих символов, ограниченной длины."""
    if not isinstance(raw, str):
        return fallback
    cleaned = "".join(ch for ch in raw if ch.isprintable()).strip()
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return fallback
    return cleaned[:MAX_NAME_LEN]


def number(value, default=0.0):
    """Конечное число из входящего значения (иначе default)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) else default


def clamp(value, low, high, default=0.0):
    return max(low, min(high, number(value, default)))


def boolean(value):
    return bool(value) if isinstance(value, bool) else False


def parse_message(message):
    """Проверяет общий конверт сообщения. Остальное — по типу."""
    if not isinstance(message, dict):
        raise ProtocolError("сообщение должно быть объектом")
    kind = message.get("t")
    if not isinstance(kind, str) or kind not in MESSAGE_TYPES:
        raise ProtocolError("неизвестный тип сообщения")
    return kind


def parse_hello(message):
    """hello: version, name. Версия обязательна и сверяется."""
    version = message.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProtocolError("нет версии протокола")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            f"несовместимая версия протокола: {version} "
            f"(нужна {PROTOCOL_VERSION})")
    return sanitize_name(message.get("name")), version


def parse_input(message):
    """input: нормализованный ввод клиента.

    Всё приводится к безопасным диапазонам ЗДЕСЬ, до попадания в
    симуляцию: координаты и углы не могут быть NaN, кнопки — строками.
    """
    move = message.get("move")
    if not isinstance(move, (list, tuple)) or len(move) != 2:
        move = (0.0, 0.0)
    mx = clamp(move[0], -1.0, 1.0)
    my = clamp(move[1], -1.0, 1.0)
    length = math.hypot(mx, my)
    if length > 1.0:
        mx, my = mx / length, my / length
    aim = clamp(message.get("aim"), -math.tau, math.tau)
    aim_x = clamp(message.get("aim_x"), -1e7, 1e7)
    aim_y = clamp(message.get("aim_y"), -1e7, 1e7)
    actions = message.get("actions")
    if not isinstance(actions, (list, tuple)):
        actions = ()
    # Одно нажатие = одно действие. Дубликаты в одном кадре отбрасываем.
    actions = [a for a in actions if isinstance(a, str) and a in ACTION_KEYS]
    seen = set()
    actions = [a for a in actions if not (a in seen or seen.add(a))]
    return {
        "move": (mx, my),
        "aim": aim,
        "aim_x": aim_x,
        "aim_y": aim_y,
        "fire": boolean(message.get("fire")),
        "melee": boolean(message.get("melee")),
        "actions": actions[:4],
        "seq": int(number(message.get("seq"), 0.0)),
    }


def parse_buy(message):
    """buy: покупка в магазине. Проверяем позицию и индекс товара."""
    pos = message.get("shop")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        raise ProtocolError("покупка без магазина")
    x = clamp(pos[0], -1e7, 1e7)
    y = clamp(pos[1], -1e7, 1e7)
    cursor = message.get("cursor")
    if not isinstance(cursor, int) or isinstance(cursor, bool):
        cursor = -1
    kind = message.get("kind")
    kind = kind[:24] if isinstance(kind, str) else ""
    key = message.get("key")
    key = key[:32] if isinstance(key, str) else ""
    return {"shop": (x, y), "cursor": max(-1, min(200, cursor)),
            "kind": kind, "key": key}


# ------------------------------------------------------------------ СООБЩЕНИЯ
def hello(name):
    return {"t": "hello", "version": PROTOCOL_VERSION, "name": name}


def welcome(pid, seed, depth, zone, host_name):
    return {"t": "welcome", "version": PROTOCOL_VERSION, "pid": pid,
            "seed": seed, "depth": depth, "zone": zone,
            "host": host_name, "max_players": MAX_PLAYERS}


def reject(reason, code="rejected"):
    return {"t": "reject", "reason": reason, "code": code}


def start(seed, depth, zone):
    return {"t": "start", "seed": seed, "depth": depth, "zone": zone}


def bye(reason=""):
    return {"t": "bye", "reason": reason}


def notice(text, color=None, timer=2.4):
    message = {"t": "notice", "text": str(text)[:160], "timer": timer}
    if color is not None:
        message["color"] = [int(c) for c in color]
    return message


def parse_skill(message):
    """skill: покупка узла доски навыков. Идентификаторы — только строки."""
    zone = message.get("zone")
    node = message.get("node")
    if not isinstance(zone, str) or not zone or len(zone) > 32:
        raise ProtocolError("некорректная зона навыка")
    if not isinstance(node, str) or not node or len(node) > 64:
        raise ProtocolError("некорректный узел навыка")
    return zone, node


def buy_result(ok, text):
    return {"t": "buy_result", "ok": bool(ok), "text": str(text)[:160]}


def ping(stamp):
    return {"t": "ping", "stamp": stamp}


def pong(stamp):
    return {"t": "pong", "stamp": stamp}
