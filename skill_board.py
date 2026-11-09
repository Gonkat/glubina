"""
ГЕОМЕТРИЯ ЕДИНОЙ ДОСКИ НАВЫКОВ.

Раньше дерево было тремя колонками внутри окна. Теперь это одна большая
карта: в центре — древо героя, слева — отдельные древа всего оружия
ближнего боя, справа — отдельные древа огнестрельного оружия. Доска
больше экрана, поэтому skill_tree_ui.py двигает по ней камеру.

Здесь только ДАННЫЕ РАСКЛАДКИ: координаты, ветви, цвета, подписи. Ни
правил покупки, ни отрисовки — ими занимаются skill_tree.py и UI.
"""
import heapq
import math

from skill_data import PLAYER_TREE, SKILL_TREES
from weapon_data import FIREARMS, MELEE

ZONE_GAP = 120
BOARD_MARGIN = 120
ZONE_COLUMNS = 2

MELEE_ORDER = ("knife", "machete", "katana", "hammer", "shovel", "shield")
RANGED_ORDER = ("pistol", "shotgun", "sniper", "cannon",
                "disc", "arc", "cutter")
ZONE_ORDER = ("player",) + MELEE_ORDER + RANGED_ORDER

WEAPON_SLOT = {key: "firearm" for key in FIREARMS}
WEAPON_SLOT.update({key: "melee" for key in MELEE})

WEAPON_COLORS = {
    "knife": (202, 224, 240),
    "machete": (234, 152, 92),
    "katana": (126, 202, 255),
    "hammer": (255, 166, 78),
    "shovel": (168, 204, 142),
    "shield": (246, 204, 102),
    "pistol": (112, 208, 242),
    "shotgun": (248, 180, 92),
    "sniper": (174, 154, 255),
    # Энергопушка — холодная плазма: цвет отличается от пистолета и
    # снайперки даже на мини-карте.
    "cannon": (104, 238, 226),
    # Новые школы: диск — золото траектории, дуга — электрический синий,
    # резак — горячий красно-оранжевый. На мини-карте они не сливаются.
    "disc": (255, 196, 96),
    "arc": (150, 190, 255),
    "cutter": (255, 128, 96),
}
PLAYER_COLOR = (255, 206, 116)
PLAYER_BRANCH_COLORS = ((116, 234, 156), (94, 196, 255), (255, 206, 116))
CATEGORY_COLORS = {
    "player": PLAYER_COLOR,
    "melee": (234, 144, 100),
    "firearm": (108, 200, 244),
}
CATEGORY_LABELS = {
    "melee": "БЛИЖНИЙ БОЙ",
    "firearm": "ОГНЕСТРЕЛЬНОЕ",
}
CATEGORY_SUBTITLES = {
    "melee": "шесть отдельных древ",
    "firearm": "семь отдельных древ",
}

# Лучи ветвей: вверх и две диагонали вниз. Так каждое малое древо
# читается как дерево, а не как список из трёх столбцов.
BRANCH_ANGLES = (-90.0, 30.0, 150.0)
BRANCH_BENDS = (7.0, -6.0, 5.0)
# Пять колец: tier 5 — пара доктрин, поэтому последнее кольцо чуть шире.
WEAPON_TIER_RADIUS = (132.0, 194.0, 256.0, 318.0, 380.0)
PLAYER_TIER_RADIUS = (148.0, 216.0, 284.0, 352.0, 420.0)
# Два tier-5 узла одной ветви стоят рядом: не сливаются и читаются
# как развилка, а не как один узел с двойной подписью.
CHOICE_LANE_ANGLE = 8.5
# Длинные мастерские цепочки не должны растягивать остров на километры:
# после пятого кольца шаг меньше, а лёгкий зигзаг разводит соседние узлы.
WEAPON_EXTENSION_STEP = 38.0
WEAPON_EXTENSION_LANE = 0.25

NODE_RADIUS = 16
PLAYER_NODE_RADIUS = 18
ROOT_RADIUS = 37

# Подпись ветви — не точка на конце луча, а прямоугольник с текстом.
# Поэтому конец ветви выносится за последний узел настолько, чтобы
# горизонтальная плашка не легла на пару доктрин (самый широкий случай —
# боковая ветвь, где плашка растёт к центру дерева).
BRANCH_LABEL_RESERVE = 122.0
BRANCH_LABEL_PAD = 92.0

# Маршрутизация связей: сетка и клиренс вокруг чужих узлов. Эти числа
# общие для всех древ, поэтому новая ветвь/оружие не требует ручной
# подгонки координат.
LINK_GRID_STEP = 8.0
LINK_NODE_CLEARANCE = 5.0
LINK_ROOT_CLEARANCE = 8.0


def category_of(zone):
    if zone == "player":
        return "player"
    return "firearm" if zone in FIREARMS else "melee"


def zone_name(zone):
    if zone == "player":
        return "ГЕРОЙ"
    if zone in FIREARMS:
        return FIREARMS[zone]["name"].upper()
    if zone in MELEE:
        return MELEE[zone]["name"].upper()
    return zone.upper()


def zone_color(zone):
    if zone == "player":
        return PLAYER_COLOR
    return WEAPON_COLORS.get(zone, CATEGORY_COLORS[category_of(zone)])


def _polar(cx, cy, angle_deg, distance):
    angle = math.radians(angle_deg)
    return (cx + math.cos(angle) * distance,
            cy + math.sin(angle) * distance)


def _branch_geometry(index, count):
    if count <= len(BRANCH_ANGLES):
        return BRANCH_ANGLES[index], BRANCH_BENDS[index]
    # Четыре и больше ветвей делят круг поровну и не закручиваются:
    # повторять три старых наклона здесь значило бы ломать симметрию
    # и сближать подписи соседних ветвей.
    return -90.0 + 360.0 * index / count, 0.0


def _node_lane(branch, node):
    tier_nodes = [candidate for candidate in branch["nodes"]
                  if candidate["tier"] == node["tier"]]
    if len(tier_nodes) == 1:
        return node.get("lane", 0)
    if all("lane" in candidate for candidate in tier_nodes):
        lanes = [candidate["lane"] for candidate in tier_nodes]
        if len(set(lanes)) == len(lanes):
            return node["lane"]
    index = next(i for i, candidate in enumerate(tier_nodes)
                 if candidate["id"] == node["id"])
    return (index - (len(tier_nodes) - 1) / 2) * 2


class BoardLayout:
    """Кэш координат и непересекающихся областей всех древ на доске."""

    def __init__(self):
        self.player_positions = {}
        self.player_branch_ends = []
        self.weapon_positions = {}
        self.weapon_branch_ends = {}
        self.zone_centers = {}
        self.zone_extents = {}
        self.board_w = 0
        self.board_h = 0
        self._build_player()
        self._build_weapons()
        self._place_zones()

    def _build_player(self):
        branches = PLAYER_TREE["branches"]
        for bi, branch in enumerate(branches):
            base, bend = _branch_geometry(bi, len(branches))
            for node in branch["nodes"]:
                tier = max(1, node["tier"])
                angle = base + bend * (tier - 1) * 0.72
                self.player_positions[node["id"]] = _polar(
                    0, 0, angle, self._tier_radius(PLAYER_TIER_RADIUS, tier))
            last_tier = max(node["tier"] for node in branch["nodes"])
            terminals = [node for node in branch["nodes"]
                         if node["tier"] == last_tier]
            x = sum(self.player_positions[node["id"]][0] for node in terminals) / len(terminals)
            y = sum(self.player_positions[node["id"]][1] for node in terminals) / len(terminals)
            dx, dy = x, y
            length = math.hypot(dx, dy) or 1.0
            self.player_branch_ends.append(
                (x + dx / length * BRANCH_LABEL_RESERVE,
                 y + dy / length * BRANCH_LABEL_RESERVE))

    def _build_weapons(self):
        for key, tree in SKILL_TREES.items():
            positions = {}
            ends = []
            branches = tree["branches"]
            for bi, branch in enumerate(branches):
                base, bend = _branch_geometry(bi, len(branches))
                max_tier = max(node["tier"] for node in branch["nodes"])
                for node in branch["nodes"]:
                    tier = max(1, node["tier"])
                    lane = _node_lane(branch, node)
                    angle = (base + bend * (tier - 1) * 0.70
                             + lane * CHOICE_LANE_ANGLE)
                    positions[node["id"]] = _polar(
                        0, 0, angle, self._tier_radius(
                            WEAPON_TIER_RADIUS, tier, WEAPON_EXTENSION_STEP))
                # Подпись ветви стоит за СРЕДНЕЙ точкой финальных узлов:
                # у пары доктрин нет одного «последнего» узла.
                terminals = [n for n in branch["nodes"]
                             if n["tier"] == max_tier]
                tx = sum(positions[n["id"]][0] for n in terminals) / len(terminals)
                ty = sum(positions[n["id"]][1] for n in terminals) / len(terminals)
                dx, dy = tx, ty
                length = math.hypot(dx, dy) or 1.0
                ends.append((tx + dx / length * BRANCH_LABEL_RESERVE,
                             ty + dy / length * BRANCH_LABEL_RESERVE))
            self.weapon_positions[key] = positions
            self.weapon_branch_ends[key] = ends

    @staticmethod
    def _tier_radius(radii, tier, step=62.0):
        if tier <= len(radii):
            return radii[tier - 1]
        return radii[-1] + (tier - len(radii)) * step

    def _place_zones(self):
        for zone in ZONE_ORDER:
            positions = (self.player_positions if zone == "player"
                         else self.weapon_positions[zone])
            radius = PLAYER_NODE_RADIUS if zone == "player" else NODE_RADIUS
            extent = max((math.hypot(x, y) + radius for x, y in positions.values()),
                         default=0.0)
            branch_ends = (self.player_branch_ends if zone == "player"
                           else self.weapon_branch_ends[zone])
            extent = max(extent, max(
                (math.hypot(x, y) + BRANCH_LABEL_PAD
                 for x, y in branch_ends), default=0.0))
            extent = max(extent, ROOT_RADIUS + 180)
            self.zone_extents[zone] = extent

        max_extent = max(self.zone_extents.values(), default=0.0)
        spacing = math.ceil(2 * max_extent + ZONE_GAP)
        melee_columns = min(ZONE_COLUMNS, max(1, len(MELEE_ORDER)))
        ranged_columns = min(ZONE_COLUMNS, max(1, len(RANGED_ORDER)))
        melee_rows = math.ceil(len(MELEE_ORDER) / max(1, melee_columns))
        ranged_rows = math.ceil(len(RANGED_ORDER) / max(1, ranged_columns))
        row_count = max(1, melee_rows, ranged_rows)
        self.board_w = math.ceil(
            (melee_columns + 1 + ranged_columns - 1) * spacing
            + 2 * (max_extent + BOARD_MARGIN))
        self.board_h = math.ceil(
            max((row_count - 1) * spacing + 2 * (max_extent + BOARD_MARGIN),
                2 * (max_extent + BOARD_MARGIN)))

        center_y = self.board_h / 2
        first_x = max_extent + BOARD_MARGIN
        melee_x = [first_x + column * spacing
                   for column in range(melee_columns)]
        player_x = first_x + melee_columns * spacing
        ranged_x = [player_x + (column + 1) * spacing
                    for column in range(ranged_columns)]
        self.zone_centers["player"] = (player_x, center_y)
        self._place_group(MELEE_ORDER, melee_x, melee_rows, center_y, spacing)
        self._place_group(RANGED_ORDER, ranged_x, ranged_rows, center_y, spacing)

    def _place_group(self, zones, columns, rows, center_y, spacing):
        for index, zone in enumerate(zones):
            row, column = divmod(index, max(1, len(columns)))
            x = columns[min(column, len(columns) - 1)]
            y = center_y + (row - (rows - 1) / 2) * spacing
            self.zone_centers[zone] = (x, y)

    # ------------------------------------------------------------ ЗАПРОСЫ
    def root(self, zone):
        return self.zone_centers[zone]

    def center(self, zone):
        return self.root(zone)

    def node_pos(self, zone, node_id):
        local = (self.player_positions[node_id] if zone == "player"
                 else self.weapon_positions[zone][node_id])
        center = self.zone_centers[zone]
        return center[0] + local[0], center[1] + local[1]

    def branch_end(self, zone, branch_index):
        local = (self.player_branch_ends[branch_index] if zone == "player"
                 else self.weapon_branch_ends[zone][branch_index])
        center = self.zone_centers[zone]
        return center[0] + local[0], center[1] + local[1]

    def category_center(self, category):
        zones = (MELEE_ORDER if category == "melee" else RANGED_ORDER)
        return (sum(self.zone_centers[zone][0] for zone in zones) / len(zones),
                sum(self.zone_centers[zone][1] for zone in zones) / len(zones))

    @staticmethod
    def node_radius(zone):
        return PLAYER_NODE_RADIUS if zone == "player" else NODE_RADIUS

    @staticmethod
    def branch_color(zone, branch_index):
        if zone == "player":
            return PLAYER_BRANCH_COLORS[branch_index % len(PLAYER_BRANCH_COLORS)]
        base = zone_color(zone)
        shift = ((branch_index * 23) % 45) - 22
        return tuple(max(24, min(255, c + shift)) for c in base)


# ------------------------------------------------------------ МАРШРУТЫ СВЯЗЕЙ
def _segment_circle_distance(a, b, cx, cy):
    """Расстояние от центра окружности до отрезка a-b (не до прямой)."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.000001:
        return math.hypot(cx - ax, cy - ay)
    t = ((cx - ax) * dx + (cy - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(cx - (ax + dx * t), cy - (ay + dy * t))


def segment_clear(a, b, obstacles):
    """True, если отрезок не задевает ни один круг (x, y, radius)."""
    return all(_segment_circle_distance(a, b, x, y) > radius
               for x, y, radius in obstacles)


def _simplify_path(points, obstacles):
    """Убирает лишние точки, сохраняя видимость и не задевая круги."""
    if len(points) <= 2:
        return list(points)
    result = [points[0]]
    index = 0
    while index < len(points) - 1:
        target = len(points) - 1
        while target > index + 1 and not segment_clear(
                points[index], points[target], obstacles):
            target -= 1
        result.append(points[target])
        index = target
    return result


def route_around_circles(start, goal, obstacles, step=LINK_GRID_STEP,
                         max_expansions=150000):
    """
    Кратчайший путь по сетке в обход узлов.

    Нужен не «красивым», а предсказуемым: гибридный узел может требовать
    навык из соседней ветви, и линия не должна проходить сквозь чужие
    карточки. Если путь не нужен (прямая свободна), возвращаются две точки.
    Если путь не найден, возвращается прямая — вызывающий код всё равно
    нарисует связь, но не потеряет зависимость.
    """
    obstacles = tuple((float(x), float(y), float(r))
                      for x, y, r in obstacles if r > 0.0)
    if segment_clear(start, goal, obstacles):
        return [start, goal]

    xs = [start[0], goal[0]]
    ys = [start[1], goal[1]]
    for x, y, radius in obstacles:
        xs.extend((x - radius, x + radius))
        ys.extend((y - radius, y + radius))
    pad = step * 2.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    cols = max(2, int(math.ceil((max_x - min_x) / step)) + 1)
    rows = max(2, int(math.ceil((max_y - min_y) / step)) + 1)
    # Защита от гигантской сетки, если в будущем появится очень широкая
    # ветвь: шаг увеличивается, а клиренс сохраняется.
    while cols * rows > 90000:
        step *= 1.35
        cols = max(2, int(math.ceil((max_x - min_x) / step)) + 1)
        rows = max(2, int(math.ceil((max_y - min_y) / step)) + 1)

    def cell_xy(index):
        return index % cols, index // cols

    def coord(index):
        cx, cy = cell_xy(index)
        return min_x + cx * step, min_y + cy * step

    def cell_of(point):
        cx = int(round((point[0] - min_x) / step))
        cy = int(round((point[1] - min_y) / step))
        return max(0, min(cols - 1, cx)), max(0, min(rows - 1, cy))

    blocked = bytearray(cols * rows)
    clearance = step * 0.55
    for x, y, radius in obstacles:
        radius += clearance
        left = max(0, int((x - radius - min_x) / step) - 1)
        right = min(cols - 1, int((x + radius - min_x) / step) + 1)
        top = max(0, int((y - radius - min_y) / step) - 1)
        bottom = min(rows - 1, int((y + radius - min_y) / step) + 1)
        for gy in range(top, bottom + 1):
            for gx in range(left, right + 1):
                px = min_x + gx * step
                py = min_y + gy * step
                if (px - x) ** 2 + (py - y) ** 2 <= radius * radius:
                    blocked[gy * cols + gx] = 1

    start_cell = cell_of(start)
    goal_cell = cell_of(goal)
    start_index = start_cell[1] * cols + start_cell[0]
    goal_index = goal_cell[1] * cols + goal_cell[0]
    blocked[start_index] = 0
    blocked[goal_index] = 0

    def heuristic(index):
        gx, gy = cell_xy(index)
        return math.hypot(gx - goal_cell[0], gy - goal_cell[1])

    frontier = [(heuristic(start_index), 0.0, start_index)]
    distance = {start_index: 0.0}
    parent = {}
    found = False
    expansions = 0
    while frontier:
        _, cost, current = heapq.heappop(frontier)
        if current == goal_index:
            found = True
            break
        if cost > distance.get(current, float("inf")):
            continue
        expansions += 1
        if expansions > max_expansions:
            break
        cx, cy = cell_xy(current)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < cols and 0 <= ny < rows):
                continue
            nxt = ny * cols + nx
            if blocked[nxt]:
                continue
            if dx and dy:
                # Не срезать угол между двумя занятыми клетками.
                if blocked[cy * cols + nx] or blocked[ny * cols + cx]:
                    continue
                move = 1.41421356237
            else:
                move = 1.0
            new_cost = cost + move
            if new_cost >= distance.get(nxt, float("inf")):
                continue
            distance[nxt] = new_cost
            parent[nxt] = current
            heapq.heappush(frontier,
                           (new_cost + heuristic(nxt), new_cost, nxt))

    if not found:
        # Резервный обход по внешнему периметру: даже если сетка не нашла
        # щель, связь не должна проходить сквозь узлы.
        for corner in ((min_x, min_y), (max_x, min_y),
                       (min_x, max_y), (max_x, max_y)):
            if (segment_clear(start, corner, obstacles)
                    and segment_clear(corner, goal, obstacles)):
                return _simplify_path([start, corner, goal], obstacles)
        return [start, goal]

    cells = []
    current = goal_index
    while current != start_index:
        cells.append(current)
        current = parent.get(current)
        if current is None:
            return [start, goal]
    cells.append(start_index)
    cells.reverse()
    points = [start]
    for cell in cells[1:-1]:
        points.append(coord(cell))
    points.append(goal)
    return _simplify_path(points, obstacles)
