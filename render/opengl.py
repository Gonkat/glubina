"""OpenGL-презентер: кадр Surface загружается в текстуру и рисуется квадратом."""
from __future__ import annotations

import ctypes
from contextlib import nullcontext

import pygame

from render.base import surface_pixels
from render_metrics import FrameMetrics

try:  # PyOpenGL остаётся необязательным: без него игра идёт через CPU.
    from OpenGL import GL
    from OpenGL.GL import shaders
except Exception:  # pragma: no cover - зависит от машины
    GL = None
    shaders = None


def gl_available() -> bool:
    """Установлен ли PyOpenGL (контекст проверяется при создании)."""
    return GL is not None and shaders is not None


_VERTEX_SHADER = """
#version 120
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
    // Текстура загружается сверху вниз (BGRA из Surface), поэтому V
    // инвертируется здесь, а не лишним копированием пикселей.
    v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = """
#version 120
uniform sampler2D u_scene;
uniform vec2 u_texel;
uniform float u_effects;
varying vec2 v_uv;

void main() {
    vec3 color = texture2D(u_scene, v_uv).rgb;
    if (u_effects > 0.5) {
        vec3 b = texture2D(u_scene, v_uv + vec2(-2.0 * u_texel.x, 0.0)).rgb;
        b += texture2D(u_scene, v_uv + vec2(2.0 * u_texel.x, 0.0)).rgb;
        b += texture2D(u_scene, v_uv + vec2(0.0, -2.0 * u_texel.y)).rgb;
        b += texture2D(u_scene, v_uv + vec2(0.0, 2.0 * u_texel.y)).rgb;
        b += texture2D(u_scene, v_uv + vec2(-1.5 * u_texel.x, 1.5 * u_texel.y)).rgb;
        b += texture2D(u_scene, v_uv + vec2(1.5 * u_texel.x, 1.5 * u_texel.y)).rgb;
        b += texture2D(u_scene, v_uv + vec2(-1.5 * u_texel.x, -1.5 * u_texel.y)).rgb;
        b += texture2D(u_scene, v_uv + vec2(1.5 * u_texel.x, -1.5 * u_texel.y)).rgb;
        b *= 0.125;
        float light = dot(b, vec3(0.299, 0.587, 0.114));
        color += b * smoothstep(0.58, 0.96, light) * 0.22;
    }
    gl_FragColor = vec4(color, 1.0);
}
"""


def _gl_string(name: int) -> str:
    try:
        value = GL.glGetString(name)
    except Exception:
        return ""
    if not value:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


class OpenGLPresenter:
    """Загружает готовый Surface в GPU-текстуру и рисует его на окне."""

    def __init__(self, size: tuple[int, int], effects: bool = True,
                 metrics: FrameMetrics | None = None, vsync: bool = False):
        if GL is None or shaders is None:
            raise RuntimeError("PyOpenGL не установлен")
        self.size = (int(size[0]), int(size[1]))
        self.surface = pygame.Surface(self.size)
        self.effects = bool(effects)
        self.metrics = metrics
        self._closed = False

        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 0)
        pygame.display.set_mode(
            self.size, pygame.OPENGL | pygame.DOUBLEBUF,
            vsync=1 if vsync else 0,
        )

        self.name = _gl_string(GL.GL_RENDERER) or "OpenGL"
        self.version = _gl_string(GL.GL_VERSION)
        self.vendor = _gl_string(GL.GL_VENDOR)
        self._init_gl()

    def _init_gl(self):
        GL.glViewport(0, 0, self.size[0], self.size[1])
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)

        vertex = shaders.compileShader(_VERTEX_SHADER, GL.GL_VERTEX_SHADER)
        fragment = shaders.compileShader(_FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER)
        self._program = shaders.compileProgram(vertex, fragment)
        GL.glUseProgram(self._program)
        masks = self.surface.get_masks()
        self._raw_bgra = self.surface.get_bytesize() == 4 and masks[:3] == (
            0x00FF0000, 0x0000FF00, 0x000000FF,
        )

        self._texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8,
            self.size[0], self.size[1], 0,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None,
        )

        self._quad = (ctypes.c_float * 8)(
            -1.0, -1.0,
            1.0, -1.0,
            -1.0, 1.0,
            1.0, 1.0,
        )
        self._vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, ctypes.sizeof(self._quad),
            self._quad, GL.GL_STATIC_DRAW,
        )
        self._pos = GL.glGetAttribLocation(self._program, "a_pos")
        self._scene = GL.glGetUniformLocation(self._program, "u_scene")
        self._texel = GL.glGetUniformLocation(self._program, "u_texel")
        self._effects_loc = GL.glGetUniformLocation(self._program, "u_effects")
        if self._pos >= 0:
            GL.glEnableVertexAttribArray(self._pos)
        GL.glUniform1i(self._scene, 0)
        GL.glUniform2f(
            self._texel,
            1.0 / max(1, self.size[0]), 1.0 / max(1, self.size[1]),
        )
        self._closed = False

    def set_effects(self, enabled: bool):
        self.effects = bool(enabled)

    def present(self):
        if self._closed:
            return
        metrics = self.metrics
        upload_timer = (
            metrics.measure("tex_upload") if metrics is not None
            else nullcontext()
        )
        draw_timer = (
            metrics.measure("present") if metrics is not None
            else nullcontext()
        )
        pixels, pixel_format = surface_pixels(self.surface)
        if pixel_format != "BGRA":
            pixel_format = GL.GL_RGBA
        else:
            pixel_format = GL.GL_BGRA
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(self._program)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        with upload_timer:
            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D, 0, 0, 0,
                self.size[0], self.size[1],
                pixel_format, GL.GL_UNSIGNED_BYTE, pixels,
            )
        GL.glUniform1f(self._effects_loc, 1.0 if self.effects else 0.0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        if self._pos >= 0:
            GL.glEnableVertexAttribArray(self._pos)
            GL.glVertexAttribPointer(
                self._pos, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None
            )
        with draw_timer:
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            pygame.display.flip()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            GL.glDeleteBuffers(1, [self._vbo])
            GL.glDeleteTextures([self._texture])
            GL.glDeleteProgram(self._program)
        except Exception:
            pass
