"""
Точка входа. Запуск:  python main.py

Здесь нет логики — только создание игры и старт.
"""
import os
import traceback


def _report_startup_error(details):
    """Сохраняет ошибку запуска и показывает её на Windows."""
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(root, "Glubina")
    log_path = os.path.join(log_dir, "startup-error.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as file:
            file.write(details)
    except OSError:
        log_path = ""

    message = "Не удалось запустить игру."
    if log_path:
        message += f"\n\nПодробности сохранены в:\n{log_path}"
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "ГЛУБИНА", 0x10)
    except (AttributeError, OSError):
        print(message)
        print(details)


def main():
    try:
        from game import Game

        game = Game()   # pygame.init(), окно и настройки — внутри класса Game
        game.run()
    except Exception:
        details = traceback.format_exc()
        _report_startup_error(details)
        raise


if __name__ == "__main__":
    main()
