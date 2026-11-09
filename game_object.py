"""
Базовый класс всех объектов игры.
"""
import pygame


class GameObject:
    """
    «Прародитель» для всех объектов: герой, враги, пули, эффекты.

    Задаёт ОДИН контракт (соглашение) для подклассов:
      * update(dt, game)  — что делать каждый кадр
      * draw(screen, camera) — как нарисоваться (camera переводит
        мировые координаты в экранные)

    Сам GameObject напрямую не создаётся — только наследуется.
    """

    # Признак «светящегося» объекта: такие рисуются ПОСЛЕ наложения темноты.
    emissive = False

    # Радиус света, если объект светится сам (например, взрыв).
    # 0 = не является источником света. Game собирает все источники
    # и передаёт их в LightingManager (см. Game.draw).
    light_radius = 0

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.alive = True

    @property
    def pos(self):
        """Текущая позиция в виде кортежа (x, y) — мировые координаты."""
        return self.x, self.y

    def kill(self):
        """Помечает объект удалённым — сам объект исчезнет из списков игры."""
        self.alive = False

    def update(self, dt, game):
        """Обновление состояния. Подклассы ОБЯЗАНЫ переопределить."""
        raise NotImplementedError(
            f"{type(self).__name__} должен реализовать update()"
        )

    def draw(self, screen, camera):
        """Отрисовка. Подклассы ОБЯЗАНЫ переопределить."""
        raise NotImplementedError(
            f"{type(self).__name__} должен реализовать draw()"
        )
