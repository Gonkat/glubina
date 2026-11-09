import os
from unittest.mock import Mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import game as game_module
import graphics_backend
from game import Game
from graphics_backend import (
    VideoAdapter,
    VideoManager,
    _adapter_preference,
    _parse_powershell_adapters,
)


def test_settings_menu_cycles_four_items_and_volume():
    app = Game.__new__(Game)
    app.settings_menu_index = 0
    app.settings_notice = ""
    app.video = Mock(requested_mode="cpu", mode="cpu", effects=False)

    for _ in range(4):
        app._handle_settings_menu(pygame.K_DOWN)
    assert app.settings_menu_index == 0

    old_volume = game_module.soundbank.get_volume()
    app._handle_settings_menu(pygame.K_RIGHT)
    assert game_module.soundbank.get_volume() > old_volume
    game_module.soundbank.set_volume(old_volume)


def test_render_mode_switch_updates_screen(monkeypatch):
    app = Game.__new__(Game)
    app.settings_menu_index = 1
    app.settings_notice = ""
    app.screen = pygame.Surface((16, 16))
    app._world_layer = object()
    app.attack_overlay = pygame.Surface((16, 16), pygame.SRCALPHA)
    app._tints = {1: object()}
    app.video = Mock()
    app.video.requested_mode = "opengl"
    app.video.mode = "opengl"
    app.video.active_renderer = "Test GPU"
    app.video.surface = pygame.Surface((16, 16))
    app.video.notice = ""
    monkeypatch.setattr(game_module.pygame.display, "set_caption", Mock())
    monkeypatch.setattr(game_module.pygame.mouse, "set_visible", Mock())

    app._set_render_mode("opengl")

    app.video.switch_mode.assert_called_once_with("opengl")
    assert app.screen is app.video.surface
    assert app._world_layer is None
    assert app._tints == {}
    assert "Test GPU" in app.settings_notice


def test_adapter_selection_and_enter_restart():
    app = Game.__new__(Game)
    app.settings_menu_index = 2
    app.settings_notice = ""
    app.video = Mock()
    app.video.notice = "Выбран GPU."
    app._restart_with_video = Mock()

    app._handle_settings_menu(pygame.K_RIGHT)
    app.video.cycle_adapter.assert_called_once_with(1)
    assert app.settings_notice == "Выбран GPU."

    app._handle_settings_menu(pygame.K_RETURN)
    app._restart_with_video.assert_called_once_with()


def test_restart_with_video_saves_and_relaunches(monkeypatch):
    app = Game.__new__(Game)
    app.settings_notice = ""
    app.video = Mock()
    app.video.apply_selected_preference.return_value = (True, "ok")
    exec_mock = Mock()
    quit_mock = Mock()
    monkeypatch.setattr(game_module.os, "execv", exec_mock)
    monkeypatch.setattr(game_module.pygame, "quit", quit_mock)

    app._restart_with_video()

    app.video.save.assert_called_once_with()
    app.video.close.assert_called_once_with()
    quit_mock.assert_called_once_with()
    exec_mock.assert_called_once()


def test_effects_toggle():
    app = Game.__new__(Game)
    app.settings_menu_index = 3
    app.settings_notice = ""
    app.video = Mock(effects=True)

    app._handle_settings_menu(pygame.K_RETURN)

    app.video.set_effects.assert_called_once_with(False)
    assert "выключены" in app.settings_notice


def test_adapter_parser_filters_virtual_and_orders_discrete_first():
    raw = """[
        {"Name": "Intel(R) UHD Graphics", "AdapterCompatibility": "Intel Corporation",
         "AdapterRAM": 2147479552, "PNPDeviceID": "PCI-INTEL"},
        {"Name": "iDisplay (Microsoft Corporation - WDDM v1.1)",
         "AdapterCompatibility": "SHAPE Services, AG", "AdapterRAM": 41943040,
         "PNPDeviceID": "PCI-VIRTUAL"},
        {"Name": "NVIDIA GeForce RTX 4050 Laptop GPU",
         "AdapterCompatibility": "NVIDIA", "AdapterRAM": 4293918720,
         "PNPDeviceID": "PCI-NVIDIA"}
    ]"""
    adapters = _parse_powershell_adapters(raw)
    assert [adapter.name for adapter in adapters] == [
        "NVIDIA GeForce RTX 4050 Laptop GPU",
        "Intel(R) UHD Graphics",
    ]
    assert [adapter.preference for adapter in adapters] == [2, 1]
    assert all(adapter.device for adapter in adapters)


def test_effects_toggle_reenables_from_false():
    app = Game.__new__(Game)
    app.settings_menu_index = 3
    app.settings_notice = ""
    app.video = Mock(effects=False)

    app._handle_settings_menu(pygame.K_RETURN)

    app.video.set_effects.assert_called_once_with(True)
    assert "включены" in app.settings_notice


def test_gpu_preference_mapping():
    assert _adapter_preference("NVIDIA GeForce RTX 4050 Laptop GPU") == 2
    assert _adapter_preference("Intel(R) UHD Graphics") == 1
    assert _adapter_preference("AMD Radeon(TM) Graphics") == 1
    assert _adapter_preference("AMD Radeon RX 7600") == 2


def test_video_config_roundtrip(tmp_path):
    path = tmp_path / "video_settings.json"
    manager = VideoManager(config_path=path)
    manager.requested_mode = "cpu"
    manager.selected_key = "GPU\\TEST"
    manager.selected_preference = 1
    manager.effects = False
    manager.save()

    loaded = VideoManager(config_path=path)
    assert loaded.requested_mode == "cpu"
    assert loaded.selected_key == "GPU\\TEST"
    assert loaded.selected_preference == 1
    assert loaded.effects is False


def test_select_adapter_saves_choice_and_applies_preference(tmp_path, monkeypatch):
    path = tmp_path / "video_settings.json"
    adapters = [
        VideoAdapter(name="Auto", key="auto"),
        VideoAdapter(
            name="NVIDIA GeForce RTX 4050 Laptop GPU",
            key="GPU\\NVIDIA",
            preference=2,
            device=True,
        ),
    ]
    manager = VideoManager(config_path=path)
    monkeypatch.setattr(manager, "get_adapters", lambda: adapters)
    apply = Mock(return_value=(True, "ok"))
    monkeypatch.setattr(graphics_backend, "_set_windows_gpu_preference", apply)

    adapter = manager.select_adapter(1)

    assert adapter.key == "GPU\\NVIDIA"
    assert manager.selected_preference == 2
    apply.assert_called_once_with(2)
    assert "перезапустить" in manager.notice
    loaded = VideoManager(config_path=path)
    assert loaded.selected_key == "GPU\\NVIDIA"


def test_headless_start_falls_back_to_cpu(tmp_path):
    manager = VideoManager(config_path=tmp_path / "video_settings.json")
    manager.start()
    try:
        assert manager.mode == "cpu"
        assert manager.surface is not None
    finally:
        manager.close()
