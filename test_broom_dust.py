"""Focused checks for the broom's independent dust branch and status."""
import math
import os
from types import SimpleNamespace

import pygame

from attacks import MeleeAttack
from status_effects import apply_dust, update_dust
from weapon_data import MELEE


def test_broom_png_is_loaded_and_baseline_dust_works():
    pygame.init()
    from weapons import create_weapon

    image_path = os.path.join(
        os.path.dirname(__file__), "assets", "sprites", "weapons", "shovel.png")
    assert os.path.isfile(image_path)
    broom = create_weapon("shovel")
    assert broom.sprite is not None
    assert broom.sprite.get_size() == (72, 36)

    enemy = SimpleNamespace(
        x=0.0, y=0.0, hp=100.0, max_hp=100.0, alive=True,
        windup_timer=0.0, dust_remaining=0.0, dust_dps=0.0, dust_stacks=0,
        dust_visual_timer=0.0, slow_timer=0.0, slow_factor=1.0,
    )
    dust_spawned = []

    class Game:
        def damage_enemy(self, target, amount, **kwargs):
            target.hp -= amount
            target.alive = target.hp > 0

        def spawn_dust(self, target, amount):
            dust_spawned.append((target, amount))

    attack = MeleeAttack(dict(MELEE["shovel"]))
    attack.hit(SimpleNamespace(move_dir=(0.0, 0.0)), Game(), enemy,
               10.0, (1.0, 0.0), 0.0)
    assert math.isclose(enemy.dust_dps, 0.15)
    assert math.isclose(enemy.slow_factor, 0.9)
    assert dust_spawned == [(enemy, 1)]


def test_broom_branch_is_independent_and_upgrades_handle():
    import skill_tree
    from skill_data import SKILL_TREES
    from skill_board import BoardLayout

    weapon = SimpleNamespace(
        key="shovel", nodes=set(), node_order=[], main_branch=None,
        spec={"reach": 112.0}, mods={}, invested=0,
    )
    branch = next(
        item for item in SKILL_TREES["shovel"]["branches"]
        if item["key"] == "dust"
    )
    assert len(branch["nodes"]) == 20
    layout = BoardLayout()
    assert len(layout.weapon_branch_ends["shovel"]) == 5
    for node in branch["nodes"]:
        layout.node_pos("shovel", node["id"])

    for node in branch["nodes"]:
        assert skill_tree.node_state(weapon, branch, node) == "ok"
        skill_tree.buy(weapon, branch, node, node["cost"])

    assert weapon.main_branch is None
    assert math.isclose(weapon.spec["reach"], 134.4)
    assert weapon.mods["dust_stack_cap_add"] == 2
    assert weapon.mods["dust_damage_add"] >= 0.035
    assert weapon.mods["dust_slow_add"] >= 0.04

    weapon.main_branch = "melee_0"
    weapon.nodes.clear()
    weapon.node_order.clear()
    weapon.mods.clear()
    weapon.spec["reach"] = 112.0
    for node in branch["nodes"]:
        assert skill_tree.node_state(weapon, branch, node) == "ok"
        skill_tree.buy(weapon, branch, node, node["cost"])
    assert weapon.main_branch == "melee_0"
    assert math.isclose(weapon.spec["reach"], 134.4)


def test_dust_stacks_deals_damage_and_spawns_motes():
    enemy = SimpleNamespace(
        alive=True, dust_remaining=0.0, dust_dps=0.0, dust_stacks=0,
        dust_visual_timer=0.0, slow_timer=0.0, slow_factor=1.0,
    )
    damage_events = []
    mote_events = []

    class Game:
        def damage_enemy(self, target, amount, show_number=True):
            damage_events.append((target, amount, show_number))

        def spawn_dust(self, target, amount):
            mote_events.append((target, amount))

    apply_dust(enemy, 2.0, duration=2.6, stack_cap=2, slow=0.22)
    apply_dust(enemy, 3.0, duration=2.6, stack_cap=2, slow=0.22)
    assert enemy.dust_stacks == 2
    assert enemy.dust_dps == 5.0
    assert enemy.slow_factor == 0.78

    update_dust(enemy, 0.5, Game())
    assert damage_events == [(enemy, 2.5, False)]
    assert mote_events == [(enemy, 2)]
    assert enemy.dust_remaining == 2.1


def test_melee_hit_spreads_dust_to_nearby_enemies():
    primary = SimpleNamespace(
        x=0.0, y=0.0, hp=100.0, max_hp=100.0, alive=True,
        windup_timer=0.0, dust_remaining=0.0, dust_dps=0.0, dust_stacks=0,
        dust_visual_timer=0.0, slow_timer=0.0, slow_factor=1.0,
    )
    nearby = SimpleNamespace(
        x=25.0, y=0.0, hp=100.0, max_hp=100.0, alive=True,
        windup_timer=0.0, dust_remaining=0.0, dust_dps=0.0, dust_stacks=0,
        dust_visual_timer=0.0, slow_timer=0.0, slow_factor=1.0,
    )

    class Game:
        def nearby_enemies(self, x, y, radius):
            return [primary, nearby]

        def damage_enemy(self, target, amount, **kwargs):
            target.hp -= amount
            target.alive = target.hp > 0

        def spawn_dust(self, target, amount):
            pass

    owner = SimpleNamespace(move_dir=(0.0, 0.0))
    attack = MeleeAttack({
        "dust_damage": 0.02, "dust_duration": 2.4,
        "dust_stack_cap": 1, "dust_slow": 0.1,
    })
    attack.mods = {
        "dust_damage_add": 0.015, "dust_stack_cap_add": 2,
        "dust_slow_add": 0.04, "dust_radius_add": 40,
    }
    attack.hit(owner, Game(), primary, 10.0, (1.0, 0.0), 0.0)

    assert math.isclose(primary.dust_dps, 0.35)
    assert math.isclose(nearby.dust_dps, 0.35)
    assert math.isclose(nearby.slow_factor, 0.86)


if __name__ == "__main__":
    test_broom_png_is_loaded_and_baseline_dust_works()
    test_broom_branch_is_independent_and_upgrades_handle()
    test_dust_stacks_deals_damage_and_spawns_motes()
    test_melee_hit_spreads_dust_to_nearby_enemies()
    print("broom dust: ok")
