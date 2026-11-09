"""
Экран спуска (M12): три карты усиления между секторами.

Интерфейс заморожен, пока игрок выбирает. Это единственная пауза,
которая является наградой, а не наказанием: мир уже позади, впереди —
новый, более глубокий сектор.
"""
import math
import random

import pygame

import soundbank
import visuals
from descent import choose_boons
from settings import HEIGHT, STATE_PLAYING, WIDTH

PANEL = (14, 19, 28)
DIM = (144, 156, 178)


class DescentUI:
    def __init__(self):
        self.options = []
        self.index = 0
        self.opened_at = 0

    # ---------------------------------------------------------- ЛОГИКА
    def open(self, game):
        taken = {boon["key"] for boon in game.player.boons}
        rng = random.Random(
            f"{game.world.seed}:boon:{game.depth}:{game.score}:{game.kills}")
        self.options = choose_boons(rng, taken, 3)
        self.index = 0
        self.opened_at = pygame.time.get_ticks()
        soundbank.play("descend", 0.8)

    def handle_event(self, event, game):
        if event.key in (pygame.K_a, pygame.K_LEFT):
            self.index = (self.index - 1) % max(1, len(self.options))
            soundbank.play("ui_move", 0.7)
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            self.index = (self.index + 1) % max(1, len(self.options))
            soundbank.play("ui_move", 0.7)
        elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
            value = event.key - pygame.K_1
            if value < len(self.options):
                self.index = value
                self._take(game)
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                           pygame.K_SPACE):
            self._take(game)
        elif event.key == pygame.K_ESCAPE:
            self._skip(game)

    def _take(self, game):
        if not self.options:
            self._skip(game)
            return
        boon = self.options[self.index]
        boon["apply"](game.player, game)
        game.player.boons.append(boon)
        game.toast(f"УСИЛЕНИЕ: {boon['name']}", 3.2, color=boon["color"])
        soundbank.play("boon_pick", 0.9)
        game.state = STATE_PLAYING
        self.options = []

    def _skip(self, game):
        game.toast("Спуск без усиления", 2.0, color=(150, 160, 180))
        soundbank.play("close", 0.6)
        game.state = STATE_PLAYING
        self.options = []

    # ---------------------------------------------------------- ОТРИСОВКА
    def draw(self, screen, game):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((4, 8, 14, 232))
        screen.blit(dim, (0, 0))
        time = pygame.time.get_ticks() / 1000.0

        # фоновая сетка-шахта: глубина читается даже без текста
        for i in range(9):
            y = 120 + i * 70
            pygame.draw.line(screen, (16, 38, 44), (80, y),
                             (WIDTH - 80, y), 1)
        for i in range(7):
            x = 130 + i * 128
            pygame.draw.line(screen, (13, 30, 38), (x, 96),
                             (x - 40, HEIGHT - 70), 1)

        visuals.text(screen, f"СПУСК · СЕКТОР {game.depth:02d}",
                     (WIDTH // 2, 62), 46, (235, 244, 250), align="center")
        visuals.text(screen, "выберите одно усиление — оно останется до конца вылазки",
                     (WIDTH // 2, 120), 18, (146, 194, 190), align="center")
        pygame.draw.line(screen, (68, 156, 148), (WIDTH // 2 - 210, 150),
                         (WIDTH // 2 + 210, 150), 2)
        visuals.text(screen, f"ГЛУБИНА {game.depth}    ·    МОНЕТЫ {game.money}"
                             f"    ·    ОЧКИ {game.score:,}".replace(",", " "),
                     (WIDTH // 2, 164), 15, DIM, align="center")

        count = max(1, len(self.options))
        card_w, card_h = 250, 306
        gap = 26
        total = count * card_w + (count - 1) * gap
        start_x = (WIDTH - total) // 2
        top = 206
        for i, boon in enumerate(self.options):
            x = start_x + i * (card_w + gap)
            rect = pygame.Rect(x, top, card_w, card_h)
            selected = i == self.index
            self._card(screen, rect, boon, selected, time, i)

        # уже взятые усиления — маленькая строка-память забега
        owned = game.player.boons
        if owned:
            names = "   ·   ".join(b["name"] for b in owned[-4:])
            visuals.text(screen, "УЖЕ ВЗЯТО:  " + names,
                         (WIDTH // 2, HEIGHT - 82), 15, (172, 196, 208),
                         align="center")
        else:
            visuals.text(screen, "УСИЛЕНИЙ ПОКА НЕТ",
                         (WIDTH // 2, HEIGHT - 82), 15, (120, 138, 158),
                         align="center")

        visuals.text(screen, "A / D — выбор     1 / 2 / 3 — взять     ENTER — подтвердить"
                             "     Esc — спуститься без усиления",
                     (WIDTH // 2, HEIGHT - 42), 16, DIM, align="center")

    def _card(self, screen, rect, boon, selected, time, index):
        color = boon["color"]
        if selected:
            glow = pygame.Surface((rect.w + 22, rect.h + 22), pygame.SRCALPHA)
            for i in range(7, 0, -1):
                pygame.draw.rect(glow, (*color, 5 + i * 2), glow.get_rect(),
                                 border_radius=17)
            screen.blit(glow, (rect.x - 11, rect.y - 11))
        panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        panel.fill((*PANEL, 240 if selected else 220))
        pygame.draw.rect(panel, color if selected else (58, 70, 88),
                         panel.get_rect(), 2 if selected else 1,
                         border_radius=14)
        screen.blit(panel, rect.topleft)
        pygame.draw.rect(screen, (22, 30, 42),
                         (rect.x + 1, rect.y + 1, rect.w - 2, 58),
                         border_radius=13)

        # иконка в круге
        cx = rect.centerx
        cy = rect.y + 48
        pygame.draw.circle(screen, (16, 22, 32), (cx, cy), 28)
        pygame.draw.circle(screen, color, (cx, cy), 28, 1)
        self._boon_icon(screen, boon["key"], color, cx, cy)

        visuals.text(screen, boon["name"], (cx, rect.y + 88), 21,
                     (244, 248, 252), align="center")
        divider = tuple(int(c * 0.62) for c in color)
        pygame.draw.line(screen, divider, (rect.x + 30, rect.y + 120),
                         (rect.right - 30, rect.y + 120), 1)
        for i, line in enumerate(boon["lines"]):
            visuals.text(screen, line, (cx, rect.y + 142 + i * 28), 18,
                         (206, 218, 232) if i == 0 else (166, 182, 202),
                         align="center")
        visuals.text(screen, "эффект складывается", (cx, rect.y + 212), 14,
                     (118, 138, 158), align="center")

        # нижняя плашка: порядковый номер и призыв
        plate = pygame.Rect(rect.x + 20, rect.bottom - 66, rect.w - 40, 40)
        if selected:
            pygame.draw.rect(screen, (24, 42, 44), plate, border_radius=8)
            pygame.draw.rect(screen, color, plate, 1, border_radius=8)
            pulse = 0.72 + 0.28 * math.sin(time * 6.0)
            visuals.text(screen, "ВЗЯТЬ · ENTER", (plate.centerx, plate.y + 9),
                         18, tuple(int(c * pulse) for c in color),
                         align="center")
        else:
            visuals.text(screen, f"[{index + 1}]", (plate.centerx, plate.y + 9),
                         18, (132, 148, 168), align="center")

    @staticmethod
    def _boon_icon(screen, key, color, cx, cy):
        """Геометрические эмблемы: системный шрифт не обязан иметь юникод."""
        if key == "hollow":
            pts = [(cx, cy - 12), (cx + 6, cy), (cx, cy + 12), (cx - 6, cy)]
            pygame.draw.polygon(screen, color, pts, 2)
            pygame.draw.circle(screen, color, (cx, cy), 3)
        elif key == "plating":
            pts = [(cx, cy - 12), (cx + 10, cy - 6), (cx + 8, cy + 7),
                   (cx, cy + 13), (cx - 8, cy + 7), (cx - 10, cy - 6)]
            pygame.draw.polygon(screen, color, pts, 2)
            pygame.draw.line(screen, color, (cx, cy - 6), (cx, cy + 7), 2)
        elif key == "vitality":
            pygame.draw.line(screen, color, (cx - 9, cy), (cx + 9, cy), 4)
            pygame.draw.line(screen, color, (cx, cy - 9), (cx, cy + 9), 4)
        elif key == "servo":
            for offset in (-5, 3):
                pygame.draw.lines(screen, color, False,
                                  [(cx - 9 + offset, cy - 7),
                                   (cx + 1 + offset, cy),
                                   (cx - 9 + offset, cy + 7)], 3)
        elif key == "marauder":
            pygame.draw.circle(screen, color, (cx, cy), 10, 2)
            pygame.draw.polygon(screen, color, [
                (cx, cy - 6), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)], 2)
        elif key == "regen":
            pygame.draw.circle(screen, color, (cx - 4, cy - 3), 6, 2)
            pygame.draw.circle(screen, color, (cx + 4, cy - 3), 6, 2)
            pygame.draw.polygon(screen, color, [
                (cx - 9, cy), (cx + 9, cy), (cx, cy + 11)], 2)
        elif key == "pierce":
            pygame.draw.line(screen, color, (cx - 11, cy), (cx + 9, cy), 3)
            pygame.draw.lines(screen, color, False,
                              [(cx + 3, cy - 6), (cx + 11, cy),
                               (cx + 3, cy + 6)], 3)
            pygame.draw.line(screen, color, (cx - 8, cy - 8),
                             (cx - 4, cy - 4), 2)
        elif key == "execute":
            pygame.draw.circle(screen, color, (cx, cy), 11, 2)
            pygame.draw.line(screen, color, (cx - 5, cy - 5), (cx + 5, cy + 5), 3)
            pygame.draw.line(screen, color, (cx + 5, cy - 5), (cx - 5, cy + 5), 3)
        elif key == "leech":
            pygame.draw.polygon(screen, color, [
                (cx, cy - 12), (cx - 8, cy + 3), (cx, cy + 11),
                (cx + 8, cy + 3)], 2)
            pygame.draw.circle(screen, color, (cx, cy + 3), 2)
        elif key == "phase":
            pygame.draw.circle(screen, color, (cx, cy), 10, 2)
            pygame.draw.arc(screen, color, (cx - 14, cy - 6, 14, 12),
                            0.6, 2.5, 2)
            pygame.draw.arc(screen, color, (cx, cy - 6, 14, 12),
                            3.8, 5.7, 2)
        elif key == "trigger":
            pygame.draw.polygon(screen, color, [
                (cx - 2, cy - 13), (cx + 7, cy - 2), (cx + 1, cy - 1),
                (cx + 5, cy + 13), (cx - 7, cy + 1), (cx - 1, cy + 1)], 2)
        else:
            pygame.draw.rect(screen, color, (cx - 9, cy - 8, 18, 16), 2,
                             border_radius=3)
            pygame.draw.line(screen, color, (cx - 9, cy - 2),
                             (cx + 9, cy - 2), 2)
            pygame.draw.rect(screen, color, (cx - 3, cy + 4, 6, 4), 1)
