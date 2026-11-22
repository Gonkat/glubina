"""
Точка входа. Запуск:  python main.py

Здесь нет логики — только создание игры и старт.
"""
import os
import traceback


def _raise_timer_resolution():
    """Windows: системный таймер 1 мс вместо 15.6 мс.

    SDL_Delay/pygame Clock спят по системному кванту: при 15.6 мс кадры
    «дышат» даже при ровном FPS, и это видно как дрожание картинки у
    гостя. Точный таймер даёт ровный шаг ~16.7 мс. Возвращает функцию
    восстановления или None. Вне Windows и на ошибках — просто None.
    """
    try:
        import ctypes

        winmm = ctypes.WinDLL("winmm")
        if winmm.timeBeginPeriod(1) != 0:
            return None
        return lambda: winmm.timeEndPeriod(1)
    except (AttributeError, OSError):
        return None


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
    restore_timer = _raise_timer_resolution()
    try:
        from game import Game

        game = Game()   # pygame.init(), окно и настройки — внутри класса Game
        game.run()
    except Exception:
        details = traceback.format_exc()
        _report_startup_error(details)
        raise
    finally:
        if restore_timer is not None:
            restore_timer()


if __name__ == "__main__":
    main()
