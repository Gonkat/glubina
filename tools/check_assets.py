"""
ПРОВЕРКА АССЕТОВ:  python tools/check_assets.py

Сверяет то, что просит код, с тем, что лежит в assets/:

  * спрайты  — ключи из assets/sprite_manifest.json плюс динамические
               ключи (оружие, артефакты, персонажи, дропы);
  * звуки    — имена из soundbank.play("...") и поля "sound" в
               weapon_data.py против файлов assets/sounds/.

Код возврата 1, если чего-то не хватает: удобно гонять перед сборкой.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import spritebank                                    # noqa: E402
import soundbank                                     # noqa: E402


def sprite_keys():
    keys = set(spritebank.get_bank()._config)
    from artifact_data import ARTIFACTS
    from weapon_data import FIREARMS, MELEE
    keys.update("weapons/" + key for key in list(FIREARMS) + list(MELEE))
    keys.update("artifacts/" + key for key in ARTIFACTS)
    keys.update(("player", "enemy", "runner", "tank", "bomber", "stalker",
                 "spitter", "brute", "boss/warden", "boss/reaper",
                 "boss/overlord"))
    keys.update(("coin", "ammo", "grenade", "medkit", "artifact"))
    return keys


def sound_names():
    names = set()
    pattern = re.compile(
        r'soundbank\.(?:play|play_loop|stop_loop)\(\s*[\'"]([a-z0-9_]+)[\'"]')
    for folder, _dirs, files in os.walk(ROOT):
        if any(part in folder for part in ("dist", "build", ".git",
                                           "__pycache__", "docs")):
            continue
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(folder, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                continue
            names.update(pattern.findall(text))
    try:
        from weapon_data import FIREARMS, MELEE
    except ImportError:
        return names
    for spec in list(FIREARMS.values()) + list(MELEE.values()):
        sound = spec.get("sound")
        if isinstance(sound, str) and sound:
            names.add(sound)
    return names


def main():
    bank = spritebank.get_bank()
    missing_sprites = []
    for key in sorted(sprite_keys()):
        path = bank._path(key)
        if path is None or not os.path.isfile(path):
            missing_sprites.append((key, bank._path(key)))

    missing_sounds = []
    for name in sorted(sound_names()):
        if name not in soundbank.get_bank().sounds:
            found = any(os.path.isfile(os.path.join(
                soundbank.SOUNDS_DIR, name + ext))
                for ext in soundbank.SOUND_EXTS)
            if not found:
                missing_sounds.append(name)

    print(f"спрайты: {len(sprite_keys())} ключей, "
          f"нет файлов: {len(missing_sprites)}")
    for key, path in missing_sprites:
        print("  -", key, "->", path or "недопустимый путь")
    print(f"звуки: {len(sound_names())} имён, нет файлов: {len(missing_sounds)}")
    for name in missing_sounds:
        print("  -", name)
    if missing_sprites or missing_sounds:
        print("\nСоздать недостающее:  python assets_gen.py")
        return 1
    print("\nВсе ассеты на месте.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
