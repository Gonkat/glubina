"""
Проверки нового арсенала (M16): диск, дуга и резак.

Запуск: python test_new_arsenal.py
Тест headless: SDL переводится в dummy-режим до импорта pygame.

Что проверяется:
  * у каждой новой школы 5 ветвей по 20 узлов;
  * диск улетает на дальность, возвращается, подзывается ЛКМ и бьёт
    на обратном проходе сильнее;
  * дуга перескакивает по ближним целям с затуханием и не бьёт дважды
    одну и ту же цель;
  * нагрев резака усиливает выстрел, перегрев блокирует ствол, ранит
    героя, но не отменяет уже начатый выстрел;
  * прототипы всегда есть в оружейном магазине и не дублируются
    в случайном пуле.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import math

import pygame

from game import Game
from player import Player
from projectiles import Bullet
from settings import SHOP_STOCK_COUNTS, STATE_PLAYING
from shop_data import SHOP_TYPES
from skill_data import SKILL_TREES
from weapon_data import FIREARMS, PROTOTYPE_FIREARMS


class StubEnemy:
    """Минимальный враг: всё, что читает Game.damage_enemy."""

    def __init__(self, x, y, hp=1000.0, radius=12.0):
        self.x, self.y = x, y
        self.radius = radius
        self.hp = self.max_hp = hp
        self.alive = True
        self.armor_factor = 1.0
        self.vulnerable_timer = 0.0
        self.vulnerable_mul = 1.0
        self.explosion_mark = 0.0
        self.bleed_remaining = 0.0
        self.bleed_dps = 0.0
        self.score = 10
        self.bounty = 1
        self.color = (200, 200, 200)
        self.kind = "runner"

    def take_damage(self, amount):
        self.hp -= amount
        if self.hp <= 0.0:
            self.alive = False

    def apply_knockback(self, direction, force):
        return None


class FakeWorld:
    @staticmethod
    def is_solid_at(x, y):
        return False


class FakeGame:
    world = FakeWorld()
    player = type("FakePlayer", (), {"x": 0.0, "y": 0.0, "alive": True})()


def fresh_game(with_enemies):
    game = Game()
    game.reset()
    game.state = STATE_PLAYING
    game.enemies = list(with_enemies)
    game.enemy_index.rebuild(game.enemies)
    return game


def test_new_trees_shape():
    for key in PROTOTYPE_FIREARMS:
        tree = SKILL_TREES[key]
        branches = tree["branches"]
        assert len(branches) == 5, (key, len(branches))
        ids = []
        for branch in branches:
            assert len(branch["nodes"]) == 20, (key, branch["key"])
            ids.extend(node["id"] for node in branch["nodes"])
        assert len(ids) == 100 and len(set(ids)) == 100, key
        # У каждой ветви есть межветвевые связи, иначе это не дерево,
        # а пять отдельных линеек.
        for branch in branches:
            assert any(node.get("hybrid") for node in branch["nodes"]), (
                key, branch["key"])
    print("new trees shape: ok")


def test_disc_flies_out_and_returns():
    bullet = Bullet(0, 0, 0, damage=10, speed=200, radius=8,
                    return_range=100, return_speed_mul=1.25,
                    return_damage_mul=0.55, recall_speed_mul=1.9)
    for _ in range(120):
        bullet.update(1 / 60, FakeGame())
        if bullet.returning:
            break
    assert bullet.returning, "диск должен вернуться после дальности"
    assert bullet.return_speed > 200, "возврат должен быть быстрее заброса"

    fresh = Bullet(0, 0, 0, damage=10, speed=200, radius=8,
                   return_range=1000, recall_speed_mul=2.0)
    assert not fresh.returning
    # Подзыв мгновенно разворачивает диск, даже если предел не достигнут.
    assert fresh.recall()
    assert fresh.returning
    print("disc return: ok")


def test_disc_return_hits_harder():
    enemy = StubEnemy(0, 0)
    game = fresh_game([enemy])
    plain = Bullet(0, 0, 0, damage=100.0, speed=0, radius=8)
    game._bullet_hit(plain, enemy)
    first = enemy.max_hp - enemy.hp
    enemy.hp = enemy.max_hp
    heavy = Bullet(0, 0, 0, damage=100.0, speed=0, radius=8,
                   return_damage_mul=0.5)
    heavy.returning = True
    game._bullet_hit(heavy, enemy)
    second = enemy.max_hp - enemy.hp
    assert first > 0 and second > 0
    assert math.isclose(second / first, 1.5, rel_tol=1e-6), (first, second)
    print("disc return damage: ok")


def test_arc_chains_with_falloff():
    enemies = [StubEnemy(0, 0), StubEnemy(60, 0),
               StubEnemy(120, 0), StubEnemy(900, 0)]
    game = fresh_game(enemies)
    bullet = Bullet(0, 0, 0, damage=100.0, speed=0, radius=5,
                    chain_jumps=3, chain_range=100, chain_falloff=0.5,
                    chain_damage_mul=1.0)
    game._bullet_hit(bullet, enemies[0])
    dealt = [enemy.max_hp - enemy.hp for enemy in enemies]
    assert math.isclose(dealt[0], 100.0, rel_tol=1e-6), dealt
    assert math.isclose(dealt[1], 50.0, rel_tol=1e-6), dealt
    assert math.isclose(dealt[2], 25.0, rel_tol=1e-6), dealt
    assert dealt[3] == 0.0, "цель вне радиуса цепи не должна получить урон"

    # Дистанция больше радиуса цепи — переходов нет вовсе.
    far = [StubEnemy(0, 0), StubEnemy(400, 0)]
    game = fresh_game(far)
    bullet = Bullet(0, 0, 0, damage=100.0, speed=0, radius=5,
                    chain_jumps=3, chain_range=100, chain_falloff=0.5)
    game._bullet_hit(bullet, far[0])
    assert far[1].max_hp - far[1].hp == 0.0
    print("arc chain: ok")


def test_cutter_heat_scales_damage():
    player = Player(0, 0)
    player.switch_firearm("cutter")
    weapon = player.firearm
    weapon.last_heat = 0.0
    cold = weapon.resolve_shot(player)["damage"]
    weapon.last_heat = 1.0
    hot = weapon.resolve_shot(player)["damage"]
    assert cold > 0.0
    assert math.isclose(hot / cold, 1.85, rel_tol=1e-6), (cold, hot)
    print("cutter heat scaling: ok")


def test_cutter_overheats_and_locks():
    player = Player(0, 0)
    player.switch_firearm("cutter")
    weapon = player.firearm
    for _ in range(6):
        weapon.cooldown = 0.0
        weapon.loaded = weapon.magazine_size
        weapon.consume_shot(player)
    assert weapon.vent_pending, "шесть выстрелов должны загнать ствол в пик"
    weapon.start_vent()
    assert weapon.heat == 0.0
    assert weapon.is_venting
    assert not weapon.can_fire, "во время сброса стрельбы быть не должно"
    weapon.vent_timer = 0.0
    weapon.cooldown = 0.0
    weapon.loaded = weapon.magazine_size
    assert weapon.can_fire, "после сброса ствол снова готов"
    print("cutter overheat: ok")


def test_cutter_vent_hurts_player_but_shot_lands():
    player = Player(0, 0)
    game = fresh_game([])
    game.player = player
    player.switch_firearm("cutter")
    weapon = player.firearm
    weapon.loaded = weapon.magazine_size
    weapon.cooldown = 0.0
    weapon.heat = 0.9
    player.trigger_held = True
    player.invuln_timer = 0.0
    player.hurt_timer = 0.0
    before = player.hp
    player.try_attack(game)
    assert game.bullets, "выстрел, который добил нагрев, всё равно должен выйти"
    assert weapon.heat == 0.0 and weapon.is_venting
    assert player.hp < before, "сброс — это риск, а не бесплатный сброс"
    print("cutter vent cost: ok")


def test_disc_recall_does_not_spend_ammo():
    game = fresh_game([])
    player = game.player
    player.switch_firearm("disc")
    weapon = player.firearm
    weapon.loaded = weapon.magazine_size
    weapon.cooldown = 0.0
    player.try_attack(game)
    assert len(game.bullets) == 1
    disc = game.bullets[0]
    assert weapon.has_live_disc
    loaded = weapon.loaded
    player.try_attack(game)          # второй ЛКМ — подзыв
    assert len(game.bullets) == 1, "подзыв не должен тратить второй патрон"
    assert weapon.loaded == loaded
    assert disc.returning, "диск должен развернуться к герою"
    print("disc recall: ok")


def test_prototypes_are_always_in_shop():
    pool = {offer["key"]: offer
            for offer in SHOP_TYPES["weapons"]["pools"]["prototype"]}
    assert set(pool) == set(PROTOTYPE_FIREARMS)
    for key, offer in pool.items():
        assert offer["price"] == FIREARMS[key]["cost"], key
    minimum, maximum = SHOP_STOCK_COUNTS["prototype"]
    assert minimum >= 2 and maximum <= 3, (minimum, maximum)
    random_pool = {offer["key"]
                   for offer in SHOP_TYPES["weapons"]["pools"]["firearm"]}
    assert not random_pool & set(PROTOTYPE_FIREARMS), (
        "прототипы не должны дублироваться в случайном пуле")
    print("prototype shop: ok")


def main():
    pygame.init()
    test_new_trees_shape()
    test_disc_flies_out_and_returns()
    test_disc_return_hits_harder()
    test_arc_chains_with_falloff()
    test_cutter_heat_scales_damage()
    test_cutter_overheats_and_locks()
    test_cutter_vent_hurts_player_but_shot_lands()
    test_disc_recall_does_not_spend_ammo()
    test_prototypes_are_always_in_shop()
    print("ALL NEW ARSENAL TESTS PASSED")


if __name__ == "__main__":
    main()
