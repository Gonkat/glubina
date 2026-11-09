"""
Главный класс игры: владеет всеми объектами и управляет циклом.
"""
import logging
import math
import os
import random
import sys

import pygame
import spritebank

import graphics_backend
import soundbank
import progression
from camera import Camera
from settings import (
    AMBIENT_VOLUME,
    BEACON_SURGE_MAX,
    CLOSE_RANGE,
    COMBO_BONUS_CAP,
    COMBO_BONUS_PER_KILL,
    COMBO_MAX,
    COMBO_WINDOW,
    BOSS_TOKEN_REWARD,
    ELITE_TOKEN_CHANCE,
    DEPTH_DAMAGE_GROWTH,
    DEPTH_HP_GROWTH,
    DEPTH_LOOT_GROWTH,
    DEPTH_SPEED_GROWTH,
    DIFFICULTIES,
    ENEMY_SPAWN_WEIGHTS,
    ENEMY_UNLOCK_TIMES,
    EXPLOSION_DAMAGE_PER_PX,
    EXPLOSION_MARK_TIME,
    EXPLOSION_SYNERGY,
    FPS,
    HITSTOP_BIG,
    HITSTOP_KILL,
    SECTOR_TINTS,
    SHAKE_EXPLOSION,
    SHAKE_HIT,
    SHAKE_HURT,
    SHAKE_SHOOT,
    SPAWN_FIRST_DELAY,
    SPAWN_INTERVAL_MIN,
    SPAWN_INTERVAL_START,
    SPAWN_MIN_DISTANCE,
    ENEMY_DESPAWN_DISTANCE,
    STATE_DESCENT,
    STATE_GAME_OVER,
    STATE_DIFFICULTY,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_SETTINGS,
    STATE_SHOP,
    STATE_TITLE,
    STATE_TREE,
    TITLE,
    WIDTH,
    HEIGHT,
)
from world import World
from drops import roll_drops
from weapon_data import TOKEN_KEYS, TOKEN_NAMES
from bosses import RECIPES, MATERIALS, roll_material, summon
from exploration import Exploration
from status_effects import (apply_bleed, apply_slow, apply_stun,
                           apply_vulnerable, update_bleed, update_dust)
from spatial_index import EnemySpatialIndex
from enemies import Bomber, Brute, Enemy, Runner, Spitter, Stalker, Tank
from hud import HUD
from lighting import LightingManager
from player import Player
from projectiles import (ArcBolt, Bullet, Casing, DashGhost, EnemyShot,
                         Explosion, FloatingText, Particle, Spark)
from shop import Shop
from shop_ui import ShopUI
from skill_tree_ui import SkillTreeUI
from descent import DescentManager
from descent_ui import DescentUI
from utils import circles_collide, distance, mix
import visuals


class Game:
    """Централизованное состояние раунда + игровой цикл."""

    def __init__(self):
        pygame.init()
        self.video = graphics_backend.VideoManager(WIDTH, HEIGHT)
        self.video.start()
        self.screen = self.video.surface
        pygame.display.set_caption(TITLE)
        self.clock = pygame.time.Clock()
        pygame.mouse.set_visible(False)

        self.world = World()               # чанки генерируются по мере исследования
        self.camera = Camera()
        self.hud = HUD()
        self.descent_ui = DescentUI()
        # прозрачный слой для визуала атак ближнего боя (альфа-канал!)
        self.attack_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        # Полотно мира при снайперской оптике: больше окна, затем
        # масштабируется в screen. При обычном обзоре не используется.
        self._world_layer = None
        self.difficulty_key = "normal"
        self.settings_menu_index = 0
        self.settings_notice = self.video.notice
        self.exit_requested = False
        self.best_score = 0
        self.title_index = 0
        self.reset()
        self.state = STATE_TITLE
        soundbank.play_loop("ambient", AMBIENT_VOLUME)

    # ------------------------------------------------------------ СОЗДАНИЕ МИРА
    def reset(self):
        """Создаёт (или пересоздаёт после смерти) все объекты раунда."""
        self.world = World()
        start_x, start_y = self.world.player_start()
        self.world.ensure_chunks_around(start_x, start_y, 2)
        self.player = Player(start_x, start_y)
        self.enemies = []
        self.enemy_shots = []   # снаряды дальних врагов (M12)
        self.enemy_index = EnemySpatialIndex()
        self.bullets = []
        self.effects = []
        self.drops = []        # монеты/патроны/гранаты на полу
        self.grenades = []     # брошенные гранаты (свой список: у них своя физика)
        self.shops = []
        self.exploration = Exploration(self.world)
        self.active_cooldown = 0.0
        self.boss_menu = False
        self.boss_selection = 0
        self.boss_notice = ""
        self.boss_notice_timer = 0.0
        self.debug_visible = False
        self._sync_shops()
        self.shop_ui = ShopUI()
        self.skill_ui = SkillTreeUI()   # единая доска навыков (T / Y)
        self.lighting = LightingManager()
        self.depth = 1
        self.descent = DescentManager(self, self.depth)
        self._tints = {}

        self.score = 0
        self.money = 0         # кошелёк: тратится в магазинах (M5)
        self.kills = 0
        self.elapsed = 0.0
        self.run_time = 0.0
        self.spawn_timer = SPAWN_FIRST_DELAY
        self.pause_menu_index = 0
        self.difficulty_menu_index = list(DIFFICULTIES).index(
            self.difficulty_key
        )

        # --- ощущение боя ---
        self.hitstop = 0.0
        self.recoil = 0.0
        self.damage_flash = 0.0
        self.hitmarker_timer = 0.0
        self.toast_text = ""
        self.toast_timer = 0.0
        self.toast_color = (255, 220, 140)
        self._ghost_timer = 0.0
        self._heartbeat_timer = 0.0
        self._hit_sound_cd = 0.0

        # --- серия убийств ---
        self.combo = 0
        self.combo_timer = 0.0
        self.max_combo = 0

        # --- статистика прогона ---
        self.shots_fired = 0
        self.shots_hit = 0
        self.boss_kills = 0

        self.state = STATE_PLAYING
        self.toast("СЕКТОР 01 · активируйте три сигнальных маяка", 5.0,
                   color=(150, 226, 210))
        self.camera.reset_zoom()
        self.camera.follow(self.player.x, self.player.y)
        self.camera.reset_shake()

    # ------------------------------------------------------------ ЦИКЛ
    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)  # защита от «скачка»
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
                    # Потеря фокуса — это прерывание, а не «игрок отпустил
                    # кнопку»: иначе заряд выстрелил бы в свёрнутое окно.
                    self.player.cancel_charge()
                elif self.state == STATE_TREE and event.type in (
                        pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                        pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
                    # доска навыков живёт мышью: перетаскивание, колесо и клики
                    self.skill_ui.handle_event(event, self)
                elif (event.type == pygame.MOUSEWHEEL
                      and self.state == STATE_PLAYING):
                    # Снайперская оптика: колесо только в бою и только
                    # когда куплена ветвь обзора. В меню/паузе не мешаем.
                    if not self.boss_menu:
                        self.handle_camera_zoom(event.y)
                elif event.type == pygame.KEYDOWN:
                    if self.state == STATE_TITLE:
                        self._handle_title(event.key)
                        continue
                    if self.state == STATE_DESCENT:
                        self.descent_ui.handle_event(event, self)
                        continue
                    if event.key == pygame.K_F5:
                        spritebank.reload()
                        if self.player.firearm is not None:
                            self.player.firearm.sprite = self.player.firearm._build_sprite()
                        melee = self.player.equipment.get("melee")
                        if melee is not None:
                            melee.sprite = melee._build_sprite()
                        for (cx, cy), chunk in self.world._chunks.items():
                            chunk["surface"] = self.world._render_chunk(
                                chunk["grid"], cx, cy)
                    elif event.key == pygame.K_ESCAPE:
                        if self.boss_menu:
                            self.boss_menu = False
                            continue
                        if self.state == STATE_SHOP:
                            self.close_shop()      # ESC в магазине = выйти из него
                        elif self.state == STATE_TREE:
                            self.close_tree()      # ESC в дереве = закрыть его
                        elif self.state == STATE_PLAYING:
                            self.player.cancel_charge()
                            self.state = STATE_PAUSED
                            self.pause_menu_index = 0
                        elif self.state in (STATE_SETTINGS, STATE_DIFFICULTY):
                            self.state = STATE_PAUSED
                        elif self.state == STATE_PAUSED:
                            self.state = STATE_PLAYING
                        elif self.state == STATE_GAME_OVER:
                            self.enter_title()
                    elif self.state == STATE_PAUSED:
                        self._handle_pause_menu(event.key)
                    elif self.state == STATE_SETTINGS:
                        self._handle_settings_menu(event.key)
                    elif self.state == STATE_DIFFICULTY:
                        self._handle_difficulty_menu(event.key)
                    elif event.key == pygame.K_r and self.state == STATE_GAME_OVER:
                        self.reset()
                    elif self.state == STATE_SHOP:
                        if event.key == pygame.K_e:
                            self.close_shop()      # E тоже закрывает
                        else:
                            self.shop_ui.handle_event(event, self)
                    elif self.state == STATE_TREE:
                        # Доска навыков: T/Y/E закрывают, остальное уходит
                        # в окно (WASD — камера, стрелки — узлы, Enter — купить).
                        if event.key in (pygame.K_t, pygame.K_y, pygame.K_e):
                            self.close_tree()
                        else:
                            self.skill_ui.handle_event(event, self)
                    elif self.state == STATE_PLAYING:
                        if self.boss_menu:
                            if event.key in (pygame.K_UP, pygame.K_w):
                                self.boss_selection = (self.boss_selection - 1) % len(RECIPES)
                            elif event.key in (pygame.K_DOWN, pygame.K_s):
                                self.boss_selection = (self.boss_selection + 1) % len(RECIPES)
                            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                                key = list(RECIPES)[self.boss_selection]
                                self.boss_notice = summon(self, key)
                                self.boss_notice_timer = 4.0
                                if self.boss_notice.startswith("Призван"):
                                    self.boss_menu = False
                            elif event.key == pygame.K_b:
                                self.boss_menu = False
                            continue
                        if event.key == pygame.K_b:
                            self.boss_menu = True
                        elif event.key == pygame.K_r:
                            self.player.start_reload()
                        elif event.key == pygame.K_v:
                            self.player.cycle_firearm_mode(self)
                        elif event.key == pygame.K_SPACE:
                            self.player.start_dash()          # перекат с i-кадрами
                        elif event.key == pygame.K_q:
                            self.player.throw_grenade(self)   # расходник
                        elif event.key == pygame.K_g:
                            self.player.use_medkit(self)      # расходник
                        elif event.key == pygame.K_f:
                            self.player.use_artifact(self)    # активный артефакт
                        elif event.key == pygame.K_e:
                            # приоритет: маяк/лифт -> сундук -> магазин
                            if not self.descent.interact(self):
                                if not self.exploration.open_nearest(self):
                                    self.try_open_shop()
                        elif event.key == pygame.K_t:
                            self.open_tree("firearm")
                        elif event.key == pygame.K_y:
                            self.open_tree("melee")
                        elif event.key == pygame.K_x:
                            self.use_melee_ability()
                        elif event.key == pygame.K_F3:
                            self.debug_visible = not self.debug_visible                  # дерево навыков
            if self.exit_requested:
                running = False
            if self.state == STATE_PLAYING:
                self.update(dt)
            self.draw()
            self.video.present()
        self.video.close()
        pygame.quit()

    def _handle_title(self, key):
        """Титульный экран: Начать / Сложность / Выход."""
        if key in (pygame.K_w, pygame.K_UP):
            self.title_index = (self.title_index - 1) % 3
            soundbank.play("ui_move")
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.title_index = (self.title_index + 1) % 3
            soundbank.play("ui_move")
        elif key in (pygame.K_a, pygame.K_LEFT, pygame.K_d, pygame.K_RIGHT):
            if self.title_index == 1:
                keys = list(DIFFICULTIES)
                step = -1 if key in (pygame.K_a, pygame.K_LEFT) else 1
                index = (keys.index(self.difficulty_key) + step) % len(keys)
                self.difficulty_key = keys[index]
                self.difficulty_menu_index = index
                soundbank.play("ui_move")
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.title_index == 0:
                self.reset()
                soundbank.play("open")
            elif self.title_index == 1:
                keys = list(DIFFICULTIES)
                index = (keys.index(self.difficulty_key) + 1) % len(keys)
                self.difficulty_key = keys[index]
                self.difficulty_menu_index = index
                soundbank.play("ui_move")
            else:
                self.exit_requested = True
        elif key == pygame.K_ESCAPE:
            self.exit_requested = True

    def _handle_pause_menu(self, key):
        if key in (pygame.K_UP, pygame.K_w):
            self.pause_menu_index = (self.pause_menu_index - 1) % 4
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.pause_menu_index = (self.pause_menu_index + 1) % 4
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.pause_menu_index == 0:
                self.state = STATE_PLAYING
            elif self.pause_menu_index == 1:
                self.state = STATE_SETTINGS
                self.settings_menu_index = 0
                self.settings_notice = ""
            elif self.pause_menu_index == 2:
                self.state = STATE_DIFFICULTY
                self.difficulty_menu_index = list(DIFFICULTIES).index(
                    self.difficulty_key
                )
            else:
                self.enter_title()

    def enter_title(self):
        """Выход в главное меню: раунд сбрасывается, рекорд остаётся."""
        self.reset()
        self.state = STATE_TITLE
        self.title_index = 0

    def _handle_settings_menu(self, key):
        # 0 громкость, 1 рендер, 2 видеоадаптер, 3 GPU-эффекты
        if key in (pygame.K_UP, pygame.K_w):
            self.settings_menu_index = (self.settings_menu_index - 1) % 4
            soundbank.play("ui_move")
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.settings_menu_index = (self.settings_menu_index + 1) % 4
            soundbank.play("ui_move")
        elif key in (pygame.K_LEFT, pygame.K_a):
            self._change_setting(-1)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self._change_setting(1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.settings_menu_index == 2:
                self._restart_with_video()
            else:
                self._change_setting(1)

    def _change_setting(self, step):
        index = self.settings_menu_index
        if index == 0:
            soundbank.set_volume(soundbank.get_volume() + 0.05 * step)
            return
        if index == 1:
            target = "cpu" if self.video.requested_mode == "opengl" else "opengl"
            self._set_render_mode(target)
            return
        if index == 2:
            self.video.cycle_adapter(step)
            self.settings_notice = self.video.notice
            return
        enabled = not self.video.effects
        self.video.set_effects(enabled)
        self.settings_notice = (
            "GPU-эффекты включены." if enabled
            else "GPU-эффекты выключены."
        )

    def _set_render_mode(self, mode):
        """Переключает presenter без сброса раунда и возвращает новый Surface."""
        previous = self.screen
        try:
            self.video.switch_mode(mode)
        except Exception as exc:
            logging.getLogger(__name__).exception("Could not switch renderer")
            self.settings_notice = f"Не удалось переключить рендер: {exc}"
            self.screen = previous
            return
        self.screen = self.video.surface
        pygame.display.set_caption(TITLE)
        pygame.mouse.set_visible(False)
        # Слои привязаны к старому Surface; пересоздадим их лениво.
        self._world_layer = None
        self.attack_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._tints.clear()
        if self.video.mode != self.video.requested_mode:
            self.settings_notice = self.video.notice or "OpenGL недоступен — оставлен CPU."
        elif self.video.mode == "opengl":
            self.settings_notice = f"Рендер: OpenGL · {self.video.active_renderer}"
        else:
            self.settings_notice = "Рендер: CPU · SDL"

    def _restart_with_video(self):
        """Сохраняет выбор и перезапускает игру, чтобы Windows применила GPU."""
        ok, message = self.video.apply_selected_preference()
        self.video.save()
        if not ok:
            self.settings_notice = message
            return
        self.settings_notice = "Перезапуск…"
        self.video.close()
        pygame.quit()
        if getattr(sys, "frozen", False):
            args = [sys.executable] + sys.argv[1:]
        else:
            args = [sys.executable] + sys.argv
        try:
            os.execv(sys.executable, args)
        except OSError as exc:
            logging.getLogger(__name__).exception("Could not restart game")
            self.settings_notice = f"Не удалось перезапустить игру: {exc}"
            pygame.init()
            self.video.start()
            self.screen = self.video.surface
            pygame.display.set_caption(TITLE)
            pygame.mouse.set_visible(False)

    def _handle_difficulty_menu(self, key):
        difficulty_keys = list(DIFFICULTIES)
        if key in (pygame.K_UP, pygame.K_w):
            self.difficulty_menu_index = (
                self.difficulty_menu_index - 1
            ) % len(difficulty_keys)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.difficulty_menu_index = (
                self.difficulty_menu_index + 1
            ) % len(difficulty_keys)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.difficulty_key = difficulty_keys[self.difficulty_menu_index]
            self.spawn_timer = min(self.spawn_timer, self._spawn_interval())
            self.state = STATE_PAUSED

    def update(self, dt):
        # камера живёт и во время «стопа кадра»: тряска должна доигрывать
        self.camera.update(dt)
        self._sync_camera_zoom()
        # Оружие читает это же значение для «дальних» бонусов ветвей.
        self.player.camera_zoom = self.camera.zoom
        if self.hitstop > 0.0:
            self.hitstop = max(0.0, self.hitstop - dt)
            return

        self.elapsed += dt
        self.run_time += dt
        self.boss_notice_timer = max(0.0, self.boss_notice_timer - dt)
        self.active_cooldown = max(0.0, self.active_cooldown - dt)
        self.recoil = max(0.0, self.recoil - dt * 3.4)
        self.damage_flash = max(0.0, self.damage_flash - dt * 3.0)
        self.hitmarker_timer = max(0.0, self.hitmarker_timer - dt)
        self.toast_timer = max(0.0, self.toast_timer - dt)
        self._ghost_timer = max(0.0, self._ghost_timer - dt)
        self._hit_sound_cd = max(0.0, self._hit_sound_cd - dt)

        # серия: убийства подряд дают больше денег, пауза — обнуляет
        if self.combo_timer > 0.0:
            self.combo_timer = max(0.0, self.combo_timer - dt)
            if self.combo_timer == 0.0:
                self.combo = 0

        # сердцебиение на низком HP — звуковая подсказка, а не только цвет
        hp_ratio = self.player.hp / max(1, self.player.max_hp)
        if hp_ratio < 0.32 and self.player.alive:
            self._heartbeat_timer -= dt
            if self._heartbeat_timer <= 0.0:
                soundbank.play("heartbeat", 0.65)
                self._heartbeat_timer = 0.85
        else:
            self._heartbeat_timer = 0.9

        # мышь сначала переводится в мировые координаты — дальше всё в мире
        mouse_world = self.camera.to_world(*pygame.mouse.get_pos())
        self.player.handle_input(
            pygame.key.get_pressed(),
            mouse_world,
            pygame.mouse.get_pressed(),
        )
        self.enemy_index.rebuild(self.enemies)
        self.player.update(dt, self)
        self.camera.follow(self.player.x, self.player.y)
        self.world.ensure_chunks_around(self.player.x, self.player.y, 2)
        self._sync_shops()
        self.exploration.update(self.player.x, self.player.y)
        self.descent.update(dt, self)

        # Удаляем врагов, оставшихся далеко позади игрока, до расчёта ИИ.
        # Это не убийства: опыт, монеты и предметы не начисляются.
        px, py = self.player.x, self.player.y
        despawn_distance_sq = ENEMY_DESPAWN_DISTANCE ** 2
        self.enemies = [
            enemy for enemy in self.enemies
            if enemy.alive and (getattr(enemy, "is_boss", False) or (enemy.x - px) ** 2 + (enemy.y - py) ** 2
            <= despawn_distance_sq)
        ]

        # враги
        self._update_spawner(dt)
        for enemy in self.enemies:
            # защита: сосед-бомбер мог убить этого врага СЕРИДИНОЙ
            # этого же цикла — мёртвому update() делать нечего
            if enemy.alive:
                update_bleed(enemy, dt, self)
                update_dust(enemy, dt, self)
            if enemy.alive:
                enemy.update(dt, self)
        self.enemy_index.rebuild(self.enemies)
        # магазины — «невидимая охрана»: враги не заходят в зону безопасности
        for shop in self.shops:
            shop.update(dt, self)
            for enemy in self.enemies:
                if enemy.alive:
                    shop.push_out(enemy)

        # пули
        for bullet in self.bullets:
            bullet.update(dt, self)
        self._check_bullet_hits()

        # снаряды дальних врагов
        for shot in self.enemy_shots:
            shot.update(dt, self)
        self._check_enemy_shot_hits()

        # эффекты
        for effect in self.effects:
            effect.update(dt, self)

        # гранаты (взрыв может родить новый эффект — список обновляется ниже)
        for grenade in self.grenades:
            grenade.update(dt, self)

        # добыча: покачивание, притяжение, подбор
        for drop in self.drops:
            drop.update(dt, self)

        # уборка мёртвых (списки пересоздаются — так Python чище)
        self.enemies = [e for e in self.enemies if e.alive]
        self.bullets = [b for b in self.bullets if b.alive]
        self.enemy_shots = [s for s in self.enemy_shots if s.alive]
        self.effects = [e for e in self.effects if e.alive]
        self.grenades = [g for g in self.grenades if g.alive]
        self.drops = [d for d in self.drops if d.alive]

        if not self.player.alive:
            self.state = STATE_GAME_OVER

    # ------------------------------------------------------------ СОБЫТИЯ БОЯ
    @property
    def combo_multiplier(self):
        """Множитель денег и очков за серию (1.0 … 2.6)."""
        bonus = min(COMBO_BONUS_CAP,
                    COMBO_BONUS_PER_KILL * min(self.combo, COMBO_MAX))
        return 1.0 + bonus

    def toast(self, message, duration=2.2, color=(255, 220, 140)):
        """Короткая подсказка по центру снизу — вместо «тихой» ошибки."""
        self.toast_text = message
        self.toast_timer = duration
        self.toast_color = color

    def on_shot(self, weapon):
        """Звук/тряска/гильза на каждый выстрел."""
        self.shots_fired += 1
        self.recoil = min(1.0, self.recoil + 0.16)
        shake = weapon.mode_profile.get(
            "shake", weapon.spec.get("shake", SHAKE_SHOOT))
        self.camera.add_shake(shake * (1.0 + self.recoil * 0.4))
        if weapon.uses_charge:
            # У плазмы нет гильзы; вместо неё игрок видит вспышку и шлейф.
            return
        muzzle_angle = self.player.angle
        mx = self.player.x + math.cos(muzzle_angle) * (weapon.muzzle_offset - 6)
        my = self.player.y + math.sin(muzzle_angle) * (weapon.muzzle_offset - 6)
        if random.random() < 0.75:
            self.effects.append(Casing(mx, my, muzzle_angle))

    def spawn_dash_ghost(self, player):
        """След переката — частота ограничена, чтобы не пух список эффектов."""
        if self._ghost_timer > 0.0:
            return
        self._ghost_timer = 0.028
        self.effects.append(DashGhost(player.x, player.y, player.angle,
                                      player.radius))

    def spawn_enemy_attack(self, enemy):
        """Красные искры в конце замаха: удар видно даже без звука."""
        for _ in range(4):
            self.effects.append(Spark(enemy.x, enemy.y, enemy.angle,
                                      (255, 110, 90), 90))

    def on_player_hurt(self, amount):
        """Обратная связь при получении урона."""
        self.camera.add_shake(SHAKE_HURT, self.player.angle + math.pi)
        self.damage_flash = min(1.0, self.damage_flash + 0.8)
        self.hitstop = max(self.hitstop, 0.045)
        if self.combo >= 5:
            self.toast("Серия прервана", 1.4, color=(240, 140, 120))
        self.combo = 0
        self.combo_timer = 0.0

    def on_player_death(self):
        """Фиксируем рекорд до показа экрана смерти."""
        self.best_score = max(self.best_score, self.score)
        self.player.cancel_charge()
        soundbank.play("enemy_die", 0.4)

    # ------------------------------------------------------------ СПАВН
    def _update_spawner(self, dt):
        self.spawn_timer -= dt
        if self.spawn_timer > 0:
            return
        difficulty = DIFFICULTIES[self.difficulty_key]
        # M10: потолок и волны — чистые функции progression.py
        # (та же математика, что в отчёте баланса и тестах)
        cap = progression.spawn_cap(self.elapsed, difficulty["population"])
        if len(self.enemies) < cap:
            wave = progression.spawn_wave(self.elapsed)
            for _ in range(wave):
                if len(self.enemies) < cap:
                    self._spawn_enemy()
        self.spawn_timer = self._spawn_interval()

    def _spawn_interval(self):
        spawn_scale = DIFFICULTIES[self.difficulty_key]["spawn"]
        return max(
            SPAWN_INTERVAL_MIN * spawn_scale,
            SPAWN_INTERVAL_START * spawn_scale / (1 + self.elapsed / 120),
        )

    def _spawn_enemy(self):
        enemy_class = self._pick_enemy_class()
        for _ in range(50):   # 50 попыток найти подходящее место
            try:
                x, y = self.world.random_floor_position(
                    enemy_class.radius,
                    center=self.player.pos,
                    min_distance=SPAWN_MIN_DISTANCE,
                    max_distance=1500,
                )
            except RuntimeError:
                # свободного места рядом нет (редкий тупик) — просто
                # пропускаем этот спавн, игра не должна падать из-за моба
                return
            if distance(x, y, self.player.x, self.player.y) < SPAWN_MIN_DISTANCE:
                continue
            if any(distance(x, y, shop.x, shop.y)
                   < shop.interior_radius + enemy_class.radius
                   for shop in self.shops):
                continue
            if any(distance(x, y, other.x, other.y)
                   < enemy_class.radius + other.radius
                   for other in self.enemies if other.alive):
                continue
            self.spawn_enemy_at(x, y, enemy_class)
            return

    def spawn_enemy_at(self, x, y, enemy_class=None, allow_elite=True):
        """Создаёт врага в заданной точке и применяет баланс сектора."""
        enemy_class = enemy_class or self._pick_enemy_class()
        enemy = enemy_class(x, y)
        self._configure_enemy(enemy, allow_elite=allow_elite)
        self.enemies.append(enemy)
        return enemy

    def _configure_enemy(self, enemy, allow_elite=True):
        """
        Кривые времени (progression.py) × сложность × глубина (M12).

        Глубина — это не только HP: враги быстрее и больнее, а их
        ранние типы появляются раньше. Игрок отвечает усилениями,
        которые выбирает между секторами.
        """
        strength = DIFFICULTIES[self.difficulty_key]["strength"]
        depth = max(1, getattr(self, "depth", 1))
        hp_depth = 1.0 + (depth - 1) * DEPTH_HP_GROWTH
        damage_depth = 1.0 + (depth - 1) * DEPTH_DAMAGE_GROWTH
        speed_depth = 1.0 + (depth - 1) * DEPTH_SPEED_GROWTH
        enemy.max_hp *= (progression.hp_multiplier(self.elapsed)
                         * strength * hp_depth)
        enemy.hp = enemy.max_hp
        enemy.speed *= (strength * progression.speed_multiplier(self.elapsed)
                        * speed_depth)
        enemy.damage *= (strength * progression.damage_multiplier(self.elapsed)
                         * damage_depth)
        if hasattr(enemy, "shot_damage"):
            enemy.shot_damage *= (strength
                                  * progression.damage_multiplier(self.elapsed)
                                  * damage_depth)
        elite_time = max(35, 75 - 8 * (depth - 1))
        elite_chance = 0.07 + 0.02 * (depth - 1)
        if allow_elite and self.elapsed > elite_time and random.random() < elite_chance:
            enemy.elite = True
            enemy.elite_trait = random.choice(("armored", "swift", "vampiric"))
            if enemy.elite_trait == "armored":
                enemy.armor_factor = 0.65
            elif enemy.elite_trait == "swift":
                enemy.speed *= 1.3
            enemy.max_hp *= 2.4
            enemy.hp = enemy.max_hp
            enemy.damage *= 1.35
            enemy.speed *= 1.12
            enemy.bounty = int(enemy.bounty * 5)
            enemy.score *= 3
            enemy.color = (190, 100, 225)

    def spawn_beacon_surge(self, beacon, count=1):
        """Волна защиты маяка: враги приходят из темноты к сигналу."""
        for _ in range(count):
            near = sum(1 for enemy in self.enemies
                       if enemy.alive
                       and distance(enemy.x, enemy.y, beacon.x, beacon.y) < 620)
            if near >= BEACON_SURGE_MAX:
                return
            enemy_class = self._pick_enemy_class()
            for _attempt in range(24):
                try:
                    x, y = self.world.random_floor_position(
                        enemy_class.radius,
                        center=(beacon.x, beacon.y),
                        min_distance=130,
                        max_distance=360,
                    )
                except RuntimeError:
                    break
                if distance(x, y, self.player.x, self.player.y) < 170:
                    continue
                if any(distance(x, y, shop.x, shop.y)
                       < shop.interior_radius + enemy_class.radius
                       for shop in self.shops):
                    continue
                self.spawn_enemy_at(x, y, enemy_class)
                break

    def _pick_enemy_class(self):
        """Выбирает доступный тип врага по настраиваемым весам."""
        classes = {
            "enemy": Enemy,
            "runner": Runner,
            "spitter": Spitter,
            "bomber": Bomber,
            "tank": Tank,
            "stalker": Stalker,
            "brute": Brute,
        }
        unlock_scale = DIFFICULTIES[self.difficulty_key]["unlock_time"]
        # run_time не сбрасывается на спуске: чем глубже вылазка, тем
        # раньше в секторе появляются поздние типы врагов.
        available = [
            (classes[key], weight)
            for key, weight in ENEMY_SPAWN_WEIGHTS.items()
            if key in classes
            and weight > 0
            and self.run_time
            >= ENEMY_UNLOCK_TIMES.get(key, 0) * unlock_scale
        ]
        if not available:
            raise ValueError("Не настроены доступные типы врагов")
        return random.choices(
            [enemy_class for enemy_class, _ in available],
            weights=[weight for _, weight in available],
            k=1,
        )[0]

    # ------------------------------------------------------------ СТОЛКНОВЕНИЯ
    def _check_bullet_hits(self):
        for bullet in self.bullets:
            if not bullet.alive:
                continue
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                if id(enemy) in bullet.hit_enemies:
                    continue
                if circles_collide(bullet.x, bullet.y, bullet.radius,
                                   enemy.x, enemy.y, enemy.radius):
                    self._bullet_hit(bullet, enemy)
                    if not bullet.alive:
                        break   # пуля исчерпала пробитие — дальше не летит

    def _bullet_hit(self, bullet, enemy):
        """
        Одно попадание пули — слой синергий и механик ветвей (M11).

        Порядок важен и читается сверху вниз:
        1) модификаторы урона (взрывная дробь → пробивная снайперка);
        2) сам урон через ЕДИНСТВЕННУЮ точку damage_enemy;
        3) «хвост» выстрела: рост урона, взрывы, возврат патронов;
        4) судьба пули: пробитие / рикошет от врага / смерть.
        """
        damage = bullet.damage
        if bullet.bounced and bullet.bounced_bonus:
            damage *= 1.0 + bullet.bounced_bonus   # «Зеркальный капкан»
        if bullet.returning:
            # Магнитный диск: обратный проход — вторая, более тяжёлая атака.
            damage *= 1.0 + bullet.return_damage_mul
        if bullet.close_bonus:
            # «Осадный дробовик»: вблизи точки выстрела бьёт крепче
            d = math.hypot(enemy.x - bullet.spawn_x, enemy.y - bullet.spawn_y)
            if d <= CLOSE_RANGE:
                damage *= 1.0 + bullet.close_bonus
        if bullet.mark_id == id(enemy) and bullet.mark_bonus:
            damage *= 1.0 + bullet.mark_bonus        # «Метка»/«Уязвимая точка»
        if enemy.explosion_mark > 0.0:
            # СИНЕРГИЯ: только что взорванная цель (дробь-подрывник)
            # добивается любым снарядом эффективнее
            damage *= EXPLOSION_SYNERGY
        execute = getattr(self.player, "execute_bonus", 0.0)
        if execute > 0.0 and enemy.hp <= enemy.max_hp * 0.35:
            damage *= 1.0 + execute           # усиление «Добивание»

        knockback_dir = None
        if bullet.knockback:
            vlen = math.hypot(bullet.vx, bullet.vy) or 1.0
            knockback_dir = (bullet.vx / vlen, bullet.vy / vlen)
        # Кровотечение ставим ДО прямого урона: добивающий выстрел тоже
        # оставляет рану, и «Кровавая картечь» разносит её при смерти.
        if bullet.bleed and enemy.alive:
            apply_bleed(enemy, damage * min(1.0, bullet.bleed))
        self.damage_enemy(enemy, damage, knockback_dir, bullet.knockback)
        self.shots_hit += 1
        bullet.hits += 1
        bullet.hit_enemies.add(id(enemy))
        distance_from_shot = math.hypot(enemy.x - bullet.spawn_x,
                                        enemy.y - bullet.spawn_y)

        # --- статусы поздних доктрин: ставятся ПОСЛЕ прямого урона, ---
        # --- чтобы взрыв и следующие пули уже пользовались меткой. ---
        if bullet.pierce_vulnerable and enemy.alive:
            apply_vulnerable(enemy, 1.5, bullet.pierce_vulnerable)
        if (bullet.mark_id == id(enemy) and bullet.mark_vulnerable
                and enemy.alive):
            apply_vulnerable(enemy, bullet.mark_duration,
                             bullet.mark_vulnerable)
        if bullet.bounced and bullet.bounced_mark and enemy.alive:
            apply_vulnerable(enemy, 1.5, bullet.bounced_mark)
        if bullet.impact_slow and enemy.alive:
            apply_slow(enemy, bullet.impact_slow, bullet.impact_slow_factor)
            radius = bullet.impact_slow_radius
            if radius:
                for other in self.nearby_enemies(enemy.x, enemy.y, radius):
                    if other is not enemy and other.alive:
                        apply_slow(other, bullet.impact_slow,
                                   bullet.impact_slow_factor)
        if (bullet.close_stun and enemy.alive
                and distance_from_shot <= bullet.close_stun_range):
            apply_stun(enemy, bullet.close_stun)

        # «Накопление импульса»: каждая цель очереди усиливает следующую
        if bullet.growth:
            bullet.damage *= 1.0 + bullet.growth
        # «Подрывник»: дробина взрывается при попадании (игроку не вредит)
        if bullet.explode:
            r = bullet.explode
            self.explode(
                enemy.x, enemy.y, r,
                r * EXPLOSION_DAMAGE_PER_PX * bullet.explosion_power,
                140.0, hurt_player=False,
                bleed=bullet.explosion_bleed,
                slow=bullet.explosion_slow,
                color=bullet.explosion_color)
            if bullet.blast_stun or bullet.explosion_vulnerable:
                # Статус взрыва получает и основная цель: «оглушение
                # полного заряда» не должно обходить того, в кого попали.
                for other in self.nearby_enemies(enemy.x, enemy.y, r):
                    if not other.alive:
                        continue
                    if bullet.blast_stun:
                        apply_stun(other, bullet.blast_stun)
                    if bullet.explosion_vulnerable:
                        apply_vulnerable(other, 2.0,
                                         bullet.explosion_vulnerable)
        # «Дуговая пушка»: разряд перескакивает по ближним целям.
        if bullet.chain_jumps:
            self._chain_arc(bullet, enemy, damage)
        if not enemy.alive:
            # «Кровавая картечь»: смерть кровоточащей цели разносит рану
            if bullet.bleed_spread and enemy.bleed_remaining > 0.0:
                radius = bullet.bleed_spread_radius
                for other in self.nearby_enemies(enemy.x, enemy.y, radius):
                    if other is not enemy and other.alive:
                        apply_bleed(other, damage * bullet.bleed_spread)
            # «Цепная детонация»/«Каскад»: убийство рождает второй взрыв
            if bullet.cascade:
                r = bullet.cascade
                self.explode(enemy.x, enemy.y, r, r * EXPLOSION_DAMAGE_PER_PX,
                             140.0, hurt_player=False)
            # «Осколочный каскад»: из точки смерти летят лёгкие дробины
            if bullet.cascade_shrapnel:
                for _ in range(int(bullet.cascade_shrapnel)):
                    angle = random.uniform(0.0, math.tau)
                    shrapnel = Bullet(
                        enemy.x, enemy.y, angle,
                        damage=damage * 0.35,
                        speed=math.hypot(bullet.vx, bullet.vy) * 0.8,
                        radius=bullet.radius,
                    )
                    self.bullets.append(shrapnel)
            # «Добивание» (ветвь Экономист): убийство возвращает боезапас
            if (bullet.refund_kill_amount
                    and random.random() < bullet.refund_kill_chance):
                self.player.equipment.add_ammo(bullet.refund_kill_amount)

        if bullet.pierces_further():
            return
        if bullet.enemy_bounce and bullet.ricochets > 0:
            # «Цепной рикошет»: от врага к следующему, пробитие не тратится
            bullet.ricochets -= 1
            if bullet.retarget(self.enemies):
                return                        # перенацелилась — летит дальше
        bullet.kill()

    def _chain_arc(self, bullet, origin, damage):
        """
        Цепь дуговой пушки: каждый переход ищет БЛИЖАЙШУЮ ещё не задетую
        цель в радиусе и передаёт ей урон с затуханием. Именно поэтому
        оружие сильно против группы и посредственно против одиночки.
        """
        jumps = int(bullet.chain_jumps)
        if jumps <= 0 or bullet.chain_range <= 0.0:
            return
        seen = set(bullet.chain_hit)
        seen.add(id(origin))
        prev_x, prev_y = origin.x, origin.y
        dealt = damage
        for _ in range(jumps):
            best, best_d = None, bullet.chain_range
            for other in self.enemies:
                if not other.alive or id(other) in seen:
                    continue
                d = math.hypot(other.x - prev_x, other.y - prev_y)
                if d <= best_d:
                    best, best_d = other, d
            if best is None:
                break
            dealt *= bullet.chain_falloff * bullet.chain_damage_mul
            self.effects.append(ArcBolt(prev_x, prev_y,
                                        best.x, best.y,
                                        color=bullet.color))
            span = max(best_d, 1.0)
            self.damage_enemy(best, dealt,
                              ((best.x - prev_x) / span,
                               (best.y - prev_y) / span), 40.0)
            seen.add(id(best))
            bullet.chain_hit.add(id(best))
            prev_x, prev_y = best.x, best.y

    def spawn_enemy_shot(self, enemy, angle):
        """Spitter плюёт сгусток: чуть разброса, яркий след и звук."""
        angle += random.uniform(-0.035, 0.035)
        mx = enemy.x + math.cos(angle) * (enemy.radius + 9)
        my = enemy.y + math.sin(angle) * (enemy.radius + 9)
        self.enemy_shots.append(EnemyShot(
            mx, my, angle,
            damage=getattr(enemy, "shot_damage", 12),
            speed=330.0 + random.uniform(-18.0, 18.0),
        ))
        for _ in range(3):
            self.effects.append(Spark(mx, my, angle,
                                      (150, 246, 190), 130))
        soundbank.play("enemy_shot", 0.45)

    def _check_enemy_shot_hits(self):
        player = self.player
        for shot in self.enemy_shots:
            if not shot.alive or not player.alive:
                continue
            if circles_collide(shot.x, shot.y, shot.radius,
                               player.x, player.y, player.radius):
                player.take_damage(shot.damage, self)
                for _ in range(6):
                    self.effects.append(Spark(
                        shot.x, shot.y, random.uniform(0, math.tau),
                        (156, 248, 192), 180))
                self.camera.add_shake(2.4)
                shot.kill()

    def descend_to_next(self):
        """
        Лифт: новый сектор, тот же герой и его снаряжение.

        Мир пересоздаётся полностью, но прогресс забега (оружие,
        артефакты, усиления, деньги) остаётся. Враги, дроп и эффекты
        старого сектора не переезжают — иначе спуск был бы наказанием.
        """
        self.depth += 1
        self.score += 500 * (self.depth - 1)
        self.world = World()
        start_x, start_y = self.world.player_start()
        self.world.ensure_chunks_around(start_x, start_y, 2)
        self.player.x, self.player.y = start_x, start_y
        self.player.cancel_charge()
        self.player.dash_timer = 0.0
        self.player.invuln_timer = 0.0
        self.player.hurt_timer = 0.0
        self.player.heal(self.player.max_hp * 0.22)
        weapon = self.player.firearm
        if weapon is not None:
            weapon.loaded = weapon.magazine_size
            weapon.reload_timer = 0.0
            weapon._reload_take = 0

        self.enemies = []
        self.enemy_shots = []
        self.enemy_index = EnemySpatialIndex()
        self.bullets = []
        self.effects = []
        self.drops = []
        self.grenades = []
        self.shops = []
        self.exploration = Exploration(self.world)
        self._sync_shops()
        self.lighting = LightingManager()
        self.active_cooldown = 0.0
        self.combo = 0
        self.combo_timer = 0.0
        self.hitstop = 0.0
        self.damage_flash = 0.0
        self.elapsed = 0.0
        self.spawn_timer = SPAWN_FIRST_DELAY + 1.0
        self.boss_menu = False
        self.descent = DescentManager(self, self.depth)
        self.camera.follow(self.player.x, self.player.y)
        self.camera.reset_shake()
        self.descent_ui.open(self)
        self.state = STATE_DESCENT

    def use_melee_ability(self):
        """X: weapon-specific active attack, cooldown shared per melee weapon."""
        weapon = self.player.melee
        if weapon is None or self.active_cooldown > 0:
            return
        kind = weapon.key if hasattr(weapon, "key") else weapon.spec.get("key", "")
        if not kind:
            kind = weapon.spec.get("id", "")
        angle = self.player.angle
        x, y = self.player.x, self.player.y
        dx, dy = math.cos(angle), math.sin(angle)
        base = weapon.spec.get("damage", 20)
        abilities = {
            "knife": (85, 1.9, 170),
            "machete": (135, 1.3, 220),
            "katana": (165, 1.6, 120),
            "hammer": (170, 1.9, 260),
            "shovel": (135, 1.15, 180),
            "shield": (130, 0.9, 340),
        }
        radius, multiplier, force = abilities.get(kind, (115, 1.2, 150))
        cx, cy = x + dx * 95, y + dy * 95
        self.explode(cx, cy, radius, base * multiplier, force, hurt_player=False)
        if kind == "hammer":
            for enemy in self.enemies:
                if enemy.alive and (enemy.x - cx) ** 2 + (enemy.y - cy) ** 2 < radius ** 2:
                    enemy.slow_timer = max(enemy.slow_timer, 2.0)
                    enemy.slow_factor = min(enemy.slow_factor, 0.45)
        elif kind == "knife":
            from status_effects import apply_bleed
            for enemy in self.enemies:
                if enemy.alive and (enemy.x - cx) ** 2 + (enemy.y - cy) ** 2 < radius ** 2:
                    apply_bleed(enemy, base * 1.2)
        elif kind == "shield":
            self.player.heal(8)
        self.active_cooldown = 9.0

    def nearby_enemies(self, x, y, radius):
        return self.enemy_index.query(x, y, radius)

    def damage_enemy(self, enemy, damage, knockback_dir=None, knockback=0.0,
                     show_number=True):
        """
        ЕДИНСТВЕННОЕ место, где наносится урон врагу.

        Здесь же рождаются цифры урона, искры и тряска камеры — поэтому
        любая атака (пуля, взрыв, ближний бой, кровотечение) ощущается
        одинаково «вкусно», без дублирования в каждом классе.
        """
        if getattr(enemy, "vulnerable_timer", 0.0) > 0.0:
            damage *= getattr(enemy, "vulnerable_mul", 1.0)
        dealt = damage * getattr(enemy, "armor_factor", 1.0)
        enemy.take_damage(dealt)
        self.hitmarker_timer = max(self.hitmarker_timer, 0.12)
        if knockback and knockback_dir:
            enemy.apply_knockback(knockback_dir, knockback)

        # Цифры урона: схлопываем очереди дроби в одну цифру на 50 мс.
        if show_number and dealt >= 1.0:
            now = pygame.time.get_ticks() / 1000.0
            if now - getattr(enemy, "_last_number", 0.0) > 0.05:
                enemy._last_number = now
                if dealt >= 90:
                    color, size = (255, 226, 130), 30
                elif dealt >= 35:
                    color, size = (255, 246, 210), 24
                else:
                    color, size = (255, 238, 200), 19
                self.effects.append(FloatingText(
                    enemy.x + random.uniform(-7, 7), enemy.y - enemy.radius * 0.7,
                    int(round(dealt)), color, size))

        if enemy.alive:
            self._spawn_particles(enemy, 3)
            for _ in range(3):
                self.effects.append(Spark(enemy.x, enemy.y,
                                          math.atan2(enemy.y - self.player.y,
                                                     enemy.x - self.player.x),
                                          (255, 220, 150)))
            self.camera.add_shake(SHAKE_HIT)
            if self._hit_sound_cd <= 0.0:
                self._hit_sound_cd = 0.035
                soundbank.play("hit", 0.38)   # не 7 наложений от дроби
        else:
            self.hitmarker_timer = 0.24
            self._on_enemy_killed(enemy)

    def _on_enemy_killed(self, enemy):
        self.kills += 1
        # СЕРИЯ: убийства подряд увеличивают награду. Игрок сам решает,
        # идти ли вперёд за деньгами или отступить и сохранить жизнь.
        self.combo = min(COMBO_MAX + 20, self.combo + 1)
        self.combo_timer = COMBO_WINDOW
        self.max_combo = max(self.max_combo, self.combo)
        multiplier = self.combo_multiplier
        depth_mult = 1.0 + (max(1, getattr(self, "depth", 1)) - 1) * DEPTH_LOOT_GROWTH
        self.score += int(round(enemy.score * multiplier * depth_mult))
        gain = max(1, int(round(
            enemy.bounty * (0.7 + 0.3 * multiplier) * multiplier
            * depth_mult * self.player.boon_loot_mult
            * (1.0 + self.player.skill_mod("loot_add")))))
        self.money += gain

        self.effects.append(FloatingText(
            enemy.x, enemy.y - enemy.radius * 0.9, f"+{gain}",
            (255, 208, 100), 21, 64.0))
        if self.player.boon_lifesteal > 0.0:
            self.player.heal(self.player.boon_lifesteal)
            self.effects.append(Particle(self.player.x, self.player.y,
                                         (122, 242, 156)))
        soundbank.play("kill", 0.7)
        soundbank.play("enemy_die", 0.45)
        self._spawn_particles(enemy, 14)
        self.camera.add_shake(SHAKE_HIT * 1.5)
        self.hitstop = max(self.hitstop, HITSTOP_KILL)
        if self.combo in (5, 10, 15, 20, 30):
            soundbank.play("combo", 0.6)
            self.toast(f"СЕРИЯ x{multiplier:.1f} — награда растёт", 1.6,
                       color=(255, 220, 130))

        # розыгрыш дропа по таблице монстра (монеты/патроны/гранаты)
        self.drops.extend(roll_drops(enemy))
        material = roll_material(enemy)
        if material is not None:
            self.drops.append(material)
        if getattr(enemy, "is_boss", False):
            from drops import ArtifactDrop, AmmoDrop, HealDrop
            from artifact_data import ALL_KEYS
            self.drops.append(ArtifactDrop(enemy.x + 18, enemy.y, random.choice(ALL_KEYS)))
            self.drops.append(AmmoDrop(enemy.x - 18, enemy.y, 80))
            self.drops.append(HealDrop(enemy.x, enemy.y + 20, 2))
            # Босс — гарантированный источник жетонов: их хватает и на
            # подготовку чужой школы, и на углубление второй ветви.
            for key in random.sample(TOKEN_KEYS, BOSS_TOKEN_REWARD):
                self.player.add_weapon_token(key, 1)
            self.boss_kills += 1
            self.camera.add_shake(10)
            self.hitstop = max(self.hitstop, HITSTOP_BIG * 2)
            self.toast("БОСС ПОВЕРЖЕН — артефакт, припасы и жетоны на земле", 4.0,
                       color=(255, 210, 110))
        elif (getattr(enemy, "elite", False)
              and random.random() < ELITE_TOKEN_CHANCE):
            key = random.choice(TOKEN_KEYS)
            self.player.add_weapon_token(key, 1)
            self.toast(f"ЭЛИТА: жетон школы «{TOKEN_NAMES[key]}»", 2.2,
                       color=(255, 208, 140))
        # событийный хук пассивного артефакта (M7): «Пожиратель» лечит
        # и т.п. Нет артефакта или нет хука — база отвечает пустотой.
        passive = self.player.equipment.get("passive_artifact")
        if passive is not None:
            passive.on_kill(self.player, self, enemy)

    def explode(self, x, y, radius, damage, knockback, hurt_player=True,
                bleed=0.0, slow=0.0, color=None):
        """
        Взрыв (граната, бомбер или дропина M11): урон по площади с
        затуханием по расстоянию, плюс свет и частицы.

        hurt_player=False — взрывы СНАРЯДОВ (ветвь «Подрывник») не вредят
        герою: GDD-дизайн «дробовик наказывает за близость», а не за
        собственный выстрел. Гранаты и бомберы бьют по-старому.
        Попавшие в радиус враги получают «след взрыва» — по нему работает
        синергия с пробивным снарядом (см. _bullet_hit).
        """
        soundbank.play("explosion")
        self.camera.add_shake(SHAKE_EXPLOSION)
        self.hitstop = max(self.hitstop, HITSTOP_BIG * 0.6)
        for enemy in self.nearby_enemies(x, y, radius):
            if not enemy.alive:
                continue
            dist = distance(x, y, enemy.x, enemy.y)
            if dist > radius + enemy.radius:
                continue
            enemy.explosion_mark = EXPLOSION_MARK_TIME   # цель «горит»
            scale = 1.0 - 0.5 * min(1.0, dist / radius)   # ближе — больнее
            dealt = damage * scale
            self.damage_enemy(
                enemy, dealt,
                knockback_dir=((enemy.x - x) / max(dist, 1.0),
                               (enemy.y - y) / max(dist, 1.0)),
                knockback=knockback * scale,
            )
            if enemy.alive:
                if bleed:
                    apply_bleed(enemy, dealt * bleed)
                if slow:
                    apply_slow(enemy, slow, 0.55)

        if hurt_player:
            player = self.player
            dist = distance(x, y, player.x, player.y)
            if dist <= radius + player.radius:
                scale = 1.0 - 0.5 * min(1.0, dist / radius)
                player.take_damage(damage * scale, self)

        self.effects.append(Explosion(x, y, radius, color=color))
        particle_color = tuple(color or (255, 170, 60))
        for _ in range(16):
            self.effects.append(Particle(x, y, particle_color))
        for _ in range(8):
            self.effects.append(Spark(x, y, random.uniform(0, math.tau),
                                      mix(particle_color, (255, 255, 255), 0.2),
                                      220))

    def _spawn_particles(self, enemy, count):
        color = mix(enemy.color, (255, 255, 255), 0.35)
        for _ in range(count):
            self.effects.append(Particle(enemy.x, enemy.y, color))

    def spawn_dust(self, enemy, amount=1):
        for _ in range(max(1, min(5, int(amount)))):
            particle = Particle(
                enemy.x + random.uniform(-enemy.radius * 0.35,
                                         enemy.radius * 0.35),
                enemy.y + random.uniform(-enemy.radius * 0.2,
                                         enemy.radius * 0.2),
                (190, 170, 132),
            )
            particle.vx *= 0.3
            particle.vy = particle.vy * 0.3 - 14.0
            particle.life = particle.max_life = random.uniform(0.4, 0.65)
            particle.size = random.randint(2, 4)
            self.effects.append(particle)

    # ------------------------------------------------------------ МАГАЗИН
    def nearest_shop(self):
        """Магазин, рядом с которым стоит герой (или None)."""
        for shop in self.shops:
            if shop.near_player(self):
                return shop
        return None

    def _sync_shops(self):
        """Держит объекты магазинов только в локальной области игрока."""
        nearby = self.world.shop_spots_near(
            self.player.x,
            self.player.y,
            2 * self.world.chunk_pixels,
        )
        previous = {(shop.x, shop.y): shop for shop in self.shops}
        self.shops = [
            previous.get((spot["x"], spot["y"])) or Shop(**spot)
            for spot in nearby
        ]

    def try_open_shop(self):
        """Клавиша E: открыть магазин, только если герой рядом."""
        shop = self.nearest_shop()
        if shop is not None:
            self.player.cancel_charge()
            self.state = STATE_SHOP
            self.shop_ui.open(shop)
            soundbank.play("open")

    def close_shop(self):
        """Закрыть магазин — мир продолжает жить с того же места."""
        self.state = STATE_PLAYING
        self.shop_ui.message = ""
        soundbank.play("close")

    def open_tree(self, slot="firearm"):
        """T/Y: единая доска навыков, сразу на древе нужного слота."""
        self.player.cancel_charge()
        self.state = STATE_TREE
        self.skill_ui.open(slot, self)
        soundbank.play("open")

    def close_tree(self):
        """Закрыть дерево навыков — мир продолжает жить с того же места."""
        self.state = STATE_PLAYING
        self.skill_ui.message = ""
        soundbank.play("close")

    def _sync_camera_zoom(self):
        """Разрешает отдаление только при купленной оптике в руках."""
        weapon = self.player.firearm
        unlocked = (weapon is not None
                    and float(weapon.mod("camera_zoom_unlock", 0.0)) > 0.0)
        if not unlocked:
            self.camera.set_zoom_range(1.0)
            return
        max_out = max(0.0, float(weapon.mod("camera_zoom_add", 0.0)))
        self.camera.set_zoom_range(1.0 - max_out)

    def handle_camera_zoom(self, wheel):
        """Колесо мыши: вверх — ближе, вниз — шире (если оптика куплена)."""
        if not wheel:
            return
        if self.camera.zoom_by(1 if wheel > 0 else -1):
            soundbank.play("ui_move", 0.22)

    # ------------------------------------------------------------ ОТРИСОВКА
    def _world_layer_for(self, size):
        size = (max(1, int(size[0])), max(1, int(size[1])))
        layer = self._world_layer
        if layer is None or layer.get_size() != size:
            layer = pygame.Surface(size)
            self._world_layer = layer
        return layer

    def _attack_layer_for(self, size):
        size = (max(1, int(size[0])), max(1, int(size[1])))
        if self.attack_overlay.get_size() != size:
            self.attack_overlay = pygame.Surface(size, pygame.SRCALPHA)
        return self.attack_overlay

    def draw(self):
        screen = self.screen
        if self.state == STATE_TITLE:
            self.hud.draw_title(screen, self)
            return
        if self.state == STATE_TREE:
            # Доска навыков непрозрачна: не тратим кадр на мир и HUD под ней.
            self.skill_ui.draw(screen, self)
            return

        # 1. физический слой мира
        world = screen
        if self.camera.is_zoomed:
            world = self._world_layer_for(
                (self.camera.view_w, self.camera.view_h))
        self.lighting.set_view(*world.get_size())
        self.world.draw(world, self.camera)
        self.exploration.draw(world, self.camera, self.player)
        self.descent.draw(world, self.camera, self.elapsed)
        for effect in self.effects:
            if not effect.emissive and self.camera.is_visible(effect.x, effect.y):
                effect.draw(world, self.camera)
        for drop in self.drops:
            if self.camera.is_visible(drop.x, drop.y):
                drop.draw(world, self.camera)
        for grenade in self.grenades:
            grenade.draw(world, self.camera)
        for shop in self.shops:
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius):
                shop.draw(world, self.camera)
        for enemy in self.enemies:
            if self.camera.is_visible(enemy.x, enemy.y):
                enemy.draw(world, self.camera)

        # 2. свет: дуло, взрывы, магазины и лампы комнат
        player_screen = self.camera.to_screen(self.player.x, self.player.y)
        weapon = self.player.firearm
        muzzle_offset = weapon.muzzle_offset if weapon else 0
        muzzle_world = (
            self.player.x + math.cos(self.player.angle) * muzzle_offset,
            self.player.y + math.sin(self.player.angle) * muzzle_offset,
        )
        muzzle_screen = self.camera.to_screen(*muzzle_world)
        flashes = [
            (*self.camera.to_screen(effect.x, effect.y), effect.light_radius,
             getattr(effect, "light_color", (255, 168, 84)))
            for effect in self.effects
            if effect.light_radius
            and self.camera.is_visible(effect.x, effect.y, effect.light_radius)
        ]
        flashes += [
            (*self.camera.to_screen(shop.x, shop.y), shop.light_radius, shop.color)
            for shop in self.shops
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius)
        ]
        for lamp in self.world.lamps_near(self.player.x, self.player.y, 1500):
            if self.camera.is_visible(lamp["x"], lamp["y"], lamp["radius"]):
                sx, sy = self.camera.to_screen(lamp["x"], lamp["y"])
                flicker = 0.86 + 0.14 * math.sin(self.elapsed * 5.0 + lamp["phase"])
                flashes.append((sx, sy, int(lamp["radius"] * flicker), lamp["color"]))
        for bx, by, radius, color in self.descent.lights():
            if self.camera.is_visible(bx, by, radius):
                sx, sy = self.camera.to_screen(bx, by)
                pulse = 0.82 + 0.18 * math.sin(self.elapsed * 3.2 + bx * 0.01)
                flashes.append((sx, sy, int(radius * pulse), color))
        for shot in self.enemy_shots:
            if shot.light_radius and self.camera.is_visible(
                    shot.x, shot.y, shot.light_radius):
                sx, sy = self.camera.to_screen(shot.x, shot.y)
                flashes.append((sx, sy, shot.light_radius, shot.light_color))

        danger = 0.0
        if self.player.alive:
            ratio = self.player.hp / max(1, self.player.max_hp)
            if ratio < 0.35:
                danger = (0.35 - ratio) / 0.35
        self.lighting.render(world, player_screen, muzzle_screen,
                             self.player.angle, self.player.flash_timer,
                             flashes, time=self.elapsed, danger=danger,
                             hurt=self.damage_flash)

        # 3. геометрия и светящиеся объекты — поверх темноты
        self.world.draw_edges(world, self.camera)
        self.world.draw_lamps(world, self.camera, self.elapsed)
        for shop in self.shops:
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius):
                shop.draw_overlay(world, self.camera, self.elapsed)
        self.exploration.draw_overlay(world, self.camera, self.player)
        self.descent.draw_overlay(world, self.camera, self.elapsed, self)
        for drop in self.drops:
            if self.camera.is_visible(drop.x, drop.y, 30):
                drop.draw_glow(world, self.camera, self.elapsed)

        # визуал атак ближнего боя — ПОВЕРХ темноты, иначе удар не видно
        melee = self.player.melee
        if melee is not None:
            overlay = self._attack_layer_for(world.get_size())
            overlay.fill((0, 0, 0, 0))
            melee.draw(overlay, self.camera, self.player)
            world.blit(overlay, (0, 0))

        # герой всегда яркий: он сам источник света
        self.player.draw(world, self.camera)
        for enemy in self.enemies:
            if self.camera.is_visible(enemy.x, enemy.y):
                enemy.draw_overlay(world, self.camera)

        for bullet in self.bullets:
            if self.camera.is_visible(bullet.x, bullet.y):
                bullet.draw(world, self.camera)
        for shot in self.enemy_shots:
            if self.camera.is_visible(shot.x, shot.y):
                shot.draw(world, self.camera)
        for effect in self.effects:
            if effect.emissive and self.camera.is_visible(effect.x, effect.y):
                effect.draw(world, self.camera)

        # Полотно мира шире окна: уменьшаем его целиком, чтобы игрок
        # действительно видел больше карты, а HUD остался 1:1.
        if world is not screen:
            pygame.transform.scale(world, (WIDTH, HEIGHT), screen)

        if self.debug_visible:
            lines = (f"FPS {self.clock.get_fps():.0f}  enemies {len(self.enemies)}  bullets {len(self.bullets)}",
                     f"Seed {self.world.seed}  chunks {len(self.world._chunks)}  effects {len(self.effects)}",
                     f"Depth {self.depth}  beacons {self.descent.active_count}/{len(self.descent.beacons)}"
                     f"  shots {len(self.enemy_shots)}",
                     f"Melee X: {self.active_cooldown:.1f}s   combo {self.combo}")
            for index, line in enumerate(lines):
                visuals.text(screen, line, (14, 14 + 22 * index), 20,
                             (255, 230, 130))

        # 4. интерфейс
        tint_index = (self.depth - 1) % len(SECTOR_TINTS)
        tint = SECTOR_TINTS[tint_index]
        if tint[3] > 0:
            layer = self._tints.get(tint_index)
            if layer is None:
                layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                layer.fill(tint)
                self._tints[tint_index] = layer
            screen.blit(layer, (0, 0))
        self.hud.draw(screen, self)
        if self.boss_menu and self.state == STATE_PLAYING:
            self._draw_boss_menu(screen)
        if self.state == STATE_SHOP:
            self.shop_ui.draw(screen, self)
        elif self.state == STATE_DESCENT:
            self.descent_ui.draw(screen, self)
        elif self.state in (STATE_PAUSED, STATE_SETTINGS, STATE_DIFFICULTY):
            self.hud.draw_pause_menu(screen, self)

    def _draw_boss_menu(self, screen):
        """Алтарь призыва: карточки боссов вместо голого списка."""
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((4, 7, 12, 170))
        screen.blit(dim, (0, 0))
        w, h = 700, 400
        x, y = (WIDTH - w) // 2, (HEIGHT - h) // 2
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.fill((13, 17, 27, 242))
        pygame.draw.rect(panel, (74, 94, 118), panel.get_rect(), 2, border_radius=16)
        pygame.draw.rect(panel, (28, 36, 54), (0, 0, w, 58), border_radius=16)
        screen.blit(panel, (x, y))
        visuals.text(screen, "АЛТАРЬ ПРИЗЫВА", (x + 24, y + 16), 30,
                     (255, 220, 150))
        visuals.text(screen, "B / ESC — закрыть", (x + w - 24, y + 20), 20,
                     (150, 160, 184), align="right")
        for i, (key, recipe) in enumerate(RECIPES.items()):
            yy = y + 78 + i * 94
            selected = i == self.boss_selection
            card = pygame.Rect(x + 24, yy, w - 48, 82)
            if selected:
                pygame.draw.rect(screen, (38, 48, 66), card, border_radius=10)
                pygame.draw.rect(screen, recipe["color"], card, 2, border_radius=10)
            else:
                pygame.draw.rect(screen, (24, 30, 42), card, border_radius=10)
            visuals.text(screen, recipe["name"], (card.x + 18, card.y + 12), 26,
                         recipe["color"] if selected else (210, 216, 230))
            parts = []
            for material, need in recipe["cost"].items():
                have = self.player.equipment.item_count(material)
                parts.append((MATERIALS[material], have, need))
            cursor_x = card.x + 18
            for label, have, need in parts:
                color = (140, 230, 160) if have >= need else (240, 150, 120)
                label_text = f"{label} {have}/{need}"
                visuals.text(screen, label_text, (cursor_x, card.y + 44), 19, color)
                cursor_x += visuals.text_width(label_text, 19) + 22
            visuals.text(screen, "вызов в мир · награда: артефакт и припасы",
                         (card.x + 18, card.y + 62), 17, (130, 140, 160))
        visuals.text(screen, "W/S — выбор    Enter — призвать    материалы падают с врагов",
                     (x + w // 2, y + h - 28), 18, (150, 160, 184), align="center")