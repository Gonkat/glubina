"""
Кривые прогрессии сложности (M10).

Почему отдельный модуль: баланс — это МАТЕМАТИКА от времени игры,
а не побочный эффект игрового цикла. Функции здесь чистые (ничего не
меняют в игре), поэтому:

  * их можно тестировать напрямую, не запуская игру (smoke_test_m10);
  * отчёт баланса печатается из тех же формул, по которым играет игрок —
    расхождений «в тесте одно, в игре другое» не бывает;
  * вся настройка — числа в settings.py: поменял константу — поменял
    кривую, не трогая код.

M10 «почему так»: раньше потолок врагов рос как (6 + t/5), волны —
каждые 45 с до 5 штук, HP — +25% каждые 60 с без потолка. Игрок
не успевал зарабатывать на оружие, а мир уже был забит танками.
Теперь рост мягче, у каждой кривой есть ПОТОЛОК, а деньги игроку
даёт награда за убийство (bounty) — прокачка догоняет сложность.
"""
from settings import (
    ENEMY_DAMAGE_GROWTH,
    ENEMY_DAMAGE_GROWTH_CAP,
    ENEMY_HP_GROWTH,
    ENEMY_HP_GROWTH_CAP,
    ENEMY_HP_GROWTH_PERIOD,
    ENEMY_SPEED_GROWTH,
    ENEMY_SPEED_GROWTH_CAP,
    MAX_ENEMIES,
    SPAWN_CAP_BASE,
    SPAWN_CAP_GROWTH,
    SPAWN_CAP_MIN,
    SPAWN_WAVE_MAX,
    SPAWN_WAVE_STEP,
)


def _periods(elapsed):
    """Сколько «шагов роста» прошло с начала игры."""
    return int(elapsed / ENEMY_HP_GROWTH_PERIOD)


def hp_multiplier(elapsed):
    """
    Множитель HP при спавне: ступени каждые ENEMY_HP_GROWTH_PERIOD
    секунд, но не выше ENEMY_HP_GROWTH_CAP.
    """
    factor = 1.0 + _periods(elapsed) * ENEMY_HP_GROWTH
    return min(factor, ENEMY_HP_GROWTH_CAP)


def speed_multiplier(elapsed):
    """Множитель скорости: мягче HP-кривой, потолок ниже."""
    factor = 1.0 + _periods(elapsed) * ENEMY_SPEED_GROWTH
    return min(factor, 1.0 + ENEMY_SPEED_GROWTH_CAP)


def damage_multiplier(elapsed):
    """Множитель урона: растёт, чтобы поздние враги били заметно."""
    factor = 1.0 + _periods(elapsed) * ENEMY_DAMAGE_GROWTH
    return min(factor, 1.0 + ENEMY_DAMAGE_GROWTH_CAP)


def spawn_cap(elapsed, population=1.0):
    """
    Сколько врагов МОЖЕТ жить одновременно (до MAX_ENEMIES).
    population — множитель сложности (DIFFICULTIES[...]).
    """
    raw = (SPAWN_CAP_BASE + elapsed * SPAWN_CAP_GROWTH) * population
    return min(MAX_ENEMIES, max(SPAWN_CAP_MIN, int(raw)))


def spawn_wave(elapsed):
    """Сколько новых врагов рождается за один шаг спавна."""
    return 1 + min(SPAWN_WAVE_MAX - 1, int(elapsed / SPAWN_WAVE_STEP))
