"""
Поиск пути по тайлам мира (A*, M9).

Раньше враг шёл к игроку по ПРЯМОЙ и впирался в стену, если та стояла
между ними. Теперь у врага есть разведка и план пути:

  * есть прямая видимость до игрока (line of sight) — идём напрямую;
  * нет — строим путь по тайлам и идём по путевым точкам.

Как устроен поиск:
  * сетка 8-связная (по горизонтали/вертикали и по диагонали);
  * g — реальная цена пути от старта (диагональ дороже: 1.414 против 1);
  * h — «восьмиугольное» расстояние до цели: он НЕ переоценивает
    стоимость (адмиссивный), поэтому A* найдёт кратчайший путь;
  * диагональю нельзя «резать угол» — обе соседние клетки обязаны быть
    полом, иначе враг застрянет в вершине стены;
  * БЮДЖЕТ УЗЛОВ (ENEMY_PATH_MAX_NODES) — даже заведомо тупиковый поиск
    заканчивается за ограниченное время и не подвешивает кадр;
  * поиск учитывает РАДИУС агента: тайл свободен, только если в его
    центре помещается круг врага — путь никогда не ведёт в щель уже
    не проходимую физически;
  * после поиска путь СГЛАЖИВАЕТСЯ: подряд идущие точки, между которыми
    есть прямая видимость, схлопываются в одну — враг идёт по дугам
    «на глаз», а не топчется по каждому тайлу.
"""
import heapq
import math

from settings import ENEMY_PATH_MAX_NODES, TILE

SQRT2 = math.sqrt(2.0)

# (dx, dy, цена) — 8 соседей; диагональ дороже, чтобы не «срезать» углы
_NEIGHBORS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2),
)


def tile_of(x, y):
    """Мировые пиксели -> координаты тайла."""
    return math.floor(x / TILE), math.floor(y / TILE)


def tile_center(tx, ty):
    """Центр тайла в мировых пикселях."""
    return tx * TILE + TILE / 2, ty * TILE + TILE / 2


def has_line_of_sight(world, x0, y0, x1, y1):
    """
    Правда ли, что между точками нет стен.
    Проверяем сэмплированием каждые ~10 px: для игровых дистанций
    этого достаточно, а стоит дёшево.
    """
    dist = math.hypot(x1 - x0, y1 - y0)
    steps = max(1, int(dist / 10))
    for i in range(steps + 1):
        t = i / steps
        if world.is_solid_at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t):
            return False
    return True


def _octile(a, b):
    """Эвристика для 8-связной сетки: |dx|+|dy| поправленный на диагональ."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return dx + dy + (SQRT2 - 2.0) * min(dx, dy)


def _circle_fits(solid, tx, ty, radius):
    """
    Помещается ли круг radius в центре тайла (tx, ty).
    Та же математика, что у World.is_valid_position, но без pygame.Rect
    и с внешним кэшем solid — путь считается тысячи раз за кадр.
    """
    cx, cy = tile_center(tx, ty)
    reach = math.ceil(radius / TILE)
    r2 = radius * radius
    for y in range(ty - reach, ty + reach + 1):
        for x in range(tx - reach, tx + reach + 1):
            if not solid(x, y):
                continue
            rx, ry = x * TILE, y * TILE
            closest_x = min(max(cx, rx), rx + TILE)
            closest_y = min(max(cy, ry), ry + TILE)
            if (cx - closest_x) ** 2 + (cy - closest_y) ** 2 < r2:
                return False
    return True


def find_path(world, start_xy, goal_xy, radius=0, max_nodes=None):
    """
    A* от start_xy к goal_xy (мировые пиксели).

    radius — половина ширины идущего агента (px). Тайл считается свободным
    для него, только если в ЦЕНТРЕ тайла помещается его круг: так враг
    не строит путь сквозь 32-пиксельные щели, в которые он физически
    не пролезет (resolve_circle просто вытолкнул бы его обратно).

    Возвращает:
      * []        — старт и цель в одном тайле, идти некуда;
      * None      — пути нет (бюджет исчерпан или цель недостижима);
      * [p1, p2…] — список путевых точек в пикселях (без стартовой),
                    между соседними точками есть прямая видимость.
    """
    if max_nodes is None:
        max_nodes = ENEMY_PATH_MAX_NODES
    start = tile_of(*start_xy)
    goal = tile_of(*goal_xy)
    if start == goal:
        return []
    if world.is_solid_tile(*goal):
        return None                    # цель оказалась в стене — не идём

    # Локальные кэши поиска: один A* много раз натыкается на одни и те же
    # тайлы (окна проверок перекрываются) — без них худший кадр с толпой
    # доходил до 250 ms. Кэш живёт только внутри одного вызова:
    # мир может измениться (взрыв, пули) — между поисками мы его не держим.
    solid_cache = {}

    def solid(tx, ty):
        key = (tx, ty)
        ok = solid_cache.get(key)
        if ok is None:
            ok = world.is_solid_tile(tx, ty)
            solid_cache[key] = ok
        return ok

    free_cache = {}

    def free(tx, ty):
        # старт не проверяем: агент там уже стоит, его круг там помещается
        key = (tx, ty)
        if key in free_cache:
            return free_cache[key]
        if radius <= 0:
            ok = not solid(tx, ty)
        else:
            ok = _circle_fits(solid, tx, ty, radius)
        free_cache[key] = ok
        return ok

    open_heap = [(_octile(start, goal), 0, start)]   # (f, счётчик, тайл)
    counter = 0
    g_cost = {start: 0.0}
    came_from = {}
    closed = set()
    found = False
    expanded = 0

    while open_heap:
        _, _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        if cur == goal:
            found = True
            break
        expanded += 1
        if expanded > max_nodes:
            break                       # бюджет исчерпан — выходим вовремя
        cx, cy = cur
        for dx, dy, step_cost in _NEIGHBORS:
            nxt = (cx + dx, cy + dy)
            if nxt in closed or not free(*nxt):
                continue
            if dx and dy:
# диагональ только если ОБА ортогональных соседа свободны
                if (solid(cx + dx, cy)
                        or solid(cx, cy + dy)):
                    continue
            new_g = g_cost[cur] + step_cost
            if new_g >= g_cost.get(nxt, math.inf):
                continue
            g_cost[nxt] = new_g
            came_from[nxt] = cur
            counter += 1
            heapq.heappush(open_heap, (new_g + _octile(nxt, goal), counter, nxt))

    if not found:
        return None

    # восстановление пути: от цели назад к старту
    tiles = [goal]
    while tiles[-1] != start:
        tiles.append(came_from[tiles[-1]])
    tiles.reverse()

    return _smooth(world, tiles, goal_xy)


def _smooth(world, tiles, goal_xy):
    """
    Отсечка: из опорной точки берём ДАЛЬНЕЙШУЮ точку пути, до которой
    ещё видно — и идём к ней напрямую. Путь укорачивается в разы,
    враг не «ступает» по тайлам, а режет по дуге.
    """
    points = []
    anchor = 0
    last = len(tiles) - 1
    while anchor < last:
        ax, ay = tile_center(*tiles[anchor])
        best = anchor + 1
        b = anchor + 1
        while b <= last:
            bx, by = tile_center(*tiles[b])
            if not has_line_of_sight(world, ax, ay, bx, by):
                break
            best = b
            b += 1
        points.append(tile_center(*tiles[best]))
        anchor = best
    if points:
        points[-1] = goal_xy            # последняя точка — точная позиция цели
    return points
