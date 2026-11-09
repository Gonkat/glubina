"""Centralized, replaceable sprite assets with safe procedural fallbacks."""
import json
import math
import os

import pygame

ROOT = os.path.dirname(os.path.abspath(__file__))
SPRITES_DIR = os.path.join(ROOT, 'assets', 'sprites')
MANIFEST = os.path.join(ROOT, 'assets', 'sprite_manifest.json')

_FALLBACK_SIZE = {
    "player": 42, "enemy": 54, "runner": 40, "tank": 82, "bomber": 48,
    "stalker": 46, "brute": 92,
    "coin": 20, "ammo": 24, "grenade": 22, "medkit": 26, "artifact": 30,
}
_FALLBACK_COLOR = {
    "player": (70, 130, 220), "enemy": (150, 110, 170), "runner": (140, 200, 80),
    "tank": (110, 120, 135), "bomber": (196, 108, 40),
    "stalker": (194, 66, 118), "brute": (116, 52, 62),
    "coin": (235, 196, 62), "ammo": (168, 132, 74), "grenade": (74, 96, 66),
    "medkit": (232, 232, 236), "artifact": (196, 122, 255),
}


class SpriteBank:
    def __init__(self):
        self._images = {}
        self._rotated = {}
        self._scaled = {}
        self._fallbacks = {}
        self._config = {}
        self.reload()

    def reload(self):
        self._images.clear()
        self._rotated.clear()
        self._scaled.clear()
        self._fallbacks.clear()
        try:
            with open(MANIFEST, encoding='utf-8') as file:
                data = json.load(file)
            self._config = data.get('sprites', {})
        except (OSError, ValueError, TypeError):
            self._config = {}

    def _entry(self, name):
        entry = self._config.get(name, {})
        return entry if isinstance(entry, dict) else {'file': entry}

    def _path(self, name):
        entry = self._entry(name)
        relative = entry.get('file') or name + '.png'
        if not isinstance(relative, str):
            return None
        path = os.path.realpath(os.path.join(SPRITES_DIR, relative))
        if os.path.commonpath((os.path.realpath(SPRITES_DIR), path)) != os.path.realpath(SPRITES_DIR):
            return None
        return path

    def _load_gif(self, path):
        try:
            from PIL import Image, ImageSequence
        except ImportError:
            return None
        frames = []
        with Image.open(path) as gif:
            for frame in ImageSequence.Iterator(gif):
                rgba = frame.convert('RGBA')
                surface = pygame.image.fromstring(rgba.tobytes(), rgba.size, 'RGBA')
                if pygame.display.get_surface():
                    surface = surface.convert_alpha()
                frames.append((surface, max(20, frame.info.get('duration', gif.info.get('duration', 100)))))
        return frames or None

    def _load(self, name):
        path = self._path(name)
        if not path or not os.path.isfile(path):
            return None
        try:
            if path.lower().endswith('.gif'):
                frames = self._load_gif(path)
                if frames:
                    return frames
            surface = pygame.image.load(path)
            if pygame.display.get_surface():
                surface = surface.convert_alpha()
            return [(surface, 100)]
        except (pygame.error, OSError, ValueError):
            return None

    def try_get(self, name):
        if name not in self._images:
            self._images[name] = self._load(name)
        frames = self._images[name]
        if not frames:
            return None
        if len(frames) == 1:
            return frames[0][0]
        duration = sum(delay for _, delay in frames)
        tick = pygame.time.get_ticks() % duration
        for frame, delay in frames:
            if tick < delay:
                return frame
            tick -= delay
        return frames[-1][0]

    def _fallback(self, name):
        side = _FALLBACK_SIZE.get(name, 40)
        surface = pygame.Surface((side, side), pygame.SRCALPHA)
        color = _FALLBACK_COLOR.get(name, (200, 200, 200))
        pygame.draw.circle(surface, color, (side // 2, side // 2), side // 2 - 2)
        pygame.draw.circle(surface, (30, 30, 34), (side // 2, side // 2), side // 2 - 2, 2)
        if name in ("stalker", "brute"):
            pygame.draw.circle(surface, (245, 225, 205), (side * 3 // 4, side * 2 // 5), max(2, side // 12))
            pygame.draw.circle(surface, (245, 225, 205), (side * 3 // 4, side * 3 // 5), max(2, side // 12))
        return surface

    def get(self, name):
        result = self.try_get(name)
        if result is not None:
            return result
        if name not in self._fallbacks:
            self._fallbacks[name] = self._fallback(name)
        return self._fallbacks[name]

    def get_rotated(self, name, angle):
        deg = int(round(math.degrees(angle) / 3) * 3) % 360
        base = self.get(name)
        key = (name, deg, id(base))
        if key not in self._rotated:
            if len(self._rotated) > 2048:
                self._rotated.clear()
            self._rotated[key] = pygame.transform.rotate(base, -deg)
        return self._rotated[key]

    def get_scaled(self, name, size):
        base = self.try_get(name)
        if base is None:
            return None
        size = tuple(map(int, size))
        key = (name, size, id(base))
        if key not in self._scaled:
            if len(self._scaled) > 1024:
                self._scaled.clear()
            self._scaled[key] = pygame.transform.smoothscale(base, size)
        return self._scaled[key]


_bank = SpriteBank()
get_bank = lambda: _bank
get = _bank.get
try_get = _bank.try_get
get_rotated = _bank.get_rotated
get_scaled = _bank.get_scaled
reload = _bank.reload


def missing_assets():
    return {name: entry.get("file", name + ".png") for name, entry in _bank._config.items()
            if _bank._path(name) is None or not os.path.isfile(_bank._path(name))}
