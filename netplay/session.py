"""Сессия кооператива: жизненный цикл хоста и клиента.

Хост — единственный источник истины. Он принимает ввод клиентов,
применяет его к своим экземплярам Player и рассылает снимки мира.
Клиент отправляет ввод и намерения (покупка), а получает снимки.

Модуль не рисует и не знает про меню: интерфейс спрашивает у сессии
status/error/clients и вызывает pump() из кадра игры.
"""

import threading
import time

from settings import SHOP_OPEN_DIST

from . import protocol, transport


class HostClient:
    """Подключённый участник на стороне хоста."""

    def __init__(self, conn, pid, name):
        self.conn = conn
        self.pid = pid
        self.name = name
        self.player = None          # назначается при старте вылазки
        self.input_state = {
            "move": (0.0, 0.0), "aim": 0.0, "aim_x": 0.0, "aim_y": 0.0,
            "fire": False, "melee": False, "actions": [], "seq": 0,
        }
        self._window_start = time.monotonic()
        self._window_count = 0
        self.joined_at = time.monotonic()

    def throttle(self):
        """Ограничение частоты входящих сообщений (антифлуд)."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._window_count = 0
        self._window_count += 1
        return self._window_count <= 90


class HostSession:
    """Хост-авторитетная сессия."""

    def __init__(self, host_name, port=protocol.DEFAULT_PORT):
        self.listener = transport.HostListener(port)
        self.port = self.listener.port
        self.host_name = protocol.sanitize_name(host_name, "Хост")
        self.clients = []
        self.status = "waiting"      # waiting | playing | closed
        self.error = ""
        self.notices = []            # [(текст, цвет, таймер)] для интерфейса
        self.seed = None
        self.depth = 1
        self.zone = "medium"
        self._snapshot_timer = 0.0
        self._next_pid = 2
        self._handshake_deadline = {}
        self._pending = []           # принятые, но ещё не прошедшие handshake
        self.game = None

    # ------------------------------------------------------------ СОСТОЯНИЕ
    @property
    def player_count(self):
        return 1 + len(self.clients)

    @property
    def addresses(self):
        return transport.local_addresses()

    def notify(self, text, color=None):
        self.notices.append((text, color, 3.0))

    def drain_notices(self):
        notices = list(self.notices)
        self.notices.clear()
        return notices

    # ------------------------------------------------------------ ПРИЁМ
    def _accept(self):
        for conn in self.listener.accept():
            self._handshake_deadline[conn] = time.monotonic() + 6.0
            conn._host_pending = True
            self._pending.append(conn)

    def _close_pending(self):
        now = time.monotonic()
        for conn in list(self._pending):
            if now >= self._handshake_deadline.get(conn, 0.0):
                conn.close()
                self._pending.remove(conn)
                self._handshake_deadline.pop(conn, None)

    def pump(self, game, dt):
        """Обрабатывает сеть. Вызывать один раз за кадр игры."""
        if self.status == "closed":
            return
        self.game = game
        self._accept()
        self._close_pending()
        for client in list(self.clients):
            for kind, payload in client.conn.poll():
                if kind == "closed":
                    self._drop_client(client, "отключился")
                elif kind == "error":
                    self._drop_client(client, f"ошибка протокола: {payload}")
                elif kind == "message":
                    self._handle(client, payload, game)
        if self.status == "playing":
            self._snapshot_timer += dt
            if self._snapshot_timer >= 1.0 / protocol.SNAPSHOT_HZ:
                self._snapshot_timer = 0.0
                self.broadcast_snapshot(game)

    def _handle(self, client, message, game):
        try:
            kind = protocol.parse_message(message)
        except protocol.ProtocolError:
            self._drop_client(client, "некорректное сообщение")
            return
        if kind == "input":
            if not client.throttle():
                return
            state = protocol.parse_input(message)
            # Порядок сообщений TCP гарантирует; старые seq просто игнорируем.
            if state["seq"] < client.input_state["seq"]:
                return
            client.input_state = state
        elif kind == "buy":
            if not client.throttle():
                return
            try:
                intent = protocol.parse_buy(message)
            except protocol.ProtocolError:
                return
            ok, text = game.purchase_for(client.player, intent["shop"],
                                         intent["cursor"], intent["kind"],
                                         intent["key"])
            client.conn.send(protocol.buy_result(ok, text))
            if ok:
                client.conn.send(protocol.notice(text, (140, 236, 170)))
        elif kind == "skill":
            if not client.throttle():
                return
            try:
                zone, node = protocol.parse_skill(message)
            except protocol.ProtocolError:
                return
            ok, text = game.purchase_skill(client.player, zone, node)
            client.conn.send(protocol.buy_result(ok, text))
            if ok:
                client.conn.send(protocol.notice(text, (140, 236, 170)))
        elif kind == "ping":
            client.conn.send(protocol.pong(message.get("stamp", 0)))
        elif kind == "bye":
            self._drop_client(client, "вышел")
        elif kind == "hello":
            # Повторный hello при живом соединении — не повод плодить игроков.
            return

    def _drop_client(self, client, reason):
        if client not in self.clients:
            return
        self.clients.remove(client)
        client.conn.close()
        if client.player is not None:
            game = self.game
            if game is not None and client.player in game.players:
                game.players.remove(client.player)
                if client.player in game.render_players:
                    game.render_players.remove(client.player)
        self.notify(f"{client.name} {reason}", (240, 180, 140))

    # ------------------------------------------------------------ ПОДКЛЮЧЕНИЕ
    def accept_handshakes(self):
        """Завершает hello → welcome для новых соединений."""
        if self.status == "closed":
            return
        self._accept()
        self._close_pending()
        for conn in list(self._pending):
            pending_messages = conn.poll()
            for kind, payload in pending_messages:
                if kind == "closed":
                    conn.close()
                    self._pending.remove(conn)
                    self._handshake_deadline.pop(conn, None)
                    break
                if kind != "message":
                    continue
                try:
                    name, version = protocol.parse_hello(payload)
                except protocol.ProtocolError as exc:
                    conn.send_and_close(protocol.reject(str(exc), "version"))
                    self._pending.remove(conn)
                    self._handshake_deadline.pop(conn, None)
                    break
                if self.status != "waiting":
                    conn.send_and_close(protocol.reject(
                        "Вылазка уже началась — присоединиться нельзя",
                        "started"))
                    self._pending.remove(conn)
                    self._handshake_deadline.pop(conn, None)
                    break
                if len(self.clients) >= protocol.MAX_PLAYERS - 1:
                    conn.send_and_close(
                        protocol.reject("Сессия заполнена", "full"))
                    self._pending.remove(conn)
                    self._handshake_deadline.pop(conn, None)
                    break
                client = HostClient(conn, self._next_pid, name)
                self._next_pid += 1
                self.clients.append(client)
                self._pending.remove(conn)
                self._handshake_deadline.pop(conn, None)
                conn._host_pending = False
                conn.send(protocol.welcome(
                    client.pid, self.seed or 0, self.depth, self.zone,
                    self.host_name))
                self.notify(f"{name} подключился", (140, 226, 200))
                break

    # ------------------------------------------------------------ ВЫЛАЗКА
    def start_run(self, game):
        """Хост начинает вылазку: общий seed, все игроки в одном мире."""
        self.accept_handshakes()
        self.seed, self.depth, self.zone = game.start_coop_run(self.clients)
        self.status = "playing"
        self.game = game
        for client in self.clients:
            client.conn.send(protocol.start(self.seed, self.depth, self.zone))
        self.broadcast_snapshot(game)

    def broadcast(self, message):
        for client in list(self.clients):
            client.conn.send(message)

    def broadcast_snapshot(self, game):
        game.net_seq += 1
        payload = game.snapshot_payload()
        for client in list(self.clients):
            client.conn.send(payload)

    def close(self, reason="Хост закрыл сессию"):
        if self.status == "closed":
            return
        self.status = "closed"
        for client in list(self.clients):
            client.conn.send_and_close(protocol.bye(reason))
        self.clients.clear()
        for conn in list(self._pending):
            conn.close()
        self._pending.clear()
        self.listener.close()


class ClientSession:
    """Клиент: подключение, ввод и последний снимок."""

    def __init__(self, address, player_name):
        self.address = address
        self.player_name = protocol.sanitize_name(player_name, "Гость")
        self.status = "connecting"   # connecting | connected | playing | error | closed
        self.error = ""
        self.snapshot = None
        self.pid = None
        self.host_name = ""
        self.seed = 0
        self.depth = 1
        self.zone = "medium"
        self.notices = []
        self._conn = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()
        self._seq = 0
        self._snapshot_seq = -1

    def _connect_loop(self):
        try:
            conn = transport.connect(self.address)
        except (OSError, ValueError) as exc:
            with self._lock:
                self.status = "error"
                self.error = f"Не удалось подключиться: {exc}"
            return
        with self._lock:
            self._conn = conn
        conn.send(protocol.hello(self.player_name))

    def pump(self):
        """Забирает сообщения сервера. Возвращает события для Game."""
        events = []
        with self._lock:
            conn = self._conn
        if conn is None:
            return events
        for kind, payload in conn.poll():
            if kind == "closed":
                if self.status not in ("error", "closed"):
                    self.status = "closed"
                    self.error = "Соединение с хостом потеряно"
                events.append(("closed", None))
                continue
            if kind == "error":
                self.status = "error"
                self.error = f"Ошибка сети: {payload}"
                events.append(("error", self.error))
                continue
            try:
                message_type = protocol.parse_message(payload)
            except protocol.ProtocolError:
                self.status = "error"
                self.error = "Хост прислал некорректные данные"
                events.append(("error", self.error))
                continue
            if message_type == "welcome":
                version = payload.get("version")
                if version != protocol.PROTOCOL_VERSION:
                    self.status = "error"
                    self.error = "Несовместимая версия протокола"
                    continue
                self.pid = payload.get("pid")
                self.host_name = payload.get("host", "Хост")
                self.seed = int(payload.get("seed", 0))
                self.depth = int(payload.get("depth", 1))
                self.zone = payload.get("zone", "medium")
                self.status = "connected"
                self.player_name = self.player_name
                events.append(("welcome", payload))
            elif message_type == "reject":
                self.status = "error"
                self.error = payload.get("reason", "Хост отклонил подключение")
                events.append(("reject", self.error))
            elif message_type == "start":
                self.status = "playing"
                self.seed = int(payload.get("seed", 0))
                self.depth = int(payload.get("depth", 1))
                self.zone = payload.get("zone", "medium")
                events.append(("start", payload))
            elif message_type == "snapshot":
                if self.status == "playing":
                    seq = int(payload.get("seq", 0))
                    if seq > self._snapshot_seq:
                        self._snapshot_seq = seq
                        self.snapshot = payload
            elif message_type == "notice":
                events.append(("notice", payload))
            elif message_type == "buy_result":
                events.append(("buy_result", payload))
            elif message_type == "bye":
                self.status = "closed"
                self.error = payload.get("reason") or "Хост завершил сессию"
                events.append(("closed", self.error))
        return events

    def send_input(self, move, aim, aim_pos, fire, melee, actions):
        with self._lock:
            conn = self._conn
        if conn is None or self.status not in ("connected", "playing"):
            return
        if self.status != "playing":
            return
        self._seq += 1
        conn.send({
            "t": "input",
            "seq": self._seq,
            "move": [round(move[0], 3), round(move[1], 3)],
            "aim": round(aim, 4),
            "aim_x": round(aim_pos[0], 1),
            "aim_y": round(aim_pos[1], 1),
            "fire": bool(fire),
            "melee": bool(melee),
            "actions": list(actions)[:4],
        })

    def request_buy(self, shop, cursor, kind="", key=""):
        with self._lock:
            conn = self._conn
        if conn is None or self.status != "playing":
            return False
        conn.send({"t": "buy", "shop": [round(shop.x, 1), round(shop.y, 1)],
                   "cursor": int(cursor), "kind": str(kind)[:24],
                   "key": str(key)[:32]})
        return True

    def request_skill(self, zone, node):
        """Намерение купить узел: решение и списание делает хост."""
        with self._lock:
            conn = self._conn
        if conn is None or self.status != "playing":
            return False
        conn.send({"t": "skill", "zone": str(zone)[:32],
                   "node": str(node)[:64]})
        return True

    def close(self):
        with self._lock:
            conn = self._conn
        if conn is not None:
            conn.send(protocol.bye("выход"))
            conn.close()
        if self.status != "error":
            self.status = "closed"


def shop_near(shops, position, limit=SHOP_OPEN_DIST + 40.0):
    """Ближайший магазин к позиции (в пределах допуска)."""
    best, best_d = None, limit
    for shop in shops:
        dx = shop.x - position[0]
        dy = shop.y - position[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= best_d:
            best, best_d = shop, dist
    return best
