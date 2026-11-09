"""
Проверки ветви «Арсенал» пистолета (M13).

Запуск:  python test_pistol_arsenal.py
Тест не требует окна: SDL переводится в dummy-режим до импорта pygame.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import skill_tree
from skill_data import SKILL_TREES
from skill_board import BoardLayout
from weapon_data import PISTOL_MODE_NODES, PISTOL_MODES


def pistol_tree():
    return {branch["key"]: branch
            for branch in SKILL_TREES["pistol"]["branches"]}


def node_by_id(branch, node_id):
    return next(node for node in branch["nodes"] if node["id"] == node_id)


def fresh_player():
    pygame.init()
    from player import Player
    player = Player(0, 0)
    return player, player.firearm


def buy(player, weapon, branch, node, price=None):
    skill_tree.buy(weapon, branch, node,
                   node["cost"] if price is None else price, player)


def test_tree_shape():
    branches = pistol_tree()
    assert len(branches) == 6, "у пистолета должны быть Арсенал, Плазма и Дуэлянт"
    for branch in branches.values():
        assert len(branch["nodes"]) == 20, branch["key"]
    # старые id capstone не переименованы
    for node_id in ("pistol_s5a", "pistol_m6a", "pistol_e6b",
                    "pistol_p1", "pistol_p6b"):
        assert any(node["id"] == node_id
                   for branch in branches.values() for node in branch["nodes"])
    layout = BoardLayout()
    assert len(layout.weapon_branch_ends["pistol"]) == 6
    for branch in branches.values():
        for node in branch["nodes"]:
            layout.node_pos("pistol", node["id"])
    print("tree shape: ok")


def test_training_gate_and_token():
    player, weapon = fresh_player()
    branches = pistol_tree()
    arsenal = branches["arsenal"]
    x1 = node_by_id(arsenal, "pistol_x1")
    scatter = node_by_id(arsenal, "pistol_x_scatter")

    assert skill_tree.node_state(weapon, arsenal, x1, player) == "ok"
    buy(player, weapon, arsenal, x1)
    assert weapon.main_branch is None, "устав не должен фиксировать специализацию"
    assert skill_tree.node_state(weapon, arsenal, scatter, player) == "training"

    try:
        skill_tree.buy(weapon, arsenal, scatter, scatter["cost"], player)
    except ValueError:
        pass
    else:
        raise AssertionError("насадок куплен без подготовки")

    player.add_weapon_token("shotgun", 1)
    assert skill_tree.can_cover_training(player, scatter)
    buy(player, weapon, arsenal, scatter)
    assert player.weapon_tokens["shotgun"] == 0
    assert player.weapon_training["shotgun"] == 1
    assert weapon.main_branch == "arsenal"
    assert weapon.available_modes == ("standard", "scatter")
    print("training gate + token: ok")


def test_modes_and_rounds():
    player, weapon = fresh_player()
    branches = pistol_tree()
    arsenal = branches["arsenal"]
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x1"))
    for node_id, source in (("pistol_x_scatter", "shotgun"),
                            ("pistol_x_lance", "sniper"),
                            ("pistol_x_hammer", "hammer"),
                            ("pistol_x_bleed", "knife")):
        player.add_weapon_token(source, 1)
        buy(player, weapon, arsenal, node_by_id(arsenal, node_id))

    assert weapon.available_modes == ("standard", "scatter", "lance",
                                      "hammer", "bleed")
    # каждый режим действительно меняет выстрел и цену патронов
    weapon.mode = "scatter"
    weapon.switch_timer = 0.0
    pellets, spread = weapon.shot_params(player)
    assert pellets == 3 and spread == 16.0
    assert weapon.rounds_per_shot == 2
    assert abs(weapon.resolve_shot(player)["damage"] - 25 * 0.38) < 1e-6

    weapon.mode = "lance"
    shot = weapon.resolve_shot(player)
    assert shot["pierce"] >= 2 and shot["wall_pen"] == 1
    assert weapon.rounds_per_shot == 2

    weapon.mode = "hammer"
    shot = weapon.resolve_shot(player)
    assert shot["explode"] >= 45 and shot["knockback"] >= 220
    assert weapon.rounds_per_shot == 3

    weapon.mode = "bleed"
    shot = weapon.resolve_shot(player)
    assert shot["bleed"] >= 0.45
    assert weapon.rounds_per_shot == 1

    # смена режима тратит время, но не патроны
    weapon.mode = "standard"
    before = weapon.loaded
    assert weapon.cycle_mode() == "scatter"
    assert weapon.switch_timer > 0
    assert weapon.loaded == before
    print("modes and rounds: ok")


def test_cross_branch_specializations():
    player, weapon = fresh_player()
    branches = pistol_tree()
    arsenal, small, economist = (branches["arsenal"], branches["small"],
                                 branches["economist"])
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x1"))
    player.add_weapon_token("shotgun", 2)
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x_scatter"))
    buy(player, weapon, small, node_by_id(small, "pistol_m1"))
    buy(player, weapon, small, node_by_id(small, "pistol_m2"))
    buy(player, weapon, economist, node_by_id(economist, "pistol_e1"))
    buy(player, weapon, economist, node_by_id(economist, "pistol_e2"))

    scatter3 = node_by_id(arsenal, "pistol_x_scatter3")
    assert scatter3["hybrid"] is True
    assert skill_tree.node_price(weapon, arsenal, scatter3) == round(
        380 * 1.15)
    buy(player, weapon, arsenal, scatter3)
    weapon.mode = "scatter"
    weapon.switch_timer = 0.0
    assert weapon.shot_params(player)[0] == 5
    assert weapon.mods["scatter_pellets_add"] == 1

    hammer3 = node_by_id(arsenal, "pistol_x_hammer3")
    player.add_weapon_token("hammer", 2)
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x_hammer"))
    buy(player, weapon, arsenal, hammer3)
    weapon.mode = "hammer"
    shot = weapon.resolve_shot(player)
    assert shot["close_stun"] == 0.35
    # оглушение специализации не протекает в другие режимы
    weapon.mode = "lance"
    weapon.nodes.add("pistol_x_lance")
    assert weapon.resolve_shot(player)["close_stun"] == 0.0
    print("cross-branch specialization: ok")


def test_training_and_tree_survive_weapon_swap():
    player, weapon = fresh_player()
    branches = pistol_tree()
    arsenal = branches["arsenal"]
    player.add_weapon_training("shotgun", 2)
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x1"))
    buy(player, weapon, arsenal, node_by_id(arsenal, "pistol_x_scatter"))
    assert weapon.main_branch == "arsenal"

    from weapons import create_weapon
    replacement = create_weapon("pistol")
    player.restore_weapon_tree(replacement)
    player.equipment.equip("firearm", replacement)
    assert player.weapon_training["shotgun"] == 2
    assert replacement.nodes == {"pistol_x1", "pistol_x_scatter"}
    assert replacement.main_branch == "arsenal"
    assert replacement.available_modes == ("standard", "scatter")
    # подготовка не начисляется повторно при восстановлении
    assert player.weapon_training["pistol"] == 2
    print("training and tree survive swap: ok")


def test_ui_and_shop():
    from game import Game
    from settings import STATE_PLAYING
    from shop_data import generate_shop_inventory
    from shop import Shop

    game = Game()
    game.reset()
    game.state = STATE_PLAYING
    game.money = 5000
    branches = pistol_tree()
    arsenal = branches["arsenal"]
    buy(game.player, game.player.firearm, arsenal,
        node_by_id(arsenal, "pistol_x1"))
    game.skill_ui.open("firearm", game)
    rows = game.skill_ui.rows(game)
    scatter_row = next(row for row in rows
                       if row["node"]["id"] == "pistol_x_scatter")
    assert scatter_row["state"] == "training"

    # жетон покупается в оружейном магазине
    inventory = None
    for _ in range(100):
        candidate = generate_shop_inventory("weapons")
        if any(offer["kind"] == "token" for offer in candidate):
            inventory = candidate
            break
    assert inventory is not None, "оружейный магазин должен уметь продавать жетоны"
    assert any(offer["kind"] == "firearm" and offer["key"] == "pistol"
               for offer in inventory), "пистолет должен возвращаться в магазин"
    offer = next(offer for offer in inventory if offer["kind"] == "token")
    shop = Shop(0, 0, "weapons", inventory, 1.0)
    game.shop_ui.open(shop)
    game.shop_ui.cursor = game.shop_ui._items(game).index(offer)
    game.shop_ui.buy(game)
    assert game.player.weapon_token_count(offer["key"]) == 1
    print("ui and shop token: ok")


def main():
    test_tree_shape()
    test_training_gate_and_token()
    test_modes_and_rounds()
    test_cross_branch_specializations()
    test_training_and_tree_survive_weapon_swap()
    test_ui_and_shop()
    print("ALL PISTOL ARSENAL TESTS PASSED")


if __name__ == "__main__":
    main()
