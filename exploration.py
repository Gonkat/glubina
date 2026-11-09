"""Детерминированные точки интереса и одноразовые сундуки."""
import math
import random

import pygame
import spritebank
import visuals


class Exploration:
    LABELS = {"camp": "Лагерь", "warehouse": "Склад", "arena": "Арена", "cache": "Тайник"}

    def __init__(self, world):
        self.world = world
        self.sites = {}
        self.opened = set()
        self.notice = ""
        self.notice_until = 0

    def update(self, x, y):
        size = self.world.chunk_pixels
        cx, cy = math.floor(x / size), math.floor(y / size)
        sites = {}
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                for site in self.world.exploration_sites(cx + dx, cy + dy):
                    sites[site["id"]] = site
        self.sites = sites

    def open_nearest(self, game):
        player = game.player
        candidates = [site for site in self.sites.values()
                      if site["id"] not in self.opened
                      and (site["x"] - player.x) ** 2 + (site["y"] - player.y) ** 2 < 105 ** 2]
        if not candidates:
            return False
        site = min(candidates, key=lambda item: (item["x"] - player.x) ** 2 + (item["y"] - player.y) ** 2)
        self.opened.add(site["id"])
        rng = random.Random(f"{self.world.seed}:chest:{site['id']}")
        rewards = []
        rarity = self.rarity(site)
        scale = {"common": 1, "rare": 2, "legendary": 4}[rarity]
        money = rng.randint(30, 100) * scale
        game.money += money
        rewards.append(f"{money} монет")
        if rng.random() < 0.8:
            ammo = rng.randint(8, 25) * scale
            player.equipment.add_ammo(ammo)
            rewards.append(f"{ammo} патронов")
        if rng.random() < 0.35:
            player.equipment.add_item("grenade", 1)
            rewards.append("граната")
        if rng.random() < 0.3:
            player.equipment.add_item("medkit", 1)
            rewards.append("аптечка")
        # Реликвии нельзя купить за монеты. Усиление принадлежит экземпляру
        # экипированного оружия и не дублируется при выгрузке чанка.
        relic_chance = {"common": 0.12, "rare": 0.55, "legendary": 1.0}[rarity]
        if rng.random() < relic_chance:
            weapon = player.melee if rng.random() < 0.5 else player.firearm
            if weapon is not None:
                self.grant_relic(weapon, rng, rewards)
        self.notice = f"{self.rarity_label(rarity)} сундук: " + ", ".join(rewards)
        self.notice_until = pygame.time.get_ticks() + 5500
        return True

    @staticmethod
    def rarity_label(rarity):
        return {"common": "Обычный", "rare": "Редкий", "legendary": "Легендарный"}[rarity]

    def rarity(self, site):
        rng = random.Random(f"{self.world.seed}:rarity:{site['id']}")
        roll = rng.random()
        bonus = 0.12 if site["kind"] in ("arena", "cache") else 0.0
        if roll < 0.045 + bonus * 0.3:
            return "legendary"
        if roll < 0.22 + bonus:
            return "rare"
        return "common"

    @staticmethod
    def grant_relic(weapon, rng, rewards):
        # Each relic is unique per weapon instance and changes its combat behaviour.
        choices = ["power", "tempo", "reach"]
        if weapon.key == "hammer":
            choices.append("quake")
        rng.shuffle(choices)
        owned = set(weapon.mods.get("world_relics", ()))
        relic = next((name for name in choices if name not in owned), None)
        if relic is None:
            rewards.append("реликвия уже изучена")
            return
        owned.add(relic)
        weapon.mods["world_relics"] = tuple(sorted(owned))
        if hasattr(weapon, "attack"):
            weapon.attack.mods["world_relics"] = weapon.mods["world_relics"]
        if relic == "power":
            weapon.spec["damage"] *= 1.16
        elif relic == "tempo":
            weapon.spec["cooldown"] *= 0.87
        elif relic == "reach":
            for key in ("reach", "radius"):
                if key in weapon.spec:
                    weapon.spec[key] *= 1.18
        elif relic == "quake":
            weapon.mods["shock_slow"] = max(weapon.mods.get("shock_slow", 0), 2.0)
            weapon.attack.mods["shock_slow"] = max(weapon.attack.mods.get("shock_slow", 0), 2.0)
        rewards.append(f"реликвия {weapon.name}: {relic}")

    def draw(self, screen, camera, player):
        """Физические сундуки: до темноты, чтобы свет их подсвечивал."""
        for site in self.sites.values():
            x, y = camera.to_screen(site["x"], site["y"])
            if not (-60 < x < screen.get_width() + 60 and -60 < y < screen.get_height() + 60):
                continue
            opened = site["id"] in self.opened
            rarity = self.rarity(site)
            palette = {"common": (194, 135, 59), "rare": (116, 177, 221),
                       "legendary": (237, 196, 68)}
            color = (93, 91, 91) if opened else palette[rarity]
            chest = spritebank.get_scaled("chest/opened" if opened else "chest/" + rarity, (40, 30))
            if chest is not None:
                screen.blit(chest, chest.get_rect(center=(x, y)))
            else:
                pygame.draw.rect(screen, (29, 23, 18), (x - 19, y - 13, 38, 27), border_radius=4)
                pygame.draw.rect(screen, color, (x - 17, y - 11, 34, 23), border_radius=3)
                pygame.draw.rect(screen, (245, 206, 105) if not opened else (64, 64, 64),
                                 (x - 3, y - 9, 6, 20))

    def draw_overlay(self, screen, camera, player):
        """Метки и подсказки поверх темноты — только у ближних точек."""
        for site in self.sites.values():
            if site["id"] in self.opened:
                continue
            d2 = (site["x"] - player.x) ** 2 + (site["y"] - player.y) ** 2
            if d2 > 820 ** 2:
                continue
            x, y = camera.to_screen(site["x"], site["y"])
            if not (-60 < x < screen.get_width() + 60 and -60 < y < screen.get_height() + 60):
                continue
            rarity = self.rarity(site)
            palette = {"common": (222, 168, 82), "rare": (110, 190, 236),
                       "legendary": (255, 210, 70)}
            color = palette[rarity]
            pulse = 1.0 + 0.12 * math.sin(pygame.time.get_ticks() / 260 + site["x"] * 0.01)
            pygame.draw.polygon(screen, color, [
                (x, y - 30 - 4 * pulse), (x + 5, y - 25), (x, y - 20),
                (x - 5, y - 25),
            ])
            if d2 < 340 ** 2:
                label = (self.LABELS[site["kind"]] + " · " +
                         self.rarity_label(rarity))
                visuals.text(screen, label, (x, y - 48), 16, color, align="center")
        if self.notice and pygame.time.get_ticks() < self.notice_until:
            width = visuals.text_width(self.notice, 18) + 36
            background = pygame.Rect(screen.get_width() // 2 - width // 2, 46,
                                     width, 32)
            panel = pygame.Surface((background.w, background.h), pygame.SRCALPHA)
            panel.fill((20, 26, 34, 232))
            pygame.draw.rect(panel, (255, 200, 100), panel.get_rect(), 1,
                             border_radius=8)
            screen.blit(panel, background.topleft)
            visuals.text(screen, self.notice, background.center, 18,
                         (255, 226, 143), align="center")
