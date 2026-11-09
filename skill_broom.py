"""Independent dust-and-handle branch for the broom skill tree."""


def inject_broom_branch(skill_trees):
    branches = skill_trees["shovel"]["branches"]
    dust_branch = {
        "key": "dust",
        "name": "Пыльный след",
        "independent": True,
        "nodes": (
            {"id": "shovel_d1", "name": "Пыльный взмах", "tier": 1,
             "cost": 75, "no_main": True,
             "desc": "урон пыли увеличен, замедление усилено",
             "mods": {"dust_damage_add": 0.015, "dust_slow_add": 0.04}},
            {"id": "shovel_d2", "name": "Густой след", "tier": 2,
             "cost": 145,
             "desc": "пыль накапливается до 3 слоёв, каждый наносит урон",
             "mods": {"dust_stack_cap_add": 2}},
            {"id": "shovel_d3", "name": "Едкая пыль", "tier": 3,
             "cost": 250,
             "desc": "урон каждого слоя пыли увеличен на 2% урона удара",
             "mods": {"dust_damage_add": 0.02}},
            {"id": "shovel_d4", "name": "Широкое облако", "tier": 4,
             "cost": 390,
             "desc": "облако пыли задевает врагов в радиусе 40",
             "mods": {"dust_radius_add": 40}},
            {"id": "shovel_d5", "name": "Длинный черенок", "tier": 5,
             "cost": 560,
             "desc": "длина черенка и дальность удара увеличены на 20%",
             "apply": {"reach_mul": 1.2}},
        ),
    }
    skill_trees["shovel"]["branches"] = (*branches, dust_branch)
