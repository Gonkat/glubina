# -*- mode: python ; coding: utf-8 -*-
#
# Сборка «ГЛУБИНЫ» в раскладке как у Unity-игр:
#   dist/ГЛУБИНА/
#       ГЛУБИНА.exe          <- только загрузчик + Python-байткод
#       ГЛУБИНА_Data/        <- ассеты, спрайты, звуки, библиотеки
#
# Ассеты лежат отдельными файлами в ГЛУБИНА_Data/assets, а не внутри .exe:
# их можно править/заменять, не пересобирая игру.

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = collect_submodules("netplay")


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("video_settings.json", "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ГЛУБИНА",
    # Папка с данными рядом с exe (аналог <Игра>_Data у Unity).
    contents_directory="ГЛУБИНА_Data",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ГЛУБИНА",
)
