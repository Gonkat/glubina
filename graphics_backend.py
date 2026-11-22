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

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pygame

from render import CPUDisplay, OpenGLPresenter
from render_metrics import FrameMetrics
from settings import FPS, HEIGHT, WIDTH


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


# ------------------------------------------------------------------ manager
# Лимит кадров: 0 — без ограничения. 144 — прежнее поведение (settings.FPS).
FPS_CAP_OPTIONS = (60, 120, 144, 240, 0)

DEFAULT_CONFIG = {
    "renderer": "opengl",
    "adapter": "auto",
    "adapter_preference": 0,
    "effects": True,
    "fps_cap": FPS,
    "vsync": False,
}


class VideoManager:
    """Владеет окном, OpenGL-презентером и сохранённым выбором GPU."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT,
                 config_path: str | os.PathLike | None = None,
                 metrics: FrameMetrics | None = None):
        self.width = int(width)
        self.height = int(height)
        # Один сборщик на игру: игра пишет update/draw, презентер — present.
        self.metrics = metrics if metrics is not None else FrameMetrics()
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
        try:
            self.fps_cap = int(config.get("fps_cap", FPS))
        except (TypeError, ValueError):
            self.fps_cap = FPS
        if self.fps_cap not in FPS_CAP_OPTIONS:
            self.fps_cap = FPS
        self.vsync = bool(config.get("vsync", False))

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
                    (self.width, self.height), effects=self.effects,
                    metrics=self.metrics, vsync=self.vsync,
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
            display = CPUDisplay(
                (self.width, self.height), metrics=self.metrics,
                vsync=self.vsync,
            )
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

    # --------------------------------------------------------------- кадры
    def frame_rate(self) -> int:
        """Лимит для ``clock.tick()``; 0 — без ограничения."""
        return int(self.fps_cap)

    def cycle_fps_cap(self, step: int) -> int:
        """Следующий/предыдущий предел кадров из списка настроек."""
        try:
            index = FPS_CAP_OPTIONS.index(self.fps_cap)
        except ValueError:
            index = FPS_CAP_OPTIONS.index(FPS)
        self.fps_cap = FPS_CAP_OPTIONS[
            (index + (1 if step > 0 else -1)) % len(FPS_CAP_OPTIONS)
        ]
        self.save()
        return self.fps_cap

    def set_vsync(self, enabled: bool) -> bool:
        """Включает/выключает вертикальную синхронизацию, пересоздавая окно."""
        enabled = bool(enabled)
        if enabled == self.vsync:
            return self.vsync
        self.vsync = enabled
        self.save()
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
            pygame.display.quit()
            pygame.display.init()
            self._create_display(self.requested_mode)
        return self.vsync

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
            "fps_cap": self.fps_cap,
            "vsync": self.vsync,
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
