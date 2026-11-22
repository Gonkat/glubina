"""Сессия кооператива: жизненный цикл хоста и клиента.

Хост — единственный источник истины. Он принимает ввод клиентов,
применяет его к своим экземплярам Player и рассылает снимки мира.
Клиент отправляет ввод и намерения (покупка), а получает снимки.

Модуль не рисует и не знает про меню: интерфейс спрашивает у сессии
status/error/clients и вызывает pump() из кадра игры.
"""

import threading
import time
from collections import deque

from settings import SHOP_OPEN_DIST

from . import binary, protocol, transport
from .replication import ClientReplication, ProgressTracker
from .snapshot import collect, progress_state


def _json_sounds(events, focus=None):
    """Отладочный режим: звуки обычным JSON-сообщением."""
    items = []
    radius2 = binary.SOUND_RADIUS * binary.SOUND_RADIUS
    for pid, name, x, y, volume in events:
        if focus is not None:
            dx = float(x) - focus[0]
            dy = float(y) - focus[1]
            if dx * dx + dy * dy > radius2:
                continue
        items.append([int(pid), str(name), round(float(x), 1),
                      round(float(y), 1), round(float(volume), 3)])
    if not items:
        return None
    return protocol.encode({"t": "sounds", "items": items})


def accept_input_seq(previous, seq):
    """Не устарел ли кадр ввода (счётчик 16-битный и переполняется).

    Порядок TCP уже гарантирует доставку; проверка нужна только от
    повторов. Сравнение по модулю: после ~18 минут игры ``seq`` гостя
    переходит через ноль, и наивное ``seq < previous`` навсегда съедало
    бы его ввод — герой замирал посреди вылазки.
    """
    delta = (int(seq) - int(previous)) & 0xFFFF
    return delta < 0x8000


class HostClient:
    """Подключённый участник на стороне хоста."""

    def __init__(self, conn, pid, name):
        self.conn = conn
        self.pid = pid
        self.name = name
        self.player = None          # назначается при старте вылазки
        self.input_state = {
            "move": (0.0, 0.0), "aim": 0.0, "aim_x": 0.0, "aim_y": 0.0,
            "pos": None, "fire": False, "melee": False, "actions": [],
            "seq": 0,
        }
        self._window_start = time.monotonic()
        self._window_count = 0
        self.joined_at = time.monotonic()
        # Что именно этот гость уже знает (интерес, spawn/despawn).
        self.replication = ClientReplication(pid)
        self.last_snapshot_at = 0.0
        self.snapshot_bytes = 0

    # Антифлуд: ввод идёт на частоте INPUT_HZ, плюс пинги и покупки.
    # Лимит с двукратным запасом — он должен ловить мусор, а не честный
    # ввод: зажатый лимит молча съедал часть кадров ввода, и герой гостя
    # у хоста двигался рывками.
    INBOX_LIMIT = int(protocol.INPUT_HZ * 2) + 20

    def throttle(self):
        """Ограничение частоты входящих сообщений (антифлуд)."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._window_count = 0
        self._window_count += 1
        return self._window_count <= self.INBOX_LIMIT


class HostSession:
    """Хост-авторитетная сессия."""

    def __init__(self, host_name, port=protocol.DEFAULT_PORT, host="0.0.0.0"):
        self.listener = transport.HostListener(port, host)
        self.port = self.listener.port
        self.host_name = protocol.sanitize_name(host_name, "Хост")
        self.clients = []
        self.status = "waiting"      # waiting | playing | closed
        self.error = ""
        self.notices = []            # [(текст, цвет, таймер)] для интерфейса
        self.seed = None
        self.depth = 1
        self.zone = "medium"
        # Снимок идёт по ЧАСАМ, а не по кадру: просадка кадра у хоста не
        # должна превращаться в залп из пяти снимков у всех гостей.
        self._next_tick = None
        self._writer = binary.Writer(8192)
        self._progress = ProgressTracker()
        # Какой мир гости уже знают. Смена сектора/глубины пересобирает
        # зеркало у клиента и стирает прогрессию, поэтому её надо прислать
        # заново — иначе после спуска гость остаётся с дефолтным оружием.
        self._world_key = None
        self._tick_ms = 0.0
        self.stats = {"ticks": 0, "build_ms": 0.0, "bytes": 0,
                      "entities": 0, "clients": 0}
        self._next_pid = 2
        self._handshake_deadline = {}
        self._pending = []           # принятые, но ещё не прошедшие handshake
        # Отключившиеся гости: pid -> герой и срок, до которого его можно
        # вернуть в ту же вылазку (см. accept_handshakes).
        self._resume = {}
        self.game = None
        # Выделенный сервер разрешает вход в идущую вылазку: игроку не
        # нужно ждать, пока все соберутся до старта.
        self.allow_late_join = False
        # Сколько гостей принимаем. У игрока-хоста одно место занято им
        # самим, у выделенного сервера — свободны все.
        self.max_clients = protocol.MAX_PLAYERS - 1

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

    def pump(self, game, dt=None):
        """Обрабатывает сеть. Вызывать один раз за кадр игры.

        ``dt`` больше не задаёт частоту снимков: тик идёт по
        ``time.monotonic()``, ровно ``SNAPSHOT_HZ`` при любом FPS хоста. Аргумент
        оставлен, чтобы не менять вызовы в игре и тестах.
        """
        if self.status == "closed":
            return
        self.game = game
        self._expire_resume()
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
            self._pump_ticks(game)

    # ------------------------------------------------------------ ТИК
    def _pump_ticks(self, game):
        """Накопитель по монотонным часам: SNAPSHOT_HZ независимо от кадра."""
        if self._next_tick is None:
            self._next_tick = time.monotonic() + self.interval
        now = time.monotonic()
        steps = 0
        while now >= self._next_tick and steps < 3:
            self._tick(game)
            self._next_tick += self.interval
            steps += 1
        if now > self._next_tick + self.interval:
            # Хост долго не заходил в pump: не копим долг снимков.
            self._next_tick = now + self.interval

    @property
    def interval(self):
        return 1.0 / protocol.SNAPSHOT_HZ

    def _tick(self, game):
        """Один авторитетный тик: собрать мир один раз, разослать гостям."""
        started = time.perf_counter()
        game.net_seq += 1
        world = collect(game)
        seq = game.net_seq
        # Звуки игроков — очередь кадра. Забираем ОДИН раз: у каждого гостя
        # своя слышимость, но события общие.
        sound_events = ()
        take_sounds = getattr(game, "take_sound_events", None)
        if take_sounds is not None:
            sound_events = take_sounds()
        # Разовые визуальные события (взрывы, удары врагов) — тоже очередь
        # кадра: их нельзя восстановить из двух снимков, они уже погасли.
        net_events = ()
        take_events = getattr(game, "take_net_events", None)
        if take_events is not None:
            net_events = take_events()
        # Смена мира (спуск/новая вылазка): у клиента зеркало строится
        # заново и прогрессия теряется, а сигнатура у хоста не меняется.
        # Инвалидируем её — следующий poll пришлёт всё заново.
        world_key = (world.seed, world.depth, world.zone)
        if self._world_key is not None and world_key != self._world_key:
            self._progress.invalidate()
        self._world_key = world_key
        # Прогрессия — только по изменению, маленькими кадрами на всех.
        players = [row[0] for row in world.players]
        progress_frames = self._progress.poll(players, progress_state)
        if progress_frames and self.clients:
            for frame in progress_frames:
                for client in list(self.clients):
                    client.conn.send_bytes(frame)
        total_bytes = 0
        total_entities = (len(world.players) + len(world.enemies)
                          + len(world.bullets) + len(world.drops))
        if not protocol.USE_BINARY:
            # Отладочный режим: полный JSON-снимок, читается глазами.
            payload = protocol.encode(game.snapshot_payload())
            for client in list(self.clients):
                client.conn.send_bytes(payload)
            total_bytes = len(payload) * len(self.clients)
            total_bytes += self._send_sounds(sound_events)
            if net_events:
                items = [[kind, round(x, 1), round(y, 1), round(size, 1),
                          list(color) if color else None]
                         for kind, x, y, size, color in net_events]
                frame = protocol.encode({"t": "events", "items": items})
                for client in list(self.clients):
                    client.conn.send_bytes(frame)
                total_bytes += len(frame) * len(self.clients)
            self._record_stats(total_bytes, total_entities, started)
            return
        for client in list(self.clients):
            replication = client.replication
            replication.local_pid = client.pid
            despawn, spawn, snapshot = replication.frames(
                world, seq, self._writer, self._progress.rev)
            if despawn is not None:
                client.conn.send_bytes(despawn)
                total_bytes += len(despawn)
            if spawn is not None:
                client.conn.send_bytes(spawn)
                total_bytes += len(spawn)
            client.conn.send_bytes(snapshot)
            total_bytes += len(snapshot)
            total_bytes += self._send_sounds(sound_events, client)
            total_bytes += self._send_events(net_events, client)
            client.last_snapshot_at = time.monotonic()
            client.snapshot_bytes = len(snapshot)
        self._record_stats(total_bytes, total_entities, started)

    def _send_sounds(self, events, only=None):
        """Рассылка звуков: каждому гостю — только слышимые ему.

        По сети едет позиция и базовая громкость; затухание и панораму
        гость считает сам по расстоянию до своего героя.
        """
        if not events:
            return 0
        targets = [only] if only is not None else list(self.clients)
        total = 0
        for client in targets:
            if client not in self.clients:
                continue
            player = client.player
            focus = None
            if player is not None:
                focus = (float(player.x), float(player.y))
            if protocol.USE_BINARY:
                frame = binary.encode_sounds(events, focus)
            else:
                frame = _json_sounds(events, focus)
            if frame is None:
                continue
            client.conn.send_bytes(frame)
            total += len(frame)
        return total

    def _send_events(self, events, client):
        """Взрывы и удары врагов — только тому, кто их увидит."""
        if not events:
            return 0
        player = client.player
        focus = None
        if player is not None:
            focus = (float(player.x), float(player.y))
        frame = binary.encode_events(events, focus)
        if frame is None:
            return 0
        client.conn.send_bytes(frame)
        return len(frame)

    def _record_stats(self, total_bytes, total_entities, started):
        self._tick_ms = (time.perf_counter() - started) * 1000.0
        self.stats["ticks"] += 1
        self.stats["build_ms"] = self._tick_ms
        self.stats["bytes"] = total_bytes
        self.stats["entities"] = total_entities
        self.stats["clients"] = len(self.clients)
        if self._tick_ms > 1.0:
            # Не стоим кадром: пропускаем ближайший тик, следующий — через 50 мс.
            self._next_tick = max(self._next_tick, time.monotonic()
                                  + self.interval)

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
            # Порядок сообщений TCP гарантирует; старые seq игнорируем.
            # Сравнение по модулю 16 бит: после ~18 минут игры счётчик
            # гостя переполняется, и наивное `<` навсегда съедало его
            # ввод — герой замирал посреди вылазки.
            previous = int(client.input_state.get("seq", 0))
            if not accept_input_seq(previous, state["seq"]):
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
            # rid возвращается как есть: гость сам решит, к какому
            # намерению относится ответ (и не покажет его дважды).
            client.conn.send(protocol.buy_result(ok, text, intent["rid"]))
            if ok:
                client.conn.send(protocol.notice(text, (140, 236, 170)))
                # Прогрессию — сразу, а не следующим тиком: иначе доска
                # навыков у гостя обновлялась бы на кадр позже подтверждения
                # покупки, и всё дерево ощущалось бы «тормозным».
                self._push_progress(client.player)
        elif kind == "skill":
            if not client.throttle():
                return
            try:
                zone, node, rid = protocol.parse_skill(message)
            except protocol.ProtocolError:
                return
            ok, text = game.purchase_skill(client.player, zone, node)
            client.conn.send(protocol.buy_result(ok, text, rid))
            if ok:
                client.conn.send(protocol.notice(text, (140, 236, 170)))
                self._push_progress(client.player)
        elif kind == "ping":
            client.conn.send(protocol.pong(message.get("stamp", 0)))
        elif kind == "bye":
            self._drop_client(client, "вышел")
        elif kind == "hello":
            # Повторный hello при живом соединении — не повод плодить игроков.
            return

    def _push_progress(self, player):
        """Внеочередная прогрессия одного героя (после покупки).

        Тик пришлёт её и сам, но только на следующем кадре сети; покупка
        должна менять доску и оружие сразу после подтверждения.
        """
        if player is None:
            return
        pid = int(getattr(player, "pid", 0) or 0)
        if pid <= 0:
            return
        self._progress.mark_dirty(pid)
        for frame in self._progress.poll([player], progress_state):
            for other in list(self.clients):
                other.conn.send_bytes(frame)

    def _expire_resume(self):
        """Забывает героев, которых так и не вернули в вылазку."""
        if not self._resume:
            return
        now = time.monotonic()
        for pid in list(self._resume):
            if self._resume[pid]["expires"] < now:
                self._resume.pop(pid, None)

    def _drop_client(self, client, reason):
        if client not in self.clients:
            return
        self.clients.remove(client)
        client.conn.close()
        if client.player is not None:
            pid = int(getattr(client.player, "pid", 0))
            self._progress.forget(pid)
            game = self.game
            if game is not None and client.player in game.players:
                game.players.remove(client.player)
                if client.player in game.render_players:
                    game.render_players.remove(client.player)
            # Герой с деньгами, навыками и оружием ждёт возвращения:
            # вылазка продолжается, и терять прогресс из-за мигания Wi-Fi
            # незачем. Мир при этом не держит лишнего участника.
            if self.status == "playing" and pid > 0:
                self._resume[pid] = {
                    "player": client.player,
                    "name": client.name,
                    "expires": time.monotonic() + HOST_RESUME_GRACE,
                }
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
                    # Возврат в ту же вылазку: герой, прогресс и pid целы.
                    if self._resume_client(conn, payload):
                        self._pending.remove(conn)
                        self._handshake_deadline.pop(conn, None)
                        break
                    if self.allow_late_join:
                        if len(self.clients) >= self.max_clients:
                            conn.send_and_close(protocol.reject(
                                "Сессия заполнена", "full"))
                        else:
                            self._join_running(conn, name)
                        self._pending.remove(conn)
                        self._handshake_deadline.pop(conn, None)
                        break
                    conn.send_and_close(protocol.reject(
                        "Вылазка уже началась — присоединиться нельзя",
                        "started"))
                    self._pending.remove(conn)
                    self._handshake_deadline.pop(conn, None)
                    break
                if len(self.clients) >= self.max_clients:
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
                client.replication.local_pid = client.pid
                conn.send(protocol.welcome(
                    client.pid, self.seed or 0, self.depth, self.zone,
                    self.host_name))
                self.notify(f"{name} подключился", (140, 226, 200))
                break

    def _resume_client(self, conn, payload):
        """Возвращает гостя в идущую вылазку: тот же pid, герой, прогресс.

        Вызывается только из handshake. Герой всё это время отсутствовал
        в мире (его не били и не лечили), а новый клиент репликации
        заново пришлёт дескрипторы и полную прогрессию.
        """
        pid = protocol.parse_resume(payload)
        if not pid:
            return False
        entry = self._resume.pop(pid, None)
        if entry is None or entry["expires"] < time.monotonic():
            return False
        player = entry["player"]
        if any(client.pid == pid for client in self.clients):
            return False
        client = HostClient(conn, pid, entry["name"])
        client.player = player
        self.clients.append(client)
        conn._host_pending = False
        client.replication.local_pid = pid
        client.replication.reset()
        game = self.game
        if game is not None:
            player.is_local = False
            if player not in game.players:
                game.players.append(player)
            if player not in game.render_players:
                game.render_players.append(player)
        # Прогрессию этому pid отправляем заново: клиент после обрыва
        # сбрасывает зеркало и ждёт rev с нуля.
        self._progress.forget(pid)
        self._progress.mark_dirty(pid)
        conn.send(protocol.welcome(pid, self.seed or 0, self.depth, self.zone,
                                   self.host_name))
        conn.send(protocol.start(self.seed or 0, self.depth, self.zone))
        self.notify(f"{client.name} вернулся в игру", (140, 226, 200))
        return True

    def _join_running(self, conn, name):
        """Поздний вход (выделенный сервер): герой появляется сразу.

        Новому клиенту сразу уходят welcome и start, а репликация
        пришлёт дескрипторы, снимок и полную прогрессию с нуля.
        """
        game = self.game
        if game is None:
            conn.send_and_close(protocol.reject("Сервер не готов", "busy"))
            return
        pid = self._next_pid
        self._next_pid += 1
        client = HostClient(conn, pid, name)
        client.player = game.spawn_coop_player(pid, name)
        self.clients.append(client)
        conn._host_pending = False
        client.replication.local_pid = pid
        self._progress.forget(pid)
        self._progress.mark_dirty(pid)
        conn.send(protocol.welcome(pid, self.seed or 0, self.depth, self.zone,
                                   self.host_name))
        conn.send(protocol.start(self.seed or 0, self.depth, self.zone))
        self.notify(f"{name} подключился", (140, 226, 200))

    # ------------------------------------------------------------ ВЫЛАЗКА
    def start_run(self, game, dedicated=False):
        """Хост начинает вылазку: общий seed, все игроки в одном мире."""
        self.accept_handshakes()
        self.seed, self.depth, self.zone = game.start_coop_run(
            self.clients, dedicated=dedicated)
        self.status = "playing"
        self.game = game
        # Новый сектор: прогрессию отправляем заново, с новым rev.
        self._progress.reset()
        for client in self.clients:
            # Новый сектор: гость ещё ничего не знает о его сущностях.
            client.replication.reset()
            client.conn.send(protocol.start(self.seed, self.depth, self.zone))
        self.broadcast_snapshot(game)

    def broadcast(self, message):
        for client in list(self.clients):
            client.conn.send(message)

    def broadcast_snapshot(self, game):
        """Внеочередной снимок (старт вылазки) — тем же путём, что и тик."""
        self._next_tick = None
        self._tick(game)

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


# Сколько снимков держим в очереди кадра. Это ~200 мс: всё, что старше,
# уже не нужно для интерполяции. Без ограничения пауза (меню, фриз окна)
# копила бы секунды снимков, и гость после неё «пересматривал» бы
# прошедшее время ускоренной перемоткой.
SNAPSHOT_QUEUE_LIMIT = 12

# Сколько гость пытается вернуться после обрыва и сколько хост держит его
# героя с прогрессом. Окно хоста больше: гость может успеть с третьей
# попытки, а герой не должен исчезнуть из мира раньше времени.
RESUME_WINDOW = 10.0
HOST_RESUME_GRACE = 45.0

# Сколько ждать ответа хоста на покупку, прежде чем снять «проверка».
# Это НЕ таймаут повторной отправки: повторять покупку автоматически
# нельзя (хост мог применить её, а ответ потерялся бы) — гость только
# честно сообщает, что подтверждение не пришло.
INTENT_TIMEOUT = 8.0
RESOLVED_MEMORY = 64


class ClientSession:
    """Клиент: подключение, ввод и последний снимок."""

    def __init__(self, address, player_name, resume_pid=0):
        self.address = address
        self.player_name = protocol.sanitize_name(player_name, "Гость")
        # connecting | connected | playing | reconnecting | error | closed
        self.status = "connecting"
        # Свой pid из welcome: по нему же просим вернуть нас после обрыва.
        self._resume_pid = int(resume_pid or 0)
        self._resume_pending = False
        self._reconnect_thread = None
        self._reconnect_stop = False
        self._emit_closed = False
        self.error = ""
        self.snapshot = None
        # Все снимки, пришедшие с прошлого кадра, по порядку. Раньше
        # хранился только последний: пачка после рывка хоста теряла
        # промежуточные точки и интерполяция прыгала.
        self.snapshots = []
        # Диагностика для F3: пинг, джиттер и возраст последнего снимка.
        self.rtt_ms = 0.0
        self.jitter_ms = 0.0
        self.last_snapshot_at = 0.0
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
        # Ввод уходит бинарным кадром: ~30 байт вместо ~120 байт JSON.
        self.stats = {"snapshots": 0, "bytes": 0, "spawns": 0}
        self._writer = binary.Writer(256)
        # Намерения покупки «в полёте»: rid -> {kind, key, at}.
        # Пока ответа нет, интерфейс рисует локальную «проверку», но
        # НИЧЕГО не меняет в состоянии героя: истина — у хоста.
        self.pending = {}
        self._next_rid = 1
        self._resolved = deque(maxlen=RESOLVED_MEMORY)
        # Пинг раз в секунду: RTT и джиттер видно в F3, и по ним понятно,
        # виновата сеть или хост/интерполяция.
        self._last_ping_at = 0.0
        self._last_rtt = None

    # ------------------------------------------------------------ НАМЕРЕНИЯ
    def _register_intent(self, kind, key):
        rid = self._next_rid
        self._next_rid = rid + 1 if rid < 0x7FFFFFFF else 1
        self.pending[rid] = {"kind": kind, "key": key,
                             "at": time.monotonic()}
        return rid

    def pending_count(self, kind, key):
        """Сколько намерений этого вида ждут ответа хоста."""
        return sum(1 for intent in self.pending.values()
                   if intent["kind"] == kind and intent["key"] == key)

    def pending_total(self):
        return len(self.pending)

    def _expire_intents(self, events, reason="timeout"):
        """Снимает «проверку» у намерений без ответа — без повторной отправки."""
        now = time.monotonic()
        for rid, intent in list(self.pending.items()):
            if reason == "timeout" and now - intent["at"] < INTENT_TIMEOUT:
                continue
            self.pending.pop(rid, None)
            events.append(("intent_timeout",
                           {"rid": rid, "reason": reason,
                            "kind": intent["kind"], "key": intent["key"]}))

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
        conn.send(protocol.hello(self.player_name, self._resume_pid))

    def _start_reconnect(self):
        """Пробует вернуться в ту же вылазку вместо «соединение потеряно»."""
        if (getattr(self, "_reconnect_thread", None) is not None
                or not getattr(self, "_resume_pid", 0)):
            return False
        self.status = "reconnecting"
        self._reconnect_stop = False
        with self._lock:
            self._conn = None
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop,
                                                  daemon=True)
        self._reconnect_thread.start()
        return True

    def _reconnect_loop(self):
        deadline = time.monotonic() + RESUME_WINDOW
        while (time.monotonic() < deadline
               and not getattr(self, "_reconnect_stop", False)):
            time.sleep(0.35)
            try:
                conn = transport.connect(self.address, timeout=1.5)
            except (OSError, ValueError):
                continue
            self._resume_pending = True
            with self._lock:
                self._conn = conn
            conn.send(protocol.hello(self.player_name, self._resume_pid))
            # Ждём welcome + start: их разбирает тот же pump, что и в игре.
            self.status = "connected"
            return
        if getattr(self, "_reconnect_stop", False):
            return
        self.status = "closed"
        self.error = "Связь с хостом потеряна"
        self._emit_closed = True

    def pump(self):
        """Забирает сообщения сервера. Возвращает события для Game."""
        events = []
        if getattr(self, "_emit_closed", False):
            self._emit_closed = False
            events.append(("closed", self.error))
            return events
        with self._lock:
            conn = self._conn
        if conn is None:
            return events
        # Пинг раз в секунду — только после старта. Он едет JSON-кадром
        # (десятки байт), на фоне снимков это ничто.
        if self.status == "playing":
            now = time.monotonic()
            if now - self._last_ping_at >= 1.0:
                self._last_ping_at = now
                conn.send(protocol.ping(now))
        self._expire_intents(events)
        for kind, payload in conn.poll():
            if kind == "closed":
                self._expire_intents(events, "connection")
                if (self.status == "playing"
                        and self._start_reconnect()):
                    # Не рвём вылазку: до RESUME_WINDOW секунд пытаемся
                    # вернуться и сохранить героя и прогресс.
                    events.append(("reconnecting", None))
                    continue
                if self.status not in ("error", "closed"):
                    self.status = "closed"
                    self.error = "Соединение с хостом потеряно"
                events.append(("closed", None))
                continue
            if kind == "error":
                self.status = "error"
                self.error = f"Ошибка сети: {payload}"
                self._expire_intents(events, "connection")
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
                self._resume_pid = int(self.pid or 0)
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
                resumed = self._resume_pending
                self._resume_pending = False
                if resumed:
                    # Старые снимки и очередь кадра — от прошлого соединения.
                    if getattr(self, "snapshots", None) is not None:
                        self.snapshots.clear()
                    self._snapshot_seq = -1
                    events.append(("resumed", payload))
                else:
                    events.append(("start", payload))
            elif message_type == "snapshot":
                if self.status == "playing":
                    seq = int(payload.get("seq", 0))
                    if seq > self._snapshot_seq:
                        self._snapshot_seq = seq
                        self.snapshot = payload
                        self._queue_snapshot(payload)
                        self.last_snapshot_at = time.monotonic()
                        self.stats["snapshots"] += 1
            elif message_type == "spawn":
                self.stats["spawns"] += 1
                events.append(("spawn", payload))
            elif message_type == "despawn":
                events.append(("despawn", payload))
            elif message_type == "progress":
                events.append(("progress", payload))
            elif message_type == "sounds":
                events.append(("sounds", payload))
            elif message_type == "events":
                events.append(("events", payload))
            elif message_type == "pong":
                stamp = payload.get("stamp", 0.0)
                try:
                    stamp = float(stamp)
                except (TypeError, ValueError):
                    stamp = 0.0
                if stamp > 0.0:
                    # Пакет принят в сетевом потоке (``_rx``). Без этой метки
                    # в RTT входило бы ожидание кадра клиента — на LAN это
                    # лишние 16 мс, по которым видно «фальшивый пинг».
                    arrived = payload.get("_rx") or time.monotonic()
                    rtt = max(0.0, (arrived - stamp) * 1000.0)
                    self.rtt_ms = rtt
                    if self._last_rtt is not None:
                        # Джиттер — сглаженная разница соседних RTT:
                        # одиночный всплеск не должен пугать в HUD.
                        jitter = abs(rtt - self._last_rtt)
                        self.jitter_ms = self.jitter_ms * 0.8 + jitter * 0.2
                    self._last_rtt = rtt
            elif message_type == "notice":
                events.append(("notice", payload))
            elif message_type == "buy_result":
                rid = payload.get("rid")
                intent = None
                if isinstance(rid, int) and not isinstance(rid, bool) and rid:
                    intent = self.pending.pop(rid, None)
                    if intent is None and rid in self._resolved:
                        # Повторный/запоздалый ответ на уже закрытое
                        # намерение: второй раз игроку его не показываем.
                        continue
                    if intent is not None:
                        self._resolved.append(rid)
                result = dict(payload)
                result["_intent"] = intent
                events.append(("buy_result", result))
            elif message_type == "bye":
                self.status = "closed"
                self.error = payload.get("reason") or "Хост завершил сессию"
                events.append(("closed", self.error))
        return events

    def _queue_snapshot(self, payload):
        """Снимок в очередь кадра: лишнее сверх лимита отбрасываем.

        Старые кадры не нужны ни интерполяции, ни предсказанию: окно
        истории — единицы снимков. Зато именно они превращают секундный
        фриз в длинную перемотку после него.
        """
        self.snapshots.append(payload)
        extra = len(self.snapshots) - SNAPSHOT_QUEUE_LIMIT
        if extra > 0:
            del self.snapshots[:extra]
            self.stats["dropped_snapshots"] = (
                self.stats.get("dropped_snapshots", 0) + extra)

    def take_snapshots(self):
        """Отдаёт накопленные снимки (не больше лимита) и очищает очередь."""
        frames = self.snapshots
        if frames:
            self.snapshots = []
        return frames

    def send_input(self, move, aim, aim_pos, fire, melee, actions,
                   position=None):
        with self._lock:
            conn = self._conn
        if conn is None or self.status not in ("connected", "playing"):
            return 0
        if self.status != "playing":
            return 0
        self._seq = (self._seq + 1) & 0xFFFF
        sent = conn.send_bytes(binary.encode_input(
            self._seq, move, aim, aim_pos, fire, melee, list(actions)[:4],
            position=position))
        return self._seq if sent else 0

    def request_buy(self, shop, cursor, kind="", key=""):
        """Отправляет намерение купить и возвращает rid (0 — не ушло)."""
        with self._lock:
            conn = self._conn
        if conn is None or self.status != "playing":
            return 0
        # Пустой key (товар без ключа) и None дают одну и ту же подпись —
        # иначе интерфейс не узнал бы своё же намерение.
        kind = str(kind or "")[:24]
        key = str(key or "")[:32]
        rid = self._register_intent("buy", f"{kind}|{key}")
        sent = conn.send({"t": "buy",
                          "shop": [round(shop.x, 1), round(shop.y, 1)],
                          "cursor": int(cursor), "kind": kind, "key": key,
                          "rid": rid})
        if not sent:
            self.pending.pop(rid, None)
            return 0
        return rid

    def request_skill(self, zone, node):
        """Намерение купить узел: решение и списание делает хост."""
        with self._lock:
            conn = self._conn
        if conn is None or self.status != "playing":
            return 0
        zone = str(zone)[:32]
        node = str(node)[:64]
        rid = self._register_intent("skill", f"{zone}|{node}")
        sent = conn.send({"t": "skill", "zone": zone, "node": node,
                          "rid": rid})
        if not sent:
            self.pending.pop(rid, None)
            return 0
        return rid

    def close(self):
        self._reconnect_stop = True
        with self._lock:
            conn = self._conn
        if conn is not None:
            conn.send(protocol.bye("выход"))
            conn.close()
        # Сессия закрыта осознанно: ждать подтверждений больше некуда.
        self.pending.clear()
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
