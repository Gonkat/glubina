"""
Главный класс игры: владеет всеми объектами и управляет циклом.
"""
import gc
import logging
import math
import os
import random
import sys
import time
from contextlib import contextmanager

import pygame
import spritebank

import graphics_backend
import soundbank
import progression
import zones
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
    HITSTOP_BIG,
    HITSTOP_KILL,
    SECTOR_TINTS,
    SHAKE_EXPLOSION,
    SHAKE_HIT,
    SHAKE_HURT,
    SHAKE_SHOOT,
    SHOP_OPEN_DIST,
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
    STATE_ONLINE,
    TITLE,
    TILE,
    WIDTH,
    HEIGHT,
    LOS_FADE_PX,
)
from world import World
from drops import roll_drops
from weapon_data import TOKEN_KEYS, TOKEN_NAMES
from bosses import RECIPES, MATERIALS, SoulShardDrop, roll_material, summon
from exploration import Exploration
from status_effects import (apply_bleed, apply_slow, apply_stun,
                           apply_vulnerable, update_bleed, update_dust)
from spatial_index import EnemySpatialIndex
from enemies import Bomber, Brute, Enemy, Runner, Spitter, Stalker, Tank
from hud import HUD
from lighting import LightingManager
from player import Player
import netplay
from netplay import protocol
from netplay import snapshot as net_snapshot
from netplay.client_view import ClientView
from netplay.online_ui import OnlineUI
from netplay.session import ClientSession, HostSession, shop_near
from projectiles import (ArcBolt, Bullet, Casing, DashGhost, EnemyShot,
                         Explosion, FloatingText, Particle, Spark)
from shop import Shop
from shop_ui import BUY_HANDLERS, ShopUI
from skill_tree_ui import SkillTreeUI
from descent import DescentManager
from descent_ui import DescentUI
from utils import circles_collide, distance, fade_draw, mix
import visuals


# Меню хоста, при которых онлайн-мир НЕ встаёт на паузу. Список намеренно
# узкий: настройки/сложность могут пересоздавать окно, и останавливать
# симуляцию на них безопаснее, чем гонять её во время смены vsync.
COOP_LIVE_MENUS = (STATE_SHOP, STATE_TREE, STATE_PAUSED)

# Хост — источник истины: его просадка тормозит всех гостей. Поэтому при
# подключённых гостях хост сам снимает косметическую нагрузку, если его
# кадр не укладывается в бюджет (порог с запасом от 60 FPS).
HOST_PERF_BAD_MS = 18.5       # выше — копим «плохие» кадры
HOST_PERF_GOOD_MS = 15.5      # ниже — считаем, что уже легко
HOST_PERF_ON_AFTER = 0.6      # с, плохих кадров подряд
HOST_PERF_OFF_AFTER = 3.0     # с, хороших кадров подряд
HOST_PERF_LAMPS = 6           # сколько ламп освещает сцену в этом режиме
HOST_PERF_FLASHES = 12        # сколько источников света всего
HOST_EFFECT_CAP = 220         # сколько эффектов держим


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
        # Спрайты грузим один раз на старте: в бою и на подключении кадр
        # не должен платить за pygame.image.load / convert_alpha().
        spritebank.preload()

        self.world = World()               # чанки генерируются по мере исследования
        self.camera = Camera()
        self.hud = HUD()
        self.descent_ui = DescentUI()
        # --- кооператив (netplay) ---
        # role: None — одиночная игра, "host" / "client" — сессия.
        self.online_ui = OnlineUI()
        self.net_role = None
        self.session = None
        self.client_view = None
        self.players = []          # все участники, локальный — первый
        self.remote_players = []   # все, кроме локального
        self.render_players = []   # кого включать в снимок мира
        self.net_seq = 0
        self.local_pid = 1
        self.local_name = "Хост"
        self.coop_active = False
        self._online_actions = []
        self._online_input_timer = 0.0
        # Звуки игроков: очередь на тик и антифлуд по (pid, звук).
        self._sound_events = []
        self._sound_last = {}
        # Разовые эффекты (взрывы, удары врагов): их нельзя восстановить
        # из снимков — событие живёт доли секунды.
        self._net_events = []
        # Одиночная игра по умолчанию: без затухания и без рассылки.
        soundbank.bind_audio(None, None)
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
    def reset(self, seed=None, warm_chunks=True):
        """Создаёт (или пересоздаёт после смерти) все объекты раунда.

        seed передаётся кооперативом: клиенты обязаны получить ТОТ ЖЕ
        мир, поэтому сид выбирает хост, а не каждый процесс. Одиночная
        игра вызывает reset() без аргументов и получает случайный мир,
        как и раньше.
        """
        # Сид и тип локации выбираются ДО создания мира: профиль зоны
        # участвует в генерации ламп первого же чанка.
        if seed is None:
            seed = random.SystemRandom().randrange(0, 2**63)
        self.seed = seed
        self.zone_key = zones.zone_for_sector(1, seed)
        self.zone_prev = self.zone_key   # новый забег — без перехода
        self.world = World(seed=seed, zone_key=self.zone_key,
                           prefetch=warm_chunks)
        start_x, start_y = self.world.player_start()
        if warm_chunks:
            self.world.ensure_chunks_around(start_x, start_y, 2)
        else:
            # Клиент: мир достраивается порциями в кадрах (без фриза).
            self._begin_client_warm(start_x, start_y)
        self.player = Player(start_x, start_y)
        # Стабильный идентификатор игрока переживает спуск и смерть:
        # по нему сеть, награды и враги различают участников.
        self.local_pid = getattr(self, "local_pid", 1)
        self.player.pid = self.local_pid
        self.player.is_local = True
        self.player.name = getattr(self, "local_name", "Хост")
        self.players = [self.player]
        # Наблюдение павшего: pid соратника, за которым смотрит камера.
        # Это ЛОКАЛЬНОЕ состояние взгляда, ему не нужен сетевой протокол.
        self.spectate_pid = None
        self._spectate_dir = 0
        self.remote_players = []
        self.render_players = self.players
        self.coop_active = False
        self.enemies = []
        self._net_events = []
        # Стабильные u32-номера сущностей для сети (id() в u32 не влезает).
        self.net_ids = net_snapshot.EntityIds()
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
        # Откуда прилетел урон (гость): направление и таймер подсказки.
        self.hit_dir = 0.0
        self.hit_dir_timer = 0.0
        self._client_trigger = False
        # Хост: авто-режим производительности (см. _update_host_perf).
        self.host_perf = False
        self.frame_ms = 0.0
        self._perf_bad = 0.0
        self._perf_good = 0.0
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
            # Лимит кадров задаётся настройкой (0 — без ограничения).
            dt = min(self.clock.tick(self.video.frame_rate()) / 1000.0, 0.05)
            frame_started = time.perf_counter()
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
                    if self.state == STATE_ONLINE:
                        self.online_ui.handle_event(event, self)
                        continue
                    if (self.net_role == "client"
                            and self.state == STATE_PLAYING
                            and event.key not in (pygame.K_ESCAPE,
                                                  pygame.K_F5)):
                        # Клиент НЕ исполняет действия локально: он шлёт
                        # намерение хосту. Поэтому двойного выстрела или
                        # подбора из-за локальной копии здесь не бывает.
                        self._client_key(event.key)
                        continue
                    if event.key == pygame.K_F5:
                        spritebank.reload()
                        visuals.reload_assets()
                        self.world._wall_tile = None
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
                    elif (event.key == pygame.K_r
                          and self.state == STATE_GAME_OVER):
                        if (self.coop_active
                                and self.net_role == 'host'
                                and self.session is not None):
                            # Перезапуск кооп-вылазки делает только хост:
                            # новый seed сам перестроит мир у клиентов.
                            self.session.start_run(self)
                        elif self.net_role == 'client':
                            self.toast('Перезапуск делает хост', 2.4,
                                       color=(240, 190, 110))
                        else:
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
                            if not self.player.alive:
                                continue
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
            # Метрики бесплатны по кадру, но показывают, где реально
            # уходит время: симуляция, сборка сцены или презентация.
            metrics = self.video.metrics
            if self.state == STATE_ONLINE:
                with metrics.measure("update"):
                    self.pump_online(dt)
            elif self.state == STATE_PLAYING:
                with metrics.measure("update"):
                    self.update(dt)
            elif (self.net_role == "host" and self.coop_active
                  and self.session is not None
                  and self.state in COOP_LIVE_MENUS):
                # Онлайн нельзя поставить на паузу: пока у хоста открыт
                # магазин/доска/меню паузы, мир и сеть продолжают жить,
                # а его герой стоит. Иначе у гостя замирает картинка на
                # всё время окна, а потом его «дёргает» накопленными
                # снимками.
                with metrics.measure("update"):
                    self.update(dt)
            elif (self.net_role == "client" and self.session is not None
                  and self.state in (STATE_PAUSED, STATE_SHOP, STATE_TREE,
                                     STATE_DESCENT, STATE_SETTINGS,
                                     STATE_DIFFICULTY, STATE_GAME_OVER)):
                # Клиент не симулирует мир; даже с открытым окном он
                # продолжает принимать снимки, иначе очередь сети росла бы.
                with metrics.measure("update"):
                    self._client_pump_only(dt)
            elif (self.net_role == "host" and self.coop_active
                  and self.session is not None):
                # Спуск/экран смерти: мир хоста стоит, но сеть обязана
                # жить. Иначе у гостя замирает картинка на всё время
                # экрана, а потом его «дёргает» пачкой снимков.
                with metrics.measure("update"):
                    self.session.pump(self, dt)
                    for text, color, timer in self.session.drain_notices():
                        self.toast(text, timer, tuple(color or (255, 220, 140)))
            with metrics.measure("draw"):
                self.draw()
            self.video.present()
            # Полное время кадра (включая презентацию): именно его p99
            # показывает F3 — средний FPS прячет рывки.
            frame_ms = (time.perf_counter() - frame_started) * 1000.0
            metrics.add("frame", frame_ms)
            # Сглаженное время кадра — вход для авто-режима хоста.
            self.frame_ms = self.frame_ms * 0.94 + frame_ms * 0.06
        self.video.close()
        pygame.quit()

    def _handle_title(self, key):
        """Титульный экран: Начать / Сложность / Онлайн / Выход."""
        if key in (pygame.K_w, pygame.K_UP):
            self.title_index = (self.title_index - 1) % 4
            soundbank.play("ui_move")
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.title_index = (self.title_index + 1) % 4
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
                self.online_leave()      # одиночная игра — без сети
                self.reset()
                soundbank.play("open")
            elif self.title_index == 1:
                keys = list(DIFFICULTIES)
                index = (keys.index(self.difficulty_key) + 1) % len(keys)
                self.difficulty_key = keys[index]
                self.difficulty_menu_index = index
                soundbank.play("ui_move")
            elif self.title_index == 2:
                self.open_online()
                soundbank.play("open")
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
        self.online_leave()
        self.reset()
        self.state = STATE_TITLE
        self.title_index = 0

    def _handle_settings_menu(self, key):
        # 0 громкость, 1 рендер, 2 видеоадаптер, 3 GPU-эффекты,
        # 4 лимит кадров, 5 вертикальная синхронизация
        if key in (pygame.K_UP, pygame.K_w):
            self.settings_menu_index = (self.settings_menu_index - 1) % 6
            soundbank.play("ui_move")
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.settings_menu_index = (self.settings_menu_index + 1) % 6
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
        if index == 3:
            enabled = not self.video.effects
            self.video.set_effects(enabled)
            self.settings_notice = (
                "GPU-эффекты включены." if enabled
                else "GPU-эффекты выключены."
            )
            return
        if index == 4:
            cap = self.video.cycle_fps_cap(step)
            self.settings_notice = (
                "Лимит кадров: без ограничения." if not cap
                else f"Лимит кадров: {cap} FPS."
            )
            return
        enabled = not self.video.vsync
        self.video.set_vsync(enabled)
        self._rebind_display()
        self.settings_notice = (
            "Вертикальная синхронизация включена." if enabled
            else "Вертикальная синхронизация выключена."
        )

    def _rebind_display(self):
        """Окно пересоздано: всё, что привязано к Surface, — заново."""
        previous = self.screen
        try:
            self.screen = self.video.surface
        except Exception:
            self.screen = previous
            return
        pygame.display.set_caption(TITLE)
        pygame.mouse.set_visible(False)
        self._world_layer = None
        self.attack_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._tints.clear()

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
        # Слои привязаны к старому Surface; пересоздадим их заново.
        self._rebind_display()
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
        if self.net_role == "client":
            # Клиент не симулирует: только сеть, сглаживание и отрисовка.
            self._client_update(dt)
            return
        if self.net_role == "host" and self.session is not None:
            # Сеть обрабатывается ДО симуляции: ввод гостей должен попасть
            # в этот же кадр, а отключения — не оставить «фантомного» игрока.
            self.session.pump(self, dt)
            for text, color, timer in self.session.drain_notices():
                self.toast(text, timer, tuple(color or (255, 220, 140)))
            self._update_host_perf(dt)
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
        if self.net_role == "host" and self.session is not None:
            # Сначала ввод гостей, потом свой: все игроки обновляются в
            # одном и том же кадре хоста, поэтому мир для всех един.
            for client in self.session.clients:
                if client.player is not None:
                    self._apply_remote_input(client)
        if self.state == STATE_PLAYING and not getattr(
                self, "server_authority", False):
            self.player.handle_input(
                pygame.key.get_pressed(),
                mouse_world,
                pygame.mouse.get_pressed(),
            )
        elif self.state == STATE_PLAYING:
            # Выделенный сервер: клавиатуры нет, ввод приходит только от
            # гостей (он уже применён выше).
            pass
        else:
            # Меню хоста в онлайне не останавливает мир (см. COOP_LIVE_MENUS):
            # герой стоит и не стреляет, а клавиши достаются интерфейсу.
            self.player.move_dir = (0.0, 0.0)
            self.player.trigger_held = False
            self.player.melee_held = False
            if self.player.firearm is not None:
                self.player.cancel_charge()
        self._update_spectator_input()
        self.enemy_index.rebuild(self.enemies)
        for player in self.players:
            if not player.alive:
                # Павший не стреляет и не тратит предметы до следующего
                # сектора — иначе смерть в кооперативе была бы выгодна.
                player.trigger_held = False
                player.melee_held = False
                continue
            player.update(dt, self)
        view = self.view_player()
        self.camera.follow(view.x, view.y)
        self.world.ensure_chunks_around(self.player.x, self.player.y, 2)
        self._sync_shops()
        self.exploration.update(self.player.x, self.player.y)
        self.descent.update(dt, self)

        # Удаляем врагов, оставшихся далеко позади игрока, до расчёта ИИ.
        # Это не убийства: опыт, монеты и предметы не начисляются.
        despawn_distance_sq = ENEMY_DESPAWN_DISTANCE ** 2
        self.enemies = [
            enemy for enemy in self.enemies
            if enemy.alive and (getattr(enemy, "is_boss", False)
                                or self._nearest_distance_sq(enemy.x, enemy.y)
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
        if self.host_perf and len(self.effects) > HOST_EFFECT_CAP:
            # Гостям важнее ровный кадр хоста, чем сотая искра.
            del self.effects[:len(self.effects) - HOST_EFFECT_CAP]
        self.grenades = [g for g in self.grenades if g.alive]
        self.drops = [d for d in self.drops if d.alive]

        if self.coop_active:
            if not any(player.alive for player in self.players):
                self.state = STATE_GAME_OVER
        elif not self.player.alive:
            self.state = STATE_GAME_OVER

    # ------------------------------------------------------------ ЛИЧНОЕ vs ОБЩЕЕ
    # Деньги, очки и убийства — ПЕРСОНАЛЬНЫЕ (ТЗ: отдельное развитие).
    # Старые имена Game.money/score/kills оставлены как свойства локального
    # героя, чтобы HUD, магазины и экран смерти не пришлось переписывать.
    @property
    def money(self):
        return self.player.money

    @money.setter
    def money(self, value):
        self.player.money = int(value)

    @property
    def score(self):
        return self.player.score

    @score.setter
    def score(self, value):
        self.player.score = int(value)

    @property
    def kills(self):
        return self.player.kills

    @kills.setter
    def kills(self, value):
        self.player.kills = int(value)

    def nearest_player(self, x, y, alive_only=True):
        """Предсказуемая цель для врага: ближайший живой игрок.

        При равном расстоянии выбирает меньший pid — порядок обновления
        списка игроков не должен менять поведение врагов (иначе два
        клиента видели бы разные цели и «дёргались»).
        """
        candidates = [p for p in self.players if p.alive or not alive_only]
        if not candidates:
            return self.player
        return min(candidates,
                   key=lambda p: ((p.x - x) ** 2 + (p.y - y) ** 2, p.pid))

    # ------------------------------------------------------------ НАБЛЮДЕНИЕ
    def spectate_candidates(self):
        """Живые герои, между которыми листает павший."""
        return sorted((p for p in self.players if p.alive),
                      key=lambda p: p.pid)

    def view_player(self):
        """Герой, вокруг которого строятся камера и свет.

        Живой игрок смотрит за себя; павший — наблюдатель: камера
        цепляется к ближайшему живому соратнику, а нажатия движения
        листают остальных (никто не ждёт спуска вслепую).
        """
        local = self.player
        if local is None or local.alive:
            return local
        candidates = self.spectate_candidates()
        if not candidates:
            return local
        target = next((p for p in candidates if p.pid == self.spectate_pid),
                      None)
        if target is None:
            target = min(candidates, key=lambda p: (
                (p.x - local.x) ** 2 + (p.y - local.y) ** 2, p.pid))
            self.spectate_pid = target.pid
        return target

    def cycle_spectate(self, step):
        """Следующий/предыдущий живой соратник (по кругу)."""
        candidates = self.spectate_candidates()
        if len(candidates) < 2:
            return False
        pids = [p.pid for p in candidates]
        try:
            index = pids.index(self.spectate_pid)
        except ValueError:
            index = 0
        self.spectate_pid = pids[(index + step) % len(pids)]
        return True

    def _update_spectator_input(self):
        """A/D или стрелки листают наблюдаемых — только по краю нажатия."""
        if not self.coop_active:
            return
        local = self.player
        if local is None or local.alive or not self.spectate_candidates():
            self._spectate_dir = 0
            return
        keys = pygame.key.get_pressed()
        direction = (1 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0) - (
            1 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0)
        if direction and direction != self._spectate_dir:
            if self.cycle_spectate(direction):
                soundbank.play("ui_move", 0.35)
        self._spectate_dir = direction

    def revive_player(self, player, x, y):
        """Поднять павшего у алтаря: половина HP и потеря половины навыков."""
        if player is None or player.alive:
            return False
        x, y = self.world.resolve_circle(x, y, player.radius)
        player.x, player.y = float(x), float(y)
        player.alive = True
        player.hp = max(1.0, player.max_hp * 0.5)
        player.hurt_timer = 0.0
        player.invuln_timer = 1.2      # секунда на осмотреться после возврата
        player.cancel_charge()
        lost = player.lose_half_skills()
        self.effects.append(FloatingText(player.x, player.y - 30,
                                         "ВОЗВРАЩЕНИЕ", (198, 158, 255),
                                         20, 70.0))
        soundbank.play("heal", 0.85)
        self.camera.add_shake(4.0)
        self.toast(f"{player.name} возвращён · сгорело навыков: {lost}", 3.2,
                   color=(198, 160, 255))
        if player is self.player:
            self.spectate_pid = None
        return True

    def player_within(self, x, y, radius):
        """Есть ли живой игрок в радиусе (общие цели: маяк, лифт)."""
        limit = radius * radius
        for player in self.players:
            if not player.alive:
                continue
            if (player.x - x) ** 2 + (player.y - y) ** 2 <= limit:
                return player
        return None

    def _nearest_distance_sq(self, x, y):
        best = None
        for player in self.players:
            dist = (player.x - x) ** 2 + (player.y - y) ** 2
            if best is None or dist < best:
                best = dist
        return float("inf") if best is None else best

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

    def on_shot(self, weapon, player=None):
        """Звук/тряска/гильза на каждый выстрел."""
        player = self.player if player is None else player
        if player is self.player:
            self.shots_fired += 1
            self.recoil = min(1.0, self.recoil + 0.16)
        shake = weapon.mode_profile.get(
            "shake", weapon.spec.get("shake", SHAKE_SHOOT))
        self.camera.add_shake(shake * (1.0 + self.recoil * 0.4))
        if weapon.uses_charge:
            # У плазмы нет гильзы; вместо неё игрок видит вспышку и шлейф.
            return
        muzzle_angle = self.player.angle
        mx = player.x + math.cos(muzzle_angle) * (weapon.muzzle_offset - 6)
        my = player.y + math.sin(muzzle_angle) * (weapon.muzzle_offset - 6)
        if random.random() < 0.75 and not self.host_perf:
            self.effects.append(Casing(mx, my, muzzle_angle))

    def spawn_dash_ghost(self, player):
        """След переката — частота ограничена, чтобы не пух список эффектов."""
        if self.host_perf or self._ghost_timer > 0.0:
            return
        self._ghost_timer = 0.028
        self.effects.append(DashGhost(player.x, player.y, player.angle,
                                      player.radius))

    def spawn_enemy_attack(self, enemy):
        """Красные искры в конце замаха: удар видно даже без звука."""
        self.queue_net_event("enemy_attack", enemy.x, enemy.y, 0.0,
                             (255, 110, 90))
        for _ in range(4):
            self.effects.append(Spark(enemy.x, enemy.y, enemy.angle,
                                      (255, 110, 90), 90))

    def on_player_hurt(self, amount, player=None):
        """Обратная связь при получении урона (только для локального)."""
        player = self.player if player is None else player
        if player is not self.player:
            # Чужой игрок получает урон на хосте, но тряска камеры —
            # событие ТОГО клиента, а не всех участников.
            return
        self.camera.add_shake(SHAKE_HURT, player.angle + math.pi)
        self.damage_flash = min(1.0, self.damage_flash + 0.8)
        self.hitstop = max(self.hitstop, 0.045)
        if self.combo >= 5:
            self.toast("Серия прервана", 1.4, color=(240, 140, 120))
        self.combo = 0
        self.combo_timer = 0.0
        # Мир в онлайне не встаёт на паузу, поэтому удар по хосту в окне
        # магазина/доски должен немедленно вернуть его в бой — иначе можно
        # умереть, глядя в инвентарь.
        if (self.net_role == "host" and self.coop_active
                and self.state in (STATE_SHOP, STATE_TREE, STATE_PAUSED)):
            if self.state == STATE_SHOP:
                self.close_shop()
            elif self.state == STATE_TREE:
                self.close_tree()
            else:
                self.state = STATE_PLAYING
            self.toast("Окно закрыто: атака", 1.8, color=(240, 160, 120))

    def on_player_death(self, player=None):
        """Фиксируем рекорд до показа экрана смерти."""
        player = self.player if player is None else player
        if player is self.player:
            self.best_score = max(self.best_score, self.score)
        player.cancel_charge()
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
                # Спавн идёт вокруг СЛУЧАЙНОГО живого игрока, но не ближе
                # SPAWN_MIN_DISTANCE ни к одному из них.
                anchors = [p for p in self.players if p.alive] or [self.player]
                anchor = random.choice(anchors)
                x, y = self.world.random_floor_position(
                    enemy_class.radius,
                    center=anchor.pos,
                    min_distance=SPAWN_MIN_DISTANCE,
                    max_distance=1500,
                )
            except RuntimeError:
                # свободного места рядом нет (редкий тупик) — просто
                # пропускаем этот спавн, игра не должна падать из-за моба
                return
            if self._nearest_distance_sq(x, y) < SPAWN_MIN_DISTANCE ** 2:
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
                if self._nearest_distance_sq(x, y) < 170 ** 2:
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
                if enemy.hit_test(bullet.x, bullet.y, bullet.radius):
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
        owner = getattr(bullet, "owner", None) or self.player
        execute = getattr(owner, "execute_bonus", 0.0)
        if execute > 0.0 and enemy.hp <= enemy.max_hp * 0.35:
            damage *= 1.0 + execute           # усиление «Добивание»

        knockback_dir = None
        if bullet.knockback:
            vlen = math.hypot(bullet.vx, bullet.vy) or 1.0
            knockback_dir = (bullet.vx / vlen, bullet.vy / vlen)
        # Кровотечение ставим ДО прямого урона: добивающий выстрел тоже
        # оставляет рану, и «Кровавая картечь» разносит её при смерти.
        if bullet.bleed and enemy.alive:
            apply_bleed(enemy, damage * min(1.0, bullet.bleed),
                        source=owner)
        self.damage_enemy(enemy, damage, knockback_dir, bullet.knockback,
                          source=owner)
        if owner is self.player:
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
                140.0, hurt_player=False, source=owner,
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
                        apply_bleed(other, damage * bullet.bleed_spread,
                                    source=owner)
            # «Цепная детонация»/«Каскад»: убийство рождает второй взрыв
            if bullet.cascade:
                r = bullet.cascade
                self.explode(enemy.x, enemy.y, r, r * EXPLOSION_DAMAGE_PER_PX,
                             140.0, hurt_player=False, source=owner)
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
                    shrapnel.owner = owner
                    self.bullets.append(shrapnel)
            # «Добивание» (ветвь Экономист): убийство возвращает боезапас
            if (bullet.refund_kill_amount
                    and random.random() < bullet.refund_kill_chance):
                owner.equipment.add_ammo(bullet.refund_kill_amount)

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
                               (best.y - prev_y) / span), 40.0,
                              source=getattr(bullet, "owner", None))
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
        for shot in self.enemy_shots:
            if not shot.alive:
                continue
            for player in self.players:
                if not player.alive:
                    continue
                if not circles_collide(shot.x, shot.y, shot.radius,
                                       player.x, player.y, player.radius):
                    continue
                player.take_damage(shot.damage, self)
                for _ in range(6):
                    self.effects.append(Spark(
                        shot.x, shot.y, random.uniform(0, math.tau),
                        (156, 248, 192), 180))
                self.camera.add_shake(2.4)
                shot.kill()
                break

    def descend_to_next(self):
        """
        Лифт: новый сектор, тот же герой и его снаряжение.

        Мир пересоздаётся полностью, но прогресс забега (оружие,
        артефакты, усиления, деньги) остаётся. Враги, дроп и эффекты
        старого сектора не переезжают — иначе спуск был бы наказанием.
        """
        self.depth += 1
        # Очки за глубину — каждому участнику: это общий рубеж.
        for player in self.players:
            player.score += 500 * (self.depth - 1)
        # Новый сид и тип локации: переход между типами плавный
        # (zone_profile смешивает профили в течение ZONE_TRANSITION_TIME).
        seed = random.SystemRandom().randrange(0, 2**63)
        new_zone = zones.zone_for_sector(self.depth, seed)
        self.zone_prev = getattr(self, "zone_key", new_zone)
        self.zone_key = new_zone
        self.world = World(seed=seed, zone_key=new_zone)
        start_x, start_y = self.world.player_start()
        self.world.ensure_chunks_around(start_x, start_y, 2)
        # Все участники переезжают в новый сектор вместе. Павшие
        # возвращаются к лифту с 40% HP: правило «смерть — до конца
        # сектора» без воскрешения в бою.
        for index, player in enumerate(self.players):
            offset = 0.0 if index == 0 else 44.0 * ((index + 1) // 2)
            side = 1.0 if index % 2 else -1.0
            player.x, player.y = self.world.resolve_circle(
                start_x + offset * side, start_y + offset * 0.5,
                player.radius)
            player.cancel_charge()
            player.dash_timer = 0.0
            player.invuln_timer = 0.0
            player.hurt_timer = 0.0
            if not player.alive:
                player.alive = True
                player.hp = player.max_hp * 0.4
            else:
                player.heal(player.max_hp * 0.22)
            weapon = player.firearm
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
        self.spectate_pid = None
        self._spectate_dir = 0
        self.camera.follow(self.player.x, self.player.y)
        self.camera.reset_shake()
        self.descent_ui.open(self)
        self.state = STATE_DESCENT
        self.toast(f"ЛОКАЦИЯ · {zones.profile(self.zone_key)['name']}",
                   3.5, color=(150, 226, 210))

    def use_melee_ability(self, player=None):
        """X: активная атака оружия ближнего боя (кулдаун общий на ствол)."""
        player = self.player if player is None else player
        weapon = player.melee
        if weapon is None or self.active_cooldown > 0:
            return
        kind = weapon.key if hasattr(weapon, "key") else weapon.spec.get("key", "")
        if not kind:
            kind = weapon.spec.get("id", "")
        angle = player.angle
        x, y = player.x, player.y
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
            player.heal(8)
        self.active_cooldown = 9.0

    def nearby_enemies(self, x, y, radius):
        return self.enemy_index.query(x, y, radius)

    def damage_enemy(self, enemy, damage, knockback_dir=None, knockback=0.0,
                     show_number=True, source=None):
        """
        ЕДИНСТВЕННОЕ место, где наносится урон врагу.

        Здесь же рождаются цифры урона, искры и тряска камеры — поэтому
        любая атака (пуля, взрыв, ближний бой, кровотечение) ощущается
        одинаково «вкусно», без дублирования в каждом классе.
        """
        if getattr(enemy, "vulnerable_timer", 0.0) > 0.0:
            damage *= getattr(enemy, "vulnerable_mul", 1.0)
        source = self.player if source is None else source
        dealt = damage * getattr(enemy, "armor_factor", 1.0)
        enemy.take_damage(dealt)
        if source is self.player:
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
                                          math.atan2(enemy.y - source.y,
                                                     enemy.x - source.x),
                                          (255, 220, 150)))
            self.camera.add_shake(SHAKE_HIT)
            if self._hit_sound_cd <= 0.0:
                self._hit_sound_cd = 0.035
                soundbank.play("hit", 0.38)   # не 7 наложений от дроби
        else:
            if source is self.player:
                self.hitmarker_timer = 0.24
            self._on_enemy_killed(enemy, source)

    def _on_enemy_killed(self, enemy, source=None):
        # Награда уходит ВЛАДЕЛЬЦУ добивающего урона (последний удар).
        # Серия — личный счётчик локального героя и от чужих убийств
        # не растёт, иначе HUD показывал бы чужой ритм боя.
        source = self.player if source is None else source
        source.kills += 1
        if source is self.player:
            self.combo = min(COMBO_MAX + 20, self.combo + 1)
            self.combo_timer = COMBO_WINDOW
            self.max_combo = max(self.max_combo, self.combo)
        multiplier = self.combo_multiplier if source is self.player else 1.0
        depth_mult = 1.0 + (max(1, getattr(self, "depth", 1)) - 1) * DEPTH_LOOT_GROWTH
        source.score += int(round(enemy.score * multiplier * depth_mult))
        gain = max(1, int(round(
            enemy.bounty * (0.7 + 0.3 * multiplier) * multiplier
            * depth_mult * source.boon_loot_mult
            * (1.0 + source.skill_mod("loot_add")))))
        source.money += gain

        self.effects.append(FloatingText(
            enemy.x, enemy.y - enemy.radius * 0.9, f"+{gain}",
            (255, 208, 100), 21, 64.0))
        if source.boon_lifesteal > 0.0:
            source.heal(source.boon_lifesteal)
            self.effects.append(Particle(source.x, source.y,
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
            # Осколок души — только с босса: воскрешение павшего у алтаря
            self.drops.append(SoulShardDrop(enemy.x - 22, enemy.y - 16))
            # Босс — гарантированный источник жетонов: их хватает и на
            # подготовку чужой школы, и на углубление второй ветви.
            for key in random.sample(TOKEN_KEYS, BOSS_TOKEN_REWARD):
                source.add_weapon_token(key, 1)
            if source is self.player:
                self.boss_kills += 1
            self.camera.add_shake(10)
            self.hitstop = max(self.hitstop, HITSTOP_BIG * 2)
            self.toast("БОСС ПОВЕРЖЕН — артефакт, припасы и жетоны на земле", 4.0,
                       color=(255, 210, 110))
        elif (getattr(enemy, "elite", False)
              and random.random() < ELITE_TOKEN_CHANCE):
            key = random.choice(TOKEN_KEYS)
            source.add_weapon_token(key, 1)
            if source is self.player:
                self.toast(f"ЭЛИТА: жетон школы «{TOKEN_NAMES[key]}»", 2.2,
                           color=(255, 208, 140))
        # событийный хук пассивного артефакта (M7): «Пожиратель» лечит
        # и т.п. Нет артефакта или нет хука — база отвечает пустотой.
        passive = source.equipment.get("passive_artifact")
        if passive is not None:
            passive.on_kill(source, self, enemy)

    def explode(self, x, y, radius, damage, knockback, hurt_player=True,
                bleed=0.0, slow=0.0, color=None, source=None):
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
        # Гостям нужен сам взрыв, а не только урон в HP: к следующему
        # снимку эффект уже погас.
        self.queue_net_event("explosion", x, y, radius, color)
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
                source=source,
            )
            if enemy.alive:
                if bleed:
                    apply_bleed(enemy, dealt * bleed, source=source)
                if slow:
                    apply_slow(enemy, slow, 0.55)

        if hurt_player:
            # Взрыв бьёт ВСЕХ в радиусе, кроме того, кто его устроил:
            # своя граната в кооперативе не калечит себя, но чужая
            # (и бомбер) — полноценная угроза для всех.
            for player in self.players:
                if player is source or not player.alive:
                    continue
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

    def zone_profile(self):
        """
        Профиль текущей локации (settings.ZONE_PROFILES) с плавным
        переходом от предыдущего типа: elapsed сбрасывается при старте
        сектора, поэтому смена типа докручивается за ZONE_TRANSITION_TIME.
        """
        if self.zone_prev == self.zone_key:
            return zones.profile(self.zone_key)
        t = zones.transition_progress(self.elapsed)
        return zones.blend_profile(self.zone_prev, self.zone_key, t)

    def entity_fade(self, x, y, prof=None):
        """
        0..1 — насколько объект в мировой точке (x, y) должен быть проявлен.

        Это замена бинарного гейта «рисовать / не рисовать»: объект
        рисуется с прозрачностью, поэтому у края света и у стен он
        гаснет/проявляется плавно, а не рывком.

        Составляющие:
          * свет — конус фонарика, лампы, вспышки (reveal-штора БЕЗ
            личного ореола): за спиной и вне конуса в темноте объект
            не проявляется вовсе;
          * smoothstep по профилю (zones.visibility) — прозрачность
            теряется постепенно с удалением от яркой части света;
          * мягкие стены — alpha падает по мере того, сколько пикселей
            отрезка игрок→объект проходит сквозь стены (LOS_FADE_PX).
        """
        prof = self.zone_profile() if prof is None else prof
        sx, sy = self.camera.to_screen(x, y)
        if prof.get("gated", False):
            alpha = zones.visibility(
                self.lighting.reveal_at(sx, sy), 0.0, prof)
            if alpha <= 0.0:
                return 0.0
        else:
            alpha = 1.0
        blocked = self._line_of_sight_px(x, y)
        if blocked > 0.0:
            alpha *= max(0.0, 1.0 - blocked / LOS_FADE_PX)
        return alpha

    def _line_of_sight_px(self, x, y, step_px=6.0):
        """
        Сколько пикселей отрезка игрок→точка проходит сквозь стены.

        0 — прямая видимость; ~толщина стены и больше — обзор закрыт.
        По этой длине объект гаснет плавно (см. entity_fade): у угла
        стены он теряет прозрачность постепенно, а не пропадает сразу.
        """
        observer = self.view_player()
        px, py = observer.x, observer.y
        dx, dy = x - px, y - py
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            return 0.0
        steps = min(140, max(2, int(dist / step_px) + 1))
        solid = self.world.is_solid_at
        step_len = dist / steps
        blocked = 0.0
        for i in range(1, steps):
            t = i / steps
            if solid(px + dx * t, py + dy * t):
                blocked += step_len
        return blocked

    def _fade_draw(self, surface, x, y, alpha, draw_fn, margin=96):
        """Рисует объект с прозрачностью alpha (см. utils.fade_draw)."""
        sx, sy = self.camera.to_screen(x, y)
        fade_draw(surface, sx, sy, alpha, draw_fn, margin)

    def draw(self):
        screen = self.screen
        if self.state == STATE_ONLINE:
            self.online_ui.draw(screen, self)
            return
        if self.state == STATE_TITLE:
            self.hud.draw_title(screen, self)
            return
        if self.state == STATE_TREE:
            # Доска навыков непрозрачна: не тратим кадр на мир и HUD под ней.
            self.skill_ui.draw(screen, self)
            return
        if getattr(self, "_warm_loading", False):
            # Сектор достраивается порциями: честный прогресс вместо фриза.
            self._draw_world_sync(screen)
            return
        # 0. свет строится ДО объектов: в тёмной локации видимость
        # читает световую штору (гейт «рисовать / не рисовать»).
        world = screen
        if self.camera.is_zoomed:
            world = self._world_layer_for(
                (self.camera.view_w, self.camera.view_h))
        self.lighting.set_view(*world.get_size())
        prof = self.zone_profile()
        self.lighting.set_profile(prof)
        # Плавная видимость вместо гейта «рисовать / не рисовать»:
        # alpha = свет (конус/лампы/вспышки, БЕЗ ореола) × мягкие стены.
        # 0 — объект не рисуется; 0..1 — проявляется/гаснет постепенно.
        def fade(x, y):
            return self.entity_fade(x, y, prof)

        # 0a. источники света: дуло, взрывы, магазины, лампы комнат
        # Павший наблюдает за живым соратником — свет и камера строятся
        # вокруг НЕГО, иначе экран оставался бы тёмным пятном у тела.
        view = self.view_player()
        player_screen = self.camera.to_screen(view.x, view.y)
        weapon = view.firearm
        muzzle_offset = weapon.muzzle_offset if weapon else 0
        muzzle_world = (
            view.x + math.cos(view.angle) * muzzle_offset,
            view.y + math.sin(view.angle) * muzzle_offset,
        )
        muzzle_screen = self.camera.to_screen(*muzzle_world)
        flashes = [
            (*self.camera.to_screen(effect.x, effect.y), effect.light_radius,
             getattr(effect, "light_color", (255, 168, 84)),
             None, (effect.x, effect.y))
            for effect in self.effects
            if effect.light_radius
            and self.camera.is_visible(effect.x, effect.y, effect.light_radius)
        ]
        flashes += [
            (*self.camera.to_screen(shop.x, shop.y), shop.light_radius,
             shop.color, None, (shop.x, shop.y))
            for shop in self.shops
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius)
        ]
        lamps = self.world.lamps_near(self.player.x, self.player.y, 1500)
        if self.host_perf:
            lamps = lamps[:HOST_PERF_LAMPS]
        for lamp in lamps:
            if self.camera.is_visible(lamp["x"], lamp["y"], lamp["radius"]):
                sx, sy = self.camera.to_screen(lamp["x"], lamp["y"])
                # Профиль мерцания общий с плафоном (zones.flicker) —
                # пятый элемент вспышки задаёт готовую силу света,
                # шестой — мировую позицию (для обрезки света стенами).
                # Сила света квантуется по 0.2: «умирающая» лампа иначе
                # просит пересборку света каждый кадр, а шаг в 20% на
                # мерцающем источнике глазом не читается.
                strength = round(zones.flicker(lamp.get("flicker", "steady"),
                                               self.elapsed, lamp["phase"]) * 5) / 5
                flashes.append((sx, sy, lamp["radius"], lamp["color"],
                                strength, (lamp["x"], lamp["y"])))
        for bx, by, radius, color in self.descent.lights():
            if self.camera.is_visible(bx, by, radius):
                sx, sy = self.camera.to_screen(bx, by)
                pulse = 0.82 + 0.18 * math.sin(self.elapsed * 3.2 + bx * 0.01)
                flashes.append((sx, sy, int(radius * pulse), color,
                                None, (bx, by)))
        if not self.host_perf:
            for shot in self.enemy_shots:
                if shot.light_radius and self.camera.is_visible(
                        shot.x, shot.y, shot.light_radius):
                    sx, sy = self.camera.to_screen(shot.x, shot.y)
                    # Снаряд — движущийся свет: обрезку не кэшируем, свет мал.
                    flashes.append((sx, sy, shot.light_radius,
                                    shot.light_color))

        if self.host_perf and len(flashes) > HOST_PERF_FLASHES:
            # В тяжёлом режиме светят только ближайшие к герою источники:
            # пересборка маски света — самая дорогая часть кадра хоста.
            px, py = player_screen
            flashes.sort(key=lambda item: (item[0] - px) ** 2
                         + (item[1] - py) ** 2)
            del flashes[HOST_PERF_FLASHES:]

        danger = 0.0
        if view.alive:
            ratio = view.hp / max(1, view.max_hp)
            if ratio < 0.35:
                danger = (0.35 - ratio) / 0.35
        self.lighting.build_mask(
            player_screen, muzzle_screen, view.angle,
            view.flash_timer, flashes, time=self.elapsed,
            player_world=(view.x, view.y),
            world_to_screen=self.camera.to_screen,
            solid_at=self.world.is_solid_at)

        # 1. физический слой мира
        self.world.draw(world, self.camera)
        self.exploration.draw(world, self.camera, view, visible=fade)
        self.descent.draw(world, self.camera, self.elapsed)
        for effect in self.effects:
            if not effect.emissive and self.camera.is_visible(effect.x, effect.y):
                effect.draw(world, self.camera)
        for drop in self.drops:
            if self.camera.is_visible(drop.x, drop.y):
                a = fade(drop.x, drop.y)
                if a <= 0.01:
                    continue
                self._fade_draw(world, drop.x, drop.y, a,
                                lambda d=drop: d.draw(world, self.camera), 64)
        for grenade in self.grenades:
            grenade.draw(world, self.camera)
        for shop in self.shops:
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius):
                a = fade(shop.x, shop.y)
                if a <= 0.01:
                    continue
                self._fade_draw(world, shop.x, shop.y, a,
                                lambda s=shop: s.draw(world, self.camera), 110)
        for enemy in self.enemies:
            extent = enemy.fade_margin
            if self.camera.is_visible(enemy.x, enemy.y, extent):
                a = fade(enemy.x, enemy.y)
                if a <= 0.01:
                    continue
                self._fade_draw(world, enemy.x, enemy.y, a,
                                lambda e=enemy: e.draw(world, self.camera),
                                extent)

        # 2. штора накладывается на отрисованную сцену
        self.lighting.apply(world, danger=danger, hurt=self.damage_flash,
                            time=self.elapsed)

        # 3. геометрия и светящиеся объекты — поверх темноты
        if prof.get("edges", True):
            self.world.draw_edges(world, self.camera)
        self.world.draw_lamps(world, self.camera, self.elapsed)
        for shop in self.shops:
            if self.camera.is_visible(shop.x, shop.y, shop.light_radius):
                a = fade(shop.x, shop.y)
                if a <= 0.01:
                    continue
                self._fade_draw(
                    world, shop.x, shop.y, a,
                    lambda s=shop: s.draw_overlay(world, self.camera,
                                                  self.elapsed), 110)
        self.exploration.draw_overlay(world, self.camera, view,
                                      visible=fade)
        self.descent.draw_overlay(world, self.camera, self.elapsed, self,
                                  visible=fade)
        for drop in self.drops:
            if self.camera.is_visible(drop.x, drop.y, 30):
                a = fade(drop.x, drop.y)
                if a <= 0.01:
                    continue
                self._fade_draw(
                    world, drop.x, drop.y, a,
                    lambda d=drop: d.draw_glow(world, self.camera,
                                               self.elapsed), 64)

        # визуал атак ближнего боя — ПОВЕРХ темноты, иначе удар не видно
        melee = view.melee
        if melee is not None:
            overlay = self._attack_layer_for(world.get_size())
            overlay.fill((0, 0, 0, 0))
            melee.draw(overlay, self.camera, view)
            world.blit(overlay, (0, 0))
        # Замахи остальных героев: у чужих (и у своего на клиенте) нет
        # локальной симуляции атаки, поэтому дугу рисуем по таймеру.
        self._draw_swing_arcs(world, view)

        # Свой герой всегда яркий (он сам источник света), чужие —
        # проявляются по свету и видимости, как враги.
        for player in self.players:
            if player is self.player:
                player.draw(world, self.camera)
                continue
            if not self.camera.is_visible(player.x, player.y):
                continue
            alpha = fade(player.x, player.y)
            if alpha <= 0.01:
                continue
            self._fade_draw(world, player.x, player.y, alpha,
                            lambda p=player: p.draw(world, self.camera), 96)
        for enemy in self.enemies:
            if self.camera.is_visible(enemy.x, enemy.y):
                a = fade(enemy.x, enemy.y)
                if a <= 0.01:
                    continue
                self._fade_draw(
                    world, enemy.x, enemy.y, a,
                    lambda e=enemy: e.draw_overlay(world, self.camera), 140)

        for bullet in self.bullets:
            if self.camera.is_visible(bullet.x, bullet.y):
                a = fade(bullet.x, bullet.y)
                if a <= 0.01:
                    continue
                self._fade_draw(world, bullet.x, bullet.y, a,
                                lambda b=bullet: b.draw(world, self.camera),
                                48)
        for shot in self.enemy_shots:
            if self.camera.is_visible(shot.x, shot.y):
                a = fade(shot.x, shot.y)
                if a <= 0.01:
                    continue
                self._fade_draw(world, shot.x, shot.y, a,
                                lambda s=shot: s.draw(world, self.camera), 64)
        for effect in self.effects:
            if effect.emissive and self.camera.is_visible(effect.x, effect.y):
                effect.draw(world, self.camera)

        # Полотно мира шире окна: уменьшаем его целиком, чтобы игрок
        # действительно видел больше карты, а HUD остался 1:1.
        if world is not screen:
            pygame.transform.scale(world, (WIDTH, HEIGHT), screen)

        if self.debug_visible:
            # Гистограмма кадра вместо среднего FPS: среднее прячет рывки.
            frame_stats = self.video.metrics.snapshot(
                percentiles=(50.0, 95.0, 99.0)).get("frame", {})
            slow = self.video.metrics.over_count("frame", 33.0)
            frame_line = (
                f"frame p50 {frame_stats.get('p50', 0.0):.1f}  "
                f"p95 {frame_stats.get('p95', 0.0):.1f}  "
                f"p99 {frame_stats.get('p99', 0.0):.1f}  "
                f"max {frame_stats.get('max', 0.0):.1f} ms  "
                f">33ms {slow}")
            lines = (f"FPS {self.clock.get_fps():.0f}  enemies {len(self.enemies)}  bullets {len(self.bullets)}",
                     frame_line,
                     f"Seed {self.world.seed}  chunks {len(self.world._chunks)}  effects {len(self.effects)}",
                     f"Depth {self.depth}  zone {self.zone_key}  beacons {self.descent.active_count}/{len(self.descent.beacons)}"
                     f"  shots {len(self.enemy_shots)}",
                     f"Melee X: {self.active_cooldown:.1f}s   combo {self.combo}")
            session = getattr(self, "session", None)
            if session is not None:
                net = getattr(session, "stats", {})
                if self.net_role == "host":
                    lines += (f"net {net.get('ticks', 0)} ticks  "
                              f"build {net.get('build_ms', 0.0):.2f} ms  "
                              f"out {net.get('bytes', 0)} B/tick  "
                              f"perf {'on' if self.host_perf else 'off'}",)
                elif self.net_role == "client" and self.client_view:
                    view_stats = self.client_view.stats
                    age = 0.0
                    if getattr(session, "last_snapshot_at", 0.0):
                        age = max(0.0, (time.monotonic()
                                        - session.last_snapshot_at) * 1000.0)
                    lines += (f"net snap {net.get('snapshots', 0)}  "
                              f"rtt {getattr(session, 'rtt_ms', 0.0):.0f}  "
                              f"jit {getattr(session, 'jitter_ms', 0.0):.0f} ms  "
                              f"snap age {age:.0f} ms  "
                              f"interp {self.client_view.interp_delay * 1000:.0f} ms",)
                    lines += (f"pred err {self.client_view.predict_error:.0f} px  "
                              f"timeline age {self.client_view.snapshot_age * 1000:.0f} ms  "
                              f"hz {netplay.SNAPSHOT_HZ:.0f}/{netplay.INPUT_HZ:.0f}",)
                    lines += (f"spawn {view_stats.get('spawns', 0)}  "
                              f"despawn {view_stats.get('despawns', 0)}  "
                              f"e {len(self.enemies)} b {len(self.bullets)}",)
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
        if self.net_role == "client":
            self._draw_hit_direction(screen)
        if self.coop_active:
            self._draw_player_tags(screen)
            self._draw_net_badge(screen)
            if not self.player.alive:
                self._draw_spectator_banner(screen)
        if self.boss_menu and self.state == STATE_PLAYING:
            self._draw_boss_menu(screen)
        if self.state == STATE_SHOP:
            self.shop_ui.draw(screen, self)
        elif self.state == STATE_DESCENT:
            self.descent_ui.draw(screen, self)
        elif self.state in (STATE_PAUSED, STATE_SETTINGS, STATE_DIFFICULTY):
            self.hud.draw_pause_menu(screen, self)

    # ------------------------------------------------------------ ОНЛАЙН
    def open_online(self):
        # Отдельный экран: одиночная игра не запускается автоматически.
        self.online_ui.reset()
        self.state = STATE_ONLINE

    def online_host(self):
        # Создать игру = открыть TCP-порт и ждать подключений.
        self.online_leave()
        try:
            self.session = HostSession(self.local_name, protocol.DEFAULT_PORT)
        except OSError as exc:
            self.online_ui.error = f'Не удалось открыть порт: {exc}'
            return False
        self.net_role = 'host'
        return True

    def online_join(self, address):
        # Подключение идёт в фоновом потоке сессии, экран показывает статус.
        if not address:
            self.online_ui.error = 'Введите адрес хоста'
            return False
        self.online_leave()
        self.session = ClientSession(address, 'Гость')
        self.net_role = 'client'
        return True

    def online_leave(self):
        session = getattr(self, 'session', None)
        if session is not None:
            try:
                session.close()
            except OSError:
                pass
        self.session = None
        self.net_role = None
        self.client_view = None
        self.coop_active = False
        if getattr(self, 'player', None) is not None:
            self.players = [self.player]
            self.remote_players = []
        self._sound_events = []
        self._sound_last.clear()
        self._net_events = []
        self._bind_audio()

    # ------------------------------------------------------------ ЗВУК
    def _audio_listener(self):
        """Позиция «ушей» этого клиента: свой герой (или тот, за кем смотрим)."""
        player = self.view_player()
        if player is None:
            return None
        return float(player.x), float(player.y)

    def _bind_audio(self):
        """Позиционный звук: затухание у всех, рассылка — только у хоста."""
        if not self.coop_active or self.net_role not in ('host', 'client'):
            soundbank.bind_audio(None, None)
            return
        relay = self._queue_sound if self.net_role == 'host' else None
        soundbank.bind_audio(self._audio_listener, relay)

    def _queue_sound(self, pid, name, x, y, volume):
        """Хост: звук игрока уходит гостям с БАЗОВОЙ громкостью.

        Каждый гость сам считает затухание по расстоянию до своего героя.
        Антифлуд по паре (игрок, звук): очередь не растёт от шквала
        выстрелов, и один и тот же звук не дублируется на высоком FPS.
        """
        gap = soundbank.SOUND_MIN_GAP.get(name, 0.05)
        now = float(self.elapsed)
        key = (int(pid), name)
        if now - self._sound_last.get(key, -1e9) < gap:
            return
        self._sound_last[key] = now
        if len(self._sound_events) >= 32:
            return
        self._sound_events.append((int(pid), str(name), float(x), float(y),
                                   float(volume)))

    def take_sound_events(self):
        """Забирает накопленные звуки (вызывает сетевой тик хоста)."""
        events = self._sound_events
        self._sound_events = []
        return events

    def queue_net_event(self, kind, x, y, size=0.0, color=None):
        """Хост: разовый видимый эффект — в очередь сетевого тика."""
        if self.net_role != "host" or self.session is None:
            return
        events = getattr(self, "_net_events", None)
        if events is None:
            events = self._net_events = []
        if len(events) >= 24:
            return
        events.append((str(kind), float(x), float(y), float(size),
                       tuple(color) if color else None))

    def take_net_events(self):
        events = getattr(self, "_net_events", None) or []
        self._net_events = []
        return events

    def _play_remote_sounds(self, payload):
        """Гость: играет звуки других игроков с затуханием по расстоянию."""
        if getattr(self, '_warm_loading', False):
            # Мир ещё не построен — слушать нечего.
            return
        items = payload.get('items') if isinstance(payload, dict) else None
        if not items:
            return
        local_pid = int(getattr(self, 'local_pid', 0) or 0)
        for pid, name, x, y, volume in items:
            if name == 'swing' and self.client_view is not None:
                # Замах ближнего боя приходит звуковым событием: клиент не
                # симулирует атаки, но видеть чужой (и свой) удар должен.
                self.client_view.present_swing(pid)
            if int(pid) == local_pid:
                # Свой звук — без панорамы и затухания: он «в голове».
                soundbank.play(str(name), float(volume))
            else:
                soundbank.play_remote(str(name), float(x), float(y),
                                      float(volume))

    def pump_online(self, dt):
        # Кадр экрана «Онлайн»: только сеть и отрисовка, мир не живёт.
        session = self.session
        if session is None:
            self.online_ui.sync(self)
            return
        if self.net_role == 'host':
            session.accept_handshakes()
            session.pump(self, dt)
        else:
            for kind, payload in session.pump():
                if kind == 'start':
                    self.start_coop_client(payload)
                    # Не выходим: в этой же пачке могут лежать spawn/progress
                    # первого сектора — терять их нельзя.
                    continue
                if kind == 'notice':
                    self.toast(str(payload.get('text', '')),
                               float(payload.get('timer', 2.4)),
                               tuple(payload.get('color') or
                                     (255, 220, 140)))
                elif kind == 'buy_result':
                    self.toast(str(payload.get('text', '')), 2.6,
                               (140, 236, 170) if payload.get('ok')
                               else (240, 140, 120))
        self.online_ui.sync(self)

    def start_coop_host(self):
        if self.net_role != 'host' or self.session is None:
            return False
        if self.session.status != 'waiting':
            return False
        self.session.start_run(self)
        return True

    def start_coop_run(self, clients, dedicated=False):
        """Старт вылазки. ``dedicated`` — у сервера нет своего героя.

        В host-based режиме первый герой — игрок-хост. У выделенного
        сервера игрока нет: в мире только подключённые гости, а сам
        процесс лишь симулирует и рассылает состояние.
        """
        # Один seed на всех: клиенты построят тот же сектор сами.
        self.local_pid = 1 if not dedicated else 0
        seed = random.SystemRandom().randrange(0, 2 ** 63)
        self.reset(seed=seed)
        self.net_role = 'host'
        self.coop_active = True
        self.server_authority = bool(dedicated)
        self.player.is_local = not dedicated
        self.player.name = self.local_name
        if dedicated:
            # Пустой список: герой процесса не участвует в бою и не
            # попадает в снимок. Иначе у клиентов был бы "фантомный"
            # союзник, на которого агрятся враги.
            self.players = []
            self.render_players = self.players
        else:
            self.players = [self.player]
            self.render_players = self.players
        for client in clients:
            player = self.spawn_coop_player(client.pid, client.name)
            client.player = player
        if dedicated and self.players:
            # Мир и камера сервера строятся вокруг первого живого гостя.
            self.player = self.players[0]
        self.remote_players = [p for p in self.players if p is not self.player]
        self.state = STATE_PLAYING
        self._bind_audio()
        self.toast(f'КООПЕРАТИВ · участников {len(self.players)}', 4.0,
                   color=(150, 226, 210))
        return self.seed, self.depth, self.zone_key

    def spawn_coop_player(self, pid, name):
        """Добавляет героя гостя в мир (старт вылазки или поздний вход)."""
        start_x, start_y = self.world.player_start()
        guests = [p for p in self.players
                  if getattr(p, 'pid', 0) not in (0, 1)]
        index = len(guests)
        offset = 44.0 * ((index + 2) // 2)
        side = 1.0 if index % 2 == 0 else -1.0
        px, py = self.world.resolve_circle(
            start_x + offset * side, start_y + offset * 0.5,
            getattr(self.player, 'radius', 14))
        player = Player(px, py)
        player.pid = int(pid)
        player.is_local = False
        player.name = str(name)
        self.players.append(player)
        if player not in self.render_players:
            self.render_players.append(player)
        return player

    def start_coop_client(self, payload):
        # Клиент получает общий seed и строит тот же мир локально.
        self.net_role = 'client'
        self.coop_active = True
        self.local_pid = int(getattr(self.session, 'pid', 2) or 2)
        self.reset(seed=int(payload.get('seed', 0)), warm_chunks=False)
        self.net_role = 'client'
        self.coop_active = True
        self.player.is_local = True
        self.player.name = getattr(self.session, 'player_name', 'Гость')
        self.client_view = ClientView(self)
        self.client_view.local_pid = self.local_pid
        # Свой герой — источник истины по позиции: хост принимает её из
        # ввода и рассылает другим. Сверка с снимком отключается: она
        # стоила кадров и давала "резинку" на пинге, а защита от
        # подмены координат в кооперативе не приоритет.
        self.client_view.local_authoritative = True
        self.state = STATE_PLAYING
        self._bind_audio()
        self.toast('ПОДКЛЮЧЕНО · ждём снимок мира', 2.4,
                   color=(150, 226, 210))

    def rebuild_client_world(self, seed, depth, zone):
        # Геометрия сектора воспроизводится из seed тем же кодом, что у хоста.
        self.seed = int(seed)
        self.zone_key = zone
        self.zone_prev = zone
        self.depth = int(depth)
        self.world = World(seed=self.seed, zone_key=zone, prefetch=False)
        start_x, start_y = self.world.player_start()
        self._begin_client_warm(start_x, start_y)
        self.exploration = Exploration(self.world)
        self.descent = DescentManager(self, self.depth)
        self.lighting = LightingManager()
        self.elapsed = 0.0
        self.spawn_timer = SPAWN_FIRST_DELAY
        self.camera.reset_shake()
        self._sync_shops()

    # ------------------------------------------- КЛИЕНТ: МИР ПОРЦИЯМИ
    def _begin_client_warm(self, start_x, start_y):
        self._warm_finished = False
        # Долгоживущие объекты старта — в «вечную» генерацию: сборщик не
        # обходит их каждый раз, паузы в кадрах загрузки короче (max — 25 мс
        # вместо 38 мс на этой машине, замерено).
        """Очередь генерации чанков вокруг старта нового сектора.

        Клиенту мир нужен только для картинки и коллизий взгляда, поэтому
        строить его можно кадр за кадром. Хост этого не делает: у него
        симуляция и полный мир нужны сразу.
        """
        world = self.world
        cx = math.floor(start_x / world.chunk_pixels)
        cy = math.floor(start_y / world.chunk_pixels)
        # Радиус 3 (49 чанков): в кадре видно ~2x2, остальное — запас,
        # чтобы при движении чанки не генерировались в бою.
        queue = [(cx + dx, cy + dy)
                 for dy in range(-3, 4) for dx in range(-3, 4)]
        queue.sort(key=lambda chunk: abs(chunk[0] - cx) + abs(chunk[1] - cy))
        self._warm_queue = queue
        self._warm_total = len(queue)
        self._warm_loading = True
        gc.collect()
        gc.freeze()

    def _warm_client_world(self):
        """Генерирует 1 чанк за кадр (бюджет 6 мс) вместо длинного фриза.

        Полсекунды дольше грузимся — зато экран загрузки держит полный FPS
        и ни одного кадра > 33 мс. По завершении — gc.collect + gc.freeze:
        долгоживущие объекты старта больше не проверяются сборщиком.
        """
        queue = getattr(self, "_warm_queue", None)
        if not queue:
            if getattr(self, "_warm_loading", False):
                self._warm_loading = False
                self._finish_client_warm()
            return
        deadline = time.perf_counter() + 0.006
        while queue:
            chunk = queue.pop(0)
            if chunk in self.world._chunks:
                continue
            self.world._generate_chunk(*chunk)
            if time.perf_counter() >= deadline:
                break
        if not queue:
            self._warm_loading = False
            self._finish_client_warm()

    def _stream_client_chunks(self):
        """Достраивает мир вокруг гостя по одному чанку за кадр.

        Генерация чанка — ~14 мс: пачка из пяти дала бы рывок на 70 мс,
        которого хост не видит. Поэтому здесь только пополняется очередь,
        а работу с бюджетом кадра делает _warm_client_world. Если этого не
        делать, чанки генерировались бы внутри draw именно в тот кадр,
        когда герой подходит к краю построенного мира.
        """
        world = getattr(self, "world", None)
        player = getattr(self, "player", None)
        if world is None or player is None:
            return
        queue = getattr(self, "_warm_queue", None)
        if queue is None:
            queue = self._warm_queue = []
        if len(queue) > 24:
            return                  # запас уже есть
        cx = math.floor(player.x / world.chunk_pixels)
        cy = math.floor(player.y / world.chunk_pixels)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                key = (cx + dx, cy + dy)
                if key in world._chunks or key in queue:
                    continue
                queue.append(key)

    def _finish_client_warm(self):
        """Загрузка сектора закончена: применяем первый снимок без пауз GC."""
        if getattr(self, "_warm_finished", False):
            return
        self._warm_finished = True
        gc.collect()
        try:
            gc.freeze()
        except AttributeError:      # Python без gc.freeze — не ошибка
            pass

    def _draw_world_sync(self, screen):
        screen.fill((8, 11, 17))
        width, height = screen.get_size()
        total = max(1, getattr(self, "_warm_total", 1))
        left = len(getattr(self, "_warm_queue", []))
        progress = 1.0 - left / total
        visuals.text(screen, "СИНХРОНИЗАЦИЯ СЕКТОРА",
                     (width // 2, height // 2 - 44), 30,
                     (222, 232, 240), align="center")
        bar_w, bar_h = min(420, width - 160), 10
        x, y = (width - bar_w) // 2, height // 2 + 4
        pygame.draw.rect(screen, (28, 38, 50), (x, y, bar_w, bar_h),
                         border_radius=5)
        pygame.draw.rect(screen, (110, 210, 190),
                         (x, y, int(bar_w * progress), bar_h),
                         border_radius=5)
        visuals.text(screen, "мир строится локально · сеть не ждёт",
                     (width // 2, y + 32), 16, (130, 150, 165),
                     align="center")

    def _apply_net_events(self, items):
        """Гость: разовые эффекты с хоста (взрывы, удары врагов).

        Это ТОЛЬКО картинка: урон уже применён хостом и приедет в HP.
        Радиус взрыва и цвет берём из события, частицы считаем сами.
        """
        player = self.view_player()
        for entry in items:
            try:
                kind, x, y, size, color = entry
            except (TypeError, ValueError):
                continue
            if kind == "explosion":
                tint = tuple(color) if color else None
                self.effects.append(Explosion(float(x), float(y),
                                              float(size), color=tint))
                if player is not None:
                    dist = math.hypot(float(x) - player.x, float(y) - player.y)
                    if dist < 900.0:
                        self.camera.add_shake(6.0)
                        soundbank.play_remote("explosion", float(x), float(y),
                                              0.7)
            elif kind == "enemy_attack":
                tint = tuple(color) if color else (255, 110, 90)
                for _ in range(4):
                    self.effects.append(Spark(float(x), float(y),
                                              random.uniform(0, math.tau),
                                              tint, 90))

    def snapshot_payload(self):
        return net_snapshot.build(self)

    def net_clock(self):
        """Монотонные часы для датировки снимков.

        ``elapsed`` — игровое время: оно замирает на hitstop и теряет
        время при рывках кадра (dt clamp). По нему шкала снимков уезжала
        от реального времени, и гость периодически переякоривал таймлайн
        и получал «резинку». Сетевые метки должны идти по реальным часам.
        """
        return time.monotonic()

    def _pump_client_events(self):
        session = self.session
        if session is None:
            return
        for kind, payload in session.pump():
            if kind == 'reconnecting':
                # Связь пропала, но вылазка жива: сессия сама пробует
                # вернуться в неё до RESUME_WINDOW секунд.
                self.toast('СВЯЗЬ ПРЕРВАНА · переподключение…', 5.0,
                           (240, 200, 120))
                continue
            if kind == 'resumed':
                # Вернулись в ту же вылазку: зеркало и rev прогрессии — с нуля.
                if self.client_view is not None:
                    self.client_view.reset_mirrors()
                soundbank.play('ui_confirm', 0.7)
                self.toast('СВЯЗЬ ВОССТАНОВЛЕНА', 2.0, (150, 226, 190))
                continue
            if kind == 'closed':
                self.online_ui.screen = 'error'
                self.online_ui.error = (session.error or payload or
                                        'Хост завершил сессию')
                self.session = None
                self.net_role = None
                self.coop_active = False
                self.client_view = None
                self._bind_audio()
                self.state = STATE_ONLINE
                return
            if kind in ('spawn', 'despawn', 'progress'):
                # Репликация: дескрипторы/удаления/прогрессия идут отдельными
                # событиями и не разбираются в пути снимка.
                view = self.client_view
                if view is None:
                    continue
                if kind == 'spawn':
                    view.apply_spawn(payload)
                elif kind == 'despawn':
                    view.apply_despawn(payload)
                else:
                    view.apply_progress_message(payload)
            elif kind == 'sounds':
                # Звуки других игроков: позиция + базовая громкость,
                # затухание считается здесь, по своему герою.
                self._play_remote_sounds(payload)
            elif kind == 'events':
                self._apply_net_events(payload.get('items') or ())
            elif kind == 'notice':
                self.toast(str(payload.get('text', '')),
                           float(payload.get('timer', 2.4)),
                           tuple(payload.get('color') or (255, 220, 140)))
            elif kind == 'buy_result':
                # Ответ на намерение: подтверждение — зелёная плашка,
                # отказ — красная. Состояние героя уже пришло снимком/
                # progress от хоста, здесь только обратная связь.
                ok = bool(payload.get('ok'))
                text = str(payload.get('text', ''))
                soundbank.play('buy' if ok else 'error', 0.7)
                if self.state == STATE_SHOP:
                    self.shop_ui.notify_result(ok, text)
                elif self.state == STATE_TREE:
                    self.skill_ui.notify_result(ok, text)
                self.toast(text, 2.6,
                           (140, 236, 170) if ok else (240, 140, 120))
            elif kind == 'intent_timeout':
                # Хост молчит или связь оборвалась. Повторять покупку
                # автоматически нельзя: она могла уже примениться.
                if payload.get('reason') == 'connection':
                    text = 'Связь с хостом прервана — покупка не подтверждена'
                else:
                    text = 'Хост не ответил — покупка не подтверждена'
                soundbank.play('error', 0.6)
                self.toast(text, 3.0, (240, 190, 110))
            elif kind == 'error':
                self.toast(str(payload), 3.0, (240, 140, 120))

    def _apply_snapshot(self):
        session = self.session
        view = self.client_view
        if session is None:
            return
        frames = session.take_snapshots()
        if view is None or not frames:
            return
        if getattr(self, "_warm_loading", False):
            # Первый снимок (и все до конца генерации) ждёт в сессии:
            # применять его посреди стройки — значит рвать кадр загрузки.
            # Очередь при этом не копим: старые кадры уже не нужны.
            return
        view.local_pid = self.local_pid
        # Все снимки, пришедшие с прошлого кадра: если хост рывком отправил
        # пачку, интерполяция получит все точки, а не только последнюю.
        for snap in frames:
            view.apply(snap)

    def _client_update(self, dt):
        self.elapsed += dt
        # Красная вспышка урона — клиентская реакция, гасим её сами.
        self.damage_flash = max(0.0, self.damage_flash - dt * 3.0)
        self.hit_dir_timer = max(0.0, self.hit_dir_timer - dt)
        self.recoil = max(0.0, self.recoil - dt * 3.4)
        self.camera.update(dt)
        self._pump_client_events()
        if self.session is None:
            return
        self._apply_snapshot()
        if self.client_view is not None:
            # Насколько позиция хоста в снимке отстаёт от «сейчас»: половина
            # RTT плюс интервал снимков. По этой оценке расширяется мёртвая
            # зона предсказания — иначе честный бег постоянно подтягивало
            # бы назад и управление ощущалось вязким.
            rtt = max(0.0, float(getattr(self.session, "rtt_ms", 0.0))) / 1000.0
            # Снимок датирован моментом съёмки: половина RTT — насколько он
            # старше момента прихода. Без этой оценки сверка предсказания
            # отставала на пинг и тянула героя назад.
            # Сглаживаем: одиночный всплеск RTT не должен сдвигать курсор
            # интерполяции назад (это читалось бы как шаг чужого героя).
            latency = min(0.2, rtt * 0.5)
            current = getattr(self.client_view, "net_latency", 0.0)
            self.client_view.net_latency = current + (latency - current) * 0.1
            self.client_view.input_latency = (
                rtt * 0.5 + 1.0 / netplay.SNAPSHOT_HZ)
            # Предсказание ввода: свой герой идёт локально, без ступеньки
            # между снимками.
            if getattr(self.session, "status", "") == "playing":
                self.client_view.set_local_input(*self._local_move_dir())
                self.client_view.set_local_fire(pygame.mouse.get_pressed()[0])
            else:
                # Переподключение: герой стоит, а не убегает в стену.
                self.client_view.set_local_input(0, 0)
                self.client_view.set_local_fire(False)
            self.client_view.update(dt)
        self._warm_client_world()
        self._stream_client_chunks()
        # Точки интереса детерминированы по сиду: клиент обновляет их
        # сам, а какие сундуки уже вскрыты — приходит снимком.
        moved = self.player
        if moved is not None:
            self.exploration.update(moved.x, moved.y)
        self._sync_shops()
        self._update_spectator_input()
        view = self.view_player()
        if view is not None:
            self.camera.follow(view.x, view.y)
        # Прицел — сразу по мыши, а не углом из снимка: снимок приходит
        # 20 раз в секунду и на RTT позже, из-за чего ствол «плыл» за
        # курсором. Хост всё равно проверяет выстрел.
        self._aim_local_player(self.camera.to_world(*pygame.mouse.get_pos()))
        self._send_client_input(dt)
        self._sync_camera_zoom()

    def _client_pump_only(self, dt):
        # Клиент с открытым окном (пауза/магазин) продолжает принимать снимки.
        self.elapsed += dt
        self.damage_flash = max(0.0, self.damage_flash - dt * 3.0)
        self.hit_dir_timer = max(0.0, self.hit_dir_timer - dt)
        self._client_trigger = False
        self._pump_client_events()
        if self.session is None:
            return
        self._apply_snapshot()
        if self.client_view is not None:
            # Окно открыто (пауза/магазин): герой стоит на месте.
            self.client_view.set_local_input(0, 0)
            self.client_view.set_local_fire(False)
            self.client_view.update(dt)
        self._warm_client_world()
        self._stream_client_chunks()
        moved = self.player
        if moved is not None:
            self.exploration.update(moved.x, moved.y)
        self._sync_shops()
        self._update_spectator_input()
        view = self.view_player()
        if view is not None:
            self.camera.follow(view.x, view.y)
        self.camera.update(dt)
        self._send_client_input(dt, idle_only=True)

    def _aim_local_player(self, mouse_world):
        """Клиент: свой герой смотрит в курсор СРАЗУ, без задержки снимка.

        Направление влияет только на картинку и на то, что уйдёт хосту в
        следующем вводе: урон, патроны и кулдауны остаются за хостом.
        """
        player = self.player
        if player is None:
            return
        player.angle = math.atan2(mouse_world[1] - player.y,
                                  mouse_world[0] - player.x)

    def _send_client_input(self, dt, idle_only=False):
        session = self.session
        if session is None or session.status != 'playing':
            return
        self._online_input_timer += dt
        interval = 1.0 / netplay.INPUT_HZ
        if self._online_input_timer < interval:
            return
        # Вычитаем интервал, а не обнуляем таймер: при 144 FPS обнуление
        # давало 48 Гц ввода вместо 60 и лишнюю ступеньку в поворотах.
        self._online_input_timer = min(self._online_input_timer - interval,
                                       interval)
        if idle_only or self.player is None or not self.player.alive:
            player = self.player
            session.send_input(
                (0.0, 0.0),
                player.angle if player else 0.0,
                (player.x, player.y) if player else (0.0, 0.0),
                False, False, [],
                position=(player.x, player.y) if player else None)
            self._online_actions.clear()
            return
        dx, dy = self._local_move_dir()
        mouse_world = self.camera.to_world(*pygame.mouse.get_pos())
        angle = math.atan2(mouse_world[1] - self.player.y,
                           mouse_world[0] - self.player.x)
        buttons = pygame.mouse.get_pressed()
        # Вспышка и гильза — в кадре нажатия. Пуля и урон всё равно придут
        # от хоста, но выстрел перестаёт «залипать» на RTT.
        if buttons[0] and not self._client_trigger \
                and self.client_view is not None:
            self.client_view.present_local_shot(self.player)
        self._client_trigger = bool(buttons[0])
        # Замах ближнего боя — тоже сразу по нажатию: хост подтвердит урон
        # и кулдаун, но дуга не должна ждать RTT.
        if buttons[2] and not getattr(self, "_client_melee", False) \
                and self.client_view is not None:
            self.client_view.present_local_melee(angle)
        self._client_melee = bool(buttons[2])
        actions, self._online_actions = self._online_actions, []
        # Позиция — сразу за кадр, а не по подтверждению хоста: она же
        # уезжает другим гостям снимком.
        session.send_input((dx, dy), angle, mouse_world,
                           buttons[0], buttons[2], actions,
                           position=(self.player.x, self.player.y))

    @staticmethod
    def _local_move_dir():
        """Текущее направление движения с клавиатуры (для ввода и прогноза)."""
        keys = pygame.key.get_pressed()
        dx = (1 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0) - (
            1 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0)
        dy = (1 if keys[pygame.K_s] or keys[pygame.K_DOWN] else 0) - (
            1 if keys[pygame.K_w] or keys[pygame.K_UP] else 0)
        return dx, dy

    def _client_key(self, key):
        # Клиент превращает нажатия в НАМЕРЕНИЯ, а не в локальные действия.
        if key == pygame.K_F3:
            self.debug_visible = not self.debug_visible
            return
        if key in (pygame.K_t, pygame.K_y):
            # Доска открывается локально на ЗЕРКАЛЕ прогрессии, а
            # покупку проверяет и применяет хост.
            self.open_tree('firearm' if key == pygame.K_t else 'melee')
            return
        if key == pygame.K_e:
            if self.try_open_shop():
                return
            self._online_actions.append('interact')
            return
        actions = {
            pygame.K_SPACE: 'dash',
            pygame.K_r: 'reload',
            pygame.K_q: 'grenade',
            pygame.K_g: 'medkit',
            pygame.K_f: 'artifact',
            pygame.K_x: 'melee_ability',
            pygame.K_v: 'cycle_mode',
        }
        action = actions.get(key)
        if action is not None:
            self._online_actions.append(action)
            if action == 'dash' and self.client_view is not None:
                # Рывок предсказываем сразу: иначе герой 100+ мс стоит,
                # а потом хост «телепортирует» его на 120 px вперёд.
                self.client_view.request_dash()

    def _apply_remote_input(self, client):
        player = client.player
        if player is None:
            return
        state = client.input_state
        if not player.alive:
            player.move_dir = (0.0, 0.0)
            player.trigger_held = False
            player.melee_held = False
            state['actions'] = []
            return
        player.move_dir = state['move']
        player.angle = state['aim']
        player.aim_pos = (state['aim_x'], state['aim_y'])
        # Клиент — владелец позиции своего героя. Ставим её как есть и
        # больше не интегрируем движение на хосте: меньше работы в кадре
        # и ни одного отката у гостя.
        position = state.get('pos')
        if position is not None:
            player.x = float(position[0])
            player.y = float(position[1])
            player.position_authoritative = True
        player.trigger_held = state['fire']
        player.melee_held = state['melee']
        for action in state['actions']:
            self._run_player_action(player, action)
        state['actions'] = []

    def _run_player_action(self, player, action):
        if action == 'dash':
            player.start_dash()
        elif action == 'reload':
            player.start_reload()
        elif action == 'grenade':
            player.throw_grenade(self)
        elif action == 'medkit':
            player.use_medkit(self)
        elif action == 'artifact':
            player.use_artifact(self)
        elif action == 'melee_ability':
            self.use_melee_ability(player)
        elif action == 'cycle_mode':
            player.cycle_firearm_mode(self)
        elif action == 'interact':
            if not self.descent.interact(self, player):
                self.exploration.open_nearest(self, player)

    @contextmanager
    def _as_player(self, player):
        # Магазин и дерево навыков написаны вокруг одного hero.
        # На время покупки подменяем его покупателем и восстанавливаем
        # в finally — никакой «расщеплённой» логики в shop_ui не нужно.
        original = self.player
        self.player = player
        try:
            yield
        finally:
            self.player = original

    def purchase_for(self, player, shop_position, cursor, kind=None,
                     key=None):
        if player is None:
            return False, 'Нет игрока'
        if not player.alive:
            return False, 'Павший не торгует'
        shop = shop_near(self.shops, shop_position)
        if shop is None:
            return False, 'Магазин не найден'
        if distance(player.x, player.y, shop.x, shop.y) > SHOP_OPEN_DIST + 44:
            return False, 'Слишком далеко от магазина'
        with self._as_player(player):
            self.shop_ui.active_shop = shop
            items = self.shop_ui._items(self)
            if not items:
                return False, 'Витрина пуста'
            if cursor < 0 or cursor >= len(items):
                return False, 'Товара нет'
            offer = items[cursor]
            # Клиент называет товар, который видел. Если витрины разошлись,
            # покупка отклоняется, а не превращается в другой предмет.
            if kind and offer.get('kind') != kind:
                return False, 'Витрина изменилась'
            if key and offer.get('key') != key:
                return False, 'Витрина изменилась'
            handler = BUY_HANDLERS.get(offer['kind'])
            if handler is None:
                return False, 'Товар недоступен'
            ok, text = handler(self, offer)
        soundbank.play('buy' if ok else 'error')
        return ok, text

    def purchase_skill(self, player, zone, node_id):
        # Повторная проверка ВСЕГО на хосте: строку доски строит его
        # собственный интерфейс по его состоянию героя, поэтому цена,
        # подготовка и вторая ветвь не могут быть подделаны клиентом.
        if player is None:
            return False, 'Нет игрока'
        if not player.alive:
            return False, 'Павший не учится'
        with self._as_player(player):
            ui = self.skill_ui
            rows = ui.rows(self)
            row = next((item for item in rows
                        if item['zone'] == zone
                        and item['node']['id'] == node_id), None)
            if row is None:
                return False, 'Навык не найден'
            before = player.money
            ui.selected_key = (zone, node_id)
            ui.focus_zone = zone
            ui.buy(self)
            owned = (zone == 'player' and node_id in player.skill_nodes)
            ok = player.money < before or owned
            text = ui.message or ('Навык изучен' if ok else 'Недоступно')
        return ok, text

    def _draw_spectator_banner(self, screen):
        """Павший видит, за кем смотрит и как переключаться."""
        view = self.view_player()
        if view is self.player:
            return
        rect = pygame.Rect(WIDTH // 2 - 232, 18, 464, 74)
        layer = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        layer.fill((14, 12, 22, 218))
        pygame.draw.rect(layer, (128, 104, 176), layer.get_rect(), 1,
                         border_radius=10)
        screen.blit(layer, rect.topleft)
        visuals.text(screen, "НАБЛЮДЕНИЕ", (rect.centerx, rect.y + 8), 15,
                     (186, 160, 236), align="center")
        visuals.text(screen, f"камера: {view.name}", (rect.centerx, rect.y + 26),
                     21, (238, 230, 255), align="center")
        ratio = max(0.0, min(1.0, view.hp / max(1.0, view.max_hp)))
        visuals.bar(screen, pygame.Rect(rect.x + 26, rect.y + 52, 250, 6),
                    ratio, (126, 220, 150), (26, 30, 42))
        visuals.text(screen, "A / D — сменить", (rect.right - 26, rect.y + 46),
                     15, (170, 160, 196), align="right")

    def _update_host_perf(self, dt):
        """Хост сам решает, когда снять косметику ради ровного кадра.

        Гости не симулируют, но видят мир глазами хоста: его просадка —
        это рывки у всех. Режим включается по сглаженному времени кадра
        (а не по среднему FPS) и только когда есть кого спасать.
        """
        clients = getattr(getattr(self, "session", None), "clients", ())
        if not (self.coop_active and clients):
            self.host_perf = False
            self._perf_bad = 0.0
            self._perf_good = 0.0
            return
        if self.frame_ms > HOST_PERF_BAD_MS:
            self._perf_bad += dt
            self._perf_good = 0.0
        elif self.frame_ms < HOST_PERF_GOOD_MS:
            self._perf_good += dt
            self._perf_bad = 0.0
        if self._perf_bad >= HOST_PERF_ON_AFTER:
            self.host_perf = True
        elif self._perf_good >= HOST_PERF_OFF_AFTER:
            self.host_perf = False

    def _draw_swing_arcs(self, world, view):
        """Дуга замаха для героев, которых клиент не симулирует."""
        swings = []
        for player in self.players:
            if player is view and self.net_role != "client":
                # На хосте замах своего героя рисует сама атака. На клиенте
                # локальных атак нет: свой удар рисуется по таймеру, иначе
                # гость не видит собственный ближний бой вообще.
                continue
            if getattr(player, "melee_swing_timer", 0.0) <= 0.0:
                continue
            weapon = player.melee
            if weapon is None:
                continue
            swings.append((player, weapon))
        if not swings:
            return
        overlay = self._attack_layer_for(world.get_size())
        overlay.fill((0, 0, 0, 0))
        for player, weapon in swings:
            spec = getattr(weapon, "spec", None) or {}
            reach = float(spec.get("reach", 70.0)) * 0.9
            half = math.radians(float(spec.get("arc_deg", 90.0))) / 2
            color = tuple(spec.get("color") or (238, 226, 190))
            if not self.camera.is_visible(player.x, player.y, reach + 40.0):
                continue
            timer = max(0.0, min(1.0, player.melee_swing_timer / 0.22))
            progress = 1.0 - timer
            angle = float(getattr(player, "melee_swing_angle", player.angle))
            start = angle - half
            blade = start + 2.0 * half * progress
            cx, cy = self.camera.to_screen(player.x, player.y)
            pts = [(cx, cy)]
            steps = max(3, int(abs(blade - start) / 0.08))
            for index in range(steps + 1):
                arc = start + (blade - start) * index / steps
                pts.append((cx + math.cos(arc) * reach,
                            cy + math.sin(arc) * reach))
            pygame.draw.polygon(overlay, (*color, int(56 + 96 * progress)),
                                pts)
            tip = (cx + math.cos(blade) * reach,
                   cy + math.sin(blade) * reach)
            pygame.draw.line(overlay, (*color, 210), (cx, cy), tip, 4)
        world.blit(overlay, (0, 0))

    def _draw_hit_direction(self, screen):
        """Гость: красный сектор со стороны удара.

        Урон считает хост, поэтому в момент потери HP клиент сам решает,
        откуда он «пришёл»: ближайшая угроза. Так попадание читается как
        удар с конкретной стороны, а не как потеря HP из ниоткуда.
        """
        timer = getattr(self, "hit_dir_timer", 0.0)
        if timer <= 0.0:
            return
        player = self.view_player()
        if player is None or not player.alive:
            return
        sx, sy = self.camera.to_screen(player.x, player.y)
        angle = float(getattr(self, "hit_dir", 0.0))
        alpha = min(1.0, timer / 0.35)
        radius = float(getattr(player, "radius", 16.0)) + 30.0
        half = 0.34
        inner = 0.82
        points = [
            (sx + math.cos(angle - half * inner) * radius,
             sy + math.sin(angle - half * inner) * radius),
            (sx + math.cos(angle) * (radius + 16.0),
             sy + math.sin(angle) * (radius + 16.0)),
            (sx + math.cos(angle + half * inner) * radius,
             sy + math.sin(angle + half * inner) * radius),
        ]
        color = (int(255 * alpha), int(96 * alpha), int(84 * alpha))
        pygame.draw.lines(screen, color, False, points, 5)

    def _draw_player_tags(self, screen):
        for player in self.players:
            if player is self.player or not player.alive:
                continue
            if not self.camera.is_visible(player.x, player.y):
                continue
            sx, sy = self.camera.to_screen(player.x, player.y)
            if not (-80 < sx < WIDTH + 80 and -80 < sy < HEIGHT + 80):
                continue
            visuals.text(screen, player.name, (sx, sy - 40), 14,
                         (150, 226, 214), align='center')
            width = 46
            ratio = max(0.0, min(1.0, player.hp / max(1.0, player.max_hp)))
            x = int(sx - width / 2)
            y = int(sy - 30)
            pygame.draw.rect(screen, (12, 16, 24), (x, y, width, 4))
            pygame.draw.rect(screen, (86, 208, 118),
                             (x, y, int(width * ratio), 4))

    def _draw_net_badge(self, screen):
        role = 'ХОСТ' if self.net_role == 'host' else 'КЛИЕНТ'
        visuals.text(screen,
                     f'ОНЛАЙН · {role} · игроков {len(self.players)}',
                     (WIDTH - 16, 12), 14, (128, 210, 200),
                     align='right')

    def _draw_boss_menu(self, screen):
        """Алтарь призыва: карточки боссов вместо голого списка."""
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((4, 7, 12, 170))
        screen.blit(dim, (0, 0))
        w, h = 700, 500
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