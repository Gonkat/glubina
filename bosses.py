"""Boss encounters, recipes and material drops."""
import math
import random
import pygame
from enemies import Tank, Brute, Stalker
from drops import Drop
from utils import circles_collide
import soundbank

MATERIALS = {
    "bone": "Костяные осколки", "core": "Нестабильные ядра",
    "hide": "Плотная шкура", "shadow": "Теневая эссенция",
}
RECIPES = {
    "warden": {"name": "Каменный страж", "cost": {"bone": 8, "hide": 4}, "color": (180, 164, 114)},
    "reaper": {"name": "Теневой жнец", "cost": {"shadow": 6, "bone": 5}, "color": (164, 80, 205)},
    "overlord": {"name": "Повелитель взрывов", "cost": {"core": 7, "hide": 4}, "color": (238, 117, 65)},
    "worm": {"name": "Голодная глубина", "cost": {"hide": 9, "core": 6}, "color": (206, 160, 96)},
}
ENEMY_MATERIALS = {"Enemy": ("bone", .24), "Runner": ("bone", .38),
    "Tank": ("hide", .65), "Brute": ("hide", .9),
    "Bomber": ("core", .65), "Stalker": ("shadow", .65)}

class MaterialDrop(Drop):
    sprite_name = "boss/material"
    def __init__(self, x, y, kind):
        super().__init__(x, y)
        self.kind = kind
    def apply(self, game, player):
        # Материал получает ТОТ, кто его подобрал: в кооперативе это
        # может быть гость, а не локальный герой хоста.
        player.equipment.add_item(self.kind)
        soundbank.play("pickup")
        game.boss_notice = f"Получено: {MATERIALS[self.kind]}"
        game.boss_notice_timer = 2.5
        return True
    def draw(self, screen, camera):
        from spritebank import get_scaled
        pos = camera.to_screen(self.x, self.y + self.lift)
        surf = get_scaled("boss/material/" + self.kind, (23, 23))
        if surf is not None:
            screen.blit(surf, surf.get_rect(center=pos))
        else:
            pygame.draw.circle(screen, {"bone": (225,214,184), "hide": (148,103,67),
                "core": (247,131,54), "shadow": (169,83,220)}[self.kind], pos, 10)
            pygame.draw.circle(screen, (30,24,35), pos, 10, 2)

class SoulShardDrop(Drop):
    """Осколок души: гарантированный трофей босса.

    Тратится на алтаре возвращения, чтобы поднять павшего соратника.
    Спрайт общий с артефактом (клиент видит предмет по снимку), но
    ореол фиолетовый — трофей не путается с добычей магазина.
    """

    sprite_name = "artifact"
    glow_color = (188, 138, 255)

    def apply(self, game, player):
        player.equipment.add_item("soul_shard")
        soundbank.play("artifact")
        game.boss_notice = "Осколок души: оживите павшего у алтаря возвращения"
        game.boss_notice_timer = 3.5
        return True


def roll_material(enemy):
    kind, chance = ENEMY_MATERIALS.get(type(enemy).__name__, ("bone", .20))
    if random.random() < chance:
        return MaterialDrop(enemy.x, enemy.y, kind)
    return None

class BossBase(Brute):
    is_boss = True
    radius = 43
    max_hp = 2100
    speed = 61
    damage = 32
    bounty = 350
    score = 5000
    attack_delay = 1.2
    sprite_name = "boss/warden"
    boss_key = "warden"
    def __init__(self, x, y):
        super().__init__(x, y)
        self.phase = 1
        self.special_timer = 4.0
        self.summon_timer = 9.0
        self.max_hp = type(self).max_hp
        self.hp = self.max_hp
    def update(self, dt, game):
        self.phase = 3 if self.hp < self.max_hp * .3 else 2 if self.hp < self.max_hp * .65 else 1
        self.special_timer -= dt
        self.summon_timer -= dt
        if self.special_timer <= 0:
            self.special_timer = max(2.5, 6 - self.phase)
            self.special(game)
        super().update(dt, game)
    def special(self, game):
        game.explode(self.x, self.y, 110 + self.phase * 22, 13 + self.phase * 7, 180, True)
    def draw(self, screen, camera):
        import visuals
        x, y = camera.to_screen(self.x, self.y)
        x, y = int(x), int(y)
        body_r = int(self.radius * 1.08)
        visuals.shadow(screen, x, y + self.radius * 0.6, body_r + 6, 1.0)
        visuals.glow(screen, x, y, body_r + 40,
                     (255, 150, 90) if self.boss_key == "overlord" else
                     (190, 110, 240) if self.boss_key == "reaper" else
                     (220, 210, 160), 28)
        sprite = visuals.character(self.sprite_name, body_r, self.angle)
        screen.blit(sprite, sprite.get_rect(center=(x, y)))
        visuals.draw_ring(screen, x, y, body_r + 6, self.color, 2, 150)
        # фаза видна по цвету и числу делений вокруг тушки
        phase_color = (255, 110, 100) if self.phase >= 3 else \
            (255, 190, 100) if self.phase == 2 else (190, 216, 168)
        for i in range(self.phase):
            a = -math.pi / 2 + i * 0.5 - (self.phase - 1) * 0.25
            px = x + math.cos(a) * (body_r + 16)
            py = y + math.sin(a) * (body_r + 16)
            pygame.draw.circle(screen, phase_color, (int(px), int(py)), 4)
        visuals.draw_ring(screen, x, y, body_r + 11, phase_color, 1, 90)

class StoneWarden(BossBase):
    boss_key = "warden"
    sprite_name = "boss/warden"
    color = (145,135,113)
    max_hp = 3200
    speed = 46
    damage = 42
    def special(self, game):
        game.explode(self.x, self.y, 110 + self.phase*35, 17+self.phase*10, 270, True)

class ShadowReaper(BossBase):
    boss_key = "reaper"
    sprite_name = "boss/reaper"
    color = (141,75,190)
    max_hp = 2050
    speed = 115
    damage = 25
    def special(self, game):
        px, py = game.player.pos
        angle = math.atan2(py-self.y, px-self.x)
        self.x += math.cos(angle)*min(175,math.hypot(px-self.x,py-self.y)*.65)
        self.y += math.sin(angle)*min(175,math.hypot(px-self.x,py-self.y)*.65)
        self.x,self.y = game.world.resolve_circle(self.x,self.y,self.radius)
        game.explode(self.x,self.y,95+self.phase*18,13+self.phase*7,150,True)

class BlastOverlord(BossBase):
    boss_key = "overlord"
    sprite_name = "boss/overlord"
    color = (217,108,59)
    max_hp = 2600
    speed = 56
    damage = 34
    def special(self, game):
        for i in range(self.phase+1):
            angle = math.tau*i/(self.phase+1)
            game.explode(self.x+math.cos(angle)*100,self.y+math.sin(angle)*100,
                         75,14+self.phase*5,180,True)

class BurrowWorm(Brute):
    """Босс-червь в духе Destroyer из Terraria.

    Ползает ПОД землёй сквозь стены, поэтому его не достать: пока зарыт,
    он неуязвим. Приблизившись, земля трясётся (телеграф), червь всплывает
    и выставляет длинное сегментированное тело — вот тогда в него можно
    стрелять, причём попадания считаются по любому сегменту, а не только
    по голове. Затем он снова уходит в грунт.
    """

    is_boss = True
    boss_key = "worm"
    sprite_name = "boss/worm"
    color = (186, 142, 92)
    radius = 46
    max_hp = 3600
    speed = 92
    damage = 40
    bounty = 430
    score = 6500
    attack_delay = 0.85

    segment_count = 15
    segment_gap = 34.0
    segment_base_radius = 23.0
    # Тело уходит на ~510 px за головой: зона отрисовки/затемнения
    # должна накрывать всю цепочку, иначе хвост обрезается.
    fade_margin = 620

    def __init__(self, x, y):
        super().__init__(x, y)
        self.phase = 1
        self.max_hp = type(self).max_hp
        self.hp = self.max_hp
        self.burrowed = True
        self.surface_timer = 0.0
        self.burrow_timer = 1.2          # сколько ползает до первого всплытия
        self.warning = 0.0               # телеграф «сейчас вылезет»
        self.warning_total = 1.0
        self.dirt_timer = 0.0
        self.segments = [
            [x - (i + 1) * self.segment_gap, y, math.pi]
            for i in range(self.segment_count)
        ]

    # ---------------------------------------------------------- обновление
    def update(self, dt, game):
        if not self.alive:
            return
        self.phase = (3 if self.hp < self.max_hp * .3
                      else 2 if self.hp < self.max_hp * .65 else 1)
        self.anim_phase += dt * 5.0
        self.attack_timer = max(0.0, self.attack_timer - dt)
        self.hurt_timer = max(0.0, self.hurt_timer - dt)
        self.hp_show_timer = max(0.0, self.hp_show_timer - dt)
        self.slow_timer = max(0.0, self.slow_timer - dt)
        if self.slow_timer <= 0.0:
            self.slow_factor = 1.0
        self.aim_mark = max(0.0, self.aim_mark - dt)
        self.explosion_mark = max(0.0, self.explosion_mark - dt)
        self.vulnerable_timer = max(0.0, self.vulnerable_timer - dt)
        if self.vulnerable_timer <= 0.0:
            self.vulnerable_mul = 1.0

        player = game.nearest_player(self.x, self.y)
        dx, dy = player.x - self.x, player.y - self.y
        dist = math.hypot(dx, dy) or 1.0
        self.angle = math.atan2(dy, dx)
        speed = self.speed * (self.slow_factor if self.slow_timer > 0.0 else 1.0)

        if self.burrowed:
            self._update_burrowed(dt, game, dist, speed)
        else:
            self._update_surfaced(dt, game, dist, speed)
        self._follow_segments()

    def _update_burrowed(self, dt, game, dist, speed):
        # Под землёй стены не мешают: червь идёт напрямую и быстрее.
        self.x += math.cos(self.angle) * speed * 1.5 * dt
        self.y += math.sin(self.angle) * speed * 1.5 * dt
        self.burrow_timer -= dt
        self.dirt_timer -= dt
        if self.dirt_timer <= 0.0:
            self.dirt_timer = 0.085
            self._spawn_dirt(game, 1)
        if self.warning > 0.0:
            self.warning -= dt
            if self.warning <= 0.0:
                if game.world.is_valid_position(self.x, self.y,
                                                self.radius * 0.7):
                    self._surface(game)
                else:
                    self.warning = 0.25      # под толщей породы — рвётся дальше
        elif self.burrow_timer <= 0.0 or dist <= 360.0 + 30.0 * self.phase:
            self.warning_total = max(0.45, 0.95 - 0.12 * self.phase)
            self.warning = self.warning_total
            soundbank.play("boss_roar", 0.35)
            game.camera.add_shake(3)

    def _surface(self, game):
        self.burrowed = False
        self.warning = 0.0
        self.surface_timer = 4.2 + 0.3 * self.phase
        self.attack_timer = 0.0
        soundbank.play("boss_roar", 0.7)
        game.camera.add_shake(8)
        self._spawn_dirt(game, 18)

    def _burrow(self):
        self.burrowed = True
        self.warning = 0.0
        self.burrow_timer = max(1.6, 3.0 - 0.4 * self.phase)

    def _update_surfaced(self, dt, game, dist, speed):
        self.surface_timer -= dt
        rush = 1.5 if dist < 260.0 else 1.15
        angle = self.angle + math.sin(self.anim_phase * 0.9) * 0.16
        self.x += math.cos(angle) * speed * rush * dt
        self.y += math.sin(angle) * speed * rush * dt
        self.x, self.y = game.world.resolve_circle(
            self.x, self.y, self.radius * 0.8)
        for player in game.players:
            if not player.alive or not self._touches(player):
                continue
            if self.attack_timer <= 0.0:
                player.take_damage(self.damage, game)
                self.attack_timer = self.attack_delay
                game.spawn_enemy_attack(self)
        if self.surface_timer <= 0.0 or dist > 900.0:
            self._burrow()

    def _spawn_dirt(self, game, count):
        from projectiles import Particle
        for _ in range(max(1, count)):
            particle = Particle(
                self.x + random.uniform(-self.radius * 0.5, self.radius * 0.5),
                self.y + random.uniform(-self.radius * 0.35, self.radius * 0.35),
                (162, 136, 96),
            )
            particle.vx *= 0.35
            particle.vy = particle.vy * 0.35 - 16.0
            particle.life = particle.max_life = random.uniform(0.35, 0.6)
            particle.size = random.randint(2, 4)
            game.effects.append(particle)

    # ---------------------------------------------------------- тело
    def _segment_radius(self, index):
        taper = 1.0 - 0.45 * (index + 1) / max(1, len(self.segments))
        return self.segment_base_radius * taper

    def _follow_segments(self):
        """Жёсткая цепочка: каждый сегмент висит на шаг позади предыдущего."""
        prev_x, prev_y = self.x, self.y
        for segment in self.segments:
            dx, dy = prev_x - segment[0], prev_y - segment[1]
            distance = math.hypot(dx, dy)
            if distance < 0.0001:
                dx, dy, distance = math.cos(self.angle), math.sin(self.angle), 1.0
            segment[0] = prev_x - dx / distance * self.segment_gap
            segment[1] = prev_y - dy / distance * self.segment_gap
            segment[2] = math.atan2(prev_y - segment[1], prev_x - segment[0])
            prev_x, prev_y = segment[0], segment[1]

    def _touches(self, player):
        if circles_collide(self.x, self.y, self.radius * 0.9,
                           player.x, player.y, player.radius):
            return True
        for index, segment in enumerate(self.segments):
            if circles_collide(segment[0], segment[1],
                               self._segment_radius(index) * 0.9,
                               player.x, player.y, player.radius):
                return True
        return False

    # ---------------------------------------------------------- урон
    def take_damage(self, amount):
        if self.burrowed:
            return                      # под землёй его не достать
        super().take_damage(amount)

    def hit_test(self, x, y, radius):
        if self.burrowed:
            return False
        if super().hit_test(x, y, radius):
            return True
        for index, segment in enumerate(self.segments):
            if circles_collide(x, y, radius, segment[0], segment[1],
                               self._segment_radius(index)):
                return True
        return False

    # ---------------------------------------------------------- отрисовка
    def draw(self, screen, camera):
        import visuals
        self._follow_segments()
        if self.burrowed:
            self._draw_burrowed(screen, camera)
            return
        for index in range(len(self.segments) - 1, -1, -1):
            segment = self.segments[index]
            sx, sy = camera.to_screen(segment[0], segment[1])
            radius = int(self._segment_radius(index))
            angle = segment[2] + math.sin(
                self.anim_phase * 0.9 - index * 0.55) * 0.18
            visuals.shadow(screen, sx, sy + radius * 0.55, radius + 3, 0.55)
            sprite = visuals.character("boss/worm_segment", radius, angle)
            screen.blit(sprite, sprite.get_rect(center=(int(sx), int(sy))))
        x, y = camera.to_screen(self.x, self.y)
        x, y = int(x), int(y)
        visuals.shadow(screen, x, y + self.radius * 0.6, self.radius + 8, 1.0)
        visuals.glow(screen, x, y, self.radius + 36, (255, 172, 88), 24)
        sprite = visuals.character("boss/worm", self.radius, self.angle)
        screen.blit(sprite, sprite.get_rect(center=(x, y)))
        if self.hurt_timer > 0.0:
            visuals.draw_hit_flash(screen, x, y, self.radius * 0.9,
                                   min(1.0, self.hurt_timer / 0.12))

    def _draw_burrowed(self, screen, camera):
        for index, segment in enumerate(self.segments):
            sx, sy = camera.to_screen(segment[0], segment[1])
            radius = self._segment_radius(index)
            mound = pygame.Rect(0, 0, int(radius * 2.2), int(radius * 1.1))
            mound.center = (int(sx), int(sy))
            pygame.draw.ellipse(screen, (18, 16, 16), mound)
            inner = mound.inflate(-radius * 0.6, -radius * 0.4)
            pygame.draw.ellipse(screen, (60, 48, 34), inner)

    def draw_overlay(self, screen, camera):
        if not self.alive or not self.burrowed or self.warning <= 0.0:
            return
        import visuals
        sx, sy = camera.to_screen(self.x, self.y)
        t = 1.0 - self.warning / max(0.001, self.warning_total)
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.012)
        visuals.draw_ring(screen, sx, sy, self.radius + 14 + 22 * t,
                          (255, 168, 78), 2, int(170 + 60 * pulse))
        visuals.draw_ring(screen, sx, sy, self.radius + 6,
                          (255, 210, 130), 1, int(90 + 80 * pulse))


BOSS_CLASSES = {"warden": StoneWarden, "reaper": ShadowReaper,
                "overlord": BlastOverlord, "worm": BurrowWorm}

def summon(game, key):
    recipe = RECIPES[key]
    inv = game.player.equipment
    if any(inv.item_count(item) < count for item,count in recipe["cost"].items()):
        return "Недостаточно материалов"
    if any(getattr(enemy,"is_boss",False) and enemy.alive for enemy in game.enemies):
        return "Сначала победите текущего босса"
    angle = game.player.angle
    for radius in (430,500,580,650,720):
        for step in range(12):
            a = angle + step*math.tau/12
            x = game.player.x+math.cos(a)*radius
            y = game.player.y+math.sin(a)*radius
            if math.hypot(game.world.resolve_circle(x,y,BOSS_CLASSES[key].radius)[0]-x, game.world.resolve_circle(x,y,BOSS_CLASSES[key].radius)[1]-y) < 2:
                for item,count in recipe["cost"].items():
                    inv.items[item] -= count
                # босс тоже растёт с глубиной, но без элитных модификаторов:
                # это отдельная дуэль, а не случайный мутант
                game.spawn_enemy_at(x, y, BOSS_CLASSES[key], allow_elite=False)
                soundbank.play("boss_roar")
                game.camera.add_shake(9)
                game.toast(f"{recipe['name']} пробуждён", 3.0,
                           color=(255, 170, 120))
                return f"Призван: {recipe['name']}"
    return "Нет свободного места для призыва"
