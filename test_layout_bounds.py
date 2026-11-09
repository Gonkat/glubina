"""
Геометрические проверки единой доски навыков.

Запуск: python test_layout_bounds.py

Тест не открывает окно: SDL переводится в dummy-режим до импорта pygame.
Проверяются не только центры узлов, но и реальные прямоугольники подписей
ветвей, маршруты связей и независимость зон.
"""
import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import skill_board
import skill_tree
from game import Game
from settings import STATE_PLAYING
from skill_board import BoardLayout
from skill_data import PLAYER_TREE, SKILL_TREES
from skill_tree_ui import ZONE_ORDER


def node_screen_rect(ui, zone, node_id):
    wx, wy = ui.layout.node_pos(zone, node_id)
    sx, sy = ui.screen(wx, wy)
    radius = max(5, int(BoardLayout.node_radius(zone) * ui.zoom))
    return pygame.Rect(int(sx - radius), int(sy - radius),
                       radius * 2, radius * 2)


def assert_labels_do_not_overlap(ui, zone, rows):
    labels = ui._branch_label_layout(zone, rows)
    branches = (PLAYER_TREE["branches"] if zone == "player"
                else SKILL_TREES[zone]["branches"])
    assert len(labels) == len(branches), (
        f"{zone}: не все подписи ветвей поместились: "
        f"{len(labels)}/{len(branches)}")
    rects = []
    for item in labels:
        rect = item["rect"]
        assert ui.VIEW.contains(rect), f"{zone}: подпись вылезла за экран: {rect}"
        for row in rows:
            node_rect = node_screen_rect(ui, zone, row["node"]["id"])
            assert not rect.colliderect(node_rect), (
                f"{zone}: подпись {item['branch']['name']} легла на "
                f"{row['node']['id']}")
        for other in rects:
            assert not rect.colliderect(other), (
                f"{zone}: подписи {item['branch']['name']} и "
                f"{other} перекрываются")
        rects.append(rect)


def assert_routes_clear(ui, zone, rows):
    by_id = {row["node"]["id"]: row for row in rows}
    branches = (PLAYER_TREE["branches"] if zone == "player"
                else SKILL_TREES[zone]["branches"])
    root = ui.layout.root(zone)
    labels = ui._branch_label_layout(zone, rows)
    label_rects = [item["rect"] for item in labels]
    for branch in branches:
        for node in branch["nodes"]:
            target = ui.layout.node_pos(zone, node["id"])
            requires = skill_tree.prerequisites(branch, node)
            sources = requires if requires else (None,)
            for source_id in sources:
                if source_id is None:
                    start = root
                else:
                    if source_id not in by_id:
                        continue
                    start = ui.layout.node_pos(zone, source_id)
                route = ui._link_route(zone, source_id, node["id"],
                                       start, target, rows)
                assert route, f"{zone}: пустой маршрут {source_id}->{node['id']}"
                for first, second in zip(route, route[1:]):
                    for row in rows:
                        other = row["node"]["id"]
                        if other in (source_id, node["id"]):
                            continue
                        nx, ny = ui.layout.node_pos(zone, other)
                        clearance = skill_board._segment_circle_distance(
                            first, second, nx, ny)
                        assert clearance > BoardLayout.node_radius(zone) - 0.5, (
                            f"{zone}: связь {source_id}->{node['id']} "
                            f"проходит сквозь {other} ({clearance:.1f})")
                    if source_id is not None:
                        root_clearance = skill_board._segment_circle_distance(
                            first, second, *root)
                        assert root_clearance > skill_board.ROOT_RADIUS - 0.5, (
                            f"{zone}: связь {source_id}->{node['id']} "
                            f"проходит сквозь корень ({root_clearance:.1f})")
                    screen_a = ui.screen(*first)
                    screen_b = ui.screen(*second)
                    for rect in label_rects:
                        assert not rect.clipline(screen_a, screen_b), (
                            f"{zone}: связь {source_id}->{node['id']} "
                            f"пересекает подпись ветви")


def test_all_zones_are_clear():
    pygame.init()
    game = Game()
    game.reset()
    game.state = STATE_PLAYING
    ui = game.skill_ui

    for zone in ZONE_ORDER:
        ui._focus_zone(zone, game, select=False)
        rows = [row for row in ui.rows(game) if row["zone"] == zone]
        assert rows, zone
        assert_labels_do_not_overlap(ui, zone, rows)
        assert_routes_clear(ui, zone, rows)
        # отдельная проверка кругов: подписи не должны «спасать» наложение
        for index, first in enumerate(rows):
            x1, y1 = ui.layout.node_pos(zone, first["node"]["id"])
            for second in rows[index + 1:]:
                x2, y2 = ui.layout.node_pos(zone, second["node"]["id"])
                limit = (BoardLayout.node_radius(zone) * 2
                         + skill_board.LINK_NODE_CLEARANCE)
                assert math.hypot(x1 - x2, y1 - y2) >= limit, (
                    f"{zone}: узлы {first['node']['id']} и "
                    f"{second['node']['id']} слиплись")


def test_zone_areas_do_not_overlap():
    layout = BoardLayout()
    assert layout.board_w > 0 and layout.board_h > 0
    zones = list(ZONE_ORDER)
    for index, first in enumerate(zones):
        x1, y1 = layout.center(first)
        r1 = layout.zone_extents[first]
        for second in zones[index + 1:]:
            x2, y2 = layout.center(second)
            r2 = layout.zone_extents[second]
            distance = math.hypot(x1 - x2, y1 - y2)
            assert distance > r1 + r2, (
                f"зоны {first} и {second} перекрываются: "
                f"{distance:.1f} <= {r1 + r2:.1f}")
    # Раскладка детерминирована: повторная сборка даёт те же точки.
    again = BoardLayout()
    assert again.zone_extents == layout.zone_extents
    assert again.zone_centers == layout.zone_centers
    assert again.weapon_positions == layout.weapon_positions


def test_branch_geometry_scales_to_new_branch_counts():
    # 4 ветви — ровные квадранты; 5+ — равномерный круг без старого
    # закручивания, из-за которого подписи сближались.
    for count in (4, 5, 6, 8):
        geometry = [skill_board._branch_geometry(index, count)
                    for index in range(count)]
        assert all(bend == 0.0 for _, bend in geometry)
        angles = [angle for angle, _ in geometry]
        assert len(set(round(angle, 6) for angle in angles)) == count
        step = 360.0 / count
        for first, second in zip(angles, angles[1:]):
            assert math.isclose(second - first, step)
        assert math.isclose(angles[-1] + step - angles[0], 360.0)
    assert skill_board._branch_geometry(0, 4)[0] == -90.0


def test_router_goes_around_a_wall():
    # Сплошная стена из кругов с одним проходом: маршрут обязан найти его,
    # а не пройти напрямую и не раздуться в петлю.
    obstacles = []
    for y in range(-120, 141, 30):
        obstacles.append((0.0, float(y), 16.0))
    start, goal = (-220.0, 0.0), (220.0, 0.0)
    route = skill_board.route_around_circles(start, goal, obstacles)
    assert route[0] == start and route[-1] == goal
    assert len(route) > 2, "маршрут не обошёл стену"
    max_x = max(abs(point[0]) for point in route)
    assert max_x < 320.0, f"маршрут раздулся: {max_x}"
    for first, second in zip(route, route[1:]):
        for x, y, radius in obstacles:
            distance = skill_board._segment_circle_distance(
                first, second, x, y)
            assert distance > radius - 0.5, (
                f"синтетический маршрут задел круг ({x}, {y})")


if __name__ == "__main__":
    test_all_zones_are_clear()
    test_zone_areas_do_not_overlap()
    test_branch_geometry_scales_to_new_branch_counts()
    test_router_goes_around_a_wall()
    print("layout bounds: ok")
