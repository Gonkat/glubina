"""
Проверки позднего мастерства ветвей (M15).

Запуск: python test_skill_progression.py
Тест headless: SDL переводится в dummy-режим до импорта pygame.

Что проверяем:
  * tier 3+ второй ветви открывается только после такой же глубины основной;
  * tier 4+ второй ветви требует жетон школы;
  * жетон родственной школы подходит (подготовка и плата за глубину);
  * плазменный режим пистолета действительно заряжается и масштабирует выстрел;
  * магазин продаёт жетоны всех школ, включая пушку и пистолет;
  * при максимальной подготовке магазин предлагает жетон для второй ветви;
  * удержанный маяк выдаёт жетон школы.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import skill_tree
from player import Player
from shop_data import SHOP_TYPES, TRAINING_TOKEN_PRICES
from skill_data import SKILL_TREES
from weapon_data import TOKEN_KEYS


def branches():
    return {branch["key"]: branch
            for branch in SKILL_TREES["pistol"]["branches"]}


def node(branch, node_id):
    return next(item for item in branch["nodes"] if item["id"] == node_id)


def fresh():
    pygame.init()
    player = Player(0, 0)
    return player, player.firearm


def buy(player, weapon, branch, node_id):
    item = node(branch, node_id)
    skill_tree.buy(weapon, branch, item, item["cost"], player)
    return item


def buy_main_swift_to_4(player, weapon, br):
    """Основная ветвь «Шквал» до tier 4 без лишних покупок."""
    for node_id in ("pistol_s1", "pistol_s2", "pistol_s3"):
        buy(player, weapon, br["swift"], node_id)
    buy(player, weapon, br["economist"], "pistol_e1")
    buy(player, weapon, br["economist"], "pistol_e2")
    buy(player, weapon, br["swift"], "pistol_s4")
    assert skill_tree.main_branch_depth(weapon) == 4


def test_plasma_mode_is_charge_weapon():
    player, weapon = fresh()
    br = branches()
    buy(player, weapon, br["arsenal"], "pistol_x1")

    plasma = node(br["plasma"], "pistol_p1")
    # Подготовку пушки можно закрыть родственным жетоном дробовика.
    assert skill_tree.node_state(weapon, br["plasma"], plasma, player) == "training"
    player.add_weapon_token("shotgun", 1)
    assert skill_tree.can_cover_training(player, plasma)
    buy(player, weapon, br["plasma"], "pistol_p1")

    assert player.weapon_tokens["shotgun"] == 0
    assert player.weapon_training["cannon"] == 1
    assert weapon.main_branch == "plasma"
    assert weapon.available_modes == ("standard", "plasma")

    weapon.mode = "plasma"
    weapon.switch_timer = 0.0
    weapon.cooldown = 0.0
    weapon.loaded = 12
    assert weapon.uses_charge
    assert abs(weapon.charge_time - 0.85) < 1e-9
    assert abs(weapon.min_charge - 0.25) < 1e-9

    assert weapon.begin_charge()
    assert weapon.advance_charge(1.0, player) == "full"
    assert weapon.charge_ratio == 1.0
    assert weapon.release_charge(player) == "fire"
    shot = weapon.resolve_shot(player)
    assert abs(shot["charge"] - 1.0) < 1e-9
    assert shot["style"] == "plasma"
    assert shot["color"] == (112, 232, 255)
    assert shot["radius"] > weapon.spec["bullet_radius"]
    assert shot["explode"] >= 48

    # Полный заряд действительно сильнее недозаряда.
    weapon.mode = "plasma"
    weapon.last_charge_ratio = 0.5
    partial = weapon.resolve_shot(player)
    assert partial["damage"] < shot["damage"]
    assert partial["radius"] < shot["radius"]

    # Смена режима во время заряда — безопасная отмена, а не выстрел.
    weapon.is_charging = True
    weapon.charge = 0.4
    assert weapon.cycle_mode() == "standard"
    assert not weapon.is_charging and weapon.charge == 0.0

    # Ветвь до tier 6 действительно усиливает полный взрыв. Основная
    # ветвь здесь — плазма, поэтому жетонная плата не требуется.
    player.add_weapon_training("cannon", 1)
    buy(player, weapon, br["small"], "pistol_m1")
    buy(player, weapon, br["small"], "pistol_m2")
    for node_id in ("pistol_p2", "pistol_p3", "pistol_p4",
                    "pistol_p5a", "pistol_p6a"):
        buy(player, weapon, br["plasma"], node_id)
    weapon.mode = "plasma"
    weapon.last_charge_ratio = 1.0
    full = weapon.resolve_shot(player)
    assert full["explode"] >= 100.0
    assert full["blast_stun"] >= 0.8
    assert full["explosion_slow"] >= 2.5
    print("plasma charge mode: ok")


def test_second_branch_opens_after_main_depth():
    player, weapon = fresh()
    br = branches()
    for node_id in ("pistol_s1", "pistol_s2", "pistol_s3"):
        buy(player, weapon, br["swift"], node_id)
    assert skill_tree.main_branch_depth(weapon) == 3

    buy(player, weapon, br["small"], "pistol_m1")
    buy(player, weapon, br["small"], "pistol_m2")
    # tier 3 второй ветви уже открыт глубиной основной; жетон не нужен.
    m3 = node(br["small"], "pistol_m3")
    assert skill_tree.cross_branch_requirement(weapon, br["small"], m3) is None
    assert skill_tree.cross_branch_toll(weapon, br["small"], m3) == 0
    assert skill_tree.node_state(weapon, br["small"], m3, player) == "ok"
    buy(player, weapon, br["small"], "pistol_m3")

    # tier 4 сначала ждёт глубину 4 основной, затем — жетон школы.
    buy(player, weapon, br["economist"], "pistol_e1")
    buy(player, weapon, br["economist"], "pistol_e2")
    m4 = node(br["small"], "pistol_m4")
    assert skill_tree.node_state(weapon, br["small"], m4, player) == "depth"
    buy(player, weapon, br["swift"], "pistol_s4")
    assert skill_tree.main_branch_depth(weapon) == 4
    assert skill_tree.node_state(weapon, br["small"], m4, player) == "tokens"
    assert not skill_tree.can_pay_cross_toll(player, weapon, br["small"], m4)
    try:
        skill_tree.buy(weapon, br["small"], m4, m4["cost"], player)
    except ValueError:
        pass
    else:
        raise AssertionError("tier 4 второй ветви куплен без жетона")

    # Жетон снайперки — родственный для пистолетной ветви.
    player.add_weapon_token("sniper", 1)
    assert skill_tree.can_pay_cross_toll(player, weapon, br["small"], m4)
    buy(player, weapon, br["small"], "pistol_m4")
    assert "pistol_m4" in weapon.nodes
    assert player.weapon_tokens["sniper"] == 0

    # tier 5 требует глубину 5 основной и два жетона.
    buy(player, weapon, br["swift"], "pistol_s5a")
    assert skill_tree.main_branch_depth(weapon) == 5
    m5 = node(br["small"], "pistol_m5a")
    assert skill_tree.node_state(weapon, br["small"], m5, player) == "tokens"
    assert skill_tree.cross_branch_toll(weapon, br["small"], m5) == 2
    player.add_weapon_token("pistol", 1)
    player.add_weapon_token("cannon", 1)
    buy(player, weapon, br["small"], "pistol_m5a")
    assert "pistol_m5a" in weapon.nodes
    assert player.weapon_tokens["pistol"] == 0
    assert player.weapon_tokens["cannon"] == 0
    print("second branch mastery: ok")


def test_tokens_are_sold_for_every_school():
    pool = SHOP_TYPES["weapons"]["pools"]["token"]
    assert {offer["key"] for offer in pool} == set(TOKEN_KEYS)
    assert set(TRAINING_TOKEN_PRICES) == set(TOKEN_KEYS)
    # Пушка и пистолет раньше не продавались как жетоны вовсе.
    assert "cannon" in TRAINING_TOKEN_PRICES
    assert "pistol" in TRAINING_TOKEN_PRICES
    print("token shop coverage: ok")


def test_beacon_gives_a_token():
    from descent import Beacon
    from game import Game
    from settings import STATE_PLAYING

    game = Game()
    game.reset()
    game.state = STATE_PLAYING
    before = sum(game.player.weapon_tokens.values())
    Beacon(0, 0, 0).complete(game)
    after = sum(game.player.weapon_tokens.values())
    assert after == before + 1, "маяк должен выдавать жетон школы"
    print("beacon token reward: ok")


def test_token_shop_note_at_max_training():
    from game import Game
    from shop_data import offer_view

    game = Game()
    game.reset()
    game.player.add_weapon_training("pistol", 3)
    _, _, note = offer_view(
        game, {"kind": "token", "key": "pistol", "price": 200})
    assert "второй ветви" in note, note
    assert "+1" not in note, note
    print("token shop max note: ok")


def main():
    test_plasma_mode_is_charge_weapon()
    test_second_branch_opens_after_main_depth()
    test_tokens_are_sold_for_every_school()
    test_beacon_gives_a_token()
    test_token_shop_note_at_max_training()
    print("ALL SKILL PROGRESSION TESTS PASSED")


if __name__ == "__main__":
    main()
