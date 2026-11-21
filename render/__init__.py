"""
Пакет презентеров кадра: CPU/SDL, OpenGL и общий контракт.

Игра и VideoManager работают только с интерфейсом Presenter, поэтому
новый бэкенд (например, Vulkan) добавляется отдельным модулем, не меняя
игровой цикл и не трогая отрисовку сцены.
"""
from __future__ import annotations

from render.base import Presenter, surface_pixels
from render.cpu import CPUDisplay
from render.opengl import OpenGLPresenter, gl_available

__all__ = [
    "Presenter",
    "surface_pixels",
    "CPUDisplay",
    "OpenGLPresenter",
    "gl_available",
]
