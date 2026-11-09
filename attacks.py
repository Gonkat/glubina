"""
Четыре механики атак ближнего боя — четыре НЕЗАВИСИМЫХ класса.

Это паттерн «Стратегия»: оружие (MeleeWeapon) ВЛАДЕЕТ объектом атаки
и не знает, как именно оно бьёт. Новый тип атаки = новый класс +
запись в ATTACK_TYPES внизу файла. Ни оружие, ни боевая система
при этом не меняются (п.8 GDD: механики независимы и расширяемы).
"""
import math

import pygame

import soundbank
from status_effects import apply_bleed, apply_dust, apply_slow, apply_stun
from utils import angle_diff


def sector_points(cx, cy, reach, angle, half_angle, steps=16):
    """Точки полигона-сектора (дуга + центр) — общая геометрия для атак."""
    pts = [(cx, cy)]
    for i in range(steps + 1):
        a = angle - half_angle + 2 * half_angle * i / steps
        pts.append((cx + math.cos(a) * reach, cy + math.sin(a) * reach))
    return pts


class MeleeAttack:
    """
    Контракт любой атаки:
      start(owner, game)     — нажатие кнопки (пассивные игнорируют)
      update(dt, owner, game)— каждый кадр: таймеры и нанесение урона
      draw(overlay, camera, owner) — визуал в ПРОЗРАЧНЫЙ слой overlay
    """

    is_passive = False   # True = работает сама по себе, без нажатия (щит)

    def __init__(self, spec):
        self.spec = spec
        self.cooldown = 0.0
        self.mods = {}
        # Состояние поздних доктрин: первый удар, серии и эхо-удары.
        self.time_since_attack = 10.0
        self.attack_serial = 0
        self.first_strike_serial = -1
        self.echoes = []
        self.combo_stacks = 0
        self.combo_timer = 0.0
        self.last_combo_serial = -1

    def start(self, owner, game):
        if self.is_passive or self.cooldown > 0.0:
            return
        self.cooldown = self.spec["cooldown"]
        self.attack_serial += 1
        # «Мгновенный клинок»: удар после паузы. Серия запоминается на
        # весь замах, чтобы широкий удар не терял бонус на второй цели.
        self.first_strike_serial = (self.attack_serial
                                    if self.time_since_attack >= 1.0 else -1)
        self.time_since_attack = 0.0
        soundbank.play("swing")      # звук есть у ВСЕХ атак: одна точка
        self._on_start(owner, game)  # (срабатывает только при реальном ударе)

    def _on_start(self, owner, game):
        """Переопределяют атаки, которым нужно что-то начать."""

    def update(self, dt, owner, game):
        self.cooldown = max(0.0, self.cooldown - dt)
        self.time_since_attack += dt
        if self.combo_timer > 0.0:
            self.combo_timer -= dt
            if self.combo_timer <= 0.0:
                self.combo_stacks = 0
                self.last_combo_serial = -1
        # Эхо-удар приходит позже, но живёт в том же объекте атаки,
        # поэтому не требует ни новых пуль, ни отдельной системы эффектов.
        pending = []
        for echo in self.echoes:
            echo["time"] -= dt
            if echo["time"] > 0.0:
                pending.append(echo)
                continue
            enemy = echo["enemy"]
            if enemy.alive:
                game.damage_enemy(enemy, echo["damage"],
                                  knockback_dir=echo["direction"],
                                  knockback=echo["knockback"])
        self.echoes = pending
        self._tick(dt, owner, game)

    def _tick(self, dt, owner, game):
        """Переопределяют атаки с состоянием во времени."""

    def draw(self, overlay, camera, owner):
        """Переопределяют атаки с визуалом."""

    # ------------------------------------------------------------ ОБЩЕЕ
    @staticmethod
    def damage_of(owner, spec):
        """
        Урон удара с учётом пассивных артефактов героя («Клык» и др.).
        Один хук на все четыре механики — правь здесь, а не в каждой атаке.
        """
        return spec["damage"] * getattr(owner, "damage_mult", 1.0)

    def hit(self, owner, game, enemy, damage, direction, knockback):
        mods = self.mods
        # «Мастерство» ветвей: общий множитель урона для всех атак
        # ближнего боя, включая щит и метлу.
        damage *= 1.0 + float(mods.get("damage_mul", 0.0))
        moving = math.hypot(*getattr(owner, "move_dir", (0.0, 0.0))) > 0.1
        opening = getattr(enemy, "windup_timer", 0.0) > 0.0

        # --- условные бонусы, которые зависят от ситуации, а не от цифры ---
        if opening and mods.get("opening_bonus", 0.0):
            damage *= 1.0 + mods["opening_bonus"]
        if (mods.get("first_strike_bonus", 0.0)
                and self.first_strike_serial == self.attack_serial):
            damage *= 1.0 + mods["first_strike_bonus"]
        threshold = mods.get("low_hp_threshold", 0.4)
        if (mods.get("low_hp_bonus", 0.0)
                and getattr(owner, "hp", 1.0) <= owner.max_hp * threshold):
            damage *= 1.0 + mods["low_hp_bonus"]
        if mods.get("steady_bonus", 0.0) and not moving:
            damage *= 1.0 + mods["steady_bonus"]
        if mods.get("moving_bonus", 0.0) and moving:
            damage *= 1.0 + mods["moving_bonus"]
        if (mods.get("dash_strike_bonus", 0.0)
                and getattr(owner, "dash_strike_timer", 0.0) > 0.0):
            damage *= 1.0 + mods["dash_strike_bonus"]

        # «Вихрь»: серия считается по замахам, а не по каждой цели в дуге.
        if mods.get("combo_bonus", 0.0):
            if self.last_combo_serial != self.attack_serial:
                self.combo_stacks = min(int(mods.get("combo_max", 8)),
                                        self.combo_stacks + 1)
                self.last_combo_serial = self.attack_serial
            damage *= 1.0 + mods["combo_bonus"] * max(0, self.combo_stacks - 1)
            self.combo_timer = 2.5

        execute = mods.get("execute", 0.0) + getattr(owner, "execute_bonus", 0.0)
        execute_threshold = 0.35 + mods.get("execute_threshold", 0.0)
        if enemy.hp <= enemy.max_hp * execute_threshold:
            damage *= 1.0 + execute

        # «Паразит» лечит за удар по уже кровоточащей цели — до урона,
        # чтобы добивающий удар тоже вернул HP.
        if mods.get("bleed_heal", 0.0) and getattr(enemy, "bleed_remaining", 0.0) > 0.0:
            owner.heal(mods["bleed_heal"])

        # Раны ставятся до урона: убийство тоже оставляет кровь, которую
        # «Кровавая жатва» может разнести по соседям.
        if opening and mods.get("opening_bleed", 0.0):
            apply_bleed(enemy, damage * min(1.0, mods["opening_bleed"]))
        if mods.get("bleed", 0.0):
            apply_bleed(enemy, damage * min(1.0, mods["bleed"]))
        if (mods.get("first_strike_bleed", 0.0)
                and self.first_strike_serial == self.attack_serial):
            apply_bleed(enemy, damage * min(1.0, mods["first_strike_bleed"]))

        game.damage_enemy(enemy, damage, knockback_dir=direction,
                          knockback=knockback * (1.0 + mods.get("stagger", 0.0)))

        dust_damage = (self.spec.get("dust_damage", 0.0)
                       + mods.get("dust_damage_add", 0.0))
        if enemy.alive and dust_damage > 0.0:
            dust_radius = mods.get("dust_radius_add", 0.0)
            dust_stacks = max(
                1,
                int(self.spec.get("dust_stack_cap", 1)
                    + mods.get("dust_stack_cap_add", 0)),
            )
            dust_slow = min(
                0.85,
                self.spec.get("dust_slow", 0.0) + mods.get("dust_slow_add", 0.0),
            )
            targets = [enemy]
            if dust_radius > 0.0:
                radius_sq = dust_radius ** 2
                targets.extend(
                    other for other in game.nearby_enemies(
                        enemy.x, enemy.y, dust_radius)
                    if other is not enemy and other.alive
                    and (other.x - enemy.x) ** 2 + (other.y - enemy.y) ** 2
                    <= radius_sq
                )
            for target in targets:
                apply_dust(
                    target, damage * dust_damage,
                    self.spec.get("dust_duration", 2.4),
                    dust_stacks,
                    dust_slow,
                )
                game.spawn_dust(target, dust_stacks)

        if (mods.get("combo_every", 0)
                and self.attack_serial % int(mods["combo_every"]) == 0
                and enemy.alive):
            game.damage_enemy(enemy, damage * min(1.0, mods.get("combo_double", 0.0)))
        if mods.get("double", 0.0) and enemy.alive:
            game.damage_enemy(enemy, damage * min(1.0, mods["double"]))
        if mods.get("leech", 0.0):
            owner.heal(damage * mods["leech"])

        # --- контроль: стан, замедление, притяжение ---
        if enemy.alive and mods.get("impact_stun", 0.0):
            apply_stun(enemy, mods["impact_stun"])
        if enemy.alive and mods.get("impact_slow", 0.0):
            radius = mods.get("impact_slow_radius", 0.0)
            apply_slow(enemy, mods["impact_slow"],
                       mods.get("impact_slow_factor", 0.55))
            if radius:
                for other in game.nearby_enemies(enemy.x, enemy.y, radius):
                    if other is not enemy and other.alive:
                        apply_slow(other, mods["impact_slow"],
                                   mods.get("impact_slow_factor", 0.55))
        if mods.get("pull_radius", 0.0):
            radius = mods["pull_radius"]
            force = mods.get("pull_force", 160.0)
            for other in game.nearby_enemies(enemy.x, enemy.y, radius):
                if not other.alive or other is enemy:
                    continue
                pull_dir = self._knock_dir(other.x, other.y, owner.x, owner.y)
                other.apply_knockback(pull_dir, force)

        # --- площадь ---
        splash = mods.get("splash", 0.0)
        if splash:
            radius = 95.0 + mods.get("splash_radius_add", 0.0)
            radius_sq = radius ** 2
            for other in game.nearby_enemies(enemy.x, enemy.y, radius):
                if other is enemy or not other.alive:
                    continue
                if (other.x - enemy.x) ** 2 + (other.y - enemy.y) ** 2 <= radius_sq:
                    game.damage_enemy(other, damage * splash)

        # --- эхо-удар ---
        if mods.get("echo_damage", 0.0) and enemy.alive:
            self.echoes.append({
                "enemy": enemy,
                "time": mods.get("echo_delay", 0.25),
                "damage": damage * mods["echo_damage"],
                "direction": direction,
                "knockback": knockback * 0.5,
            })

        # --- эффекты смерти ---
        if not enemy.alive:
            if mods.get("kill_heal", 0.0):
                owner.heal(mods["kill_heal"])
            if mods.get("kill_invuln", 0.0):
                owner.invuln_timer = max(owner.invuln_timer, mods["kill_invuln"])
            if mods.get("bleed_spread", 0.0) and getattr(enemy, "bleed_remaining", 0.0) > 0.0:
                radius = mods.get("bleed_spread_radius", 90.0)
                for other in game.nearby_enemies(enemy.x, enemy.y, radius):
                    if other is enemy or not other.alive:
                        continue
                    apply_bleed(other, damage * mods["bleed_spread"])

    @staticmethod
    def _knock_dir(x, y, target_x, target_y):
        """Единичный вектор ОТ точки (x, y) к цели — куда отбрасывать."""
        dx, dy = target_x - x, target_y - y
        length = math.hypot(dx, dy)
        if length < 0.001:
            return 1.0, 0.0
        return dx / length, dy / length


# ================================================================ ТИП 1
class ArcSlashAttack(MeleeAttack):
    """
    Рубящий удар по дуге (мачете, лопата).
    Лезвие стартует СПРАВА от взгляда, проходит ВЛЕВО и возвращается
    назад. Урон получает всё, через что лезвие прошло — один раз
    за замах (набор hit_ids не даёт бить одного врага дважды).
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.swinging = False
        self.t = 0.0
        self.prev_offset = 0.0
        self.hit_ids = set()

    def _offset(self, t):
        """Положение лезвия относительно взгляда: +half → −half → +half."""
        half = math.radians(self.spec["arc_deg"]) / 2
        if t <= 0.5:
            return half - 2 * half * (t / 0.5)
        return -half + 2 * half * ((t - 0.5) / 0.5)

    def _on_start(self, owner, game):
        self.swinging = True
        self.t = 0.0
        self.prev_offset = math.radians(self.spec["arc_deg"]) / 2
        self.hit_ids.clear()

    def _tick(self, dt, owner, game):
        if not self.swinging:
            return
        self.t += dt
        t = min(1.0, self.t / self.spec["swing_time"])
        blade = owner.angle + self._offset(t)
        prev = owner.angle + self.prev_offset
        self._sweep(owner, game, prev, blade)
        self.prev_offset = self._offset(t)
        if t >= 1.0:
            self.swinging = False

    def _sweep(self, owner, game, a_prev, a_now):
        """Урон тем, через кого прошло лезвие между двумя кадрами."""
        reach = self.spec["reach"]
        blade_half = math.radians(self.spec["blade_deg"]) / 2
        rel_prev = angle_diff(a_prev, a_now)          # «хвост» удара относительно острия
        lo = min(rel_prev, 0.0) - blade_half
        hi = max(rel_prev, 0.0) + blade_half

        for enemy in game.nearby_enemies(owner.x, owner.y, reach):
            if not enemy.alive or id(enemy) in self.hit_ids:
                continue
            dx, dy = enemy.x - owner.x, enemy.y - owner.y
            dist = math.hypot(dx, dy)
            if dist > reach + enemy.radius:
                continue
            rel = angle_diff(math.atan2(dy, dx), a_now)
            margin = math.atan2(enemy.radius, max(dist, 1.0))
            if lo - margin <= rel <= hi + margin:
                self.hit_ids.add(id(enemy))
                self.hit(owner, game, enemy, self.damage_of(owner, self.spec),
                         (math.cos(a_now), math.sin(a_now)), self.spec["knockback"])

    def draw(self, overlay, camera, owner):
        if not self.swinging:
            return
        cx, cy = camera.to_screen(owner.x, owner.y)
        t = min(1.0, self.t / self.spec["swing_time"])
        blade = owner.angle + self._offset(t)
        rel_prev = angle_diff(owner.angle + self.prev_offset, blade)
        half = math.radians(self.spec["blade_deg"]) / 2
        start = blade + min(rel_prev, 0.0) - half
        end = blade + max(rel_prev, 0.0) + half
        color = self.spec["color"]

        # след замаха
        pts = [(cx, cy)]
        steps = max(3, int(abs(end - start) / 0.06))
        for i in range(steps + 1):
            a = start + (end - start) * i / steps
            pts.append((cx + math.cos(a) * self.spec["reach"],
                        cy + math.sin(a) * self.spec["reach"]))
        pygame.draw.polygon(overlay, (*color, 70), pts)

        # само лезвие в текущей позиции
        tip = (cx + math.cos(blade) * self.spec["reach"],
               cy + math.sin(blade) * self.spec["reach"])
        pygame.draw.line(overlay, (*color, 230), (cx, cy), tip, 4)


# ================================================================ ТИП 2
class DelayedHitboxAttack(MeleeAttack):
    """
    Удар с задержкой существования зоны (нож, катана).
    Направление фиксируется В МОМЕНТ удара, а зона живёт
    hitbox_time СЕКУНД ПОСЛЕ windup — и продолжает ранить всех,
    кто в неё войдёт. Зона «прилипает» к герою (следует за ним),
    но не разворачивается за мышью.
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.zone = None

    def _on_start(self, owner, game):
        self.zone = {
            "angle": owner.angle,
            "delay": self.spec.get("windup", 0.0),
            "life": self.spec["hitbox_time"],
            "hit_ids": set(),
        }

    def _tick(self, dt, owner, game):
        zone = self.zone
        if zone is None:
            return
        if zone["delay"] > 0.0:
            zone["delay"] -= dt          # анимация взмаха — зоны ещё нет
            return
        zone["life"] -= dt
        if zone["life"] <= 0.0:
            self.zone = None
            return

        reach = self.spec["reach"]
        half = math.radians(self.spec["arc_deg"]) / 2
        for enemy in game.nearby_enemies(owner.x, owner.y, reach):
            if not enemy.alive or id(enemy) in zone["hit_ids"]:
                continue
            dx, dy = enemy.x - owner.x, enemy.y - owner.y
            dist = math.hypot(dx, dy)
            if dist > reach + enemy.radius:
                continue
            rel = angle_diff(math.atan2(dy, dx), zone["angle"])
            margin = math.atan2(enemy.radius, max(dist, 1.0))
            if abs(rel) <= half + margin:
                zone["hit_ids"].add(id(enemy))
                self.hit(owner, game, enemy, self.damage_of(owner, self.spec),
                         (math.cos(zone["angle"]), math.sin(zone["angle"])),
                         self.spec["knockback"])

    def draw(self, overlay, camera, owner):
        zone = self.zone
        if zone is None or zone["delay"] > 0.0:
            return
        cx, cy = camera.to_screen(owner.x, owner.y)
        alpha = int(130 * zone["life"] / self.spec["hitbox_time"])
        half = math.radians(self.spec["arc_deg"]) / 2
        pts = sector_points(cx, cy, self.spec["reach"],
                            zone["angle"], half)
        color = self.spec["color"]
        pygame.draw.polygon(overlay, (*color, max(20, alpha)), pts)
        pygame.draw.polygon(overlay, (*color, min(255, alpha + 70)), pts, 2)


# ================================================================ ТИП 3
class ShockwaveAttack(MeleeAttack):
    """Hammer impact with expanding, independently tracked shockwave rings."""

    def __init__(self, spec):
        super().__init__(spec)
        self.waves = []
        self.resonance_point = None
        self.resonance_hits = 0
        self.charge_multiplier = 1.0
        self.fissures = []

    def _on_start(self, owner, game):
        angle = owner.angle
        reach = self.spec.get("handle_base", 95.0)
        if self.mods.get("variable_handle", 0):
            target = getattr(owner, "aim_pos", (owner.x, owner.y))
            reach = max(self.spec.get("handle_min", 48.0), min(
                self.spec.get("handle_max", 235.0)
                + self.mods.get("handle_max_add", 0.0),
                math.hypot(target[0] - owner.x, target[1] - owner.y)))
        cx = owner.x + math.cos(angle) * reach
        cy = owner.y + math.sin(angle) * reach
        if self.resonance_point and math.hypot(cx - self.resonance_point[0], cy - self.resonance_point[1]) < 100:
            self.resonance_hits = min(3, self.resonance_hits + 1)
        else:
            self.resonance_hits = 1
        self.resonance_point = (cx, cy)
        charge = self.charge_multiplier
        self.charge_multiplier = 1.0
        if charge >= 1.45 or self.mods.get("fissure", 0):
            fissure_radius = 65 + 35 * (charge - 1)
            if self.mods.get("fissure", 0):
                fissure_radius = max(fissure_radius, 80.0)
            self.fissures.append({
                "cx": cx, "cy": cy, "radius": fissure_radius,
                "time": 3.5, "max_time": 3.5,
                "slow": self.mods.get("fissure_slow", 0.18),
            })
        relics = self.mods.get("world_relics", ())
        ring_count = max(3 if "quake" in relics else 1,
                         int(self.mods.get("quake_rings", 1)))
        resonance_bonus = self.mods.get("resonance_bonus", 0.0)
        for i in range(ring_count):
            self.waves.append({
                "cx": cx, "cy": cy, "age": -i * 0.13,
                "hit_ids": set(),
                "radius": self.spec["radius"] * (1 + i * 0.24)
                          * (1 + self.mods.get("resonance_radius", 0.0)
                             * (self.resonance_hits - 1)),
                "damage": charge * (0.65 ** i)
                          * (1 + (0.12 + resonance_bonus)
                             * (self.resonance_hits - 1)),
            })

    def _tick(self, dt, owner, game):
        duration = max(0.01, self.spec["wave_time"])
        surviving_fissures = []
        for fissure in self.fissures:
            fissure["time"] -= dt
            if fissure["time"] <= 0:
                continue
            surviving_fissures.append(fissure)
            for enemy in game.nearby_enemies(fissure["cx"], fissure["cy"], fissure["radius"]):
                if enemy.alive and math.hypot(enemy.x - fissure["cx"], enemy.y - fissure["cy"]) <= fissure["radius"] + enemy.radius:
                    apply_slow(enemy, fissure.get("slow", 0.18), 0.55)
        self.fissures = surviving_fissures
        active = []
        for wave in self.waves:
            wave["age"] += dt
            if wave["age"] < 0:
                active.append(wave)
                continue
            if wave["age"] > duration:
                continue
            radius = wave["radius"] * min(1, wave["age"] / duration)
            cx, cy = wave["cx"], wave["cy"]
            for enemy in game.nearby_enemies(cx, cy, radius):
                if not enemy.alive or id(enemy) in wave["hit_ids"]:
                    continue
                dist = math.hypot(enemy.x - cx, enemy.y - cy)
                if dist > radius + enemy.radius:
                    continue
                wave["hit_ids"].add(id(enemy))
                falloff = max(0.0, 1.0 - dist / wave["radius"])
                scale = (0.5 + 0.5 * falloff) * wave["damage"]
                scale *= 1.0 + self.mods.get("epicenter_damage", 0.0) * falloff
                self.hit(owner, game, enemy, self.damage_of(owner, self.spec) * scale,
                         self._knock_dir(cx, cy, enemy.x, enemy.y),
                         self.spec["knockback"] * scale)
                slow = self.mods.get("shock_slow", 0.0)
                if slow and enemy.alive:
                    enemy.slow_timer = max(enemy.slow_timer, slow)
                    enemy.slow_factor = min(enemy.slow_factor, 0.55)
            active.append(wave)
        self.waves = active

    def draw(self, overlay, camera, owner):
        for fissure in self.fissures:
            x, y = camera.to_screen(fissure["cx"], fissure["cy"])
            radius = int(fissure["radius"])
            alpha = int(125 * fissure["time"] / fissure["max_time"])
            pygame.draw.circle(overlay, (125, 75, 40, alpha // 3), (int(x), int(y)), radius)
            for i in range(7):
                angle = i * math.tau / 7
                inner = (int(x + math.cos(angle) * radius * 0.15), int(y + math.sin(angle) * radius * 0.15))
                outer = (int(x + math.cos(angle + 0.2) * radius * 0.9), int(y + math.sin(angle + 0.2) * radius * 0.9))
                pygame.draw.line(overlay, (245, 148, 70, alpha), inner, outer, 3)
        duration = max(0.01, self.spec["wave_time"])
        for wave in self.waves:
            if wave["age"] < 0:
                continue
            progress = min(1.0, wave["age"] / duration)
            cx, cy = camera.to_screen(wave["cx"], wave["cy"])
            radius = max(1, int(wave["radius"] * progress))
            alpha = max(25, int(180 * (1.0 - progress)))
            color = self.spec["color"]
            pygame.draw.circle(overlay, (*color, alpha // 4), (int(cx), int(cy)), radius)
            pygame.draw.circle(overlay, (*color, alpha), (int(cx), int(cy)), radius, 7)
            pygame.draw.circle(overlay, (*color, min(255, alpha + 55)),
                               (int(cx), int(cy)), max(3, int(15 * (1.0 - progress))), 2)


# ================================================================ ТИП 4
class PassiveAuraAttack(MeleeAttack):
    """
    Пассивная контактная аура (щит).
    Работает сама по себе: бьёт каждого врага в радиусе раз в tick
    секунд и слегка отбрасывает его. Нажатия не требует.
    """

    is_passive = True

    def __init__(self, spec):
        super().__init__(spec)
        self.ticks = {}          # id(врага) → остаток до следующего удара
        self.heal_timer = 0.0    # «Пульс»: собственная периодичность лечения

    def _on_start(self, owner, game):
        pass                      # пассивную атаку «нажать» нельзя

    def _tick(self, dt, owner, game):
        heal = self.mods.get("aura_heal", 0.0)
        if heal:
            self.heal_timer -= dt
            if self.heal_timer <= 0.0:
                owner.heal(heal)
                self.heal_timer = max(0.25, self.mods.get("aura_heal_interval", 2.0))
        for eid in list(self.ticks):
            self.ticks[eid] -= dt

        radius = self.spec["radius"]
        for enemy in game.nearby_enemies(owner.x, owner.y, radius):
            if not enemy.alive:
                self.ticks.pop(id(enemy), None)
                continue
            dist = math.hypot(enemy.x - owner.x, enemy.y - owner.y)
            if dist > radius + enemy.radius:
                continue
            eid = id(enemy)
            if self.ticks.get(eid, 0.0) > 0.0:
                continue          # этого врага аура уже ударила в tick-окне
            self.ticks[eid] = self.spec["tick"]
            self.hit(owner, game, enemy, self.damage_of(owner, self.spec),
                     self._knock_dir(owner.x, owner.y, enemy.x, enemy.y),
                     self.spec["knockback"])

        # чистим записи, чей таймер истёк (враг ушёл из радиуса или умер)
        for eid in [k for k, v in self.ticks.items() if v <= 0.0]:
            del self.ticks[eid]

    def draw(self, overlay, camera, owner):
        cx, cy = camera.to_screen(owner.x, owner.y)
        radius = self.spec["radius"]
        color = self.spec["color"]
        pygame.draw.circle(overlay, (*color, 45), (int(cx), int(cy)),
                           int(radius))
        pygame.draw.circle(overlay, (*color, 150), (int(cx), int(cy)),
                           int(radius), 3)


# ================================================================ РЕЕСТР
# Сюда добавляется ЛЮБОЙ новый тип атаки — одна строка, без правок оружия.
ATTACK_TYPES = {
    "arc_slash": ArcSlashAttack,
    "delayed": DelayedHitboxAttack,
    "shockwave": ShockwaveAttack,
    "aura": PassiveAuraAttack,
}


def create_attack(spec):
    cls = ATTACK_TYPES.get(spec.get("attack"))
    if cls is None:
        raise ValueError(f"Неизвестный тип атаки: {spec.get('attack')!r}")
    return cls(spec)