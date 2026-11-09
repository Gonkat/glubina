# Состояние ассетов

Исходные PNG сохранены без изменений.

Отсутствующие изображения (будет использована текущая резервная отрисовка):
- `stalker`
- `brute`
- `chest/common`
- `chest/rare`
- `chest/legendary`
- `chest/opened`
- `world/floor`
- `world/wall`
- `projectile/bullet`
- `projectile/grenade`
- `projectile/explosion`
- `effects/muzzle_flash`
- `effects/hammer_wave`
- `weapons/knife`
- `weapons/machete`
- `weapons/katana`
- `weapons/hammer`
- `weapons/shield`
- `weapons/bow`
- `weapons/laser`

Для замены положите PNG по пути из `sprite_manifest.json` или укажите свой путь. F5 обновляет кэш спрайтов и оружие.
`python assets_gen.py` больше не перезаписывает существующие файлы. Принудительная перезапись: `python assets_gen.py --overwrite`.

`weapons/shovel` содержит спрайт метлы и не относится к отсутствующим файлам.
