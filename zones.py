"""
Типы локаций: профили света, видимость объектов и мерцание ламп.

Зачем отдельный модуль:
  * профили — данные из settings.ZONE_PROFILES, здесь только логика;
  * назначение зоны сектору — чистая детерминированная функция
    (нужна серверу в онлайне: клиент и сервер обязаны выбрать одинаковый
    тип локации для одного и того же сида/глубины);
  * видимость объекта — чистая функция от яркости света и дистанции,
    её же можно звать на сервере, чтобы не слать игроку невидимых врагов;
  * мерцание ламп — детерминировано от (kind, time, phase), поэтому у всех
    клиентов в онлайне лампы моргают одинаково.

Три типа локаций (см. ZONE_PROFILES в settings.py):
  dark   — тёмная: фонарик решает, тени от стен, вне света не видно ничего;
  medium — средняя: ровно прежнее поведение игры;
  cozy   — тёмная с уютными лампами: фонарик слаб, но источники света
           освещают округу, часть ламп мерцает как перегорающие.
"""
from __future__ import annotations

import math
import random

from settings import (
    ZONE_FIRST_SECTOR,
    ZONE_PROFILES,
    ZONE_TRANSITION_TIME,
    ZONE_WEIGHTS,
)

# Профили мерцания → функции: intensity(time, phase) -> 0..1.
# Все детерминированы: в онлайне все клиенты видят одно моргание.
_FLICKER_KINDS = ("steady", "pulse", "dying", "street")


def profile(key: str) -> dict:
    """Профиль локации по ключу; неизвестный ключ безопасно откатывает на medium."""
    return ZONE_PROFILES.get(key, ZONE_PROFILES["medium"])


def zone_for_sector(depth: int, world_seed: int) -> str:
    """
    Детерминированный тип локации для сектора.

    Первый сектор — обучение (ZONE_FIRST_SECTOR), дальше — взвешенный
    выбор по сиду мира и глубине: одинаковые входные данные дают
    одинаковый результат у всех игроков (важно для онлайна).
    """
    depth = max(1, int(depth))
    if depth == 1:
        return ZONE_FIRST_SECTOR
    # Строковый сид обязателен: random.Random(str) хэширует через sha512
    # и даёт одинаковый результат в разных процессах (в отличие от
    # кортежей, чей hash() солится на каждый запуск) — это нужно серверу
    # и клиенту в онлайне, чтобы выбрать одинаковый тип локации.
    rng = random.Random(f"{int(world_seed)}:{depth}:zone")
    roll = rng.random()
    total = sum(max(0.0, weight) for weight in ZONE_WEIGHTS.values())
    if total <= 0.0:
        return "medium"
    for key, weight in ZONE_WEIGHTS.items():
        roll -= max(0.0, weight) / total
        if roll <= 0.0:
            return key
    return "medium"


def zone_keys() -> tuple:
    """Ключи всех профилей в стабильном порядке (для UI/тестов)."""
    return tuple(ZONE_PROFILES)


def blend_profile(a: str, b: str, t: float) -> dict:
    """
    Плавный переход между профилями: t=0 → a, t=1 → b.

    Смешиваются только «плавные» поля (цвета и числа). Булевы поля
    (gated/shadows/edges) берутся из того профиля, к которому ближе t:
    переключение происходит на середине, дальше новое поведение
    подхватывается без рывка визуально — свет и так доезжает за
    ZONE_TRANSITION_TIME.
    """
    t = 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else float(t))
    pa, pb = profile(a), profile(b)
    if t <= 0.0:
        return dict(pa)
    if t >= 1.0:
        return dict(pb)
    out = dict(pb if t >= 0.5 else pa)
    for key in ("ambient",):
        va, vb = pa[key], pb[key]
        out[key] = tuple(
            int(round(va[i] + (vb[i] - va[i]) * t)) for i in range(3)
        )
    for key in (
        "light_threshold", "full_light", "cone_mul", "cone_strength_mul",
        "flashlight_mul", "glow_mul", "shadow_rays", "shadow_step",
        "diffraction_px", "diffraction_strength", "lamp_chance",
        "lamp_radius_mul", "post_chance",
    ):
        va, vb = pa[key], pb[key]
        out[key] = va + (vb - va) * t
    # Булевы поля — из «победившей» половины перехода.
    source = pb if t >= 0.5 else pa
    for key in ("gated", "shadows", "diffraction", "edges"):
        out[key] = bool(source[key])
    return out


# ------------------------------------------------------------ ВИДИМОСТЬ
def visibility(light: float, distance: float, prof: dict) -> float:
    """
    Насколько объект виден: 0.0 — полностью невидим, 1.0 — виден отлично.

    light     — яркость «проявляющего» света в точке объекта (0..1;
                конус фонарика, лампы, вспышки — БЕЗ личного ореола);
    distance  — дистанция до игрока (оставлена для совместимости API,
                на видимость НЕ влияет: в темноте не видно даже вплотную);
    prof      — профиль локации (dict).

    Правило из дизайна (v3):
      * видит только свет — за спиной и вне конуса объекты не видны;
      * у края света видимость теряется ПЛАВНО (smoothstep между
        light_threshold и full_light): объект проявляется/гаснет
        с потерей прозрачности, а не рывком;
      * профили без gated (яркая «средняя» зона) — всегда 1.0.
    """
    if not prof.get("gated", False):
        return 1.0
    light = 0.0 if light < 0.0 else (1.0 if light > 1.0 else float(light))
    threshold = float(prof.get("light_threshold", 0.0))
    full = max(threshold + 1e-6, float(prof.get("full_light", 0.5)))
    if light <= threshold:
        return 0.0
    t = min(1.0, (light - threshold) / (full - threshold))
    # smoothstep: мягкие края без «ступеньки» на пороге.
    return t * t * (3.0 - 2.0 * t)


def visible_enough(alpha: float) -> bool:
    """Достаточно ли виден, чтобы вообще рисовать объект."""
    return alpha >= 0.04


# ------------------------------------------------------------ МЕРЦАНИЕ ЛАМП
def _flicker_steady(time: float, phase: float) -> float:
    """Спокойное живое покачивание (поведение игры по умолчанию)."""
    return 0.82 + 0.18 * math.sin(time * 2.2 + phase)


def _flicker_pulse(time: float, phase: float) -> float:
    """Мягкая пульсация — «дышит» заметнее steady."""
    return 0.74 + 0.26 * (0.5 + 0.5 * math.sin(time * 1.1 + phase))


def _flicker_dying(time: float, phase: float) -> float:
    """
    Перегорающая лампа: яркость дрожит, периодически проседает почти до нуля.
    Сумма двух синусов даёт нерегулярный ритм без random — в онлайне
    у всех клиентов одинаково.
    """
    base = 0.70 + 0.30 * math.sin(time * 1.7 + phase)
    # «свечение накала»: быстрая мелкая дрожь
    tremble = 0.12 * math.sin(time * 23.0 + phase * 3.0)
    # редкие провалы: медленный синус периодически уходит ниже нуля
    dropout = math.sin(time * 0.55 + phase * 7.0)
    value = base + tremble
    if dropout > 0.93:
        value *= 0.15 + 0.5 * (1.0 - dropout) / 0.07
    return max(0.05, min(1.0, value))


def _flicker_street(time: float, phase: float) -> float:
    """
    Фонарный столб: почти ровный свет, но короткое «моргание»
    раз в ~5 секунд, как у реальных уличных фонарей.
    """
    cycle = (time + phase) % 5.0
    value = 0.92 + 0.08 * math.sin(time * 1.4 + phase)
    if cycle < 0.35:
        # короткое моргание: два быстрых щелчка
        value *= 0.25 if (cycle < 0.12 or 0.20 <= cycle < 0.30) else 0.6
    return max(0.05, min(1.0, value))


_FLICKERS = {
    "steady": _flicker_steady,
    "pulse": _flicker_pulse,
    "dying": _flicker_dying,
    "street": _flicker_street,
}


def flicker(kind: str, time: float, phase: float) -> float:
    """Интенсивность мерцания лампы: 0..1. Неизвестный kind → steady."""
    fn = _FLICKERS.get(kind, _flicker_steady)
    return fn(float(time), float(phase))


def pick_flicker(prof: dict, seed_value: int) -> str:
    """Детерминированный выбор профиля мерцания по профилю зоны и сиду."""
    weights = prof.get("lamp_flickers") or (("steady", 1),)
    total = sum(max(0, int(w)) for _, w in weights)
    if total <= 0:
        return "steady"
    roll = random.Random(int(seed_value)).randrange(total)
    for kind, weight in weights:
        roll -= max(0, int(weight))
        if roll < 0:
            return kind if kind in _FLICKER_KINDS else "steady"
    return "steady"


def transition_progress(elapsed_in_zone: float) -> float:
    """0..1 — насколько далеко зашёл плавный переход между типами локаций."""
    if ZONE_TRANSITION_TIME <= 0.0:
        return 1.0
    t = float(elapsed_in_zone) / ZONE_TRANSITION_TIME
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
