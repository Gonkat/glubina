"""Экран «Онлайн»: создание сессии, подключение и ожидание.

Интерфейс показывает только то, что реально работает: TCP-адрес
и порт. Никаких «кодов приглашения», которые никуда не ведут.

Состояния:
  main      — Создать игру / Подключиться / Назад
  host      — сессия создана, видно адрес и участников, Enter — старт
  join      — ввод адреса хоста
  joining   — идёт подключение
  connected — подключились, ждём старта от хоста
  error     — ошибка с понятным текстом и возвратом назад
"""

import math

import pygame

import soundbank
import visuals
from settings import DIFFICULTIES, HEIGHT, WIDTH

from . import MAX_PLAYERS, PROTOCOL_VERSION


CYAN = (128, 226, 214)
GOLD = (255, 206, 112)
DIM = (150, 162, 184)
BAD = (240, 140, 120)
GOOD = (140, 232, 178)


class OnlineUI:
    MAIN_ITEMS = ("СОЗДАТЬ ИГРУ", "ПОДКЛЮЧИТЬСЯ К ИГРЕ", "НАЗАД")

    def __init__(self):
        self.reset()

    def reset(self):
        self.screen = "main"
        self.index = 0
        self.address = "127.0.0.1:32123"
        self.error = ""
        self.notice = ""

    # ------------------------------------------------------------ ВВОД
    def handle_event(self, event, game):
        if event.type != pygame.KEYDOWN:
            return
        if self.screen == "main":
            self._handle_main(event.key, game)
        elif self.screen == "join":
            self._handle_join(event, game)
        elif self.screen == "host":
            self._handle_host(event.key, game)
        elif self.screen in ("joining", "connected", "error"):
            if event.key == pygame.K_ESCAPE:
                game.online_leave()
                self.reset()
                soundbank.play("close")

    def _handle_main(self, key, game):
        if key in (pygame.K_w, pygame.K_UP):
            self.index = (self.index - 1) % len(self.MAIN_ITEMS)
            soundbank.play("ui_move")
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.index = (self.index + 1) % len(self.MAIN_ITEMS)
            soundbank.play("ui_move")
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.index == 0:
                ok = game.online_host()
                if ok:
                    self.screen = "host"
                    self.error = ""
                    soundbank.play("open")
            elif self.index == 1:
                self.screen = "join"
                self.error = ""
                soundbank.play("open")
            else:
                game.enter_title()
                soundbank.play("close")
        elif key == pygame.K_ESCAPE:
            game.enter_title()
            soundbank.play("close")

    def _handle_join(self, event, game):
        key = event.key
        if key == pygame.K_ESCAPE:
            self.screen = "main"
            soundbank.play("close")
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            ok = game.online_join(self.address.strip())
            if ok:
                self.screen = "joining"
                self.error = ""
                soundbank.play("open")
        elif key == pygame.K_BACKSPACE:
            self.address = self.address[:-1]
        else:
            char = event.unicode
            if char and char.isprintable() and len(self.address) < 64:
                self.address += char

    def _handle_host(self, key, game):
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if game.start_coop_host():
                soundbank.play("open")
        elif key == pygame.K_ESCAPE:
            game.online_leave()
            self.reset()
            soundbank.play("close")

    # ------------------------------------------------------------ СОСТОЯНИЕ
    def sync(self, game):
        """Переносит события сессии в состояние экрана (вызывает Game)."""
        session = getattr(game, "session", None)
        if session is None:
            return
        if game.net_role == "client":
            if session.status == "error":
                self.screen = "error"
                self.error = session.error
            elif session.status == "connected" and self.screen == "joining":
                self.screen = "connected"
            elif session.status == "closed" and self.screen in (
                    "connected", "playing"):
                self.screen = "error"
                self.error = session.error or "Хост завершил сессию"

    # ------------------------------------------------------------ РИСОВКА
    def draw(self, screen, game):
        self._background(screen)
        self._panel(screen, pygame.Rect(WIDTH // 2 - 330, 96, 660, 560),
                    color=(12, 17, 25), edge=(58, 78, 96), alpha=232, radius=16)
        visuals.text(screen, "ОНЛАЙН", (WIDTH // 2, 120), 44, GOLD,
                     align="center")
        visuals.text(screen,
                     f"кооперативная вылазка · до {MAX_PLAYERS} игроков · "
                     f"протокол {PROTOCOL_VERSION}",
                     (WIDTH // 2, 176), 16, DIM, align="center")

        if self.screen == "main":
            self._draw_main(screen)
        elif self.screen == "host":
            self._draw_host(screen, game)
        elif self.screen == "join":
            self._draw_join(screen)
        elif self.screen == "joining":
            self._draw_joining(screen, game)
        elif self.screen == "connected":
            self._draw_connected(screen, game)
        elif self.screen == "error":
            self._draw_error(screen)

        visuals.text(screen,
                     "Адрес и порт — реальный TCP-сервер хоста. В локальной "
                     "сети он работает сразу;",
                     (WIDTH // 2, HEIGHT - 62), 14, (128, 138, 158),
                     align="center")
        visuals.text(screen,
                     "для игры через интернет нужен проброс порта или туннель "
                     "(NAT/фаервол не обходятся сами).",
                     (WIDTH // 2, HEIGHT - 42), 14, (128, 138, 158),
                     align="center")

    def _draw_main(self, screen):
        for index, item in enumerate(self.MAIN_ITEMS):
            y = 268 + index * 62
            selected = index == self.index
            rect = pygame.Rect(WIDTH // 2 - 260, y - 12, 520, 48)
            if selected:
                self._panel(screen, rect, color=(25, 44, 52), edge=GOLD,
                            alpha=228, radius=8)
                visuals.arrow(screen, rect.x + 24, y + 10, 0, 7, GOLD, 1)
                visuals.text(screen, "ENTER", (rect.right - 20, y + 6), 14,
                             GOLD, align="right")
            visuals.text(screen, item, (WIDTH // 2, y), 27,
                         GOLD if selected else (224, 232, 244), align="center")
        visuals.text(screen, "W/S — выбор    Enter — открыть    Esc — назад",
                     (WIDTH // 2, 560), 15, DIM, align="center")

    def _draw_host(self, screen, game):
        session = game.session
        if session is None:
            visuals.text(screen, "Сессия не создана", (WIDTH // 2, 300), 22,
                         BAD, align="center")
            return
        visuals.text(screen, "СЕССИЯ СОЗДАНА · ВЫ ХОСТ",
                     (WIDTH // 2, 214), 20, GOOD, align="center")

        addresses = [f"{ip}:{session.port}" for ip in session.addresses]
        visuals.text(screen, "АДРЕС ДЛЯ ПОДКЛЮЧЕНИЯ",
                     (WIDTH // 2, 252), 14, DIM, align="center")
        for index, address in enumerate(addresses[:3]):
            visuals.text(screen, address, (WIDTH // 2, 278 + index * 24), 20,
                         CYAN, align="center")

        visuals.text(screen, "УЧАСТНИКИ", (WIDTH // 2 - 250, 378), 14, DIM)
        names = [f"1. {session.host_name} (хост)"]
        names += [f"{client.pid}. {client.name}" for client in session.clients]
        for index, name in enumerate(names):
            visuals.text(screen, name, (WIDTH // 2 - 250, 402 + index * 26),
                         19, (224, 232, 244) if index == 0 else CYAN)
        if not session.clients:
            visuals.text(screen, "Ждём подключения второго игрока…",
                         (WIDTH // 2 - 250, 402 + 26), 17, DIM)

        if session.notices:
            self.notice = session.notices[-1][0]
        if self.notice:
            visuals.text(screen, self.notice, (WIDTH // 2, 556), 16,
                         (200, 212, 230), align="center")

        visuals.text(screen, "Enter — начать вылазку    Esc — закрыть сессию",
                     (WIDTH // 2, 596), 17, GOLD, align="center")
        visuals.text(screen,
                     f"Сложность: {DIFFICULTIES[game.difficulty_key]['name']} · "
                     "присоединиться можно только до старта",
                     (WIDTH // 2, 624), 14, DIM, align="center")

    def _draw_join(self, screen):
        visuals.text(screen, "АДРЕС ХОСТА", (WIDTH // 2, 244), 16, DIM,
                     align="center")
        rect = pygame.Rect(WIDTH // 2 - 240, 272, 480, 54)
        self._panel(screen, rect, color=(18, 25, 36), edge=CYAN, alpha=240)
        caret = "_" if int(pygame.time.get_ticks() / 450) % 2 == 0 else " "
        visuals.text(screen, self.address + caret,
                     (rect.x + 18, rect.y + 15), 22, (236, 244, 252))
        visuals.text(screen, "Например: 192.168.1.50:32123",
                     (WIDTH // 2, 344), 15, (128, 140, 162), align="center")
        if self.error:
            visuals.text(screen, self.error, (WIDTH // 2, 392), 17, BAD,
                         align="center")
        visuals.text(screen, "Enter — подключиться    Esc — назад",
                     (WIDTH // 2, 470), 17, GOLD, align="center")

    def _draw_joining(self, screen, game):
        session = game.session
        dots = "." * (1 + int(pygame.time.get_ticks() / 350) % 3)
        visuals.text(screen, f"ПОДКЛЮЧЕНИЕ{dots}", (WIDTH // 2, 300), 24,
                     CYAN, align="center")
        visuals.text(screen, (session.address if session else self.address),
                     (WIDTH // 2, 344), 18, DIM, align="center")
        visuals.text(screen, "Esc — отменить", (WIDTH // 2, 430), 16, DIM,
                     align="center")

    def _draw_connected(self, screen, game):
        session = game.session
        visuals.text(screen, "ПОДКЛЮЧЕНО", (WIDTH // 2, 286), 26, GOOD,
                     align="center")
        if session is not None:
            visuals.text(screen, f"Хост: {session.host_name}",
                         (WIDTH // 2, 330), 19, (220, 230, 246),
                         align="center")
        visuals.text(screen, "Ждём, когда хост начнёт вылазку…",
                     (WIDTH // 2, 372), 18, DIM, align="center")
        visuals.text(screen, "Esc — отключиться", (WIDTH // 2, 430), 16, DIM,
                     align="center")

    def _draw_error(self, screen):
        visuals.text(screen, "НЕ УДАЛОСЬ", (WIDTH // 2, 290), 26, BAD,
                     align="center")
        self._wrap_text(screen, self.error, WIDTH // 2, 340, 560, 18, BAD)
        visuals.text(screen, "Esc — вернуться в меню онлайна",
                     (WIDTH // 2, 448), 17, GOLD, align="center")

    # ------------------------------------------------------------ УТИЛИТЫ
    def _wrap_text(self, screen, text, cx, y, width, size, color):
        words = str(text).split()
        line = ""
        lines = []
        for word in words:
            candidate = f"{line} {word}".strip()
            if visuals.text_width(candidate, size) > width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        for index, row in enumerate(lines[:4]):
            visuals.text(screen, row, (cx, y + index * (size + 8)), size,
                         color, align="center")

    def _panel(self, screen, rect, color=(16, 22, 32), edge=(60, 78, 100),
               alpha=230, radius=10):
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, (*color, alpha), surface.get_rect(),
                         border_radius=radius)
        pygame.draw.rect(surface, edge, surface.get_rect(), 1,
                         border_radius=radius)
        screen.blit(surface, rect.topleft)

    def _background(self, screen):
        screen.fill((7, 10, 17))
        time = pygame.time.get_ticks() / 1000.0
        for index in range(46):
            x = (index * 97 + time * (6 + index % 5)) % WIDTH
            y = (index * 53 + math.sin(time * 0.6 + index) * 18) % HEIGHT
            pygame.draw.circle(screen, (34, 58, 74), (int(x), int(y)), 1)
