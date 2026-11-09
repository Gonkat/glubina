"""
Проверки энергопушки (M14).

Запуск:  python test_energy_cannon.py
Тест не открывает окно: SDL переводится в dummy-режим до импорта pygame.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import skill_tree
from skill_data import SKILL_TREES
from skill_board import BoardLayout
from shop_data import generate_shop_inventory
from weapons import create_weapon


class DummyGame:
    """Минимальный стенд для выстрела: без мира, но с теми же хуками."""

    def __init__(self):
        self.bullets = []
        self.effects = []
        self.shots = 0
        self.camera = SimpleNamespace(add_shake=lambda *args: None)

    def on_shot(self, weapon):
        self.shots += 1


def branch(key):
    return next(item for item in SKILL_TREES["cannon"]["branches"]
                if item["key"] == key)


def node(branch_key, node_id):
    return next(item for item in branch(branch_key)["nodes"]
                if item["id"] == node_id)


def fresh():
    pygame.init()
    from player import Player
    player = Player(0, 0)
    player.switch_firearm("cannon")
    return player, player.firearm, DummyGame()


def advance(player, weapon, game, seconds):
    dt = 1.0 / 60.0
    for _ in range(max(1, int(round(seconds / dt)))):
        weapon.update(dt)
        player._update_charged_weapon(dt, game, weapon)


def release(player, weapon, game):
    player.trigger_held = False
    player._update_charged_weapon(1.0 / 60.0, game, weapon)


def buy(player, weapon, branch_key, node_id, price=0):
    skill_tree.buy(weapon, branch(branch_key), node(branch_key, node_id),
                   price, player)


def test_tree_shape_and_links():
    branches = SKILL_TREES["cannon"]["branches"]
    assert len(branches) == 5
    assert {b["key"] for b in branches} == {
        "overdrive", "flex", "resonance", "capacitor", "siege"}
    all_ids = {n["id"] for b in branches for n in b["nodes"]}
    assert len(all_ids) == 100
    for b in branches:
        assert len(b["nodes"]) == 20, b["key"]
        for n in b["nodes"]:
            for req in n.get("requires", ()):
                assert req in all_ids, (n["id"], req)
            for other in n.get("excludes", ()):
                assert other in all_ids, (n["id"], other)

    # Главная развилка: полный импульс исключает оба узла гибкости.
    o2 = node("overdrive", "cannon_o2")
    f1 = node("flex", "cannon_f1")
    f2 = node("flex", "cannon_f2")
    assert set(o2["excludes"]) == {"cannon_f1", "cannon_f2"}
    assert "cannon_o2" in f1["excludes"]
    assert "cannon_o2" in f2["excludes"]
    assert node("overdrive", "cannon_o5a")["excludes"] == ("cannon_o5b",)
    assert node("flex", "cannon_f5b")["excludes"] == ("cannon_f5a",)

    # Все узлы имеют координаты на доске, ветви не слипаются.
    layout = BoardLayout()
    positions = set()
    for b in branches:
        for n in b["nodes"]:
            x, y = layout.node_pos("cannon", n["id"])
            positions.add((round(x, 2), round(y, 2)))
    assert len(positions) == 100
    assert len(layout.weapon_branch_ends["cannon"]) == 5
    print("tree shape and links: ok")


def test_charge_scales_and_early_release_cancels():
    player, weapon, game = fresh()
    assert weapon.uses_charge and weapon.magazine_size == 5
    assert weapon.charge_ratio == 0.0

    # Ранний отпуск: ни пули, ни патрона, ни «залипшего» заряда.
    player.trigger_held = True
    advance(player, weapon, game, 0.15)
    assert 0.05 < weapon.charge_ratio < weapon.min_charge
    release(player, weapon, game)
    assert not game.bullets
    assert weapon.loaded == 5
    assert not weapon.is_charging
    assert weapon.charge_ratio == 0.0

    # Полный заряд: размер, площадь и урон растут вместе.
    player.trigger_held = True
    advance(player, weapon, game, 1.3)
    assert weapon.charge_full
    assert weapon.charge_ratio == 1.0
    release(player, weapon, game)
    assert len(game.bullets) == 1
    bullet = game.bullets[0]
    assert bullet.style == "plasma"
    assert bullet.charge == 1.0
    assert abs(bullet.damage - 96.6) < 1e-6
    assert bullet.radius == 25.0
    assert bullet.explode == 64.0
    assert bullet.explosion_power > 1.0
    assert weapon.loaded == 4
    print("charge scaling and cancel: ok")


def test_death_and_reload_interrupt():
    player, weapon, game = fresh()
    player.trigger_held = True
    advance(player, weapon, game, 0.6)
    player.take_damage(9999, None)
    assert not player.alive
    release(player, weapon, game)
    assert not game.bullets
    assert weapon.loaded == 5
    assert not weapon.is_charging

    player, weapon, game = fresh()
    player.trigger_held = True
    advance(player, weapon, game, 0.6)
    player.start_reload()       # ручное прерывание
    assert not weapon.is_charging
    release(player, weapon, game)
    assert not game.bullets
    print("death and reload interrupts: ok")


def test_overdrive_full_commitment():
    player, weapon, game = fresh()
    buy(player, weapon, "overdrive", "cannon_o1")
    buy(player, weapon, "overdrive", "cannon_o2")
    assert weapon.main_branch == "overdrive"
    assert weapon.mod("full_only") == 1
    assert skill_tree.node_state(weapon, branch("flex"),
                                 node("flex", "cannon_f1"), player) == "excluded"

    # Ранний отпуск при полном импульсе — отмена, а не слабый выстрел.
    player.trigger_held = True
    advance(player, weapon, game, 0.65)
    release(player, weapon, game)
    assert not game.bullets
    assert weapon.loaded == 5

    player.trigger_held = True
    advance(player, weapon, game, 1.3)
    release(player, weapon, game)
    bullet = game.bullets[0]
    assert abs(bullet.damage - 193.2) < 1e-6
    assert bullet.radius == 50.0
    assert bullet.explode == 80.0
    print("overdrive commitment: ok")


def test_flex_partial_shot():
    player, weapon, game = fresh()
    buy(player, weapon, "flex", "cannon_f1")
    assert weapon.main_branch == "flex"
    assert weapon.mod("partial_unlock") == 1
    assert skill_tree.node_state(weapon, branch("overdrive"),
                                 node("overdrive", "cannon_o2"), player) == "excluded"

    player.trigger_held = True
    advance(player, weapon, game, 0.15)
    # Ветвь гибкости опускает порог с 35% до 8%, поэтому 15% уже
    # становится настоящим выстрелом.
    assert 0.08 < weapon.charge_ratio < 0.35
    release(player, weapon, game)
    assert len(game.bullets) == 1
    bullet = game.bullets[0]
    # Даже на 15% снаряд существует, но заметно слабее полного.
    assert bullet.damage < 96.6 * 0.5
    assert bullet.radius < 25.0
    assert weapon.loaded == 4
    print("flex partial shot: ok")


def test_cross_dependencies_training_and_excludes():
    # Овердрайв: «Критическая масса» требует соседний резонатор и
    # подготовку снайперки. Жетон закрывает подготовку.
    player, weapon, game = fresh()
    buy(player, weapon, "overdrive", "cannon_o1")
    buy(player, weapon, "overdrive", "cannon_o2")
    buy(player, weapon, "resonance", "cannon_a1")
    o3 = node("overdrive", "cannon_o3")
    assert skill_tree.node_state(weapon, branch("overdrive"), o3,
                                 player) == "training"
    player.add_weapon_token("sniper", 1)
    assert skill_tree.can_cover_training(player, o3)
    buy(player, weapon, "overdrive", "cannon_o3")
    assert player.weapon_tokens["sniper"] == 0
    assert player.weapon_training["sniper"] == 1
    assert weapon.mod("full_pierce") == 2

    # Резонанс: a3 требует молот и даёт оглушение только полному взрыву.
    player, weapon, game = fresh()
    buy(player, weapon, "resonance", "cannon_a1")
    buy(player, weapon, "resonance", "cannon_a2")
    buy(player, weapon, "overdrive", "cannon_o1")
    assert skill_tree.node_state(weapon, branch("resonance"),
                                 node("resonance", "cannon_a3"),
                                 player) == "training"
    player.add_weapon_token("hammer", 1)
    buy(player, weapon, "resonance", "cannon_a3")
    weapon.last_charge_ratio = 1.0
    shot = weapon.resolve_shot(player)
    assert shot["blast_stun"] == 0.4
    assert shot["explosion_vulnerable"] == 0.15
    weapon.last_charge_ratio = 0.6
    assert weapon.resolve_shot(player)["blast_stun"] == 0.0

    # Гибкость: f3 требует дробовик и возвращает патрон на недозаряде.
    player, weapon, game = fresh()
    buy(player, weapon, "flex", "cannon_f1")
    buy(player, weapon, "flex", "cannon_f2")
    buy(player, weapon, "capacitor", "cannon_c1")
    f3 = node("flex", "cannon_f3")
    assert skill_tree.node_state(weapon, branch("flex"), f3,
                                 player) == "training"
    player.add_weapon_token("shotgun", 1)
    buy(player, weapon, "flex", "cannon_f3")
    assert weapon.mod("partial_refund_chance") == 0.35

    # Накопитель: магазин +2 и восстановление ветви после смены ствола.
    player, weapon, game = fresh()
    buy(player, weapon, "capacitor", "cannon_c1")
    buy(player, weapon, "capacitor", "cannon_c3")
    assert weapon.magazine_size == 7
    assert weapon.spec["magazine"] == 7
    player.remember_weapon_tree(weapon)
    replacement = create_weapon("cannon")
    player.restore_weapon_tree(replacement)
    assert replacement.magazine_size == 7
    assert {"cannon_c1", "cannon_c3"} <= replacement.nodes
    print("cross dependencies and training: ok")


def test_movement_while_charging():
    """Заряд не запрещает движение; «Подвижный контур» ускоряет именно его."""
    from game import Game

    def travel(charged):
        game = Game()
        game.state = "playing"
        game.player.switch_firearm("cannon")
        if charged:
            buy(game.player, game.player.firearm, "capacitor", "cannon_c1")
        player = game.player
        player.move_dir = (1.0, 0.0)
        player.trigger_held = charged
        start = player.x
        for _ in range(30):
            player.update(1.0 / 60.0, game)
        return player.x - start, player

    plain, _ = travel(False)
    charged, player = travel(True)
    assert player.firearm.is_charging
    assert charged > plain * 1.09, (plain, charged)
    print("movement while charging: ok")


def test_hitbox_collision_and_plasma_splash():
    """Реальный Game: крупный хитбокс задевает дальше, взрыв — соседей."""
    from game import Game
    from enemies import Enemy
    from projectiles import Bullet

    game = Game()
    game.enemies = []
    game.bullets = []
    game.effects = []
    game.drops = []

    # Маленький хитбокс не достаёт до врага в 30 px, большой — достаёт.
    small = Enemy(0, 0)
    small.hp = small.max_hp = 1000
    game.enemies = [small]
    game.enemy_index.rebuild(game.enemies)
    game.bullets = [Bullet(30, 0, 0, damage=10, speed=0, radius=7)]
    game._check_bullet_hits()
    assert small.hp == 1000, "маленький снаряд не должен бить на 30 px"
    assert game.bullets[0].alive

    primary = Enemy(0, 0)
    primary.hp = primary.max_hp = 1000
    nearby = Enemy(40, 0)
    nearby.hp = nearby.max_hp = 1000
    game.enemies = [primary, nearby]
    game.enemy_index.rebuild(game.enemies)
    plasma = Bullet(30, 0, 0, damage=10, speed=0, radius=25,
                    explode=64, explosion_power=1.1,
                    explosion_vulnerable=0.2, blast_stun=0.4,
                    explosion_color=(112, 232, 255))
    game.bullets = [plasma]
    game._check_bullet_hits()
    assert primary.hp < 1000
    assert nearby.hp < 1000, "взрыв полного заряда должен задевать соседей"
    assert nearby.vulnerable_timer > 0.0
    assert nearby.slow_timer > 0.0 and nearby.slow_factor == 0.0
    print("hitbox collision and plasma splash: ok")


def test_charge_bar_matches_hitbox_and_tree_interrupts():
    """Шкала ровно по хитбоксу; вход в древо снимает заряд без выстрела."""
    from game import Game

    game = Game()
    game.player.switch_firearm("cannon")
    player, weapon = game.player, game.player.firearm
    player.trigger_held = True
    for _ in range(40):
        player.update(1.0 / 60.0, game)
    assert weapon.is_charging
    game.open_tree("firearm")
    assert not weapon.is_charging

    weapon.is_charging = True
    weapon.charge = 1.0
    weapon.charge_full = True
    screen = pygame.Surface((200, 200))
    rects = []
    original = pygame.draw.rect

    def capture(surface, color, rect, *args, **kwargs):
        rects.append(tuple(rect))
        return original(surface, color, rect, *args, **kwargs)

    pygame.draw.rect = capture
    try:
        player._draw_charge_bar(screen, 100, 100, int(player.radius * 1.5),
                                weapon)
    finally:
        pygame.draw.rect = original
    bar_w = player.radius * 2
    assert any(int(rect[2]) == bar_w for rect in rects), rects
    assert any(int(rect[2]) == bar_w + 4 for rect in rects), rects
    print("charge bar width and tree interrupt: ok")


def test_guaranteed_shop_stock():
    import random
    from game import Game
    from shop import Shop

    for seed in range(80):
        inventory = generate_shop_inventory("weapons", random.Random(seed))
        firearms = [offer for offer in inventory
                    if offer["kind"] == "firearm"]
        assert any(offer["key"] == "cannon" for offer in firearms), seed
        assert any(offer["key"] == "pistol" for offer in firearms), seed

    # И покупка действительно переключает слот, а не только показывает товар.
    game = Game()
    game.money = 5000
    inventory = generate_shop_inventory("weapons", random.Random(3))
    cannon_offer = next(offer for offer in inventory
                        if offer["kind"] == "firearm"
                        and offer["key"] == "cannon")
    shop = Shop(0, 0, "weapons", inventory, 1.0)
    game.shop_ui.open(shop)
    game.shop_ui.cursor = game.shop_ui._items(game).index(cannon_offer)
    game.shop_ui.buy(game)
    assert game.player.firearm.key == "cannon"
    assert game.player.firearm.uses_charge
    print("guaranteed cannon shop stock: ok")


def main():
    test_tree_shape_and_links()
    test_charge_scales_and_early_release_cancels()
    test_death_and_reload_interrupt()
    test_overdrive_full_commitment()
    test_flex_partial_shot()
    test_cross_dependencies_training_and_excludes()
    test_movement_while_charging()
    test_hitbox_collision_and_plasma_splash()
    test_charge_bar_matches_hitbox_and_tree_interrupts()
    test_guaranteed_shop_stock()
    print("ALL ENERGY CANNON TESTS PASSED")


if __name__ == "__main__":
    main()
