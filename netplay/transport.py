"""TCP-транспорт: слушатель хоста, клиент и одно соединение.

Почему TCP, а не UDP: у нас 60 снимков в секунду и несколько десятков
килобайт состояния. Потери UDP пришлось бы компенсировать вручную
(подтверждения, дельта-сжатие, порядок), а выигрыш по задержке на
таком объёме незначителен. TCP даёт доставку и порядок бесплатно;
при перегрузке канал сам притормозит отправителя.

Ограничения честно: TCP «голова очереди» при потере пакета даст
рывок, поэтому сглаживание позиций обязательно (см. client_view).
Для будущего BR с десятками участников потребуется UDP/ENet — это
отдельный слой, а не переделка правил мира.

Потоки: один читатель и один писатель на соединение. Игра забирает
входящие сообщения из очереди в своём кадре — никакой логики игры
в сетевых потоках нет.
"""

import queue
import socket
import threading
import time

from . import protocol


class ConnectionClosed(ConnectionError):
    pass


class Connection:
    """Одно TCP-соединение с кадрированием сообщений."""

    def __init__(self, sock, address=None):
        self.sock = sock
        self.address = address
        self._inbox = queue.Queue()
        self._outbox = queue.Queue()
        self._closed = threading.Event()
        self._send_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._reader.start()
        self._writer.start()

    # ---------------------------------------------------------- ЧТЕНИЕ
    def _read_loop(self):
        buffer = b""
        try:
            while not self._closed.is_set():
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    try:
                        message, buffer = protocol.read_frame(buffer)
                    except protocol.ProtocolError as exc:
                        self._inbox.put(("error", str(exc)))
                        return
                    if message is None:
                        break
                    # Пинг — единственное сообщение без состояния мира:
                    # отвечаем прямо здесь, не дожидаясь кадра игры. Иначе
                    # RTT в F3 мерил бы частоту кадров хоста (+16 мс), а не
                    # сеть, и врал бы на всю LAN.
                    if message.get("t") == "ping":
                        self.send(protocol.pong(message.get("stamp", 0)))
                        continue
                    if message.get("t") == "pong":
                        # Момент прихода — здесь, а не в кадре игры: иначе
                        # RTT вбирал бы в себя ожидание кадра клиента.
                        message["_rx"] = time.monotonic()
                    self._inbox.put(("message", message))
        except OSError:
            pass
        finally:
            self._inbox.put(("closed", None))
            self._shutdown()

    # ---------------------------------------------------------- ЗАПИСЬ
    def _write_loop(self):
        while not self._closed.is_set():
            item = self._outbox.get()
            if item is None:
                break
            try:
                with self._send_lock:
                    self.sock.sendall(item)
            except OSError:
                break
        self._shutdown()

    def send(self, message):
        if self._closed.is_set():
            return False
        try:
            self._outbox.put_nowait(protocol.encode(message))
        except (protocol.ProtocolError, queue.Full):
            return False
        return True

    def send_bytes(self, frame):
        """Готовый кадр (бинарный протокол) — без повторного кодирования."""
        if self._closed.is_set() or not frame:
            return False
        try:
            self._outbox.put_nowait(frame)
        except queue.Full:
            return False
        return True

    # ---------------------------------------------------------- ИГРА
    def poll(self):
        """Возвращает список событий: ("message", dict) / ("closed", None)."""
        events = []
        while True:
            try:
                events.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return events

    @property
    def closed(self):
        return self._closed.is_set()

    def send_and_close(self, message):
        """Отправляет последнее сообщение (reject/bye) и только потом закрывает.

        Обычный close() сбрасывает сокет сразу и потерял бы причину
        отказа — клиент видел бы «соединение закрыто» без объяснения.
        """
        try:
            payload = protocol.encode(message)
            with self._send_lock:
                self.sock.sendall(payload)
        except (OSError, protocol.ProtocolError):
            pass
        finally:
            self._shutdown()

    def close(self):
        self._shutdown()

    def _shutdown(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            self._outbox.put_nowait(None)
        except queue.Full:
            pass


class HostListener:
    """Слушатель хоста: принимает TCP-подключения в фоновом потоке."""

    def __init__(self, port=protocol.DEFAULT_PORT, host="0.0.0.0"):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, int(port)))
        self.sock.listen(8)
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self._pending = queue.Queue()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while not self._closed.is_set():
            try:
                sock, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._pending.put(Connection(sock, addr))

    def accept(self):
        """Забирает все новые подключения (не блокирует)."""
        connections = []
        while True:
            try:
                connections.append(self._pending.get_nowait())
            except queue.Empty:
                break
        return connections

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.close()
        except OSError:
            pass


def connect(address, timeout=5.0):
    """Синхронное подключение (вызывать из потока сессии)."""
    if not address:
        raise ValueError("пустой адрес")
    host, _, raw_port = address.rpartition(":")
    if not host:
        host, raw_port = address, str(protocol.DEFAULT_PORT)
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError(f"некорректный порт: {raw_port}") from exc
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(None)
    return Connection(sock, (host, port))


def local_addresses():
    """Адреса этого компьютера в локальной сети (для приглашения)."""
    addresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    if "127.0.0.1" not in addresses:
        addresses.append("127.0.0.1")
    # 127.0.0.1 первым: он всегда рабочий для проверки на одном ПК.
    addresses.sort(key=lambda ip: (not ip.startswith("127."), ip))
    return addresses
