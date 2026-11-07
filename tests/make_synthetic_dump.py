"""Build a plausible synthetic 40x24 map dump (DESIGN.md "Map dump format") for renderer tests.

Uses every field: varied terrain by latitude, hills/mountains, all common features, two natural
wonders, a lake (own area, lake=1), rivers in all three edge orientations (W / NW / NE flags),
resources of every class, 4 major starts + 1 city-state, area ids, continent art types.

  python tests/make_synthetic_dump.py [out/synthetic.json] [--seed N]
"""

import json
import math
import os
import random
import sys

W, H = 40, 24

TERRAINS = ["TERRAIN_GRASS", "TERRAIN_PLAINS", "TERRAIN_DESERT", "TERRAIN_TUNDRA", "TERRAIN_SNOW",
            "TERRAIN_COAST", "TERRAIN_OCEAN", "TERRAIN_MOUNTAIN", "TERRAIN_HILL"]
FEATURES = ["FEATURE_ICE", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_OASIS", "FEATURE_FLOOD_PLAINS",
            "FEATURE_FOREST", "FEATURE_FALLOUT", "FEATURE_CRATER", "FEATURE_FUJI", "FEATURE_MESA",
            "FEATURE_REEF", "FEATURE_VOLCANO", "FEATURE_GIBRALTAR", "FEATURE_GEYSER",
            "FEATURE_FOUNTAIN_YOUTH", "FEATURE_POTOSI", "FEATURE_EL_DORADO", "FEATURE_ATOLL"]
RESOURCES = ["RESOURCE_IRON", "RESOURCE_HORSE", "RESOURCE_COAL", "RESOURCE_OIL", "RESOURCE_ALUMINUM",
             "RESOURCE_URANIUM", "RESOURCE_WHEAT", "RESOURCE_COW", "RESOURCE_SHEEP", "RESOURCE_DEER",
             "RESOURCE_BANANA", "RESOURCE_FISH", "RESOURCE_STONE", "RESOURCE_WHALE", "RESOURCE_PEARLS",
             "RESOURCE_GOLD", "RESOURCE_SILVER", "RESOURCE_GEMS", "RESOURCE_MARBLE", "RESOURCE_IVORY",
             "RESOURCE_FUR", "RESOURCE_DYE", "RESOURCE_SPICES", "RESOURCE_SILK", "RESOURCE_WINE",
             "RESOURCE_BISON"]
T = {n: i for i, n in enumerate(TERRAINS)}
F = {n: i for i, n in enumerate(FEATURES)}
R = {n: i for i, n in enumerate(RESOURCES)}
MOUNTAIN, HILLS, LAND, OCEAN = 0, 1, 2, 3
# FlowDirectionTypes: NORTH 0, NORTHEAST 1, SOUTHEAST 2, SOUTH 3, SOUTHWEST 4, NORTHWEST 5


def neighbors(x, y):
    """odd-r (odd rows shifted east), y up. Returns dict dir -> (x, y) with x wrapped."""
    if y & 1:
        d = {"E": (x + 1, y), "W": (x - 1, y), "NE": (x + 1, y + 1), "NW": (x, y + 1),
             "SE": (x + 1, y - 1), "SW": (x, y - 1)}
    else:
        d = {"E": (x + 1, y), "W": (x - 1, y), "NE": (x, y + 1), "NW": (x - 1, y + 1),
             "SE": (x, y - 1), "SW": (x - 1, y - 1)}
    return {k: (xx % W, yy) for k, (xx, yy) in d.items() if 0 <= yy < H}


def build(seed=1234):
    rnd = random.Random(seed)
    n = W * H
    idx = lambda x, y: y * W + x
    plot = [OCEAN] * n
    terrain = [T["TERRAIN_OCEAN"]] * n
    feature = [-1] * n
    resource = [-1] * n
    qty = [0] * n
    rw, rnw, rne = [-1] * n, [-1] * n, [-1] * n
    lake = [0] * n

    # --- landmasses: a big continent (x 4..25) and an island (x 30..37) ---------------------
    def blob(cx, cy, rx, ry, x, y):
        dx = min(abs(x - cx), W - abs(x - cx)) / rx
        dy = (y - cy) / ry
        return dx * dx + dy * dy
    for y in range(H):
        for x in range(W):
            v = min(blob(14.5, 11.5, 11.0, 9.5, x, y), blob(33.5, 13.0, 4.0, 5.0, x, y))
            v += rnd.uniform(-0.18, 0.18)
            if v < 1.0:
                plot[idx(x, y)] = LAND

    # --- latitude-based terrain ---------------------------------------------------------------
    for y in range(H):
        lat = abs(y - (H - 1) / 2) / ((H - 1) / 2)  # 0 equator .. 1 pole
        for x in range(W):
            i = idx(x, y)
            if plot[i] == OCEAN:
                continue
            r = rnd.random()
            if lat > 0.82:
                t = "TERRAIN_SNOW"
            elif lat > 0.62:
                t = "TERRAIN_TUNDRA" if r < 0.7 else "TERRAIN_PLAINS"
            elif lat < 0.18 and 9 <= x <= 13:
                t = "TERRAIN_DESERT"
            elif lat < 0.3:
                t = "TERRAIN_GRASS" if r < 0.6 else "TERRAIN_PLAINS"
            else:
                t = "TERRAIN_PLAINS" if r < 0.5 else "TERRAIN_GRASS"
            terrain[i] = T[t]

    # --- relief: a mountain ridge + scattered hills -----------------------------------------
    for y in range(6, 17):
        x = 18 + (1 if y % 3 == 0 else 0)
        i = idx(x, y)
        if plot[i] != OCEAN:
            plot[i] = MOUNTAIN if y % 4 else HILLS
    for i in range(n):
        if plot[i] == LAND and rnd.random() < 0.14:
            plot[i] = HILLS

    # --- lake inside the continent (2-3 plots) ----------------------------------------------
    for (x, y) in ((8, 14), (9, 14), (8, 15)):
        i = idx(x, y)
        plot[i] = OCEAN
        terrain[i] = T["TERRAIN_COAST"]
        lake[i] = 1

    # --- coast: ocean next to land -----------------------------------------------------------
    for y in range(H):
        for x in range(W):
            i = idx(x, y)
            if plot[i] == OCEAN and not lake[i]:
                if any(plot[idx(*p)] != OCEAN for p in neighbors(x, y).values()):
                    terrain[i] = T["TERRAIN_COAST"]

    # --- rivers ----------------------------------------------------------------------------
    def is_land(x, y):
        return 0 <= y < H and plot[idx(x % W, y)] != OCEAN

    # (a) south-flowing zigzag along E edges + SW edges of the east neighbour
    x, y = 11, 18
    for _ in range(4):
        e = neighbors(x, y)["E"]
        if is_land(x, y) and is_land(*e):
            rw[idx(x, y)] = 3          # river on E edge, flowing south
            rne[idx(*e)] = 2           # river on E-neighbour's SW edge, flowing south-east
        x, y = neighbors(x, y)["SE"]
    # (b) south-flowing along E edges + SE edges, stepping south-west
    x, y = 6, 10
    for _ in range(3):
        if is_land(x, y):
            rw[idx(x, y)] = 3
            rnw[idx(x, y)] = 4         # river on SE edge, flowing south-west
        x, y = neighbors(x, y)["SW"]
    # (c) east-west river along the bottom of a row (SE + SW edges)
    for x in range(20, 24):
        if is_land(x, 9) and is_land(x, 8):
            rnw[idx(x, 9)] = 1
            rne[idx(x, 9)] = 5

    # --- features ---------------------------------------------------------------------------
    for y in range(H):
        lat = abs(y - (H - 1) / 2) / ((H - 1) / 2)
        for x in range(W):
            i = idx(x, y)
            tn = TERRAINS[terrain[i]]
            r = rnd.random()
            if plot[i] == OCEAN:
                if lat > 0.9 and not lake[i] and r < 0.7:
                    feature[i] = F["FEATURE_ICE"]
                continue
            if plot[i] == MOUNTAIN:
                continue
            if tn in ("TERRAIN_GRASS", "TERRAIN_PLAINS") and lat < 0.25 and r < 0.35:
                feature[i] = F["FEATURE_JUNGLE"]
            elif tn in ("TERRAIN_GRASS", "TERRAIN_PLAINS", "TERRAIN_TUNDRA") and r < 0.25:
                feature[i] = F["FEATURE_FOREST"]
            elif tn == "TERRAIN_GRASS" and plot[i] == LAND and r < 0.32:
                feature[i] = F["FEATURE_MARSH"]
    # desert specials
    for (x, y) in ((10, 11), (11, 12)):
        i = idx(x, y)
        plot[i], terrain[i], feature[i] = LAND, T["TERRAIN_DESERT"], F["FEATURE_FLOOD_PLAINS"]
    i = idx(12, 10)
    plot[i], terrain[i], feature[i] = LAND, T["TERRAIN_DESERT"], F["FEATURE_OASIS"]
    i = idx(27, 6)
    plot[i], terrain[i], feature[i] = OCEAN, T["TERRAIN_COAST"], F["FEATURE_ATOLL"]
    i = idx(16, 17)
    if plot[i] != OCEAN:
        feature[i] = F["FEATURE_FALLOUT"]
    # natural wonders
    i = idx(18, 13)
    plot[i], feature[i] = MOUNTAIN, F["FEATURE_FUJI"]
    i = idx(34, 15)
    plot[i], terrain[i], feature[i] = LAND, T["TERRAIN_PLAINS"], F["FEATURE_CRATER"]

    # --- resources --------------------------------------------------------------------------
    land_idx = [i for i in range(n) if plot[i] != OCEAN and feature[i] not in (F["FEATURE_FUJI"], F["FEATURE_CRATER"])]
    rnd.shuffle(land_idx)
    land_res = [r for r in RESOURCES if r not in ("RESOURCE_FISH", "RESOURCE_WHALE", "RESOURCE_PEARLS")]
    for k, i in enumerate(land_idx[:40]):
        rn = land_res[k % len(land_res)]
        resource[i] = R[rn]
        qty[i] = rnd.choice([2, 4, 6]) if rn in ("RESOURCE_IRON", "RESOURCE_HORSE", "RESOURCE_COAL",
                                                "RESOURCE_OIL", "RESOURCE_ALUMINUM", "RESOURCE_URANIUM") else 1
    coast_idx = [i for i in range(n) if TERRAINS[terrain[i]] == "TERRAIN_COAST" and not lake[i] and feature[i] == -1]
    rnd.shuffle(coast_idx)
    for k, i in enumerate(coast_idx[:9]):
        resource[i] = R[("RESOURCE_FISH", "RESOURCE_WHALE", "RESOURCE_PEARLS")[k % 3]]
        qty[i] = 1

    # --- areas (flood fill: land / water separately; lake is its own water area) ------------
    area = [-1] * n
    sizes = {}
    next_id = 1
    for s in range(n):
        if area[s] != -1:
            continue
        water = plot[s] == OCEAN
        stack, area[s], cnt = [s], next_id, 0
        while stack:
            c = stack.pop()
            cnt += 1
            for (nx, ny) in neighbors(c % W, c // W).values():
                j = idx(nx, ny)
                if area[j] == -1 and (plot[j] == OCEAN) == water and lake[j] == lake[s]:
                    area[j] = next_id
                    stack.append(j)
        sizes[next_id] = cnt
        next_id += 1

    # --- small enclosed water bodies are lakes (as the engine would classify them) ----------
    for a, cnt in sizes.items():
        members = [i for i in range(n) if area[i] == a]
        if plot[members[0]] == OCEAN and cnt < 10:
            for i in members:
                lake[i] = 1
                terrain[i] = T["TERRAIN_COAST"]
                if feature[i] == F["FEATURE_ATOLL"]:
                    feature[i] = -1

    # --- continent art: by landmass, biggest = 1, next = 2, ...; water 0 -------------------
    land_areas = sorted({area[i] for i in range(n) if plot[i] != OCEAN}, key=lambda a: -sizes[a])
    art = {a: (k % 4) + 1 for k, a in enumerate(land_areas)}
    continent = [art.get(area[i], 0) if plot[i] != OCEAN else 0 for i in range(n)]

    # --- start plots ---------------------------------------------------------------------
    starts = []
    wanted = [(0, "CIVILIZATION_ROME", False, (8, 7)), (1, "CIVILIZATION_ENGLAND", False, (15, 16)),
              (2, "CIVILIZATION_AZTEC", False, (21, 8)), (3, "CIVILIZATION_JAPAN", False, (33, 12)),
              (22, "MINOR_CIV_GENEVA", True, (12, 13))]
    for player, civ, minor, (x, y) in wanted:
        i = idx(x, y)
        plot[i] = LAND if plot[i] in (OCEAN, MOUNTAIN) else plot[i]
        if TERRAINS[terrain[i]] in ("TERRAIN_COAST", "TERRAIN_OCEAN"):
            terrain[i] = T["TERRAIN_GRASS"]
        if feature[i] != -1 and FEATURES[feature[i]] not in ("FEATURE_FOREST", "FEATURE_JUNGLE"):
            feature[i] = -1
        starts.append({"player": player, "x": x, "y": y, "civ": civ, "minor": minor})

    return {
        "script": "Synthetic.lua", "seed": seed, "world_size": "WORLDSIZE_DUEL",
        "width": W, "height": H, "wrap_x": True, "wrap_y": False,
        "terrain_types": TERRAINS, "feature_types": FEATURES, "resource_types": RESOURCES,
        "plot_type": plot, "terrain": terrain, "feature": feature, "resource": resource,
        "resource_qty": qty, "river_w": rw, "river_nw": rnw, "river_ne": rne,
        "area": area, "lake": lake, "continent": continent, "start_plots": starts,
        "log": "synthetic dump generated by tests/make_synthetic_dump.py\n",
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    seed = 1234
    if "--seed" in argv:
        k = argv.index("--seed")
        seed = int(argv[k + 1])
        del argv[k:k + 2]
    here = os.path.dirname(os.path.abspath(__file__))
    out = argv[0] if argv else os.path.join(here, "..", "out", "synthetic.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(build(seed), f)
    print(out)


if __name__ == "__main__":
    main()
