"""
Общий контракт презентера кадра.

Презентер владеет окном и Surface, в который игра рисует сцену.  Он не
знает ничего про игровую логику: его задача — показать готовый кадр.
Именно поэтому CPU/SDL, OpenGL (а в будущем Vulkan) взаимозаменяемы.

Сцена по-прежнему собирается на CPU в pygame.Surface; разница между
презентерами только в финальной стадии — blit и flip либо текстура,
шейдер и GPU-своп.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pygame


@runtime_checkable
class Presenter(Protocol):
    """Минимальный интерфейс, который ждёт VideoManager."""

    size: tuple[int, int]
    surface: pygame.Surface
    name: str
    version: str
    vendor: str
    effects: bool

    def set_effects(self, enabled: bool) -> None: ...

    def present(self) -> None: ...

    def close(self) -> None: ...


def surface_pixels(surface: pygame.Surface) -> tuple[bytes, str]:
    """Возвращает пиксели Surface и их формат: "BGRA" или "RGBA".

    Windows-дисплей обычно уже лежит как BGRA — тогда .raw копирует без
    перекодирования.  Иначе кадр конвертируется через pygame.image.
    """
    masks = surface.get_masks()
    if surface.get_bytesize() == 4 and masks[:3] == (
            0x00FF0000, 0x0000FF00, 0x000000FF):
        return surface.get_buffer().raw, "BGRA"
    return pygame.image.tostring(surface, "RGBA", False), "RGBA"
