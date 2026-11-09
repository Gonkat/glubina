"""
Точка входа. Запуск:  python main.py

Здесь нет логики — только создание игры и старт.
"""
from game import Game


def main():
    game = Game()   # pygame.init(), окно и настройки — внутри класса Game
    game.run()


if __name__ == "__main__":
    main()
