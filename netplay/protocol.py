"""Протокол кооператива: кадры, сообщения и валидация.

Транспорт — TCP. Кадр: 4 байта длины (big-endian) + UTF-8 JSON.
JSON выбран осознанно: он отлаживается глазами, не тянет зависимостей
и даже при 60 снимках в секунду с запасом укладывается в LAN и домашний
интернет (снимок — сотни байт, а не килобайты). Если профилирование покажет нехватку — формат кадра можно
заменить на бинарный, не меняя остальную игру.

Здесь же — единственное место, где проверяются ВХОДЯЩИЕ данные:
клиент не должен уметь прислать NaN, бесконечность, строку на месте
числа или действие чаще, чем разрешено.
"""

import json
import math
import os
import struct
import sys

PROTOCOL_VERSION = 6   # 6: снаряды врагов и телеграфы; 5: 60 Гц; 4: скорость; 3: звуки; 2: бинарь
DEFAULT_PORT = 32123

# MVP: 4 участника. Это не «магическое число» в коде игры — лимит
# объявлен здесь, показывается в интерфейсе и проверяется при входе.
MAX_PLAYERS = 4

# 60 Гц — это половина задержки «выстрел → я его вижу» по сравнению
# с 30 Гц. Бинарный снимок на несколько десятков сущностей — ~0.5 КБ,
# то есть 30 КБ/с на гостя: на LAN и на домашнем интернете это ничто,
# а запас по задержке интерполяции сокращается вдвое.
SNAPSHOT_HZ = 60.0          # частота авторитетных снимков мира
INPUT_HZ = 60.0             # частота ввода клиента
MAX_FRAME_BYTES = 1 << 20   # 1 МиБ — защита от «кадра-бомбы»
MAX_NAME_LEN = 16

# Бинарный протокол (см. netplay/binary.py) — боевой режим.
# --net-debug (или GLUBINA_NET_DEBUG=1) возвращает JSON-снимки: их видно
# глазами в логе, это нужно для отладки, а не для игры.
USE_BINARY = not ("--net-debug" in sys.argv
                  or os.environ.get("GLUBINA_NET_DEBUG") == "1")

# Допустимые типы сообщений. Всё остальное отклоняется до обработки.
MESSAGE_TYPES = frozenset({
    "hello", "welcome", "reject", "start", "snapshot", "input",
    "bye", "ping", "pong", "notice", "buy", "buy_result", "skill",
    # бинарные кадры горячего пути (netplay/binary.py)
    "spawn", "despawn", "progress", "sounds", "events",
})

ACTION_KEYS = frozenset({
    "dash", "reload", "grenade", "medkit", "artifact", "melee_ability",
    "interact", "cycle_mode",
})
# Порядок битов в бинарном вводе: он же порядок разбора, менять нельзя
# без смены версии протокола.
ACTION_KEYS_ORDER = ("dash", "reload", "grenade", "medkit", "artifact",
                     "melee_ability", "interact", "cycle_mode")


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
    return struct.pack("!I", len(payload) + 1) + b"\x00" + payload


def read_frame(buffer):
    """Достаёт один кадр из буфера: u32-длина + u8-тип + payload.

    Тип 0 — JSON (служебные сообщения и отладочный режим), остальные —
    бинарные кадры горячего пути. Возвращает (message, rest) или
    (None, buffer), если данных мало.
    """
    if len(buffer) < 4:
        return None, buffer
    (size,) = struct.unpack("!I", buffer[:4])
    if size <= 1 or size > MAX_FRAME_BYTES:
        raise ProtocolError(f"недопустимая длина кадра: {size}")
    if len(buffer) < 4 + size:
        return None, buffer
    kind = buffer[4]
    body = buffer[5:4 + size]
    if kind == 0:
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("кадр не является корректным JSON") from exc
        if not isinstance(message, dict):
            raise ProtocolError("сообщение должно быть объектом")
        return message, buffer[4 + size:]
    from . import binary
    return binary.decode(kind, body), buffer[4 + size:]


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


def parse_resume(message):
    """pid, который гость просит вернуть после обрыва (0 — новый игрок)."""
    value = message.get("resume")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 < value <= 255 else 0


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
    # Позиция героя от самого клиента (JSON-отладка). В бою она едет
    # бинарным полем; здесь — та же семантика для совместимости.
    pos = message.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        pos = (clamp(pos[0], -1e7, 1e7), clamp(pos[1], -1e7, 1e7))
    else:
        pos = None
    return {
        "move": (mx, my),
        "aim": aim,
        "aim_x": aim_x,
        "aim_y": aim_y,
        "pos": pos,
        "fire": boolean(message.get("fire")),
        "melee": boolean(message.get("melee")),
        "actions": actions[:4],
        "seq": int(number(message.get("seq"), 0.0)),
    }


def parse_rid(message):
    """Номер намерения (rid): хост возвращает его в ответе.

    Старый клиент его не присылает — тогда 0, и ответ уходит без
    привязки, как раньше. Отрицательные и мусорные значения — тоже 0.
    """
    value = message.get("rid")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 <= value <= 0x7FFFFFFF else 0


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
            "kind": kind, "key": key, "rid": parse_rid(message)}


# ------------------------------------------------------------------ СООБЩЕНИЯ
def hello(name, resume=0):
    """hello: имя и, если это возврат после обрыва, свой старый pid.

    Поле необязательное: старый хост его проигнорирует и откажет,
    новый хост вернёт гостя в ту же вылазку.
    """
    message = {"t": "hello", "version": PROTOCOL_VERSION, "name": name}
    if resume:
        message["resume"] = int(resume)
    return message


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
    return zone, node, parse_rid(message)


def buy_result(ok, text, rid=0):
    """Ответ на покупку. ``rid`` связывает его с конкретным намерением."""
    message = {"t": "buy_result", "ok": bool(ok), "text": str(text)[:160]}
    if rid:
        message["rid"] = int(rid)
    return message


def ping(stamp):
    return {"t": "ping", "stamp": stamp}


def pong(stamp):
    return {"t": "pong", "stamp": stamp}
