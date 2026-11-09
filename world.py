import hashlib
import math
import random
from collections import OrderedDict

import pygame
import spritebank
import visuals

from settings import (
    CHUNK_CACHE_LIMIT,
    CHUNK_TILES,
    CORRIDOR_WIDTH,
    FLOOR_COLOR,
    FLOOR_GRID,
    ROOM_ATTEMPTS,
    ROOM_MAX_SIZE,
    ROOM_MIN_SIZE,
    SHOP_MAX_PER_CHUNK,
    SHOP_MIN_DIST,
    SHOP_MIN_ROOM_SIZE,
    SHOP_MIN_SPACING,
    SHOP_PRICE_MULTIPLIER_RANGE,
    TILE,
    WALL_COLOR,
    WALL_DARK,
    WALL_EDGE,
    WALL_LIGHT,
)
from shop_data import SHOP_TYPES, generate_shop_inventory
from utils import mix, resolve_circle_rect


class World:
    """Бесконечный открытый мир с воспроизводимой генерацией чанков.

    passage_radius задаётся в пикселях по радиусу самого крупного персонажа.
    По умолчанию проходы рассчитаны на радиус 0.65 * TILE.
    """

    FLOOR = 0
    WALL = 1
    MAX_WALL_RUN = 6

    def __init__(self, seed=None, passage_radius=None):
        radius = TILE * 0.65 if passage_radius is None else passage_radius
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("passage_radius должен быть конечным и неотрицательным")
        if TILE <= 0 or CHUNK_CACHE_LIMIT < 1:
            raise ValueError("TILE и CHUNK_CACHE_LIMIT должны быть положительными")
        self.passage_radius = radius
        self._clearance = max(1, math.ceil(radius / TILE))
        if CHUNK_TILES < 2 * self._clearance + 10:
            raise ValueError("Чанк слишком мал для заданного passage_radius")
        self.seed = random.SystemRandom().randrange(0, 2**63) if seed is None else seed
        self.chunk_pixels = CHUNK_TILES * TILE
        self._chunks = OrderedDict()
        self._shop_spots = OrderedDict()
        self._plans = OrderedDict()
        self._generate_chunk(0, 0)
        self.ensure_chunks_around(*self.player_start(), radius_chunks=1)

    @property
    def shop_spots(self):
        return [shop for shops in self._shop_spots.values() for shop in shops]

    def shop_spots_near(self, x, y, radius):
        radius_squared = radius * radius
        return [
            shop for shop in self.shop_spots
            if (shop["x"] - x) ** 2 + (shop["y"] - y) ** 2 <= radius_squared
        ]

    def ensure_chunks_around(self, x, y, radius_chunks=1):
        center_x = math.floor(x / self.chunk_pixels)
        center_y = math.floor(y / self.chunk_pixels)
        for chunk_y in range(center_y - radius_chunks, center_y + radius_chunks + 1):
            for chunk_x in range(center_x - radius_chunks, center_x + radius_chunks + 1):
                self._generate_chunk(chunk_x, chunk_y)

    def exploration_sites(self, chunk_x, chunk_y):
        """Воспроизводимые точки интереса, не перекрывающие маршруты."""
        plan = self._plan_chunk(chunk_x, chunk_y)
        rng = self._rng(chunk_x, chunk_y, "exploration-sites-v1")
        if (chunk_x, chunk_y) == (0, 0) or rng.random() > 0.68:
            return ()
        x, y = plan["hub"]
        kind = rng.choices(("camp", "warehouse", "arena", "cache"),
                           weights=(4, 3, 2, 5), k=1)[0]
        return ({"id": (chunk_x, chunk_y), "kind": kind,
                 "x": (chunk_x * CHUNK_TILES + x + 0.5) * TILE,
                 "y": (chunk_y * CHUNK_TILES + y + 0.5) * TILE},)

    def _chunk_seed(self, chunk_x, chunk_y):
        return f"{self.seed}:{chunk_x}:{chunk_y}"

    def _rng(self, chunk_x, chunk_y, purpose):
        return random.Random(f"{self._chunk_seed(chunk_x, chunk_y)}:open-v2:{purpose}")

    def _noise(self, x, y, scale):
        gx, gy = math.floor(x / scale), math.floor(y / scale)
        tx, ty = x / scale - gx, y / scale - gy
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)

        def value(ix, iy):
            payload = f"{self.seed}:density:{scale}:{ix}:{iy}".encode()
            digest = hashlib.blake2b(payload, digest_size=8).digest()
            return int.from_bytes(digest, "big") / (2**64 - 1)

        top = value(gx, gy) * (1 - tx) + value(gx + 1, gy) * tx
        bottom = value(gx, gy + 1) * (1 - tx) + value(gx + 1, gy + 1) * tx
        return top * (1 - ty) + bottom * ty

    def _density_at(self, x, y):
        # Мировые координаты сохраняют плавность зон на стыках чанков.
        value = 0.75 * self._noise(x, y, 48) + 0.25 * self._noise(x, y, 16)
        return max(0.0, min(1.0, (value - 0.22) / 0.56))

    def _edge_portal(self, axis, edge_x, edge_y):
        rng = self._rng(edge_x, edge_y, f"edge:{axis}")
        margin = self._clearance + 2
        return rng.randint(margin, CHUNK_TILES - margin - 1)

    def _plan_chunk(self, chunk_x, chunk_y):
        key = (chunk_x, chunk_y)
        if key in self._plans:
            self._plans.move_to_end(key)
            return self._plans[key]
        rng = self._rng(chunk_x, chunk_y, "layout")
        size = CHUNK_TILES
        margin = self._clearance + 2
        center = size // 2
        hub = (center, center) if key == (0, 0) else (
            rng.randint(size // 3, size * 2 // 3),
            rng.randint(size // 3, size * 2 // 3),
        )
        portals = (
            (self._edge_portal("horizontal", chunk_x, chunk_y), 0),
            (self._edge_portal("horizontal", chunk_x, chunk_y + 1), size - 1),
            (0, self._edge_portal("vertical", chunk_x, chunk_y)),
            (size - 1, self._edge_portal("vertical", chunk_x + 1, chunk_y)),
        )
        paths = []
        for endpoint in portals:
            midpoint = (
                max(margin, min(size - margin - 1,
                    (endpoint[0] + hub[0]) // 2 + rng.randint(-size // 6, size // 6))),
                max(margin, min(size - margin - 1,
                    (endpoint[1] + hub[1]) // 2 + rng.randint(-size // 6, size // 6))),
            )
            depth = self._clearance * 2 + 2
            if endpoint[1] == 0:
                throat = (endpoint[0], depth)
            elif endpoint[1] == size - 1:
                throat = (endpoint[0], size - 1 - depth)
            elif endpoint[0] == 0:
                throat = (depth, endpoint[1])
            else:
                throat = (size - 1 - depth, endpoint[1])
            paths.append((endpoint, throat, midpoint, hub))

        starter_size = min(size - 2, max(11, self._clearance * 2 + 5))
        starter = pygame.Rect(
            center - starter_size // 2, center - starter_size // 2,
            starter_size, starter_size,
        )
        occupied = [starter] if key == (0, 0) else []
        rooms = []
        min_size = max(7, self._clearance * 2 + 5, ROOM_MIN_SIZE)
        max_size = min(max(min_size, ROOM_MAX_SIZE), 14, size - 2 * margin)
        clusters = [(rng.randrange(size), rng.randrange(size)) for _ in range(2)]
        for _ in range(max(0, ROOM_ATTEMPTS)):
            if len(rooms) >= max(1, size * size // 210) or min_size > max_size:
                break
            width, height = rng.randint(min_size, max_size), rng.randint(min_size, max_size)
            if rng.random() < 0.65:
                cx, cy = rng.choice(clusters)
                x = cx + rng.randint(-size // 3, size // 3)
                y = cy + rng.randint(-size // 3, size // 3)
                x = max(margin, min(size - margin - width, x))
                y = max(margin, min(size - margin - height, y))
            else:
                x = rng.randint(margin, size - margin - width)
                y = rng.randint(margin, size - margin - height)
            rect = pygame.Rect(x, y, width, height)
            density = self._density_at(chunk_x * size + rect.centerx,
                                       chunk_y * size + rect.centery)
            if density < 0.3 or rng.random() > 0.25 + density * 0.75:
                continue
            spacing = 2 * self._clearance + 1
            if any(rect.inflate(2 * spacing, 2 * spacing).colliderect(other)
                   for other in occupied):
                continue
            occupied.append(rect)
            rooms.append({"rect": rect, "style": rng.choice(
                ("room", "corner", "ruins", "courtyard"))})

        plan = {"hub": hub, "paths": paths, "portals": portals,
                "rooms": rooms, "starter": starter}
        shop_rooms = [room["rect"] for room in rooms]
        if key == (0, 0):
            shop_rooms.append(starter)
        plan["shops"] = self._shop_candidates(shop_rooms, chunk_x, chunk_y)
        self._plans[key] = plan
        while len(self._plans) > max(32, CHUNK_CACHE_LIMIT * 4):
            self._plans.popitem(last=False)
        return plan

    def _generate_chunk(self, chunk_x, chunk_y):
        key = (chunk_x, chunk_y)
        if key in self._chunks:
            self._chunks.move_to_end(key)
            self._shop_spots.move_to_end(key)
            return self._chunks[key]
        plan = self._plan_chunk(chunk_x, chunk_y)
        grid = [[self.FLOOR] * CHUNK_TILES for _ in range(CHUNK_TILES)]
        for index, room in enumerate(plan["rooms"]):
            rng = self._rng(chunk_x, chunk_y, f"room:{index}")
            for x, y in self._room_walls(room["rect"], room["style"], rng):
                grid[y][x] = self.WALL

        route_cells = set()
        path_radius = max(self._clearance, math.ceil((CORRIDOR_WIDTH - 1) / 2))
        for path in plan["paths"]:
            route_cells.update(self._path_cells(path, path_radius))
        self._add_obstacles(grid, plan, key, route_cells,
                            self._rng(chunk_x, chunk_y, "obstacles"))
        for x, y in route_cells:
            grid[y][x] = self.FLOOR
        # Входы и места торговли связаны широкими подходами с сетью маршрутов.
        for room in plan["rooms"]:
            target = room["rect"].center
            nearest = min(route_cells, key=lambda p: (
                abs(p[0] - target[0]) + abs(p[1] - target[1]), p[1], p[0]))
            self._carve_corridor(grid, target, nearest)
        if key == (0, 0):
            self._carve(grid, plan["starter"])
        self._connect_regions(grid, plan["hub"], 0)
        walkable = self._connect_regions(grid, plan["hub"], self._clearance)
        shops = self._generate_shops(chunk_x, chunk_y)
        lamps = self._chunk_lamps(chunk_x, chunk_y, plan, grid)
        chunk = {"grid": grid,
                 "surface": self._render_chunk(grid, chunk_x, chunk_y),
                 "walkable": walkable, "lamps": lamps}
        self._chunks[key] = chunk
        self._shop_spots[key] = shops
        while len(self._chunks) > CHUNK_CACHE_LIMIT:
            old_key, _ = self._chunks.popitem(last=False)
            self._shop_spots.pop(old_key, None)
        return chunk

    # ------------------------------------------------------------ ЛАМПЫ
    def _chunk_lamps(self, chunk_x, chunk_y, plan, grid):
        """
        Точки света в комнатах. Свет — не декор: он показывает границы
        комнаты и даёт игроку ориентир, куда идти. Расположение
        детерминировано (seed чанка), поэтому не «мигает» при перезаходе.
        """
        rng = self._rng(chunk_x, chunk_y, "lamps-v1")
        palette = ((255, 174, 96), (110, 206, 214), (255, 210, 150),
                   (150, 190, 255))
        lamps = []
        rooms = list(plan["rooms"])
        if (chunk_x, chunk_y) == (0, 0):
            rooms.append({"rect": plan["starter"], "style": "room"})
        for room in rooms:
            if rng.random() > 0.34:
                continue
            rect = room["rect"]
            # ищем стену рядом с комнатой, вешаем лампу на неё
            border = []
            for x in range(rect.left, rect.right):
                for y in (rect.top - 1, rect.bottom):
                    if 0 <= x < CHUNK_TILES and 0 <= y < CHUNK_TILES and grid[y][x] == self.WALL:
                        border.append((x, y))
            for y in range(rect.top, rect.bottom):
                for x in (rect.left - 1, rect.right):
                    if 0 <= x < CHUNK_TILES and 0 <= y < CHUNK_TILES and grid[y][x] == self.WALL:
                        border.append((x, y))
            if not border:
                continue
            tx, ty = rng.choice(border)
            # сдвигаем источник внутрь комнаты, чтобы он не был в стене
            ix = rect.centerx - tx
            iy = rect.centery - ty
            length = math.hypot(ix, iy) or 1.0
            x = (tx + 0.5) * TILE + ix / length * TILE * 0.9
            y = (ty + 0.5) * TILE + iy / length * TILE * 0.9
            lamps.append({
                "x": x, "y": y, "radius": rng.choice((225, 245, 265)),
                "color": rng.choice(palette),
                "phase": rng.uniform(0, math.tau),
                "kind": rng.choice(("lamp", "lamp", "crystal")),
            })
            if len(lamps) >= 6:
                break
        # стартовая площадка всегда освещена — новичок не рождается в аду
        if (chunk_x, chunk_y) == (0, 0):
            cx, cy = self.player_start()
            for dx in (-260, 260):
                lamps.append({"x": cx + dx, "y": cy + 40, "radius": 220,
                              "color": (255, 196, 120), "phase": rng.uniform(0, 6.28),
                              "kind": "lamp"})
        return lamps

    def lamps_near(self, x, y, radius):
        radius_sq = radius * radius
        found = []
        for chunk in self._chunks.values():
            for lamp in chunk.get("lamps", ()):
                if (lamp["x"] - x) ** 2 + (lamp["y"] - y) ** 2 <= radius_sq:
                    found.append(lamp)
        return found

    def draw_lamps(self, screen, camera, time):
        """Светящиеся плафоны рисуются ПОВЕРХ темноты (вызывается из Game)."""
        for chunk in self._chunks.values():
            for lamp in chunk.get("lamps", ()):
                if not camera.is_visible(lamp["x"], lamp["y"], 40):
                    continue
                sx, sy = camera.to_screen(lamp["x"], lamp["y"])
                pulse = 0.82 + 0.18 * math.sin(time * 2.2 + lamp["phase"])
                color = tuple(int(c * pulse) for c in lamp["color"])
                visuals.glow(screen, sx, sy, 44, color, 88)
                if lamp["kind"] == "crystal":
                    pts = [(sx, sy - 9), (sx + 7, sy), (sx, sy + 9), (sx - 7, sy)]
                    pygame.draw.polygon(screen, color, pts)
                    pygame.draw.polygon(screen, (255, 255, 240), pts, 1)
                else:
                    pygame.draw.rect(screen, (32, 36, 46), (sx - 5, sy - 5, 10, 12),
                                     border_radius=2)
                    pygame.draw.circle(screen, color, (int(sx), int(sy)), 5)
                    pygame.draw.circle(screen, (255, 255, 235), (int(sx), int(sy)), 2)
                pygame.draw.circle(screen, color, (int(sx), int(sy)), 2)

    def draw_edges(self, screen, camera):
        """
        Тонкий контур стен, видимый даже в тени. Это не «ещё один свет»,
        а линия геометрии: без неё коридоры в темноте превращаются в кашу.
        """
        surface = getattr(self, "_edge_surface", None)
        if surface is None or surface.get_size() != screen.get_size():
            surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            self._edge_surface = surface
        surface.fill((0, 0, 0, 0))
        left = math.floor(camera.x / TILE) - 1
        right = math.floor((camera.x + screen.get_width()) / TILE) + 1
        top = math.floor(camera.y / TILE) - 1
        bottom = math.floor((camera.y + screen.get_height()) / TILE) + 1
        for ty in range(top, bottom + 1):
            for tx in range(left, right + 1):
                if not self.is_solid_tile(tx, ty):
                    continue
                # рисуем только рёбра, обращённые к полу
                if not self.is_solid_tile(tx, ty - 1):
                    x1 = tx * TILE - camera.x
                    y1 = ty * TILE - camera.y
                    pygame.draw.line(surface, (104, 164, 190, 88),
                                     (x1, y1), (x1 + TILE, y1), 2)
                if not self.is_solid_tile(tx - 1, ty):
                    x1 = tx * TILE - camera.x
                    y1 = ty * TILE - camera.y
                    pygame.draw.line(surface, (62, 104, 132, 54),
                                     (x1, y1), (x1, y1 + TILE), 2)
        screen.blit(surface, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

    def _shop_candidates(self, rooms, chunk_x, chunk_y):
        available = [(kind, config["chance"]) for kind, config in SHOP_TYPES.items()
                     if config["chance"] > 0]
        chance = min(1.0, sum(weight for _, weight in available))
        if not available or SHOP_MAX_PER_CHUNK <= 0:
            return []
        origin_x, origin_y = self.player_start()
        candidates = []
        for index, room in enumerate(rooms):
            if room.w < SHOP_MIN_ROOM_SIZE or room.h < SHOP_MIN_ROOM_SIZE:
                continue
            rng = self._rng(chunk_x, chunk_y, f"shop:{index}")
            if rng.random() >= chance:
                continue
            x = (chunk_x * CHUNK_TILES + room.centerx + 0.5) * TILE
            y = (chunk_y * CHUNK_TILES + room.centery + 0.5) * TILE
            if math.hypot(x - origin_x, y - origin_y) < SHOP_MIN_DIST:
                continue
            candidates.append({
                "x": x, "y": y, "index": index,
                "priority": (rng.random(), chunk_x, chunk_y, index),
                "store_type": rng.choices(
                    [kind for kind, _ in available],
                    weights=[weight for _, weight in available], k=1,
                )[0],
            })
        candidates.sort(key=lambda candidate: candidate["priority"])
        return candidates[:SHOP_MAX_PER_CHUNK]

    def _generate_shops(self, chunk_x, chunk_y):
        candidates = self._plan_chunk(chunk_x, chunk_y)["shops"]
        stores = []
        spacing = max(0, SHOP_MIN_SPACING)
        for candidate in candidates:
            x, y = candidate["x"], candidate["y"]
            min_x = math.floor((x - spacing) / self.chunk_pixels)
            max_x = math.floor((x + spacing) / self.chunk_pixels)
            min_y = math.floor((y - spacing) / self.chunk_pixels)
            max_y = math.floor((y + spacing) / self.chunk_pixels)
            blocked = False
            # Сравниваются планы, а не загруженные чанки. Меньший приоритет
            # побеждает даже при выгруженном соседе, без рекурсивной генерации.
            for cy in range(min_y, max_y + 1):
                for cx in range(min_x, max_x + 1):
                    for other in self._plan_chunk(cx, cy)["shops"]:
                        if (other["priority"] < candidate["priority"]
                                and (other["x"] - x) ** 2 + (other["y"] - y) ** 2
                                < spacing * spacing):
                            blocked = True
                            break
                    if blocked:
                        break
                if blocked:
                    break
            if blocked:
                continue
            rng = self._rng(chunk_x, chunk_y, f"stock:{candidate['index']}")
            stores.append({
                "x": x, "y": y, "store_type": candidate["store_type"],
                "inventory": generate_shop_inventory(candidate["store_type"], rng),
                "upgrade_price_multiplier": rng.uniform(*SHOP_PRICE_MULTIPLIER_RANGE),
            })
        return stores

    def _room_walls(self, rect, style, rng):
        footprint = {(x, y) for y in range(rect.top, rect.bottom)
                     for x in range(rect.left, rect.right)}
        if style == "corner":
            footprint = {(x, y) for x, y in footprint
                         if x < rect.centerx or y >= rect.centery}
        walls = {(x, y) for x, y in footprint if any(
            neighbor not in footprint for neighbor in
            ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))}
        sides = [
            (rect.left, rng.randint(rect.top + 1, rect.bottom - 2)),
            (rect.right - 1, rng.randint(rect.top + 1, rect.bottom - 2)),
            (rng.randint(rect.left + 1, rect.right - 2), rect.top),
            (rng.randint(rect.left + 1, rect.right - 2), rect.bottom - 1),
        ]
        rng.shuffle(sides)
        openings = sides[:rng.randint(2, 3)]
        if style == "courtyard":
            walls.difference_update((x, rect.bottom - 1)
                                    for x in range(rect.left, rect.right))
        if style == "ruins":
            openings += rng.sample(sorted(walls), min(3, len(walls)))
        radius = self._clearance
        for cx, cy in openings + [rect.center]:
            walls.difference_update((x, y)
                for y in range(cy - radius, cy + radius + 1)
                for x in range(cx - radius, cx + radius + 1))
        self._break_wall_runs(walls, radius * 2 + 1)
        return walls

    def _break_wall_runs(self, cells, gap):
        for transpose in (False, True):
            lines = {}
            for x, y in cells:
                a, b = (y, x) if transpose else (x, y)
                lines.setdefault(b, []).append(a)
            for b, positions in lines.items():
                previous, run, skip = None, 0, 0
                for a in sorted(positions):
                    if previous is None or a != previous + 1:
                        run, skip = 0, 0
                    if run == self.MAX_WALL_RUN:
                        skip, run = gap, 0
                    if skip:
                        cells.discard((b, a) if transpose else (a, b))
                        skip -= 1
                    else:
                        run += 1
                    previous = a

    def _obstacle_cells(self, rng):
        kind = rng.choices(("column", "block", "wall", "corner", "cluster"),
                           weights=(20, 25, 25, 20, 10), k=1)[0]
        if kind == "column":
            width = height = rng.randint(1, 2)
        elif kind == "block":
            width, height = rng.randint(2, 3), rng.randint(2, 3)
        elif kind == "wall":
            width, height = rng.randint(3, self.MAX_WALL_RUN), 1
        else:
            width, height = rng.randint(3, 5), rng.randint(3, 5)
        if kind == "corner":
            cells = {(x, 0) for x in range(width)} | {(0, y) for y in range(height)}
        elif kind == "cluster":
            gap = 2 * self._clearance + 1
            cells = {(x + offset, y) for offset in (0, gap + 2)
                     for x in range(2) for y in range(2)}
        else:
            cells = {(x, y) for x in range(width) for y in range(height)}
        turns = rng.randrange(4)
        for _ in range(turns):
            cells = {(-y, x) for x, y in cells}
        min_x, min_y = min(x for x, _ in cells), min(y for _, y in cells)
        return {(x - min_x, y - min_y) for x, y in cells}

    def _add_obstacles(self, grid, plan, key, routes, rng):
        size = CHUNK_TILES
        margin = self._clearance + 1
        gap = 2 * self._clearance + 1
        reserved = [room["rect"].inflate(2 * gap, 2 * gap) for room in plan["rooms"]]
        if key == (0, 0):
            reserved.append(plan["starter"].inflate(2 * gap, 2 * gap))
        budget = int(size * size * 0.17)
        count = sum(row.count(self.WALL) for row in grid)
        local_density = sum(self._density_at(key[0] * size + x, key[1] * size + y)
                            for y in (size // 4, size // 2, size * 3 // 4)
                            for x in (size // 4, size // 2, size * 3 // 4)) / 9
        target = max(1, int(size * size / 45 * (0.35 + 1.2 * local_density)))
        placed = 0
        for _ in range(target * 16):
            if placed >= target or count >= budget:
                break
            shape = self._obstacle_cells(rng)
            width = max(x for x, _ in shape) + 1
            height = max(y for _, y in shape) + 1
            if width > size - 2 * margin or height > size - 2 * margin:
                continue
            x = rng.randint(margin, size - margin - width)
            y = rng.randint(margin, size - margin - height)
            density = self._density_at(key[0] * size + x, key[1] * size + y)
            if density < 0.30 or rng.random() > 0.12 + 0.88 * density * density:
                continue
            rect = pygame.Rect(x, y, width, height)
            if any(rect.colliderect(area) for area in reserved):
                continue
            cells = {(x + dx, y + dy) for dx, dy in shape}
            if cells & routes or count + len(cells) > budget:
                continue
            if any(grid[py][px] == self.WALL
                   for py in range(max(0, y - gap), min(size, y + height + gap))
                   for px in range(max(0, x - gap), min(size, x + width + gap))):
                continue
            for px, py in cells:
                grid[py][px] = self.WALL
            count += len(cells)
            placed += 1

    @staticmethod
    def _carve(grid, rect):
        for y in range(max(0, rect.top), min(CHUNK_TILES, rect.bottom)):
            for x in range(max(0, rect.left), min(CHUNK_TILES, rect.right)):
                grid[y][x] = World.FLOOR

    @staticmethod
    def _line_cells(start, end):
        x, y = start
        dx, dy = end[0] - x, end[1] - y
        steps = max(abs(dx), abs(dy))
        yield x, y
        for step in range(1, steps + 1):
            nx = round(start[0] + dx * step / steps)
            ny = round(start[1] + dy * step / steps)
            # Кардинальные шаги оставляют проход проходимым и на поворотах.
            if nx != x:
                x = nx
                yield x, y
            if ny != y:
                y = ny
                yield x, y

    def _path_cells(self, points, radius):
        cells = set()
        for start, end in zip(points, points[1:]):
            for cx, cy in self._line_cells(start, end):
                for y in range(max(0, cy - radius), min(CHUNK_TILES, cy + radius + 1)):
                    for x in range(max(0, cx - radius), min(CHUNK_TILES, cx + radius + 1)):
                        cells.add((x, y))
        return cells

    def _carve_corridor(self, grid, start, end, rng=None):
        for x, y in self._path_cells((start, end), self._clearance):
            grid[y][x] = self.FLOOR

    @staticmethod
    def _safe_cells(grid, clearance):
        size = CHUNK_TILES
        # Префиксные суммы дают проверку габарита за O(1) на клетку.
        prefix = [[0] * (size + 1) for _ in range(size + 1)]
        for y, row in enumerate(grid):
            total = 0
            for x, tile in enumerate(row):
                total += tile == World.WALL
                prefix[y + 1][x + 1] = prefix[y][x + 1] + total
        safe = set()
        for y in range(clearance, size - clearance):
            top, bottom = y - clearance, y + clearance + 1
            for x in range(clearance, size - clearance):
                left, right = x - clearance, x + clearance + 1
                count = (prefix[bottom][right] - prefix[top][right]
                         - prefix[bottom][left] + prefix[top][left])
                if count == 0:
                    safe.add((x, y))
        return safe

    def _connect_regions(self, grid, start, clearance):
        while True:
            safe = self._safe_cells(grid, clearance)
            reached, stack = {start}, [start]
            while stack:
                x, y = stack.pop()
                for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if point in safe and point not in reached:
                        reached.add(point)
                        stack.append(point)
            missing = safe - reached
            if not missing:
                return safe
            target = min(missing, key=lambda p: (p[1], p[0]))
            nearest = min(reached, key=lambda p: (
                abs(p[0] - target[0]) + abs(p[1] - target[1]), p[1], p[0]))
            for x, y in self._path_cells((target, nearest), clearance):
                grid[y][x] = self.FLOOR

    def _render_chunk(self, grid, chunk_x=0, chunk_y=0):
        """
        Богатый, но детерминированный пол и объёмные стены.

        Раньше это были две сплошные заливки — в темноте такой мир
        выглядел пустым. Теперь у каждой плитки свой оттенок, швы,
        трещины и редкие металлические накладки; стены получили
        верхнюю грань и тень на полу. Всё рисуется ОДИН раз на чанк
        и кэшируется вместе с ним.
        """
        size = self.chunk_pixels
        surface = pygame.Surface((size, size))
        rng = self._rng(chunk_x, chunk_y, "floor-detail-v2")
        surface.fill(FLOOR_COLOR)

        # --- пол: плитка, оттенок, швы, трещины, редкие пластины ---
        for ty in range(CHUNK_TILES):
            for tx in range(CHUNK_TILES):
                if grid[ty][tx] != self.FLOOR:
                    continue
                x, y = tx * TILE, ty * TILE
                shade = rng.randint(-8, 9)
                base = mix(FLOOR_COLOR, (82, 94, 118), rng.random() * 0.22)
                color = tuple(max(0, min(255, c + shade)) for c in base)
                pygame.draw.rect(surface, color, (x, y, TILE, TILE))
                pygame.draw.line(surface, (35, 40, 54), (x, y + TILE - 1),
                                 (x + TILE - 1, y + TILE - 1))
                pygame.draw.line(surface, (35, 40, 54), (x + TILE - 1, y),
                                 (x + TILE - 1, y + TILE - 1))
                roll = rng.random()
                if roll < 0.10:
                    px, py = x + rng.randint(5, TILE - 8), y + rng.randint(5, TILE - 8)
                    for _ in range(3):
                        nx, ny = px + rng.randint(-7, 8), py + rng.randint(-7, 8)
                        pygame.draw.line(surface, (37, 42, 57), (px, py), (nx, ny), 1)
                        px, py = nx, ny
                elif roll < 0.155:
                    rect = pygame.Rect(x + 4, y + 4, TILE - 8, TILE - 8)
                    pygame.draw.rect(surface, (76, 86, 104), rect, border_radius=2)
                    pygame.draw.rect(surface, (98, 112, 132), rect, 1, border_radius=2)
                    for cx2, cy2 in ((rect.left + 3, rect.top + 3),
                                     (rect.right - 4, rect.top + 3),
                                     (rect.left + 3, rect.bottom - 4),
                                     (rect.right - 4, rect.bottom - 4)):
                        pygame.draw.circle(surface, (132, 146, 166), (cx2, cy2), 1)
                elif roll < 0.19:
                    for _ in range(rng.randint(1, 3)):
                        gx = x + rng.randint(4, TILE - 5)
                        gy = y + rng.randint(4, TILE - 5)
                        pygame.draw.circle(surface, (54, 60, 76), (gx, gy), rng.randint(1, 2))

        # --- мелкие следы жизни: лужи, решётки, кабели, разметка ---
        prop_rng = self._rng(chunk_x, chunk_y, "floor-props-v1")
        for ty in range(1, CHUNK_TILES - 1):
            for tx in range(1, CHUNK_TILES - 1):
                if grid[ty][tx] != self.FLOOR:
                    continue
                if prop_rng.random() > 0.11:
                    continue
                x, y = tx * TILE, ty * TILE
                near_wall = any(grid[ty + dy][tx + dx] == self.WALL
                                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)))
                kind = prop_rng.choices(
                    ("oil", "grate", "cable", "rubble", "hazard"),
                    weights=(30, 15, 18, 28, 9) if near_wall else (30, 18, 22, 28, 2),
                    k=1)[0]
                if kind == "oil":
                    w = prop_rng.randint(10, 26)
                    h = prop_rng.randint(6, 16)
                    pygame.draw.ellipse(surface, (43, 47, 61),
                                        (x + 18 - w // 2, y + 16 - h // 2, w, h))
                    pygame.draw.ellipse(surface, (52, 58, 74),
                                        (x + 18 - w // 2 + 2, y + 16 - h // 2 + 1,
                                         max(2, w - 5), max(2, h - 4)), 1)
                elif kind == "grate":
                    rect = pygame.Rect(x + 6, y + 9, 20, 13)
                    pygame.draw.rect(surface, (44, 50, 64), rect, border_radius=2)
                    pygame.draw.rect(surface, (70, 80, 96), rect, 1, border_radius=2)
                    for gx in range(rect.left + 3, rect.right - 2, 4):
                        pygame.draw.line(surface, (34, 39, 51), (gx, rect.top + 2),
                                         (gx, rect.bottom - 3), 1)
                elif kind == "cable":
                    start = (x + 4, y + prop_rng.randint(6, 26))
                    end = (x + 28, y + prop_rng.randint(6, 26))
                    pygame.draw.line(surface, (32, 38, 50), start, end, 2)
                    pygame.draw.line(surface, (24, 30, 40),
                                     (start[0], start[1] + 2),
                                     (end[0], end[1] + 2), 1)
                elif kind == "rubble":
                    for _ in range(prop_rng.randint(2, 5)):
                        rx = x + prop_rng.randint(4, 27)
                        ry = y + prop_rng.randint(4, 27)
                        rr = prop_rng.randint(1, 3)
                        pygame.draw.circle(surface, (48, 54, 68), (rx, ry), rr)
                        pygame.draw.circle(surface, (64, 72, 88),
                                           (rx - 1, ry - 1), max(1, rr - 1))
                else:
                    for i in range(3):
                        sx = x + 5 + i * 8
                        pygame.draw.line(surface, (124, 104, 58),
                                         (sx, y + 28), (sx + 5, y + 10), 3)
        # --- тень от стен на полу (до отрисовки самих стен) ---
        for ty in range(CHUNK_TILES - 1):
            for tx in range(CHUNK_TILES):
                if grid[ty][tx] == self.WALL and grid[ty + 1][tx] == self.FLOOR:
                    pygame.draw.rect(surface, (40, 45, 60),
                                     (tx * TILE, (ty + 1) * TILE, TILE, 5))

        # --- стены: объёмная плита с верхней гранью ---
        wall_render = self._render_wall_tile()
        for ty, row in enumerate(grid):
            for tx, tile in enumerate(row):
                if tile != self.WALL:
                    continue
                x, y = tx * TILE, ty * TILE
                surface.blit(wall_render, (x, y))
                top_open = ty == 0 or grid[ty - 1][tx] == self.FLOOR
                bottom_open = ty == CHUNK_TILES - 1 or grid[ty + 1][tx] == self.FLOOR
                left_open = tx == 0 or grid[ty][tx - 1] == self.FLOOR
                right_open = tx == CHUNK_TILES - 1 or grid[ty][tx + 1] == self.FLOOR
                if top_open:
                    pygame.draw.rect(surface, WALL_LIGHT, (x, y, TILE, 6))
                    pygame.draw.line(surface, (170, 184, 208), (x, y), (x + TILE, y))
                if bottom_open:
                    pygame.draw.rect(surface, (30, 34, 48), (x, y + TILE - 6, TILE, 6))
                if left_open:
                    pygame.draw.line(surface, (66, 72, 92), (x, y), (x, y + TILE), 3)
                if right_open:
                    pygame.draw.line(surface, WALL_EDGE, (x + TILE - 1, y),
                                     (x + TILE - 1, y + TILE), 3)
                if top_open and rng.random() < 0.3:
                    pygame.draw.circle(surface, (156, 170, 194),
                                       (x + rng.randint(6, TILE - 6), y + 3), 1)
                if top_open and rng.random() < 0.18:
                    # труба на верхней грани — индустриальный силуэт
                    px = x + rng.randint(8, TILE - 8)
                    pygame.draw.line(surface, (58, 66, 84), (px, y + 4),
                                     (px, y + 13), 3)
                    pygame.draw.line(surface, (92, 104, 126), (px - 1, y + 4),
                                     (px - 1, y + 13), 1)
        return surface

    def _render_wall_tile(self):
        """Одна плита стены: тёмное тело, светлая верхняя часть, шов."""
        cached = getattr(self, "_wall_tile", None)
        if cached is not None:
            return cached
        surf = pygame.Surface((TILE, TILE))
        surf.fill(WALL_DARK)
        pygame.draw.rect(surf, WALL_COLOR, (0, 0, TILE, TILE - 3))
        pygame.draw.rect(surf, (98, 104, 126), (2, 2, TILE - 4, TILE - 9))
        pygame.draw.rect(surf, WALL_EDGE, (0, 0, TILE, TILE), 1)
        pygame.draw.line(surf, (120, 132, 154), (3, 3), (3, TILE - 8), 2)
        pygame.draw.line(surf, (46, 50, 66), (2, TILE - 5), (TILE - 2, TILE - 5), 2)
        self._wall_tile = surf
        return surf

    def is_solid_tile(self, tile_x, tile_y):
        chunk_x, local_x = divmod(tile_x, CHUNK_TILES)
        chunk_y, local_y = divmod(tile_y, CHUNK_TILES)
        chunk = self._generate_chunk(chunk_x, chunk_y)
        return chunk["grid"][local_y][local_x] == self.WALL

    def is_solid_at(self, pixel_x, pixel_y):
        return self.is_solid_tile(
            math.floor(pixel_x / TILE), math.floor(pixel_y / TILE)
        )

    def tile_rect(self, tile_x, tile_y):
        return pygame.Rect(tile_x * TILE, tile_y * TILE, TILE, TILE)

    def resolve_circle(self, x, y, radius):
        min_x = math.floor((x - radius) / TILE)
        max_x = math.floor((x + radius) / TILE)
        min_y = math.floor((y - radius) / TILE)
        max_y = math.floor((y + radius) / TILE)
        for tile_y in range(min_y, max_y + 1):
            for tile_x in range(min_x, max_x + 1):
                if self.is_solid_tile(tile_x, tile_y):
                    x, y = resolve_circle_rect(
                        x, y, radius, self.tile_rect(tile_x, tile_y)
                    )
        return x, y

    def is_valid_position(self, x, y, radius=0):
        min_x = math.floor((x - radius) / TILE)
        max_x = math.floor((x + radius) / TILE)
        min_y = math.floor((y - radius) / TILE)
        max_y = math.floor((y + radius) / TILE)
        for tile_y in range(min_y, max_y + 1):
            for tile_x in range(min_x, max_x + 1):
                if not self.is_solid_tile(tile_x, tile_y):
                    continue
                rect = self.tile_rect(tile_x, tile_y)
                closest_x = max(rect.left, min(x, rect.right))
                closest_y = max(rect.top, min(y, rect.bottom))
                if (x - closest_x) ** 2 + (y - closest_y) ** 2 < radius ** 2:
                    return False
                if radius == 0 and rect.collidepoint(x, y):
                    return False
        return True

    def random_floor_position(self, radius=0, center=None,
                              min_distance=0, max_distance=1500):
        if center is None:
            center = self.player_start()
        center_x, center_y = center
        min_tile_x = math.floor((center_x - max_distance) / TILE)
        max_tile_x = math.floor((center_x + max_distance) / TILE)
        min_tile_y = math.floor((center_y - max_distance) / TILE)
        max_tile_y = math.floor((center_y + max_distance) / TILE)
        for _ in range(1000):
            tile_x = random.randint(min_tile_x, max_tile_x)
            tile_y = random.randint(min_tile_y, max_tile_y)
            x = tile_x * TILE + TILE / 2
            y = tile_y * TILE + TILE / 2
            distance = math.hypot(x - center_x, y - center_y)
            if distance < min_distance or distance > max_distance:
                continue
            chunk_x, local_x = divmod(tile_x, CHUNK_TILES)
            chunk_y, local_y = divmod(tile_y, CHUNK_TILES)
            chunk = self._generate_chunk(chunk_x, chunk_y)
            if (local_x, local_y) not in chunk["walkable"]:
                continue
            if self.is_valid_position(x, y, radius):
                return x, y
        raise RuntimeError("Не удалось найти свободное место на полу рядом с игроком")

    def player_start(self):
        center = CHUNK_TILES // 2
        return center * TILE + TILE / 2, center * TILE + TILE / 2

    def draw(self, screen, camera):
        left = math.floor((camera.x - self.chunk_pixels) / self.chunk_pixels)
        right = math.floor((camera.x + screen.get_width()) / self.chunk_pixels)
        top = math.floor((camera.y - self.chunk_pixels) / self.chunk_pixels)
        bottom = math.floor((camera.y + screen.get_height()) / self.chunk_pixels)
        for chunk_y in range(top, bottom + 1):
            for chunk_x in range(left, right + 1):
                chunk = self._generate_chunk(chunk_x, chunk_y)
                screen.blit(
                    chunk["surface"],
                    (
                        round(chunk_x * self.chunk_pixels - camera.x),
                        round(chunk_y * self.chunk_pixels - camera.y),
                    ),
                )