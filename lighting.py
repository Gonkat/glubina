"""
Свет и темнота.

Приём остался прежним (умножение сцены на «штору»), но штора теперь
строится иначе: холодный ambient + АДДИТИВНЫЕ цветные источники. Это
позволяет делать тёплый фонарик, бирюзовые лампы и оранжевые взрывы,
не превращая экран в чёрную дыру. Края экрана затемняются виньеткой,
а при низком HP появляется красная пульсация.

Разделение на два шага (новое):
  build_mask(...)  — строит штору ДО отрисовки объектов, чтобы видимость
                     (zones.visibility) читала её при принятии решения
                     «рисовать / не рисовать»;
  apply(...)       — накладывает готовую штору на уже отрисованную сцену.

Профиль локации (zones.py / settings.ZONE_PROFILES) управляет ambient,
силой и дальностью фонарика, тенями от стен и дифракцией («огибанием»
углов). Тени считаются raycast'ом по тайлам мира и кэшируются по позиции
и углу; на слабых ПК их можно выключить флагом shadows_enabled.
"""
import math

import pygame

import zones
from settings import (
    AMBIENT_LIGHT,
    BEAM_COLOR,
    BEAM_HALF_ANGLE,
    BEAM_RANGE,
    FLASH_COLOR,
    FLASH_RADIUS,
    GLOW_COLOR,
    GLOW_RADIUS,
    HEIGHT,
    VIGNETTE_COLOR,
    WIDTH,
)
from utils import mix

CONE_SCALE = 3
_LIGHT_CACHE = {}
# Лампы при скоплении рисуются в слой половинного разрешения: свет —
# низкочастотный, а блit'ы становятся вчетверо дешевле.
_LAMP_SCALE = 0.5
_LAMP_LAYER_MIN = 3
# Бюджет пересборок обрезанного света на кадр. Мерцание меняет силу
# сразу у нескольких ламп — без бюджета они пересобираются в одном
# кадре и дают рывок. Отставание на 1-2 кадра глазом не видно.
_CLIP_REBUILD_BUDGET = 4
# База для радиального света: градиент рисуется в этом разрешении и
# растягивается до нужного радиуса. Мерцание меняет силу света и раньше
# перерисовывало 28 кругов по (2r)×(2r) — до мегапикселя на кадр.
_LIGHT_BASE_R = 48


def _lru_store(cache, key, value, limit):
    """Кладёт в кэш с вытеснением самой старой записи (а не очисткой)."""
    while len(cache) >= limit:
        cache.pop(next(iter(cache)), None)
    cache[key] = value

# Сколько света проходит сквозь стену (частичное поглощение), в/255.
# 12 — почти ноль: за стеной остаётся лишь слабая дымка (порог
# видимости тёмной зоны 0.06 её не достигает).
_SHADOW_ABSORB = 12
# Кэш raycast-дистанций: ключ — позиция в тайлах + угол.
_RAY_CACHE_MAX = 128


def _light_surface(radius, color, strength=1.0):
    """
    Аддитивный радиальный свет: чёрный снаружи, цвет — к центру.

    Градиент строится в базовом разрешении (96×96) и растягивается
    сглаженно до нужного радиуса: перерисовка при мерцании в разы
    дешевле, меньше аллокаций и пауз GC.
    """
    radius = max(6, int(radius))
    # Шаг силы — 0.1: мерцание ламп не плодит десятки кэш-вариантов.
    strength = round(max(0.05, min(1.5, strength)), 1)
    key = (radius, tuple(color), strength)
    surf = _LIGHT_CACHE.get(key)
    if surf is not None:
        return surf
    base = min(radius, _LIGHT_BASE_R)
    small = pygame.Surface((base * 2, base * 2))
    small.fill((0, 0, 0))
    steps = 28
    for i in range(steps, 0, -1):
        t = i / steps                        # 1 — край, 0 — центр
        falloff = (1.0 - t) ** 1.7 * strength
        value = tuple(min(255, int(c * falloff)) for c in color)
        pygame.draw.circle(small, value, (base, base),
                           max(1, int(base * t)))
    if base != radius:
        surf = pygame.transform.smoothscale(small, (radius * 2, radius * 2))
    else:
        surf = small
    _lru_store(_LIGHT_CACHE, key, surf, 120)
    return surf


class LightingManager:
    """Работает в координатах полотна мира: при оптике оно больше окна."""

    def __init__(self):
        self.view_w = WIDTH
        self.view_h = HEIGHT
        self.mask = pygame.Surface((WIDTH, HEIGHT))
        # «Проявляющий» свет — копия шторы без личного ореола: только им
        # (конус, лампы, вспышки) открываются объекты в темноте.
        self.reveal = pygame.Surface((WIDTH, HEIGHT))
        self.cone_small = pygame.Surface(
            (WIDTH // CONE_SCALE, HEIGHT // CONE_SCALE)
        )
        self.cone_scaled = pygame.Surface((WIDTH, HEIGHT))
        # Слои для теней конуса и дифракции (размер — как у cone_small).
        self.cone_clip = pygame.Surface(self.cone_small.get_size())
        self.cone_soft = pygame.Surface(self.cone_small.get_size())
        self.cone_weak = pygame.Surface(self.cone_small.get_size())
        # Черновики обрезки света (кэш по размеру радиуса: у ламп, магазинов
        # и ореола радиусы разные — без кэша они пересоздавались бы каждый кадр).
        self._glow_scratch_cache = {}
        # Готовые обрезанные стенами слои ламп/магазинов/взрывов:
        # полигон не зависит от сдвига камеры, а источники статичны.
        self._clip_light_cache = {}
        # Бюджет пересборок света на кадр (см. _CLIP_REBUILD_BUDGET).
        self._clip_budget = _CLIP_REBUILD_BUDGET
        # Полуразрешающий слой ламп и буфер его апскейла (см. build_mask).
        self._lamp_surface = None
        self._lamp_scaled = None
        # Готовая заливка цветом ambient — для вычитания фона из reveal.
        self._ambient_fill_cache = {}
        self.vignette = self._build_vignette(WIDTH, HEIGHT)
        self._flash_cache = _light_surface(FLASH_RADIUS, FLASH_COLOR, 0.95)
        # Профиль текущей локации; по умолчанию — «средний» (прежнее
        # поведение игры), пока Game не назначит свой.
        self.profile = zones.profile("medium")
        # Общий тумблер теней (графические настройки могут выключить).
        self.shadows_enabled = True
        self._ray_cache = {}

    def set_profile(self, prof):
        """Профиль локации (dict из settings.ZONE_PROFILES / blend)."""
        self.profile = prof if prof is not None else zones.profile("medium")

    def set_view(self, width, height):
        """Пересобирает световые слои, когда оптика меняет размер обзора."""
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == (self.view_w, self.view_h):
            return
        self.view_w, self.view_h = width, height
        size = (width, height)
        self.mask = pygame.Surface(size)
        self.reveal = pygame.Surface(size)
        small = (max(1, width // CONE_SCALE), max(1, height // CONE_SCALE))
        self.cone_small = pygame.Surface(small)
        self.cone_scaled = pygame.Surface(size)
        self.cone_clip = pygame.Surface(small)
        self.cone_soft = pygame.Surface(small)
        self.cone_weak = pygame.Surface(small)
        self.vignette = self._build_vignette(width, height)
        self._ray_cache.clear()
        self._lamp_surface = None
        self._lamp_scaled = None
        self._ambient_fill_cache.clear()

    # ------------------------------------------------------------ СВЕТ
    def build_mask(self, player_screen_pos, muzzle_screen_pos, angle,
                   flash_timer, flashes=(), time=0.0, prof=None,
                   player_world=None, world_to_screen=None, solid_at=None):
        """
        Строит световую штору, НЕ накладывая её на сцену.

        flashes — (x, y, radius) | (x, y, radius, color)
                 | (x, y, radius, color, strength)
                 | (x, y, radius, color, strength, world_pos),
                 в экранных координатах.
        Пятый элемент — готовая сила света (профиль мерцания лампы);
        без него применяется лёгкое случайное мерцание. Шестой — мировая
        позиция источника: такой свет (лампа, магазин, взрыв) режется
        стенами, как ореол.
        player_world / world_to_screen / solid_at нужны только для теней
        конуса от стен (профиль с shadows=True).

        Дополнительно ведётся self.reveal — та же штора, но БЕЗ личного
        ореола: по ней решается, открыт ли объект в темноте (см.
        reveal_at), чтобы ореол не проявлял врагов за спиной.
        """
        prof = self.profile if prof is None else prof
        mask = self.mask
        mask.fill(tuple(prof.get("ambient", AMBIENT_LIGHT)))
        # Свежий бюджет пересборок источников на этот кадр.
        self._clip_budget = _CLIP_REBUILD_BUDGET

        # 1. конус фонарика: несколько вложенных конусов дают мягкий край,
        #    при shadows — обрезается полигоном видимости от стен.
        self._add_cone(mask, player_screen_pos, angle, time, prof,
                       player_world, world_to_screen, solid_at)

        # 2. статические лампы и прочие цветные источники
        can_clip = (prof.get("shadows") and self.shadows_enabled
                    and solid_at is not None and world_to_screen is not None)
        world_lights = []
        for light in flashes:
            if len(light) >= 4:
                x, y, radius, color = light[:4]
            else:
                x, y, radius = light[:3]
                color = (255, 170, 90)
            strength = light[4] if len(light) >= 5 else None
            world_pos = light[5] if len(light) >= 6 else None
            if strength is None:
                # лёгкое мерцание делает свет живым
                strength = 0.92 + 0.08 * math.sin(
                    time * 7.0 + x * 0.07 + y * 0.05)
            if can_clip and world_pos is not None:
                # Свет с мировой позицией (лампа, магазин, взрыв) режется
                # стенами так же, как ореол: в соседнюю комнату он не льётся.
                world_lights.append((x, y, radius, color,
                                     float(strength), world_pos))
            else:
                self._add(mask, radius, color, (x, y), strength)
        if world_lights:
            if len(world_lights) >= _LAMP_LAYER_MIN:
                # Скопление источников (уютные комнаты): рисуем их в слой
                # ПОЛОВИННОГО разрешения и растягиваем один раз за кадр —
                # свет низкочастотный, а блit'ы вчетверо дешевле.
                layer = self._lamp_layer()
                layer.fill((0, 0, 0))
                for x, y, radius, color, strength, world_pos in world_lights:
                    self._add_world_light(layer, radius, color, (x, y),
                                          strength, world_pos,
                                          world_to_screen, solid_at,
                                          _LAMP_SCALE)
                pygame.transform.scale(layer, (self.view_w, self.view_h),
                                       self._lamp_scaled)
                mask.blit(self._lamp_scaled, (0, 0),
                          special_flags=pygame.BLEND_RGB_ADD)
            else:
                for x, y, radius, color, strength, world_pos in world_lights:
                    self._add_world_light(mask, radius, color, (x, y),
                                          strength, world_pos,
                                          world_to_screen, solid_at, 1.0)

        # 3. вспышка выстрела
        if flash_timer > 0.0:
            trail = max(0.0, min(1.0, flash_timer / 0.09))
            mask.blit(self._flash_cache,
                      (muzzle_screen_pos[0] - FLASH_RADIUS,
                       muzzle_screen_pos[1] - FLASH_RADIUS),
                      special_flags=pygame.BLEND_RGB_ADD)
            self._add(mask, 90, (255, 230, 190), player_screen_pos,
                      0.55 * trail)

        # 4. «проявляющий» свет = снимок шторы ДО ореола: конус, лампы и
        #    вспышки открывают объекты в темноте, а личный ореол — нет
        #    (иначе всё за спиной героя светилось бы силуэтами).
        #    Фоновая подсветка (ambient) вычитается: она освещает пол и
        #    стены, но НЕ проявляет врагов и чужих игроков — их открывает
        #    только настоящий свет. Иначе в «среднем» секторе всё было бы
        #    видно и без фонарика.
        self.reveal.blit(mask, (0, 0))
        ambient = tuple(int(c) for c in prof.get("ambient", AMBIENT_LIGHT))
        if max(ambient) > float(prof.get("light_threshold", 0.0)) * 255.0:
            # Вычитание — БЛit'ом готовой заливки, а не fill(BLEND_RGB_SUB):
            # у fill со special_flags в SDL нет SIMD-пути (4 мс на кадр),
            # а blit той же поверхности — доли миллисекунды.
            self.reveal.blit(self._ambient_fill(ambient), (0, 0),
                             special_flags=pygame.BLEND_RGB_SUB)

        # 5. личный ореол героя (тёплый, чтобы видеть ноги и стены рядом).
        #    С тенями — обрезается стенами: свет не светит сквозь них.
        #    На reveal не копируется — см. п.4.
        glow = 0.90 * float(prof.get("glow_mul", 1.0))
        if glow > 0.0:
            if (prof.get("shadows") and self.shadows_enabled
                    and solid_at is not None and player_world is not None
                    and world_to_screen is not None):
                self._add_glow(mask, GLOW_RADIUS, GLOW_COLOR,
                               player_screen_pos, glow,
                               player_world, world_to_screen, solid_at)
            else:
                self._add(mask, GLOW_RADIUS, GLOW_COLOR,
                          player_screen_pos, glow)

    def apply(self, screen, danger=0.0, hurt=0.0, time=0.0):
        """Накладывает готовую штору умножением + виньетку и эффекты."""
        screen.blit(self.mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        screen.blit(self.vignette, (0, 0))
        if danger > 0.0:
            self._draw_danger(screen, danger, time)
        if hurt > 0.0:
            self._draw_hurt(screen, hurt)

    def render(self, screen, player_screen_pos, muzzle_screen_pos,
               angle, flash_timer, flashes=(), time=0.0, danger=0.0,
               hurt=0.0, **kwargs):
        """Совместимая обёртка: build_mask + apply за один вызов."""
        self.build_mask(player_screen_pos, muzzle_screen_pos, angle,
                        flash_timer, flashes, time, **kwargs)
        self.apply(screen, danger, hurt, time)

    # ------------------------------------------------------------ ВИДИМОСТЬ
    def light_at(self, screen_x, screen_y):
        """Яркость шторы в точке полотна мира: 0.0..1.0 (max(R,G,B)/255)."""
        mask = self.mask
        x, y = int(screen_x), int(screen_y)
        if x < 0 or y < 0 or x >= self.view_w or y >= self.view_h:
            return 0.0
        color = mask.get_at((x, y))
        return max(color[0], color[1], color[2]) / 255.0

    def reveal_at(self, screen_x, screen_y):
        """
        Яркость «проявляющего» света в точке: конус, лампы, вспышки,
        но БЕЗ личного ореола героя (oreол освещает пол, но не
        открывает объекты в темноте — иначе за спиной всё светилось).
        """
        reveal = self.reveal
        x, y = int(screen_x), int(screen_y)
        if x < 0 or y < 0 or x >= self.view_w or y >= self.view_h:
            return 0.0
        color = reveal.get_at((x, y))
        return max(color[0], color[1], color[2]) / 255.0

    def visibility_at(self, screen_x, screen_y, distance, prof=None):
        """
        Видимость объекта в точке: 0.0 — не виден, 1.0 — виден отлично.

        Считает освещённость из reveal-шторы (без ореола) и правило
        smoothstep из профиля (см. zones.visibility). Для профилей
        gated=False всегда 1.0.
        """
        prof = self.profile if prof is None else prof
        if not prof.get("gated", False):
            return 1.0
        return zones.visibility(self.reveal_at(screen_x, screen_y),
                                distance, prof)

    # ------------------------------------------------------------ ВНУТРЕННЕЕ
    @staticmethod
    def _add(mask, radius, color, pos, strength=1.0):
        light = _light_surface(radius, color, strength)
        mask.blit(light, (int(pos[0] - radius), int(pos[1] - radius)),
                  special_flags=pygame.BLEND_RGB_ADD)

    def _add_glow(self, mask, radius, color, pos, strength,
                  origin_world, world_to_screen, solid_at):
        """
        Радиальный свет, обрезанный стенами: полный круг лучей от
        источника (angle=0, half=π), полигон видимости — по точкам
        попадания с доводкой на полшага, чтобы лицевая сторона стены
        ловила свет, а не темнела вплотную к освещённому полу.

        Годится и для ореола героя, и для ламп/магазинов/взрывов —
        любого источника с мировой позицией (origin_world). Лучи
        кэшируются по позиции источника: для статичных ламп raycast
        считается один раз.
        """
        # Лучей больше для крупных источников — иначе тень от стены
        # получается гранёной (шаг ~6 px по окружности).
        rays = max(24, min(48, int(radius / 6)))
        step = 16.0
        hits = self._ray_distances(origin_world, 0.0, math.pi, radius,
                                   step, rays, solid_at)
        px, py = origin_world
        n = max(1, len(hits) - 1)
        pts = []
        for i, hit in enumerate(hits):
            a = -math.pi + 2 * math.pi * i / n
            d = min(radius, hit + step * 0.5)
            sx, sy = world_to_screen(px + math.cos(a) * d,
                                     py + math.sin(a) * d)
            pts.append((sx - pos[0] + radius, sy - pos[1] + radius))
        light = _light_surface(radius, color, strength)
        scratch, clip = self._glow_scratch(light.get_size())
        scratch.blit(light, (0, 0))
        clip.fill((_SHADOW_ABSORB,) * 3)
        pygame.draw.polygon(clip, (255, 255, 255), pts)
        scratch.blit(clip, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        mask.blit(scratch, (int(pos[0] - radius), int(pos[1] - radius)),
                  special_flags=pygame.BLEND_RGB_ADD)

    def _glow_scratch(self, size):
        """Пара черновиков (свет + клип) под размер радиуса — из кэша."""
        pair = self._glow_scratch_cache.get(size)
        if pair is None:
            if len(self._glow_scratch_cache) > 8:
                self._glow_scratch_cache.clear()
            pair = (pygame.Surface(size), pygame.Surface(size))
            self._glow_scratch_cache[size] = pair
        return pair

    def _ambient_fill(self, ambient):
        """Сплошная заливка размером с кадр (кэш по цвету ambient)."""
        surf = self._ambient_fill_cache.get(ambient)
        if surf is None or surf.get_size() != (self.view_w, self.view_h):
            surf = pygame.Surface((self.view_w, self.view_h))
            surf.fill(ambient)
            self._ambient_fill_cache.clear()
            self._ambient_fill_cache[ambient] = surf
        return surf

    def _lamp_layer(self):
        """Слой ламп половинного разрешения (+ буфер апскейла) — из кэша."""
        half = (max(1, self.view_w // 2), max(1, self.view_h // 2))
        full = (self.view_w, self.view_h)
        if self._lamp_surface is None or self._lamp_surface.get_size() != half:
            self._lamp_surface = pygame.Surface(half)
            self._lamp_scaled = pygame.Surface(full)
        return self._lamp_surface

    def _add_world_light(self, target, radius, color, pos, strength,
                         origin_world, world_to_screen, solid_at, scale=1.0):
        """
        Свет с мировой позицией (лампа, магазин, взрыв), обрезанный
        стенами. Полигон обрезки не зависит от сдвига камеры, а
        источники статичны — готовый слой кэшируется (см. _clipped_light).

        scale=0.5 — рисование в полуразрешающий слой ламп (см. build_mask).
        """
        light = self._clipped_light(radius, color, strength, origin_world,
                                    world_to_screen, solid_at, scale)
        r = light.get_width() // 2
        target.blit(light, (int(pos[0] * scale - r),
                            int(pos[1] * scale - r)),
                    special_flags=pygame.BLEND_RGB_ADD)

    def _clipped_light(self, radius, color, strength, origin_world,
                       world_to_screen, solid_at, scale=1.0):
        """
        Обрезанный стенами радиальный свет (кэш по источнику).

        Сила света меняется от мерцания, поэтому кэшируется ПОСЛЕДНЯЯ
        версия источника: ключ — только позиция/радиус/цвет/масштаб,
        а сила хранится рядом. Иначе каждый шаг мерцания плодил бы
        новую поверхность и кэш бы «трясся».
        """
        r = max(4, int(radius * scale))
        key = (r, float(scale), tuple(color),
               int(origin_world[0] // 4), int(origin_world[1] // 4))
        strength = round(max(0.05, min(1.5, float(strength))), 1)
        cached = self._clip_light_cache.get(key)
        if cached is not None and cached[0] == strength:
            # Освежаем запись (LRU): источники, которые сейчас на экране,
            # не должны вытесняться теми, что давно ушли из вида.
            self._clip_light_cache[key] = self._clip_light_cache.pop(key)
            return cached[1]
        if cached is not None and self._clip_budget <= 0:
            # Бюджет кадра исчерпан — показываем прошлую силу: мерцание
            # отстанет на кадр-два, зато не будет рывка при скоплении ламп.
            return cached[1]
        self._clip_budget -= 1
        rays = max(24, min(48, int(radius / 6)))
        step = 16.0
        hits = self._ray_distances(origin_world, 0.0, math.pi, radius,
                                   step, rays, solid_at)
        px, py = origin_world
        ox, oy = world_to_screen(px, py)
        n = max(1, len(hits) - 1)
        pts = []
        for i, hit in enumerate(hits):
            a = -math.pi + 2 * math.pi * i / n
            d = min(radius, hit + step * 0.5)
            sx, sy = world_to_screen(px + math.cos(a) * d,
                                     py + math.sin(a) * d)
            # Смещение относительно источника — не зависит от камеры.
            pts.append(((sx - ox) * scale + r, (sy - oy) * scale + r))
        light = _light_surface(r, color, strength)
        scratch, clip = self._glow_scratch(light.get_size())
        scratch.blit(light, (0, 0))
        clip.fill((_SHADOW_ABSORB,) * 3)
        pygame.draw.polygon(clip, (255, 255, 255), pts)
        scratch.blit(clip, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        if cached is not None:
            # Переиспользуем поверхность источника: копия 350×350 — это
            # полмегабайта мусора на каждую пересборку и лишние паузы GC.
            result = cached[1]
            result.blit(scratch, (0, 0))
        else:
            result = scratch.copy()
        _lru_store(self._clip_light_cache, key, (strength, result), 96)
        return result

    def _add_cone(self, mask, pos, angle, time, prof,
                  player_world=None, world_to_screen=None, solid_at=None):
        """Шесть вложенных конусов в 1/3 разрешения + опциональные тени."""
        surf = self.cone_small
        surf.fill((0, 0, 0))
        cx, cy = pos[0] / CONE_SCALE, pos[1] / CONE_SCALE
        base = math.radians(BEAM_HALF_ANGLE)
        drift = math.sin(time * 1.3) * 0.012       # живое покачивание луча
        ray_angle = angle + drift
        strength = (float(prof.get("cone_strength_mul", 1.0))
                    * float(prof.get("flashlight_mul", 1.0)))
        cone_range = BEAM_RANGE * float(prof.get("cone_mul", 1.0))
        # Шесть слоёв вместо трёх: градиент к краю луча мягкий, поэтому
        # объекты у границы конуса проявляются/гаснут без ступенек.
        layers = []
        layer_count = 6
        for i in range(layer_count):
            t = i / (layer_count - 1)              # 0 — внешний, 1 — ядро
            half = base * (1.0 - 0.52 * t)         # 1.00 → 0.48 угловой ширины
            length = cone_range * (1.0 - 0.20 * t)  # 1.00 → 0.80 дальности
            k = 0.38 + 0.62 * t                    # яркость слоя 0.38 → 1.0
            layers.append((half, length,
                           (int(118 * k), int(106 * k), int(82 * k))))
        for half, length, color in layers:
            scaled = tuple(int(min(255, c * strength)) for c in color)
            pts = [(cx, cy)]
            steps = 18
            for i in range(steps + 1):
                a = ray_angle - half + 2 * half * i / steps
                pts.append((cx + math.cos(a) * length / CONE_SCALE,
                            cy + math.sin(a) * length / CONE_SCALE))
            pygame.draw.polygon(surf, scaled, pts)

        # Тени от стен: свет обрезается полигоном видимости, за углом
        # остаётся слабый дифракционный слой («огибание»).
        if (prof.get("shadows") and self.shadows_enabled
                and solid_at is not None and player_world is not None
                and world_to_screen is not None):
            self._clip_cone_to_shadows(surf, pos, ray_angle, base, cone_range,
                                       prof, player_world, world_to_screen,
                                       solid_at)

        beam = pygame.transform.scale(
            surf, (self.view_w, self.view_h), self.cone_scaled)
        mask.blit(beam, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    # --------------------------------------------------------- ТЕНИ КОНУСА
    def _ray_distances(self, player_world, angle, half, cone_range, step,
                       rays, solid_at):
        """Дистанции до стен по лучам конуса (кэшируются по тайлу/углу)."""
        key = (int(player_world[0] // 16), int(player_world[1] // 16),
               round(angle / 0.05, 2), round(half, 3),
               rays, step, cone_range)
        cached = self._ray_cache.get(key)
        if cached is not None:
            return cached
        px, py = player_world
        found = []
        for i in range(rays + 1):
            a = angle - half + 2 * half * i / rays
            dx, dy = math.cos(a), math.sin(a)
            distance = step * 0.5
            hit = cone_range
            while distance <= cone_range:
                if solid_at(px + dx * distance, py + dy * distance):
                    hit = max(step * 0.5, distance - step * 0.5)
                    break
                distance += step
            found.append(hit)
        if len(self._ray_cache) > _RAY_CACHE_MAX:
            # Вытесняем самую старую запись: очистка всего кэша заставила
            # бы пересчитать raycast сразу для всех источников на кадре.
            self._ray_cache.pop(next(iter(self._ray_cache)), None)
        self._ray_cache[key] = found
        return found

    @staticmethod
    def _shadow_points(hits, player_world, angle, half, cone_range,
                       world_to_screen, extend=0.0):
        """Полигон видимости: apex (игрок) + точки попадания лучей."""
        px, py = player_world
        n = max(1, len(hits) - 1)
        sx0, sy0 = world_to_screen(px, py)
        points = [(sx0 / CONE_SCALE, sy0 / CONE_SCALE)]
        for i, distance in enumerate(hits):
            d = min(cone_range, distance + extend)
            a = angle - half + 2 * half * i / n
            wx, wy = px + math.cos(a) * d, py + math.sin(a) * d
            sx, sy = world_to_screen(wx, wy)
            points.append((sx / CONE_SCALE, sy / CONE_SCALE))
        return points

    def _clip_cone_to_shadows(self, surf, pos, ray_angle, half, cone_range,
                              prof, player_world, world_to_screen, solid_at):
        """Обрезает конус полигоном видимости + добавляет дифракцию."""
        rays = max(8, int(prof.get("shadow_rays", 36)))
        step = max(4.0, float(prof.get("shadow_step", 14.0)))
        hits = self._ray_distances(player_world, ray_angle, half, cone_range,
                                   step, rays, solid_at)

        # Основной слой: внутри полигона — полный свет, снаружи —
        # остаток _SHADOW_ABSORB (стены поглощают почти всё).
        # Доводка на полшага: полигон доходит до лицевой стороны стены.
        clip = self.cone_clip
        clip.fill((_SHADOW_ABSORB,) * 3)
        pygame.draw.polygon(
            clip, (255, 255, 255),
            self._shadow_points(hits, player_world, ray_angle, half,
                                cone_range, world_to_screen,
                                extend=step * 0.5))
        surf.blit(clip, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

        # Дифракция: слабый широкий слой, обрезанный расширенным
        # полигоном — свет «заходит за угол» и быстро затухает.
        dstr = float(prof.get("diffraction_strength", 0.0))
        if prof.get("diffraction") and dstr > 0.0:
            extend = float(prof.get("diffraction_px", 26))
            soft = self.cone_soft
            soft.fill((0, 0, 0))
            pygame.draw.polygon(
                soft, (255, 255, 255),
                self._shadow_points(hits, player_world, ray_angle, half,
                                    cone_range, world_to_screen, extend))
            weak = self.cone_weak
            weak.fill((0, 0, 0))
            weak_half = half * 1.12
            weak_range = cone_range * 0.85
            color = tuple(int(min(255, c * dstr)) for c in (60, 54, 42))
            pts = [(pos[0] / CONE_SCALE, pos[1] / CONE_SCALE)]
            steps = 14
            for i in range(steps + 1):
                a = ray_angle - weak_half + 2 * weak_half * i / steps
                pts.append((pos[0] / CONE_SCALE
                            + math.cos(a) * weak_range / CONE_SCALE,
                            pos[1] / CONE_SCALE
                            + math.sin(a) * weak_range / CONE_SCALE))
            pygame.draw.polygon(weak, color, pts)
            weak.blit(soft, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
            surf.blit(weak, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _build_vignette(self, width, height):
        """Заранее собранная виньетка: края темнее, центр прозрачный."""
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        # дешёвый градиент из вложенных рамок
        steps = 26
        for i in range(steps):
            t = i / steps
            inset = int(min(width, height) * 0.18 * t)
            alpha = int(170 * (1.0 - t) ** 1.4)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(surf, (*VIGNETTE_COLOR, alpha), rect, 12,
                             border_radius=30)
        # углы — сильнее
        corner = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(12):
            t = i / 12
            pygame.draw.rect(corner, (*VIGNETTE_COLOR, int(30 * (1 - t))),
                             (0, 0, width, height), int(40 * (1 - t)) + 6,
                             border_radius=60)
        surf.blit(corner, (0, 0))
        return surf

    def _draw_hurt(self, screen, strength):
        """Кратковременная красная кромка — сигнал урона без заливки экрана."""
        alpha = int(150 * max(0.0, min(1.0, strength)))
        if alpha <= 0:
            return
        width, height = screen.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(12):
            t = i / 12
            inset = int(min(width, height) * 0.04 * t)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(overlay, (200, 34, 42, int(alpha * (1 - t) ** 1.4)),
                             rect, 22, border_radius=44)
        screen.blit(overlay, (0, 0))

    def _draw_danger(self, screen, danger, time):
        pulse = 0.55 + 0.45 * math.sin(time * 6.5)
        alpha = int(120 * max(0.0, min(1.0, danger)) * pulse)
        if alpha <= 0:
            return
        width, height = screen.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(10):
            t = i / 10
            inset = int(min(width, height) * 0.08 * t)
            rect = pygame.Rect(inset, inset, width - inset * 2,
                               height - inset * 2)
            pygame.draw.rect(overlay, (180, 28, 40, int(alpha * (1 - t) ** 1.6)),
                             rect, 18, border_radius=40)
        screen.blit(overlay, (0, 0))
