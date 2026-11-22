# Состояние ассетов

Все изображения и звуки, которые использует игра, лежат файлами в `assets/`.
Ничего не рисуется «только кодом»: если файла нет, включается прежняя
процедурная отрисовка, но по умолчанию всегда грузится файл.

Проверить полноту: `python tools/check_assets.py`
(код возврата 1 и список, если чего-то не хватает).

Создать/дозаполнить: `python assets_gen.py`
(перезаписать всё: `python assets_gen.py --overwrite`).

## Спрайты (`assets/sprites/`, ключи из `sprite_manifest.json`)

| Группа | Файлы |
|---|---|
| Герой и враги | `player.png`, `enemy.png`, `runner.png`, `tank.png`, `bomber.png`, `stalker.png`, `spitter.png`, `brute.png` |
| Боссы | `boss/warden.png`, `boss/reaper.png`, `boss/overlord.png` |
| Материалы боссов | `boss/material/bone.png`, `hide.png`, `core.png`, `shadow.png` |
| Дропы | `coin.png`, `ammo.png`, `grenade.png`, `medkit.png`, `artifact.png` |
| Сундуки | `chest/common.png`, `chest/rare.png`, `chest/legendary.png`, `chest/opened.png` |
| Мир | `world/floor.png`, `world/wall.png` |
| Снаряды | `projectile/bullet.png`, `projectile/grenade.png`, `projectile/explosion.png` |
| Эффекты | `effects/muzzle_flash.png`, `effects/hammer_wave.png` |
| Объекты спуска | `object/altar.png`, `object/lift.png`, `object/beacon.png` |
| Оружие в руке и в магазине | `weapons/pistol.png`, `shotgun.png`, `sniper.png`, `cannon.png`, `disc.png`, `arc.png`, `cutter.png`, `knife.png`, `machete.png`, `katana.png`, `hammer.png`, `shovel.png`, `shield.png` |
| Артефакты (витрина) | `artifacts/amulet.png`, `armor.png`, `boots.png`, `dash.png`, `devourer.png`, `fang.png`, `heart.png`, `nova.png`, `shield.png`, `thunder.png` |

Любой ключ можно перенаправить на свой файл в `sprite_manifest.json`
(`file: custom/my_player.png`), либо просто перерисовать существующий PNG.
F5 в игре перечитывает банк спрайтов.

## Звуки (`assets/sounds/`)

35 имён из кода, у каждого есть WAV (у выстрелов ещё и MP3 — он
приоритетнее). Замена — положить файл с тем же именем в `assets/sounds/`;
`mp3 > ogg > wav`. Список имён — в `assets/ASSETS_README.md`.

## Ориентация и размеры

- Персонажи и боссы — смотрят **вправо**, квадратный PNG, вписывается
  в кадр и масштабируется по радиусу в игре. Рисуйте с запасом по краям.
- Оружие — смотрит **вправо**, центр картинки = центр героя, 50–80 px
  по ширине (для магазина масштабируется автоматически).
- `world/floor.png` и `world/wall.png` — квадрат, растягивается на
  плитку 32×32 без сохранения пропорций, рисуйте сразу 32×32 (или 64×64).
- `object/*` — ставятся «низом» на точку объекта.
- Эффекты — квадрат, растягиваются на текущий радиус/диаметр.
