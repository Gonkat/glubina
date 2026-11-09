"""
Проверки расширения древ: 5–6 ветвей, 20 узлов в каждой, связи ветвей
и реальные мастерские эффекты.

Запуск: python test_skill_expansion.py
Тест headless: SDL переводится в dummy-режим до импорта pygame.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import skill_tree
from player import Player
from skill_data import SKILL_TREES
from skill_expansion import MAX_BRANCH_NODES, NEW_BRANCHES

FIREARMS = ("pistol", "shotgun", "sniper", "cannon",
            "disc", "arc", "cutter")


def fresh(weapon_key):
    player = Player(0, 0)
    if weapon_key in FIREARMS:
        player.switch_firearm(weapon_key)
        weapon = player.firearm
    else:
        player.switch_melee(weapon_key)
        weapon = player.melee
    return player, weapon


def buy_accessible(weapon_key, branch):
    """Покупает всю ветвь, разрешая зависимости и альтернативы."""
    player, weapon = fresh(weapon_key)
    weapon.main_branch = branch["key"]
    weapon.nodes.clear()
    weapon.node_order.clear()
    weapon.mods.clear()
    tree = SKILL_TREES[weapon_key]
    by_id = {node["id"]: (owner, node)
             for owner in tree["branches"] for node in owner["nodes"]}

    def ensure(node, owner):
        if node["id"] in weapon.nodes:
            return True
        state = skill_tree.node_state(weapon, owner, node, player)
        if state == "excluded":
            return False
        if state == "prev":
            for requirement in skill_tree.prerequisites(owner, node):
                if requirement not in by_id:
                    return False
                req_owner, req_node = by_id[requirement]
                if not ensure(req_node, req_owner):
                    return False
            state = skill_tree.node_state(weapon, owner, node, player)
        if state in ("training", "tokens"):
            player.add_weapon_token(weapon_key, 20)
            training = skill_tree.training_requirement(node)
            if training is not None:
                player.add_weapon_token(training[0], max(1, training[1]))
        if state not in ("ok", "training", "tokens"):
            return False
        skill_tree.buy(weapon, owner, node, 0, player)
        return True

    for node in branch["nodes"]:
        ensure(node, branch)
    return player, weapon


def test_shape_and_links():
    total = 0
    for weapon_key, tree in SKILL_TREES.items():
        branches = tree["branches"]
        assert 5 <= len(branches) <= 7, (weapon_key, len(branches))
        keys = [branch["key"] for branch in branches]
        assert len(keys) == len(set(keys)), weapon_key
        ids = [node["id"] for branch in branches for node in branch["nodes"]]
        assert len(ids) == len(set(ids)), weapon_key
        for branch in branches:
            assert len(branch["nodes"]) == MAX_BRANCH_NODES, (
                weapon_key, branch["key"], len(branch["nodes"]))
        known = set(ids)
        for branch in branches:
            for node in branch["nodes"]:
                for requirement in node.get("requires", ()):
                    assert requirement in known, (weapon_key, node["id"], requirement)
        # У каждой обычной ветви две межветвевые связи; независимая
        # «Пыльный след» намеренно остаётся в стороне.
        for branch in branches:
            if branch.get("independent"):
                continue
            hybrids = [node for node in branch["nodes"] if node.get("hybrid")]
            assert len(hybrids) >= 2, (weapon_key, branch["key"])
        total += len(ids)
    # 10 старых древ + 3 новые школы (диск, дуга, резак) = 13 школ
    # по 5–6 ветвей и 1320 узлов.
    assert total == 1320
    print("shape and cross links: ok")


def test_cost_balance():
    """Новая ветвь не должна быть в разы дороже старой 20-узловой.

    Ориентир — средняя полная цена уже существующих ветвей оружия.
    Допускаем 0.65–1.45 от неё: новая ветвь может быть чуть дороже
    за счёт уникальной механики, но не превращается в витрину.
    """
    for weapon_key, specs in NEW_BRANCHES.items():
        tree = SKILL_TREES[weapon_key]
        new_keys = {spec["key"] for spec in specs}
        old_totals = [sum(node["cost"] for node in branch["nodes"])
                      for branch in tree["branches"]
                      if branch["key"] not in new_keys]
        average = sum(old_totals) / len(old_totals)
        for spec in specs:
            branch = next(b for b in tree["branches"] if b["key"] == spec["key"])
            costs = [node["cost"] for node in branch["nodes"]]
            total = sum(costs)
            assert costs == sorted(costs), (weapon_key, spec["key"], costs)
            assert costs[-1] <= 700, (weapon_key, spec["key"], costs[-1])
            assert total <= 10000, (weapon_key, spec["key"], total)
            assert 0.65 <= total / average <= 1.45, (
                weapon_key, spec["key"], total, average)
    print("cost balance: ok")


def test_new_branch_purchases_and_effects():
    for weapon_key, specs in NEW_BRANCHES.items():
        tree = SKILL_TREES[weapon_key]
        for spec in specs:
            branch = next(b for b in tree["branches"] if b["key"] == spec["key"])
            player, weapon = buy_accessible(weapon_key, branch)
            assert len(branch["nodes"]) == 20
            assert all(node["id"] in weapon.nodes for node in branch["nodes"])
            assert weapon.mods.get("damage_mul", 0.0) > 0.0
            if weapon_key in FIREARMS:
                weapon.cooldown = 0.0
                if weapon_key == "cannon":
                    weapon.last_charge_ratio = 1.0
                shot = weapon.resolve_shot(player)
                assert shot["damage"] > 0.0
            else:
                # MeleeWeapon and its attack share the same mods dict.
                assert weapon.attack.mods is weapon.mods
    print("new branch purchases: ok")


def test_damage_mul_reaches_both_combat_paths():
    # Firearm path: the universal mastery multiplier is applied before
    # charge/mode multipliers.
    player, weapon = fresh("pistol")
    weapon.mods["damage_mul"] = 0.0
    base = weapon.resolve_shot(player)["damage"]
    weapon.mods["damage_mul"] = 0.25
    boosted = weapon.resolve_shot(player)["damage"]
    assert abs(boosted / base - 1.25) < 1e-9

    # Melee path: the same mod is read by Attack.hit.
    player, weapon = fresh("knife")
    weapon.attack.mods = {"damage_mul": 0.25}
    enemy = type("Enemy", (), {
        "alive": True, "hp": 100.0, "max_hp": 100.0,
        "windup_timer": 0.0, "bleed_remaining": 0.0,
        "x": 10.0, "y": 0.0,
    })()
    hits = []

    class Game:
        def damage_enemy(self, target, amount, show_number=True, **kwargs):
            hits.append(amount)

        def spawn_dust(self, *args, **kwargs):
            pass

    # A direct hit with the knife's normal attack goes through the same
    # modifier; damage must exceed the unmodified spec damage.
    weapon.attack.hit(player, Game(), enemy, weapon.spec["damage"], (1.0, 0.0),
                      weapon.spec.get("knockback", 0.0))
    assert hits and hits[0] > weapon.spec["damage"]
    print("damage mastery paths: ok")


def main():
    pygame.init()
    test_shape_and_links()
    test_cost_balance()
    test_new_branch_purchases_and_effects()
    test_damage_mul_reaches_both_combat_paths()
    print("ALL SKILL EXPANSION TESTS PASSED")


if __name__ == "__main__":
    main()
