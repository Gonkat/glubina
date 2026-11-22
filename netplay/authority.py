"""Выделенный сервер: игра без игрока-хоста.

Отличие от host-based режима только в одном: у процесса нет своего героя.
Авторитетная симуляция (мир, враги, урон, патроны) по-прежнему живёт в
``Game``, а сетевые обязанности — в ``HostSession``: приём ввода,
рассылка снимков, подключение/отключение. Клиенты не отличаются: они
подключаются обычным ``ClientSession`` к адресу сервера.

Запуск::

    python -m netplay.authority --port 32124 --clients 1

--clients 1 — начать вылазку, как только подключится первый игрок.
Сервер разрешает и поздний вход: новый гость появляется у старта, а
остальные получают его дескриптор следующим снимком.

Game сюда импортируется только внутри, чтобы модуль оставался лёгким
для тестов протокола.
"""

import argparse
import os
import threading
import time

# Без окна и звука: у сервера нет ни монитора, ни колонок. Переменные
# выставляются ДО pygame (его тянет game.py).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


class DedicatedAuthority:
    """Головной сервер одной вылазки (один мир на процесс)."""

    def __init__(self, port=0, host_name="Выделенный сервер",
                 bind="127.0.0.1", min_players=1):
        self.host_name = host_name
        self.bind = bind
        self.min_players = max(1, int(min_players))
        self._requested_port = int(port)
        self.port = int(port)
        self.session = None
        self.game = None
        self.started = False
        self._stop = threading.Event()
        self._thread = None
        self._step_ms = 0.0

    # ------------------------------------------------------------ ЖИЗНЕННЫЙ ЦИКЛ
    def start(self):
        """Открывает порт и готовит мир. Возвращает self."""
        from game import Game
        from .session import HostSession

        self.session = HostSession(self.host_name, self._requested_port,
                                   self.bind)
        self.session.allow_late_join = True
        # У сервера нет своего героя: все слоты — для игроков.
        from . import protocol
        self.session.max_clients = protocol.MAX_PLAYERS
        self.port = self.session.port
        self.game = Game()
        self.game.local_name = self.host_name
        self.game.session = self.session
        self.game.net_role = "host"
        self.game.coop_active = True
        # Героя у сервера нет: не даём локальному игроку вмешиваться в
        # симуляцию и не ставим его в мир.
        self.game.server_authority = True
        return self

    def step(self, dt):
        """Один кадр сервера. Вызывать из потока или из теста."""
        if self.session is None or self.game is None:
            return
        started = time.perf_counter()
        session = self.session
        session.accept_handshakes()
        if not self.started:
            session.pump(self.game, dt)
            if (session.status == "waiting"
                    and len(session.clients) >= self.min_players):
                session.start_run(self.game, dedicated=True)
                self.started = True
            self._step_ms = (time.perf_counter() - started) * 1000.0
            return
        if session.clients:
            # game.update сам вызывает session.pump (host-режим) и
            # симулирует мир: один и тот же код, что у игрока-хоста.
            self.game.update(dt)
        else:
            # Все вышли: вылазка стоит, но соединения принимаем —
            # вернувшийся в окне resume получит своего героя назад.
            session.pump(self.game, dt)
        self._keep_view_player()
        self._step_ms = (time.perf_counter() - started) * 1000.0

    def _keep_view_player(self):
        """game.player — точка отсчёта мира; гость мог отключиться."""
        game = self.game
        if game is None or not game.players:
            return
        if game.player not in game.players:
            game.player = game.players[0]
            game.render_players = list(game.players)

    def run_forever(self, tick_hz=120.0, stop_event=None):
        stop = stop_event or self._stop
        interval = 1.0 / max(1.0, float(tick_hz))
        last = time.perf_counter()
        while not stop.is_set():
            now = time.perf_counter()
            # dt ограничен: после паузы планировщика мир не должен
            # телепортироваться на секунду вперёд.
            dt = max(0.0, min(0.05, now - last))
            last = now
            self.step(dt)
            elapsed = time.perf_counter() - now
            if elapsed < interval:
                time.sleep(interval - elapsed)

    def start_background(self, tick_hz=120.0):
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(
            target=self.run_forever, kwargs={"tick_hz": tick_hz},
            daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, reason="Сервер остановлен"):
        self._stop.set()
        if self.session is not None:
            try:
                self.session.close(reason)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------ ДИАГНОСТИКА
    def status(self):
        session = self.session
        return {
            "port": self.port,
            "bind": self.bind,
            "started": self.started,
            "state": getattr(session, "status", "closed"),
            "clients": [{"pid": client.pid, "name": client.name}
                        for client in getattr(session, "clients", ())],
            "seed": getattr(session, "seed", None),
            "depth": getattr(session, "depth", 1),
            "zone": getattr(session, "zone", "medium"),
            "step_ms": round(self._step_ms, 2),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Выделенный сервер «ГЛУБИНЫ» (без игрока-хоста)")
    parser.add_argument("--port", type=int, default=32124,
                        help="порт для клиентов (0 — свободный)")
    parser.add_argument("--bind", default="127.0.0.1",
                        help="адрес прослушивания (по умолчанию только local)")
    parser.add_argument("--clients", type=int, default=1,
                        help="начать вылазку после N подключений")
    parser.add_argument("--name", default="Выделенный сервер")
    parser.add_argument("--tick", type=float, default=120.0,
                        help="частота симуляции, Гц")
    args = parser.parse_args(argv)

    import signal

    authority = DedicatedAuthority(port=args.port, host_name=args.name,
                                   bind=args.bind,
                                   min_players=args.clients).start()
    print(f"[authority] слушаю {args.bind}:{authority.port} "
          f"(старт после {args.clients} игрок(ов))", flush=True)

    def _shutdown(*_args):
        authority.stop()

    try:
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except (ValueError, AttributeError):
        pass

    start = time.monotonic()
    last_report = start
    try:
        while not authority._stop.is_set():
            now = time.perf_counter()
            dt = max(0.0, min(0.05, now - getattr(authority, "_last", now)))
            authority._last = now
            authority.step(dt)
            if time.monotonic() - last_report >= 5.0:
                last_report = time.monotonic()
                status = authority.status()
                print(f"[authority] state={status['state']} "
                      f"clients={len(status['clients'])} "
                      f"step={status['step_ms']:.2f}ms", flush=True)
            elapsed = time.perf_counter() - now
            interval = 1.0 / max(1.0, args.tick)
            if elapsed < interval:
                time.sleep(interval - elapsed)
    finally:
        authority.stop()
        print("[authority] остановлен", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
