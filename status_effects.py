"""Timed damage-over-time and control statuses for enemies."""


def apply_bleed(enemy, damage, duration=3.0):
    if not enemy.alive or damage <= 0:
        return
    enemy.bleed_remaining = max(getattr(enemy, "bleed_remaining", 0.0), duration)
    enemy.bleed_dps = max(getattr(enemy, "bleed_dps", 0.0), damage / duration)


def apply_dust(enemy, damage_per_stack, duration=2.6, stack_cap=1,
               slow=0.22):
    if not enemy.alive or damage_per_stack <= 0.0 or duration <= 0.0:
        return
    stack_cap = max(1, int(stack_cap))
    remaining = getattr(enemy, "dust_remaining", 0.0)
    stacks = getattr(enemy, "dust_stacks", 0) if remaining > 0.0 else 0
    if stacks < stack_cap:
        stacks += 1
        enemy.dust_dps = getattr(enemy, "dust_dps", 0.0) + damage_per_stack
    else:
        enemy.dust_dps = max(
            getattr(enemy, "dust_dps", 0.0),
            damage_per_stack * stacks,
        )
    enemy.dust_stacks = stacks
    enemy.dust_remaining = max(remaining, duration)
    apply_slow(enemy, duration, max(0.0, 1.0 - slow))


def apply_slow(enemy, duration, factor=0.55):
    """Замедление: factor — доля скорости (0.0 = полная остановка)."""
    if not enemy.alive or duration <= 0.0:
        return
    enemy.slow_timer = max(getattr(enemy, "slow_timer", 0.0), duration)
    enemy.slow_factor = min(getattr(enemy, "slow_factor", 1.0), factor)


def apply_stun(enemy, duration):
    """Короткий стан через тот же таймер замедления."""
    apply_slow(enemy, duration, 0.0)


def apply_vulnerable(enemy, duration, bonus):
    """
    Метка уязвимости: цель получает больше урона от ЛЮБЫХ источников.
    Несколько меток не складываются, берётся самая сильная.
    """
    if not enemy.alive or duration <= 0.0 or bonus <= 0.0:
        return
    enemy.vulnerable_timer = max(getattr(enemy, "vulnerable_timer", 0.0), duration)
    enemy.vulnerable_mul = max(getattr(enemy, "vulnerable_mul", 1.0), 1.0 + bonus)


def update_bleed(enemy, dt, game):
    remaining = getattr(enemy, "bleed_remaining", 0.0)
    if remaining <= 0 or not enemy.alive:
        return
    elapsed = min(dt, remaining)
    enemy.bleed_remaining = remaining - elapsed
    game.damage_enemy(enemy, enemy.bleed_dps * elapsed, show_number=False)
    if enemy.bleed_remaining <= 0:
        enemy.bleed_dps = 0.0


def update_dust(enemy, dt, game):
    remaining = getattr(enemy, "dust_remaining", 0.0)
    if remaining <= 0.0 or not enemy.alive:
        return
    elapsed = min(dt, remaining)
    enemy.dust_remaining = remaining - elapsed
    game.damage_enemy(enemy, enemy.dust_dps * elapsed, show_number=False)
    enemy.dust_visual_timer -= elapsed
    if enemy.alive and enemy.dust_visual_timer <= 0.0:
        game.spawn_dust(enemy, max(1, enemy.dust_stacks))
        enemy.dust_visual_timer = 0.2
    if enemy.dust_remaining <= 0.0:
        enemy.dust_dps = 0.0
        enemy.dust_stacks = 0
