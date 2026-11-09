"""
Герой: движение, прицел, фонарик, здоровье, экипировка.
"""
import math
import random

import pygame

import soundbank
import spritebank
import visuals
from settings import (
    DASH_COOLDOWN,
    DASH_INVULN,
    DASH_SPEED,
    DASH_STRIKE_WINDOW,
    DASH_TIME,
    FLASH_DURATION,
    MEDKIT_HEAL,
    PLAYER_MAX_HP,
    PLAYER_RADIUS,
    PLAYER_SPEED,
)
from equipment import Equipment
from game_object import GameObject
from projectiles import Bullet, Grenade, MuzzleFlash, Spark
from utils import mix, normalize
from weapon_data import FIREARMS, MELEE
from weapons import create_weapon


class Player(GameObject):
    """Управляемый игрок. Владеет экипировкой, фонариком и здоровьем."""

    def __init__(self, x, y):
        super().__init__(x, y)
        self.radius = PLAYER_RADIUS
        self.base_speed = PLAYER_SPEED   # «чистая» скорость без артефактов
        self.speed = self.base_speed
        self.hp = PLAYER_MAX_HP
        self.max_hp = PLAYER_MAX_HP

        # --- усиления сектора (M12): живут до конца вылазки ---
        self.boons = []                 # выбранные карты (для интерфейса)
        self.boon_damage_mult = 1.0
        self.boon_speed_mult = 1.0
        self.boon_hurt_mult = 1.0       # <1 — герой получает меньше урона
        self.boon_loot_mult = 1.0
        self.boon_fire_rate_mult = 1.0  # <1 — оружие стреляет чаще
        self.boon_heal_mult = 1.0
        self.boon_regen = 0.0           # HP в секунду
        self.boon_pierce = 0
        self.boon_execute = 0.0         # бонус урона по раненым целям
        self.boon_lifesteal = 0.0
        self.boon_dash_mult = 1.0

        # --- общее древо героя (единая доска навыков) ---
        self.skill_nodes = set()        # id купленных узлов героя
        self.skill_mods = {}            # агрегированные бонусы героя

        # --- подготовка оружия (M13) ---
        # Живёт на герое, а не на экземпляре оружия: прогресс другой
        # школы не исчезает при продаже ствола. Жетоны — валюта, которая
        # позволяет развивать школу, даже если оружие ещё не получено.
        self.weapon_training = {key: 0 for key in (*FIREARMS, *MELEE)}
        self.weapon_tokens = {key: 0 for key in (*FIREARMS, *MELEE)}
        # Купленные ветви переживают смену ствола. Без этого возврат к
        # пистолету после тренировки дробовика обнулял бы «Арсенал» и
        # заставлял покупать одни и те же насадки заново.
        self.weapon_tree_state = {}

        self.angle = 0.0         # куда смотрит (и куда светит фонарик)
        self.move_dir = (0.0, 0.0)
        self.trigger_held = False
        # Край нажатия/отпускания ЛКМ для заряжаемого оружия. Без него
        # удержание не отличить от нового нажатия, и заряд стартовал бы
        # каждый кадр.
        self._firearm_trigger_was_held = False
        self.melee_held = False
        self.melee_was_held = False
        self.hammer_charge = 0.0
        self.flash_timer = 0.0   # остаток света вспышки выстрела
        self.hurt_timer = 0.0    # мигание при уроне + короткая неуязвимость
        self.invuln_timer = 0.0  # неуязвимость переката (отдельно от вспышки)
        self.kick = 0.0          # отдача оружия для визуального толчка
        self.walk_phase = 0.0
        self.empty_click_cd = 0.0

        # РЫВОК (Space): короткий перекат с i-кадрами. Даёт игроку
        # пространство для реакции — бой перестаёт быть «стою и терплю».
        self.dash_cd = 0.0
        self.dash_timer = 0.0
        self.dash_dir = (1.0, 0.0)
        self.dash_strike_timer = 0.0  # окно бонуса «удар после рывка»
        self.retaliate_cd = 0.0      # «Отражение» щита: пауза между ответами

        # слоты + патроны + стартовое снаряжение
        self.equipment = Equipment()
        self.equipment.equip("firearm", create_weapon("pistol"))
        self.equipment.equip("melee", create_weapon("knife"))

        # ВЕТВИ ОРУЖИЯ (M11): где стоит прицел и как долго держим его на цели
        self.aim_pos = (x, y)        # прицел в мировых координатах
        self.aim_target = None       # враг под прицелом (или None)
        self.aim_time = 0.0          # секунд непрерывного удержания
        # 1.0 — обычный обзор; <1 — снайперская оптика. Обновляет Game.
        self.camera_zoom = 1.0

    # ------------------------------------------------------------ ПОДГОТОВКА
    def add_weapon_training(self, weapon_key, amount=1, cap=None):
        """Повышает подготовку школы; cap ограничивает вклад жетонов."""
        if amount <= 0:
            return 0
        current = int(self.weapon_training.get(weapon_key, 0))
        if cap is not None:
            amount = min(amount, max(0, int(cap) - current))
        self.weapon_training[weapon_key] = current + amount
        return amount

    def add_weapon_token(self, weapon_key, amount=1):
        """Жетон тренировки: потратится при покупке зависимого навыка."""
        if amount > 0:
            self.weapon_tokens[weapon_key] = (
                self.weapon_tokens.get(weapon_key, 0) + amount)

    def weapon_token_count(self, weapon_key):
        return int(self.weapon_tokens.get(weapon_key, 0))

    def remember_weapon_tree(self, weapon):
        """Запоминает покупки оружия перед тем, как оно покинет слот."""
        if weapon is None:
            return
        self.weapon_tree_state[weapon.key] = {
            "nodes": tuple(getattr(weapon, "node_order", ())),
            "mods": dict(getattr(weapon, "mods", {})),
            "main_branch": getattr(weapon, "main_branch", None),
        }

    def restore_weapon_tree(self, weapon):
        """
        Возвращает купленные узлы на НОВЫЙ экземпляр оружия.

        Уровни улучшений при смене сбрасываются (это отдельная экономика),
        а ветви — нет: они уже оплачены и определяют стиль игры. Повторно
        подготовки не начисляются, деньги не списываются.
        """
        state = self.weapon_tree_state.get(getattr(weapon, "key", None))
        if not state:
            return False
        weapon.nodes = set(state["nodes"])
        weapon.node_order = list(state["nodes"])
        weapon.mods = dict(state["mods"])
        weapon.main_branch = state["main_branch"]
        # Ленивый импорт: player.py и skill_tree.py не должны зависеть
        # друг от друга на этапе загрузки модулей.
        import skill_tree
        for node_id in state["nodes"]:
            _, node = skill_tree.find_node(weapon, node_id)
            if node is None:       # данные дерева изменились — узел пропал
                continue
            for key, value in node.get("apply", {}).items():
                skill_tree._apply_spec(weapon.spec, key, value)
        return True

    def cycle_firearm_mode(self, game=None):
        """V: следующий открытый режим пистолета (только при насадках)."""
        weapon = self.firearm
        if weapon is None or weapon.key != "pistol":
            return False
        if not getattr(weapon, "mode_switch_unlocked", False):
            if game is not None:
                game.toast("Режимы огня открывает «Полевой устав» в ветви «Арсенал»",
                           2.0, color=(240, 190, 110))
            return False
        mode = weapon.cycle_mode()
        if mode is None:
            if game is not None:
                game.toast("Купите насадок в ветви «Арсенал», чтобы сменить режим",
                           1.8, color=(240, 190, 110))
            return False
        soundbank.play("ui_move", 0.55)
        if game is not None:
            game.toast(f"Режим огня: {weapon.mode_name}", 1.4,
                       color=weapon.mode_color)
        return True

    # ------------------------------------------------------------ ДРЕВО ГЕРОЯ
    def skill_mod(self, name, default=0.0):
        """Значение общего навыка героя (0/1 — если узел не куплен)."""
        return self.skill_mods.get(name, default)

    @property
    def execute_bonus(self):
        """Бонус урона по раненым целям: усиление сектора + древо героя."""
        return self.boon_execute + self.skill_mod("execute_add", 0.0)

    # ------------------------------------------------------------ ВВОД
    def handle_input(self, keys, mouse_world_pos, mouse_buttons):
        """
        Читает клавиатуру и мышь, сохраняя результат в состояние объекта.

        mouse_world_pos — координаты мыши уже ПЕРЕВЕДЁНЫ в мировые
        координаты (Game делает это через камеру), поэтому герой
        не знает ничего о существовании экрана.
        """
        dx = dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += 1
        self.move_dir = normalize(dx, dy)

        self.angle = math.atan2(mouse_world_pos[1] - self.y,
                                mouse_world_pos[0] - self.x)
        self.aim_pos = mouse_world_pos   # для «Метки» (ветвь баллистики)
        self.trigger_held = bool(mouse_buttons[0])
        self.melee_held = bool(mouse_buttons[2])     # ПКМ — ближний бой

    # ------------------------------------------------------------ РЫВОК
    def refresh_speed(self):
        """Пересобирает скорость из базы, артефакта и усилений сектора."""
        artifact = self.equipment.get("passive_artifact")
        multiplier = 1.0
        if artifact is not None:
            multiplier = artifact.spec.get("speed_mult", 1.0)
        self.speed = (self.base_speed * multiplier * self.boon_speed_mult
                      * (1.0 + self.skill_mod("speed_add")))

    def start_dash(self):
        """Space: перекат в сторону движения (или в сторону прицела)."""
        if self.dash_cd > 0.0 or not self.alive:
            return False
        length = math.hypot(*self.move_dir)
        if length > 0.1:
            self.dash_dir = (self.move_dir[0] / length, self.move_dir[1] / length)
        else:
            self.dash_dir = (math.cos(self.angle), math.sin(self.angle))
        self.dash_cd = (DASH_COOLDOWN * self.boon_dash_mult
                        * self.skill_mod("dash_cd_mul", 1.0))
        self.dash_timer = DASH_TIME
        self.dash_strike_timer = DASH_STRIKE_WINDOW
        self.invuln_timer = max(self.invuln_timer,
                                DASH_INVULN + self.skill_mod("dash_invuln_add"))
        soundbank.play("dash", 0.55)
        return True

    # ------------------------------------------------------------ ЛОГИКА
    def update(self, dt, game):
        # таймеры
        self.dash_cd = max(0.0, self.dash_cd - dt)
        self.dash_strike_timer = max(0.0, self.dash_strike_timer - dt)
        self.invuln_timer = max(0.0, self.invuln_timer - dt)
        self.retaliate_cd = max(0.0, self.retaliate_cd - dt)
        self.kick = max(0.0, self.kick - dt * 34.0)
        self.empty_click_cd = max(0.0, self.empty_click_cd - dt)

        # усиление «Регенерация» и одноимённый навык героя
        regen = self.boon_regen + self.skill_mod("regen_add")
        if regen > 0.0 and self.alive:
            self.heal(regen * dt)

        if self.dash_timer > 0.0:
            # перекат: движемся сами, обычный ввод движения временно молчит
            self.dash_timer = max(0.0, self.dash_timer - dt)
            step = DASH_SPEED * dt
            nx = self.x + self.dash_dir[0] * step
            ny = self.y + self.dash_dir[1] * step
            self.x, self.y = game.world.resolve_circle(nx, ny, self.radius)
            self.walk_phase += dt * 24.0
            game.spawn_dash_ghost(self)
        else:
            # движение по осям, чтобы скользить вдоль стен, а не залипать.
            # «Подвижный контур» пушки добавляет скорость именно во время
            # заряда: мобильность — свойство билда, а не глобальный бафф.
            move_scale = 1.0
            carried = self.equipment.get("firearm")
            if (carried is not None and getattr(carried, "is_charging", False)
                    and getattr(carried, "uses_charge", False)):
                move_scale += float(carried.mod("charge_move_bonus", 0.0))
            self.x += self.move_dir[0] * self.speed * dt * move_scale
            self.x, self.y = game.world.resolve_circle(self.x, self.y, self.radius)
            self.y += self.move_dir[1] * self.speed * dt * move_scale
            self.x, self.y = game.world.resolve_circle(self.x, self.y, self.radius)
            if self.move_dir[0] or self.move_dir[1]:
                self.walk_phase += dt * 10.0

        # таймеры героя
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.hurt_timer = max(0.0, self.hurt_timer - dt)

        # таймеры оружия (откат, конец перезарядки)
        weapon = self.equipment.get("firearm")
        if weapon is not None:
            self._track_aim(dt, game)   # «Метка»: прицел держится на враге
            weapon.update(dt)
            if getattr(weapon, "uses_disc", False):
                # Возврат диска — не оружие, а герой: заряд/время зависят
                # от расстояния до него, а не от таймера стваола.
                self._update_disc(game, weapon)
            if getattr(weapon, "uses_charge", False):
                self._update_charged_weapon(dt, game, weapon)
            elif self.trigger_held:
                self.try_attack(game)
        else:
            self._firearm_trigger_was_held = False

        # ближний бой: обновляется ВСЕГДА (аура щита работает пассивно),
        # а ПКМ просто передаётся оружию — оно само решит, что делать
        melee = self.equipment.get("melee")
        if melee is not None:
            melee.update(dt, self, game)
            if melee.key == "hammer":
                if self.melee_held:
                    if not self.melee_was_held and melee.attack.cooldown > 0:
                        self.hammer_charge = 0.0
                    else:
                        self.hammer_charge = min(1.5, self.hammer_charge + dt)
                elif self.melee_was_held:
                    if melee.attack.cooldown <= 0:
                        melee.attack.charge_multiplier = 1.0 + 1.2 * min(1.0, self.hammer_charge / 1.5)
                        melee.try_attack(self, game)
                    self.hammer_charge = 0.0
            else:
                self.hammer_charge = 0.0
                if self.melee_held:
                    melee.try_attack(self, game)
            self.melee_was_held = self.melee_held

        # активный артефакт: тикает кулдаун и длительные эффекты (рывок)
        artifact = self.equipment.get("active_artifact")
        if artifact is not None:
            artifact.update(dt, self, game)

        # пассивный тоже может жить по таймеру — например, перезарядка
        # «Сердца титана» (M7). У остальных это пустой метод базы.
        passive = self.equipment.get("passive_artifact")
        if passive is not None:
            passive.update(dt, self, game)

    @property
    def damage_mult(self):
        """
        Итоговый множитель урона: пассивный артефакт × усиления сектора.
        Пока слотов и карт нет — 1.0, и урон не меняется.
        """
        artifact = self.equipment.get("passive_artifact")
        base = artifact.damage_mult if artifact is not None else 1.0
        return (base * self.boon_damage_mult
                * (1.0 + self.skill_mod("damage_add")))

    @property
    def firearm(self):
        """Экипированное огнестрельное оружие (или None)."""
        return self.equipment.get("firearm")

    @property
    def melee(self):
        """Экипированное оружие ближнего боя (или None)."""
        return self.equipment.get("melee")

    def _track_aim(self, dt, game):
        """
        Слежение за прицелом для ветви «Баллистический расчёт» (M11).

        Пока прицел держится на одном враге, растёт aim_time — по нему
        «Метка» (0.8 с) и «Расчёт траектории» (1.5 с) решают, чем
        станет этот выстрел. Цель видна ей самой (жёлтый ромб).
        """
        weapon = self.firearm
        if weapon is None or not (weapon.mod("aim_mark")
                                  or weapon.mod("aim_full_mul")):
            self.aim_target = None
            self.aim_time = 0.0
            return
        target = None
        # В отдалённом обзоре метка цепляет цель чуть дальше от курсора:
        # это компенсирует меньший экранный размер врага.
        grab = 10.0
        if getattr(game.camera, "is_zoomed", False):
            grab += max(0.0, float(weapon.mod("zoom_aim_mark_add", 0.0)))
        for enemy in game.enemies:
            if not enemy.alive:
                continue
            if math.hypot(enemy.x - self.aim_pos[0],
                          enemy.y - self.aim_pos[1]) <= enemy.radius + grab:
                target = enemy
                break
        if target is None:
            if self.aim_target is not None:
                self.aim_target.aim_mark = 0.0
            self.aim_target = None
            self.aim_time = 0.0
        elif target is self.aim_target:
            self.aim_time += dt
            target.aim_mark = self.aim_time   # врагу — для индикатора
        else:
            self.aim_target = target          # новая цель — таймер с нуля
            self.aim_time = 0.0
            target.aim_mark = 0.0

    def _update_charged_weapon(self, dt, game, weapon):
        """
        Край нажатия/отпускания ЛКМ для энергопушки.

        Важно: выстрел рождается ТОЛЬКО при отпускании после достаточного
        заряда. Ранний отпуск — отмена без патрона и без пули. Если герой
        умер, заряд снимается до проверки кнопки, поэтому посмертного
        выстрела не бывает.
        """
        if not self.alive:
            weapon.cancel_charge()
            self._firearm_trigger_was_held = False
            return
        held = bool(self.trigger_held)
        if not held:
            if self._firearm_trigger_was_held and weapon.is_charging:
                result = weapon.release_charge(self)
                if result == "fire":
                    self._fire_charged(game, weapon)
                elif result == "cancel":
                    # Слышимая, но тихая отмена: игрок понимает, что
                    # выстрела не было, и не ищет пропавший патрон.
                    soundbank.play("empty", 0.16)
            self._firearm_trigger_was_held = False
            return

        if not weapon.is_charging and weapon.can_fire:
            if weapon.begin_charge():
                soundbank.play(weapon.mode_profile.get(
                    "charge_start_sound",
                    weapon.spec.get("charge_start_sound", "spit_charge")), 0.35)
        elif (not weapon.is_charging and not weapon.can_fire
              and weapon.loaded < weapon.rounds_per_shot
              and not weapon.is_reloading):
            self.start_reload()

        if weapon.is_charging:
            event = weapon.advance_charge(dt, self)
            if event == "full":
                soundbank.play(weapon.mode_profile.get(
                    "charge_full_sound",
                    weapon.spec.get("charge_full_sound", "lightning")), 0.48)
        self._firearm_trigger_was_held = True

    def _fire_charged(self, game, weapon):
        """Выпускает уже оплаченный и рассчитанный заряд пушки."""
        shot = weapon.resolve_shot(self)
        pellets, spread_deg = weapon.shot_params(self)
        ratio = shot.get("charge", 0.0)
        self.flash_timer = max(self.flash_timer, FLASH_DURATION * (1.0 + ratio))
        self.kick = 1.0 + 0.65 * ratio
        for shot_angle in weapon.shot_angles(self.angle, (pellets, spread_deg)):
            mx = self.x + math.cos(shot_angle) * weapon.muzzle_offset
            my = self.y + math.sin(shot_angle) * weapon.muzzle_offset
            game.bullets.append(Bullet(mx, my, shot_angle, **shot))
        fx = self.x + math.cos(self.angle) * weapon.muzzle_offset
        fy = self.y + math.sin(self.angle) * weapon.muzzle_offset
        game.effects.append(MuzzleFlash(
            fx, fy, self.angle,
            color=weapon.charge_color))
        game.on_shot(weapon)
        soundbank.play(weapon.mode_profile.get(
            "charge_sound", weapon.spec.get("charge_sound", "sniper")),
                       0.55 + 0.35 * ratio)
        if ratio >= 0.999:
            # Сам сигнал «заряд полон» уже прозвучал в момент набора 100%;
            # здесь добавляем только вес полного выстрела, без второго пика.
            game.camera.add_shake(1.4)

    def cancel_charge(self):
        """Снять заряд при паузе, смерти, смене ствола или перезарядке."""
        weapon = self.firearm
        if weapon is not None and getattr(weapon, "uses_charge", False):
            weapon.cancel_charge()
        self._firearm_trigger_was_held = False

    def try_attack(self, game):
        """
        Спуск курка. Здесь НЕТ ни урона, ни пуль — только решение
        «стрелять / перезаряжаться / ждать откат». Вся математика выстрела
        живёт в оружии (Firearm), а параметры СНАРЯДА этого конкретного
        выстрела собирает weapon.resolve_shot (слой ProjectileDefinition).
        """
        weapon = self.firearm
        if weapon is None or getattr(weapon, "uses_charge", False):
            return
        # Магнитный диск: пока снаряд в полёте, ЛКМ возвращает его, а не
        # тратит второй патрон. Это и есть «управление траекторией».
        if getattr(weapon, "uses_disc", False) and weapon.has_live_disc:
            if weapon.recall_discs():
                soundbank.play("lightning", 0.22)
            return
        # Режимы с ценой 2-3 патрона не должны «заклинивать» на остатке 1.
        if weapon.loaded < weapon.rounds_per_shot and not weapon.is_reloading:
            self.start_reload()      # авто-перезарядка при пустом магазине
            return
        if not weapon.can_fire:
            return

        weapon.consume_shot(self)
        weapon.cooldown *= (self.boon_fire_rate_mult
                            * self.skill_mod("fire_rate_mul", 1.0))
        self.flash_timer = FLASH_DURATION
        self.kick = 1.0
        shot = weapon.resolve_shot(self)   # база + артефакты + узлы дерева
        pellets, spread_deg = weapon.shot_params(self)
        for shot_angle in weapon.shot_angles(self.angle,
                                             (pellets, spread_deg)):
            mx = self.x + math.cos(shot_angle) * weapon.muzzle_offset
            my = self.y + math.sin(shot_angle) * weapon.muzzle_offset
            bullet = Bullet(mx, my, shot_angle, **shot)
            game.bullets.append(bullet)
            if getattr(weapon, "uses_disc", False):
                weapon.track_disc(bullet)
        # «Залп»: каждый N-й спуск выпускает дополнительные пули веером.
        # Патроны они не тратят, но и урона получают меньше (см. данные).
        if weapon.volley_ready:
            extra = weapon.volley_shot(shot)
            count = max(0, int(weapon.mod("volley_count", 0)))
            spread = math.radians(weapon.mod("volley_spread_deg", 0.0))
            for _ in range(count):
                shot_angle = self.angle + random.uniform(-spread / 2, spread / 2)
                mx = self.x + math.cos(shot_angle) * weapon.muzzle_offset
                my = self.y + math.sin(shot_angle) * weapon.muzzle_offset
                game.bullets.append(Bullet(mx, my, shot_angle, **extra))
            weapon.volley_ready = False
        # одна вспышка на выстрел (пуль может быть много)
        fx = self.x + math.cos(self.angle) * weapon.muzzle_offset
        fy = self.y + math.sin(self.angle) * weapon.muzzle_offset
        game.effects.append(MuzzleFlash(fx, fy, self.angle))
        game.on_shot(weapon)
        # звук выстрела выбирается ДАННЫМИ оружия и режима (weapon_data)
        soundbank.play(weapon.mode_profile.get(
            "sound", weapon.spec.get("sound", "shoot")))
        # Резак: выстрел мог закрутить тепло до предела — тогда сброс
        # происходит сразу после выстрела, а не вместо него.
        if getattr(weapon, "vent_pending", False):
            self._vent_weapon(game, weapon)

    def _update_disc(self, game, weapon):
        """Поимка диска: выстрел не тратится, звук и искры подтверждают."""
        for disc in list(weapon.live_discs):
            if not disc.alive:
                weapon.drop_disc(disc)
                continue
            if not disc.returning:
                continue
            if math.hypot(disc.x - self.x, disc.y - self.y) <= (
                    self.radius + disc.radius + 10):
                disc.caught = True
                disc.kill()
                weapon.drop_disc(disc)
                soundbank.play("pickup", 0.35)
                for _ in range(4):
                    game.effects.append(Spark(
                        self.x, self.y, random.uniform(0, math.tau),
                        disc.color, 120))
                chance = weapon.catch_refund_chance()
                if chance > 0.0 and random.random() < chance:
                    weapon.loaded = min(weapon.magazine_size,
                                        weapon.loaded + 1)
                    game.toast("Диск вернулся в магазин", 1.0,
                               color=(255, 216, 132))

    def _vent_weapon(self, game, weapon):
        """Принудительный сброс тепла: блокировка, толчок и цена ошибки."""
        weapon.start_vent()
        game.explode(self.x, self.y, weapon.vent_radius(),
                     weapon.vent_blast(),
                     float(weapon.spec.get("vent_knockback", 200.0)),
                     hurt_player=False,
                     slow=float(weapon.mod("vent_slow", 0.0)),
                     color=(255, 140, 96))
        # Сброс вредит и самому герою: это и есть риск горячей очереди.
        self.take_damage(weapon.vent_self_damage(), game)
        game.camera.add_shake(6.0)
        game.hitstop = max(getattr(game, "hitstop", 0.0), 0.12)
        soundbank.play("lightning", 0.5)
        game.toast("ПЕРЕГРЕВ — контур сброшен", 1.4, color=(255, 150, 110))

    def start_reload(self):
        """Просит оружие перезарядиться из пула боеприпасов."""
        weapon = self.firearm
        if weapon is not None and getattr(weapon, "uses_charge", False):
            # Ручная перезарядка — тоже прерывание: заряд не должен
            # «переехать» через анимацию и выстрелить после неё.
            self.cancel_charge()
        if weapon is not None and weapon.start_reload(self.equipment):
            soundbank.play("reload")
        elif self.empty_click_cd <= 0.0:
            soundbank.play("empty", 0.5)
            self.empty_click_cd = 0.45

    def throw_grenade(self, game):
        """Бросок гранаты (Q). Подсказка вместо тишины, если гранат нет."""
        if self.equipment.use_item("grenade"):
            game.grenades.append(Grenade(self.x, self.y, self.angle))
            soundbank.play("throw")
        else:
            soundbank.play("error", 0.4)
            game.toast("Гранат нет — их роняют бомберы", color=(240, 150, 110))

    def use_artifact(self, game):
        """Клавиша F: активная способность артефакта (если есть и готова)."""
        artifact = self.equipment.get("active_artifact")
        if artifact is None:
            soundbank.play("error", 0.4)
            game.toast("Активного артефакта нет", color=(240, 150, 110))
            return
        if not artifact.ready:
            soundbank.play("error", 0.35)
            game.toast(f"{artifact.name}: ещё {artifact.cooldown_timer:.1f} с",
                       color=(240, 190, 110))
            return
        if not artifact.activate(self, game):
            game.toast("Сейчас способность бесполезна", color=(240, 150, 110))

    def use_medkit(self, game=None):
        """Клавиша G: аптечка из расходников лечит на MEDKIT_HEAL."""
        if self.equipment.use_item("medkit"):
            self.heal(MEDKIT_HEAL)
            soundbank.play("heal")
        elif game is not None:
            soundbank.play("error", 0.4)
            game.toast("Аптечек нет", color=(240, 150, 110))

    def heal(self, amount):
        """Восстановление HP — не выше максимума (артефакты его меняют)."""
        self.hp = min(self.max_hp, self.hp + amount * self.boon_heal_mult
                      * (1.0 + self.skill_mod("heal_add")))

    def switch_firearm(self, weapon_key):
        """
        ВРЕМЕННЫЙ тестовый переключатель (клавиши 1/2/3).
        Старое оружие выбрасывается — в M5 на этом месте будет
        магазин и возврат процента денег за улучшения.
        """
        self.cancel_charge()
        # Смена ствола — это прерывание: летящий диск не должен «зависнуть»
        # в мире без своего оружия, а тепло резака не переезжает на новый
        # ствол. Иначе новая пушка начинала бы забег уже перегретой.
        carried = self.firearm
        if carried is not None:
            for disc in list(getattr(carried, "live_discs", [])):
                disc.kill()
            carried.live_discs = []
        weapon = create_weapon(weapon_key)
        self.restore_weapon_tree(weapon)
        self.equipment.equip("firearm", weapon)

    def switch_melee(self, weapon_key):
        """ВРЕМЕННЫЙ тестовый переключатель (клавиши 4..9)."""
        weapon = create_weapon(weapon_key)
        self.restore_weapon_tree(weapon)
        self.equipment.equip("melee", weapon)

    def take_damage(self, amount, game=None):
        if self.hurt_timer > 0.0 or self.invuln_timer > 0.0:
            return                    # неуязвимость, чтобы удар не съедал HP каждый кадр
        # пассивный артефакт может переписать урон («Кираса»)
        artifact = self.equipment.get("passive_artifact")
        if artifact is not None:
            amount = artifact.on_hurt(self, amount)
        melee = self.melee
        guard = melee.mod("shield_guard", 0.0) if melee is not None else 0.0
        if guard:
            amount *= max(0.0, 1.0 - guard)
        amount *= self.boon_hurt_mult * self.skill_mod("damage_taken_mul", 1.0)
        self.hp -= amount
        self.hurt_timer = 0.35
        soundbank.play("hurt")
        if game is not None:
            game.on_player_hurt(amount)
            if (melee is not None and melee.mod("retaliate_damage", 0.0)
                    and self.retaliate_cd <= 0.0):
                self.retaliate_cd = melee.mod("retaliate_cd", 2.5)
                game.explode(self.x, self.y,
                             melee.mod("retaliate_radius", 90.0),
                             melee.mod("retaliate_damage", 35.0),
                             160.0, hurt_player=False)
        if self.hp <= 0:
            # артефакт может спасти («Сердце титана», M7) — тогда живём
            if artifact is not None and artifact.on_fatal(self, amount):
                self.hp = 1
                if game is not None:
                    game.toast("Сердце титана спасло вас!",
                               color=(255, 214, 120))
            else:
                self.hp = 0
                self.cancel_charge()   # смерть не должна стрелять за игрока
                if game is not None:
                    game.on_player_death()
                self.kill()

    # ------------------------------------------------------------ ОТРИСОВКА
    def draw(self, screen, camera):
        cx, cy = camera.to_screen(self.x, self.y)
        bob = math.sin(self.walk_phase) * 1.4 if (self.move_dir[0] or self.move_dir[1]) else 0.0
        by = cy + bob

        # тень — привязывает героя к полу
        body_r = int(self.radius * 1.5)
        visuals.shadow(screen, cx, cy + 6, body_r, 1.0)

        # оружие рисует само себя — герой лишь поворачивает спрайт.
        # Отдача сдвигает ствол назад к герою.
        weapon = self.firearm
        if weapon is not None:
            sprite = pygame.transform.rotate(weapon.sprite,
                                             -math.degrees(self.angle))
            kick = -self.kick * 5.0
            screen.blit(sprite, sprite.get_rect(center=(cx + math.cos(self.angle) * kick,
                                                        by + math.sin(self.angle) * kick)))

        # melee-слот: рисуем поверх героя, чтобы черенок не терялся за телом.
        melee = self.equipment.get("melee")
        melee_sprite = melee.display_sprite() if melee is not None else None
        if melee_sprite is not None and melee.key != "shovel":
            sprite = pygame.transform.rotate(melee_sprite,
                                             -math.degrees(self.angle))
            screen.blit(sprite, sprite.get_rect(center=(cx, by)))

        body = visuals.character("player", body_r, self.angle)
        screen.blit(body, body.get_rect(center=(cx, by)))

        if melee_sprite is not None and melee.key == "shovel":
            sprite = pygame.transform.rotate(melee_sprite,
                                             -math.degrees(self.angle))
            handle_offset = 10.0
            center = (cx + math.cos(self.angle) * handle_offset,
                      by + math.sin(self.angle) * handle_offset)
            screen.blit(sprite, sprite.get_rect(center=center))

        # тёплый контур героя: даже в темноте видно, где центр управления
        visuals.draw_ring(screen, cx, by, body_r + 2, (86, 214, 202), 1, 70)

        if self.hurt_timer > 0.0:
            t = min(1.0, self.hurt_timer / 0.35)
            visuals.draw_hit_flash(screen, cx, by, body_r * 0.9, t)
        # щит/перекат: голубой ободок
        if self.invuln_timer > 0.0:
            t = min(1.0, self.invuln_timer / DASH_INVULN)
            visuals.draw_ring(screen, cx, by, body_r + 7, (150, 232, 255), 2,
                              int(190 * t))
        elif self.hurt_timer > 0.35:
            visuals.draw_ring(screen, cx, by, body_r + 6, (150, 220, 255), 2, 190)

        if weapon is not None and getattr(weapon, "uses_charge", False):
            self._draw_charge_bar(screen, cx, by, body_r, weapon)
        elif weapon is not None and getattr(weapon, "uses_heat", False):
            self._draw_heat_bar(screen, cx, by, body_r, weapon)

        # короткий луч-прицел от дула помогает читать направление огня
        if weapon is not None and not weapon.is_reloading:
            start = (cx + math.cos(self.angle) * (weapon.muzzle_offset + 2),
                     by + math.sin(self.angle) * (weapon.muzzle_offset + 2))
            end = (start[0] + math.cos(self.angle) * 34,
                   start[1] + math.sin(self.angle) * 34)
            aim_color = ((112, 232, 255) if getattr(weapon, "uses_charge", False)
                         else (255, 208, 120))
            pygame.draw.line(screen, aim_color, start, end, 1)

    def _draw_heat_bar(self, screen, cx, cy, body_r, weapon):
        """
        Шкала нагрева резака — под героем, той же шириной, что хитбокс.
        Оранжевая до 70%, красная после: видно, когда пора остывать,
        не читая цифры. Во время сброса полоса показывает таймер.
        """
        heat = weapon.heat_ratio
        venting = weapon.is_venting
        if heat <= 0.02 and not venting:
            return
        bar_w = max(8, int(round(self.radius * 2)))
        bar_h = 5
        x = int(round(cx - bar_w / 2))
        y = int(round(cy + body_r + 9))
        pygame.draw.rect(screen, (10, 14, 20), (x, y, bar_w, bar_h),
                         border_radius=2)
        if venting:
            total = max(0.001, float(weapon.spec.get("vent_time", 1.0)))
            filled = max(0.0, min(1.0, weapon.vent_timer / total))
            color = (255, 96, 84)
        else:
            filled = heat
            color = (255, 168, 96) if heat < 0.7 else (255, 96, 84)
        width = int(round(bar_w * filled))
        if width > 0:
            pygame.draw.rect(screen, color, (x, y, width, bar_h),
                             border_radius=2)
        if not venting and heat >= 0.7:
            pygame.draw.line(screen, (255, 240, 220),
                             (x + int(bar_w * 0.7), y - 2),
                             (x + int(bar_w * 0.7), y + bar_h + 2), 1)

    def _draw_charge_bar(self, screen, cx, cy, body_r, weapon):
        """
        Шкала заряда ПОД героем.

        Ширина полосы — ровно диаметр хитбокса игрока (2 * radius),
        поэтому заряд читается как часть тела, а не как ещё один HUD.
        Ранний порог отмечен насечкой: до неё отпускание безопасно
        отменяет выстрел. У «Полного импульса» полоса янтарная, пока
        не набраны 100% — видно, почему выстрела ещё не будет.
        """
        if not weapon.is_charging:
            return
        ratio = weapon.charge_ratio
        bar_w = max(8, int(round(self.radius * 2)))
        bar_h = 6
        x = int(round(cx - bar_w / 2))
        y = int(round(cy + body_r + 9))
        if weapon.charge_full:
            color = (238, 255, 255)
        elif weapon.mod("full_only"):
            color = (246, 182, 82)
        elif ratio + 1e-6 < weapon.min_charge:
            color = (214, 92, 82)
        else:
            color = mix((88, 192, 246), (132, 246, 255), ratio)

        # тёмная подложка и светлый кант: шкала не теряется на полу
        pygame.draw.rect(screen, (3, 6, 11),
                         (x - 2, y - 2, bar_w + 4, bar_h + 4),
                         border_radius=3)
        pygame.draw.rect(screen, (62, 76, 96),
                         (x - 2, y - 2, bar_w + 4, bar_h + 4), 1,
                         border_radius=3)
        if ratio > 0:
            fill_w = max(1, int(round(bar_w * ratio)))
            pygame.draw.rect(screen, color, (x, y, fill_w, bar_h),
                             border_radius=2)
            shine = pygame.Rect(x + 1, y + 1, max(0, fill_w - 2), 1)
            if shine.w > 1:
                pygame.draw.rect(screen, (255, 255, 255), shine)
            # яркий торец — заряд видно даже на бегу
            pygame.draw.line(screen, (255, 255, 255),
                             (x + fill_w - 1, y), (x + fill_w - 1, y + bar_h - 1), 1)

        # деления шкалы: 25/50/75% читаются без цифр
        for step in (0.25, 0.50, 0.75):
            sx = x + int(round(bar_w * step))
            pygame.draw.line(screen, (8, 14, 22), (sx, y), (sx, y + bar_h - 1), 1)

        # насечка минимального порога: левее неё выстрела не будет
        threshold = weapon.min_charge
        if 0.0 < threshold < 0.999:
            tx = x + int(round(bar_w * threshold))
            pygame.draw.line(screen, (238, 224, 196),
                             (tx, y - 2), (tx, y + bar_h + 1), 1)

        # процент сбоку: не закрывает тело и не спорит с полосой
        visuals.text(screen, f"{int(round(ratio * 100))}%",
                     (x + bar_w + 6, y - 2), 12, color, align="left")

        # заряд светится вокруг героя — видно даже боковым зрением
        glow_color = ((250, 246, 214) if weapon.charge_full
                      else (92, 220, 246))
        visuals.draw_ring(screen, cx, cy, body_r + 5 + int(4 * ratio),
                          glow_color, 2, int(55 + 130 * ratio))
        if weapon.charge_full:
            visuals.draw_ring(screen, cx, cy, body_r + 10, glow_color, 1, 140)
