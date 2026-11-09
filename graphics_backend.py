"""
GPU-презентация кадра и выбор видеоадаптера.

Игровая сцена по-прежнему собирается из pygame.Surface: вся логика,
спрайты, свет и HUD уже написаны вокруг Surface.  Этот модуль переносит
финальную стадию на видеоадаптер: поверхность загружается в текстуру,
OpenGL растягивает её на окно и при желании добавляет мягкое свечение.
Это даёт GPU-фильтрацию/масштабирование и убирает программный blit
готового кадра, не меняя боевую логику и не требуя переписывать все
объекты на шейдеры.

На Windows выбор адаптера делается через официальное предпочтение
приложения в HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences.
Это то же предпочтение, что задаёт раздел Windows «Графика», но игра
записывает его сама и перезапускается.  Фактический адаптер виден в
настройках по строке GL_RENDERER.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pygame

from settings import HEIGHT, WIDTH

try:  # PyOpenGL остаётся необязательным: без него игра идёт через CPU.
    from OpenGL import GL
    from OpenGL.GL import shaders
except Exception:  # pragma: no cover - зависит от машины
    GL = None
    shaders = None


# ------------------------------------------------------------------ адаптеры
_VIRTUAL_MARKERS = (
    "idisplay", "virtual", "remote", "parsec", "spacedesk", "citrix",
    "vmware", "microsoft basic", "basic display", "indirect display",
)
_INTEGRATED_MARKERS = (
    "intel", "uhd", "iris", "radeon graphics", "radeon(tm) graphics",
    "vega", "apu", "integrated",
)


@dataclass(frozen=True)
class VideoAdapter:
    """Один вариант выбора в настройках."""

    name: str
    key: str
    vendor: str = ""
    memory_mb: int = 0
    preference: int = 0  # 0 авто, 1 энергосбережение, 2 высокая производительность
    device: bool = False

    @property
    def label(self) -> str:
        return self.name


AUTO_ADAPTER = VideoAdapter(
    name="Авто (решает Windows)",
    key="auto",
    preference=0,
    device=False,
)


def _adapter_preference(name: str, vendor: str = "") -> int:
    """Windows умеет выбирать только класс GPU, а не произвольный индекс."""
    text = f"{name} {vendor}".lower()
    if any(marker in text for marker in _INTEGRATED_MARKERS):
        return 1
    return 2


def _is_virtual_adapter(name: str) -> bool:
    text = name.lower()
    return any(marker in text for marker in _VIRTUAL_MARKERS)


def _parse_powershell_adapters(raw: str) -> list[VideoAdapter]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    found: list[VideoAdapter] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        if not name or _is_virtual_adapter(name):
            continue
        vendor = str(item.get("AdapterCompatibility") or "").strip()
        key = str(item.get("PNPDeviceID") or name)
        if key in seen:
            continue
        seen.add(key)
        try:
            memory = int(item.get("AdapterRAM") or 0) // (1024 * 1024)
        except (TypeError, ValueError):
            memory = 0
        found.append(VideoAdapter(
            name=name,
            key=key,
            vendor=vendor,
            memory_mb=max(0, memory),
            preference=_adapter_preference(name, vendor),
            device=True,
        ))
    found.sort(key=lambda adapter: (-adapter.preference, adapter.name.lower()))
    return found


def list_video_adapters() -> list[VideoAdapter]:
    """Возвращает физические GPU Windows; на других ОС список пуст."""
    if sys.platform != "win32":
        return []
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,AdapterRAM,PNPDeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return _parse_powershell_adapters(completed.stdout)


# ------------------------------------------------------------- Windows pref
def _set_windows_gpu_preference(preference: int) -> tuple[bool, str]:
    """Пишет предпочтение для текущего python.exe / собранного exe."""
    if sys.platform != "win32":
        return False, "Выбор адаптера доступен только в Windows."
    if preference not in (0, 1, 2):
        return False, "Неизвестный профиль GPU."
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return False, "Модуль winreg недоступен."

    path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    value_name = os.path.normcase(str(Path(sys.executable).resolve()))
    try:
        with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, path, 0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        ) as key:
            old = ""
            try:
                old, _ = winreg.QueryValueEx(key, value_name)
            except OSError:
                pass
            parts = [
                part for part in str(old or "").split(";")
                if part and not part.lower().startswith("gpupreference=")
            ]
            parts.append(f"GpuPreference={int(preference)}")
            winreg.SetValueEx(
                key, value_name, 0, winreg.REG_SZ, ";".join(parts) + ";"
            )
    except OSError as exc:
        return False, f"Windows не приняла настройку GPU: {exc}"
    return True, "Предпочтение GPU применено."


# ------------------------------------------------------------- OpenGL frame
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

    def __init__(self, size: tuple[int, int], effects: bool = True):
        if GL is None or shaders is None:
            raise RuntimeError("PyOpenGL не установлен")
        self.size = (int(size[0]), int(size[1]))
        self.surface = pygame.Surface(self.size)
        self.effects = bool(effects)
        self._closed = False

        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 0)
        pygame.display.set_mode(
            self.size, pygame.OPENGL | pygame.DOUBLEBUF
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
        if self._raw_bgra:
            # Surface уже лежит как BGRA; .raw копирует без перекодирования.
            pixels = self.surface.get_buffer().raw
            pixel_format = GL.GL_BGRA
        else:
            pixels = pygame.image.tostring(self.surface, "RGBA", False)
            pixel_format = GL.GL_RGBA
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(self._program)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
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


class CPUDisplay:
    """Обычный SDL-дисплей: тот же путь, что был до OpenGL."""

    name = "CPU (SDL)"
    version = ""
    vendor = ""

    def __init__(self, size=(WIDTH, HEIGHT)):
        self.surface = pygame.display.set_mode(tuple(size))
        self.effects = False

    def set_effects(self, enabled: bool):
        self.effects = bool(enabled)

    def present(self):
        pygame.display.flip()

    def close(self):
        pass


# ------------------------------------------------------------------ manager
DEFAULT_CONFIG = {
    "renderer": "opengl",
    "adapter": "auto",
    "adapter_preference": 0,
    "effects": True,
}


class VideoManager:
    """Владеет окном, OpenGL-презентером и сохранённым выбором GPU."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT,
                 config_path: str | os.PathLike | None = None):
        self.width = int(width)
        self.height = int(height)
        self.config_path = Path(config_path) if config_path else (
            Path(__file__).with_name("video_settings.json")
        )
        config = self._load()
        self.requested_mode = str(config.get("renderer", "opengl")).lower()
        if self.requested_mode not in ("opengl", "cpu"):
            self.requested_mode = "opengl"
        self.effects = bool(config.get("effects", True))
        self.selected_key = str(config.get("adapter", "auto"))
        try:
            self.selected_preference = int(config.get("adapter_preference", 0))
        except (TypeError, ValueError):
            self.selected_preference = 0

        self.mode = "cpu"
        self.renderer = None
        self.surface = None
        self.active_renderer = ""
        self.last_error = ""
        self.notice = ""
        self._adapters: list[VideoAdapter] | None = None
        self._adapter_ready = threading.Event()
        self._adapter_thread = None
        self._adapter_waited = False

    # ------------------------------------------------------------- lifecycle
    @staticmethod
    def _headless() -> bool:
        driver = os.environ.get("SDL_VIDEODRIVER", "").lower()
        if driver == "dummy":
            return True
        try:
            return pygame.display.get_driver().lower() == "dummy"
        except Exception:
            return False

    def start(self):
        """Создаёт окно.  При отсутствии GL мягко откатывается на CPU."""
        if self.selected_key != "auto" and not self._headless():
            ok, message = _set_windows_gpu_preference(self.selected_preference)
            if not ok and sys.platform == "win32":
                self.notice = message
        if not self._headless():
            # PowerShell перечисляет адаптеры ~1 секунду; не блокируем кадр.
            self.prefetch_adapters()
        self._create_display(self.requested_mode)

    def _create_display(self, requested: str):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.mode = "cpu"
        self.active_renderer = ""
        self.last_error = ""

        if requested == "opengl" and not self._headless():
            try:
                presenter = OpenGLPresenter(
                    (self.width, self.height), effects=self.effects
                )
            except Exception as exc:  # PyOpenGL/драйвер/контекст
                self.last_error = f"OpenGL недоступен: {exc}"
                self.notice = self.last_error
                # Не оставляем наполовину созданный GL-дисплей.
                pygame.display.quit()
                pygame.display.init()
            else:
                self.renderer = presenter
                self.surface = presenter.surface
                self.mode = "opengl"
                self.active_renderer = presenter.name
                return

        try:
            display = CPUDisplay((self.width, self.height))
        except Exception as exc:
            self.last_error = f"Не удалось открыть окно: {exc}"
            raise
        self.renderer = display
        self.surface = display.surface
        self.mode = "cpu"
        self.active_renderer = display.name

    def present(self):
        if self.renderer is not None:
            self.renderer.present()

    def switch_mode(self, mode: str):
        mode = str(mode).lower()
        if mode not in ("opengl", "cpu"):
            return
        if mode == self.requested_mode and self.mode == mode and self.renderer is not None:
            return
        self.requested_mode = mode
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        pygame.display.quit()
        pygame.display.init()
        self._create_display(mode)
        self.save()

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None

    # ------------------------------------------------------------- adapters
    def prefetch_adapters(self):
        if self._adapters is not None or self._adapter_thread is not None:
            return
        self._adapter_thread = threading.Thread(
            target=self._load_adapters, name="video-adapters", daemon=True
        )
        self._adapter_thread.start()

    def _load_adapters(self):
        try:
            adapters = [AUTO_ADAPTER] + list_video_adapters()
        except Exception:
            adapters = [AUTO_ADAPTER]
        self._adapters = adapters
        self._adapter_ready.set()

    def get_adapters(self) -> list[VideoAdapter]:
        if self._adapters is None:
            self.prefetch_adapters()
            # Ждём один раз и совсем недолго: если PowerShell ещё думает,
            # показываем «Авто», а список появится следующим кадром.
            if not self._adapter_waited:
                self._adapter_waited = True
                self._adapter_ready.wait(0.5)
        return self._adapters or [AUTO_ADAPTER]

    def selected_adapter(self) -> VideoAdapter:
        for adapter in self.get_adapters():
            if adapter.key == self.selected_key:
                return adapter
        return AUTO_ADAPTER

    def selected_adapter_index(self) -> int:
        adapters = self.get_adapters()
        for index, adapter in enumerate(adapters):
            if adapter.key == self.selected_key:
                return index
        return 0

    def select_adapter(self, index: int) -> VideoAdapter:
        if self._adapters is None:
            self.prefetch_adapters()
            self._adapter_ready.wait(3.0)
        adapters = self.get_adapters()
        if not adapters:
            return AUTO_ADAPTER
        adapter = adapters[int(index) % len(adapters)]
        self.selected_key = adapter.key
        self.selected_preference = adapter.preference
        ok, message = _set_windows_gpu_preference(adapter.preference)
        if adapter.device:
            self.notice = (
                f"Выбран {adapter.name}. Нажмите Enter, чтобы перезапустить игру."
                if ok else f"{message} Выбор сохранён, но применится вручную."
            )
        else:
            self.notice = "Выбор GPU: авто. Нажмите Enter, чтобы перезапустить игру."
        self.save()
        return adapter

    def cycle_adapter(self, step: int) -> VideoAdapter:
        adapters = self.get_adapters()
        if not adapters:
            return AUTO_ADAPTER
        index = (self.selected_adapter_index() + (1 if step > 0 else -1)) % len(adapters)
        return self.select_adapter(index)

    def apply_selected_preference(self) -> tuple[bool, str]:
        # Не перечисляем адаптеры повторно: если PowerShell не ответил,
        # сохранённый выбор всё равно должен примениться.
        preference = 0 if self.selected_key == "auto" else self.selected_preference
        ok, message = _set_windows_gpu_preference(preference)
        self.notice = message
        if ok and self.selected_key != "auto":
            adapter = self.selected_adapter()
            self.notice = (
                f"Предпочтение {adapter.name} применено. "
                "Перезапустите игру, чтобы OpenGL взял его."
            )
        return ok, message

    # ------------------------------------------------------------- settings
    def set_effects(self, enabled: bool):
        self.effects = bool(enabled)
        if self.renderer is not None:
            try:
                self.renderer.set_effects(self.effects)
            except Exception:
                pass
        self.save()

    def save(self):
        data = {
            "renderer": self.requested_mode,
            "adapter": self.selected_key,
            "adapter_preference": self.selected_preference,
            "effects": self.effects,
        }
        try:
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.config_path)
        except OSError:
            pass

    def _load(self) -> dict:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return dict(DEFAULT_CONFIG)
        return data if isinstance(data, dict) else dict(DEFAULT_CONFIG)

    @property
    def adapter_status(self) -> str:
        adapter = self.selected_adapter()
        active = self.active_renderer or "—"
        if adapter.device and self.mode == "opengl":
            return f"{adapter.name} · активно: {active}"
        return f"{adapter.name}"
