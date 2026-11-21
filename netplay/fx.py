"""Клиентские эффекты: то, что хост НЕ должен считать и рассылать.

В снимке мира нет частиц, гильз, цифр урона и вспышек — это чистая
презентация. Клиент выводит их сам из РАЗНИЦЫ двух снимков:

  * новая пуля            -> вспышка у дула + гильза;
  * пуля исчезла          -> искра в последней точке;
  * у врага упало HP      -> цифра урона и искры (с ограничением частоты);
  * враг исчез из снимка  -> облако частиц, взрыв для бомбера/босса;
  * у локального героя упало HP -> красная вспышка и тряска камеры;
  * вырос кошелёк         -> «+N» над героем.

Так сеть остаётся дешёвой (только состояние), а картинка у клиента —
такой же «вкусной», как у хоста. Всё это локальный расчёт: сервер о
клиентских эффектах не знает и не тратит на них кадры.
"""

import math
import random

import soundbank
from projectiles import (Casing, Explosion, FloatingText, MuzzleFlash,
                         Particle, Spark)

# Ограничения, чтобы эффекты не съели кадр на слабом ПК.
MAX_EFFECTS = 420
SPARK_DISTANCE = 900.0
NUMBER_COOLDOWN = 0.05


class ClientFx:
    def __init__(self, game):
        self.game = game
        self.reset()

    def reset(self):
        self._enemy_hp = {}
        self._enemy_pos = {}
        self._enemy_kind = {}
        self._bullet_pos = {}
        self._known_bullets = set()
        self._player_hp = {}
        self._money = {}
        self._numbers = {}
        self._clock = 0.0

    # ------------------------------------------------------------ СНИМОК
    def apply(self, snap):
        self._clock += 0.05
        game = self.game
        local = game.player
        self._track_players(snap.get("players", []), local)
        self._track_enemies(snap.get("enemies", []), local)
        self._track_bullets(snap.get("bullets", []), local)
        self._cap()

    def _track_players(self, states, local):
        game = self.game
        for state in states:
            pid = int(state.get("pid", 0))
            hp = float(state.get("hp", 0.0))
            money = int(state.get("money", 0))
            previous = self._player_hp.get(pid)
            previous_money = self._money.get(pid)
            self._player_hp[pid] = hp
            self._money[pid] = money
            if pid != getattr(local, "pid", -1):
                continue
            x = float(state.get("x", 0.0))
            y = float(state.get("y", 0.0))
            if previous is not None and hp < previous - 0.5:
                game.damage_flash = min(1.0, game.damage_flash + 0.8)
                game.camera.add_shake(3.6, 0.0)
                soundbank.play("hurt", 0.8)
            if previous_money is not None and money > previous_money:
                gain = money - previous_money
                if gain >= 1:
                    game.effects.append(FloatingText(
                        x + random.uniform(-5, 5), y - 28, f"+{gain}",
                        (255, 208, 100), 17, 52.0))
            if previous is not None and hp <= 0.0 < previous:
                soundbank.play("enemy_die", 0.5)
                for _ in range(12):
                    game.effects.append(Particle(x, y, (196, 82, 82)))

    def _track_enemies(self, states, local):
        game = self.game
        seen = set()
        for state in states:
            eid = int(state.get("id", 0))
            seen.add(eid)
            x = float(state.get("x", 0.0))
            y = float(state.get("y", 0.0))
            radius = float(state.get("radius", 18.0))
            hp = float(state.get("hp", 0.0))
            previous = self._enemy_hp.get(eid)
            self._enemy_hp[eid] = hp
            self._enemy_pos[eid] = (x, y, radius)
            self._enemy_kind[eid] = state.get("kind", "Enemy")
            if local is None:
                continue
            if math.hypot(x - local.x, y - local.y) > SPARK_DISTANCE:
                continue
            if previous is not None and hp < previous - 0.5:
                dealt = previous - hp
                now = self._clock
                if now - self._numbers.get(eid, -1.0) >= NUMBER_COOLDOWN:
                    self._numbers[eid] = now
                    if dealt >= 90:
                        color, size = (255, 226, 130), 28
                    elif dealt >= 35:
                        color, size = (255, 246, 210), 23
                    else:
                        color, size = (255, 238, 200), 18
                    game.effects.append(FloatingText(
                        x + random.uniform(-6, 6), y - radius * 0.7,
                        int(round(dealt)), color, size))
                for _ in range(2):
                    game.effects.append(Spark(
                        x, y, random.uniform(0, math.tau),
                        (255, 220, 150), 150))
        for eid in list(self._enemy_hp):
            if eid in seen:
                continue
            x, y, radius = self._enemy_pos.pop(eid, (0.0, 0.0, 18.0))
            kind = self._enemy_kind.pop(eid, "Enemy")
            self._enemy_hp.pop(eid, None)
            self._numbers.pop(eid, None)
            if local is None or math.hypot(x - local.x, y - local.y) > SPARK_DISTANCE:
                continue
            for _ in range(10):
                game.effects.append(Particle(x, y, (170, 92, 92)))
            if kind == "Bomber":
                game.effects.append(Explosion(x, y, 115))
                game.camera.add_shake(4.0)
                soundbank.play("explosion", 0.55)
            elif kind in ("StoneWarden", "ShadowReaper", "BlastOverlord"):
                game.effects.append(Explosion(x, y, 150))
                game.camera.add_shake(8.0)
                soundbank.play("explosion", 0.8)

    def _track_bullets(self, states, local):
        game = self.game
        seen = set()
        for state in states:
            bid = int(state.get("id", 0))
            seen.add(bid)
            x = float(state.get("x", 0.0))
            y = float(state.get("y", 0.0))
            vx = float(state.get("vx", 0.0))
            vy = float(state.get("vy", 0.0))
            self._bullet_pos[bid] = (x, y)
            # Вспышка только в кадре рождения, а не каждый снимок.
            if bid not in self._known_bullets:
                self._known_bullets.add(bid)
                if local is not None and math.hypot(x - local.x,
                                                    y - local.y) < 1000:
                    angle = math.atan2(vy, vx)
                    game.effects.append(MuzzleFlash(x, y, angle))
                    if random.random() < 0.5:
                        game.effects.append(Casing(x, y, angle))
        for bid in list(self._bullet_pos):
            if bid in seen:
                continue
            x, y = self._bullet_pos.pop(bid)
            self._known_bullets.discard(bid)
            if local is not None and math.hypot(x - local.x, y - local.y) < SPARK_DISTANCE:
                for _ in range(3):
                    game.effects.append(Spark(
                        x, y, random.uniform(0, math.tau),
                        (255, 226, 160), 140))

    # ------------------------------------------------------------ КАДР
    def update(self, dt):
        self._clock += dt

    def _cap(self):
        effects = self.game.effects
        if len(effects) > MAX_EFFECTS:
            del effects[:len(effects) - MAX_EFFECTS]
