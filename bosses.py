"""Boss encounters, recipes and material drops."""
import math
import random
import pygame
from enemies import Tank, Brute, Stalker
from drops import Drop
import soundbank

MATERIALS = {
    "bone": "Костяные осколки", "core": "Нестабильные ядра",
    "hide": "Плотная шкура", "shadow": "Теневая эссенция",
}
RECIPES = {
    "warden": {"name": "Каменный страж", "cost": {"bone": 8, "hide": 4}, "color": (180, 164, 114)},
    "reaper": {"name": "Теневой жнец", "cost": {"shadow": 6, "bone": 5}, "color": (164, 80, 205)},
    "overlord": {"name": "Повелитель взрывов", "cost": {"core": 7, "hide": 4}, "color": (238, 117, 65)},
}
ENEMY_MATERIALS = {"Enemy": ("bone", .24), "Runner": ("bone", .38),
    "Tank": ("hide", .65), "Brute": ("hide", .9),
    "Bomber": ("core", .65), "Stalker": ("shadow", .65)}

class MaterialDrop(Drop):
    sprite_name = "boss/material"
    def __init__(self, x, y, kind):
        super().__init__(x, y)
        self.kind = kind
    def apply(self, game):
        game.player.equipment.add_item(self.kind)
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

BOSS_CLASSES = {"warden": StoneWarden, "reaper": ShadowReaper, "overlord": BlastOverlord}

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
