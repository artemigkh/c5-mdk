"""metrics -- numeric "what does this map look like" metrics from a c5maps dump JSON.

Importable:
    from metrics import compute_metrics, compare
    m = compute_metrics(json.load(open("out/x/x_standard_1.json")))

CLI:
    python host/metrics.py DUMP.json [--json]
    python host/metrics.py compare DUMP.json [--baseline docs/metrics-baselines.json] [--archetype Continents]

`compare` flags every metric outside the pooled p5-p95 of the reference archetypes (same world size),
and optionally outside one archetype's p5-p95.  It is advisory: exit code is always 0.

Geometry (DESIGN.md / engine-api.md section 3): plot index i = y*W + x, y=0 is the south row, odd rows
shifted half a hex east (odd-r).  Distances are true hex distances with X (and Y) wrap, i.e. the
minimum over the wrapped copies; the engine's `plotDistance` agrees except for its documented seam
quirk at very large distances.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter, deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_BASELINE = os.path.join(ROOT, "docs", "metrics-baselines.json")

PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN = 0, 1, 2, 3
STRATEGICS = ("IRON", "HORSE", "COAL", "OIL", "ALUMINUM", "URANIUM")
FRESH_WATER_FEATURES = {"FEATURE_OASIS", "FEATURE_FOUNTAIN_YOUTH", "FEATURE_LAKE_VICTORIA"}
COMMON_FEATURES = {"FEATURE_ICE", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_OASIS", "FEATURE_FLOOD_PLAINS",
                   "FEATURE_FOREST", "FEATURE_FALLOUT", "FEATURE_ATOLL"}
NON_MAP_RESOURCES = {"RESOURCE_ARTIFACTS", "RESOURCE_HIDDEN_ARTIFACTS"}
# name-based fallback when the dump has no resource_class (e.g. the synthetic test dump)
_FALLBACK_STRATEGIC = {"IRON", "HORSE", "COAL", "ALUMINUM", "OIL", "URANIUM", "PAPER"}
_FALLBACK_BONUS = {"WHEAT", "COW", "SHEEP", "DEER", "BANANA", "BANANAS", "FISH", "STONE", "BISON",
                   "MAIZE", "RICE", "FIGS"}

# Neighbour deltas in DirectionTypes order NE, E, SE, SW, W, NW (engine-api.md 3.2)
DIRS_EVEN = ((0, 1), (1, 0), (0, -1), (-1, -1), (-1, 0), (-1, 1))
DIRS_ODD = ((1, 1), (1, 0), (1, -1), (0, -1), (-1, 0), (0, 1))
NE, E, SE, SW, W_, NW = range(6)

# ------------------------------------------------------------------------------------------------
# Metric catalogue: key -> (group, label, unit, one-line meaning).  Drives CLI output, compare and docs.
# ------------------------------------------------------------------------------------------------
METRICS = [
    # land / water
    ("land_pct", "land", "Land % of all plots", "%"),
    ("water_pct", "land", "Water % of all plots", "%"),
    ("coast_pct_of_sea", "land", "Coast % of non-lake water", "%"),
    ("ocean_pct_of_sea", "land", "Deep ocean % of non-lake water", "%"),
    ("lake_tiles", "land", "Lake tiles", "n"),
    ("lake_count", "land", "Lakes (connected lake bodies)", "n"),
    ("lake_tiles_per100", "land", "Lake tiles per 100 land", "/100"),
    ("land_per_civ", "land", "Land tiles per major civ", "n"),
    ("coastal_land_pct", "land", "Land tiles adjacent to sea (non-lake water)", "%"),
    # terrain (% of land)
    ("grass_pct", "terrain", "Grassland % of land", "%"),
    ("plains_pct", "terrain", "Plains % of land", "%"),
    ("desert_pct", "terrain", "Desert % of land", "%"),
    ("tundra_pct", "terrain", "Tundra % of land", "%"),
    ("snow_pct", "terrain", "Snow % of land", "%"),
    ("hills_pct", "terrain", "Hills % of land", "%"),
    ("mountain_pct", "terrain", "Mountains % of land", "%"),
    ("flat_pct", "terrain", "Flat land % of land", "%"),
    # features
    ("forest_pct", "features", "Forest % of land", "%"),
    ("jungle_pct", "features", "Jungle % of land", "%"),
    ("marsh_pct", "features", "Marsh % of land", "%"),
    ("floodplain_pct", "features", "Flood plains % of land", "%"),
    ("oasis_count", "features", "Oases", "n"),
    ("ice_pct_of_water", "features", "Ice % of all water", "%"),
    ("atoll_count", "features", "Atolls", "n"),
    ("natural_wonders", "features", "Natural wonders (distinct)", "n"),
    ("featureless_flat_pct", "features", "Flat land with no feature % of land", "%"),
    # rivers
    ("river_edges_per100", "rivers", "River edges per 100 land", "/100"),
    ("river_land_pct", "rivers", "Land tiles on a river %", "%"),
    ("fresh_water_pct", "rivers", "Land tiles with fresh water %", "%"),
    # resources
    ("strategic_per100", "resources", "Strategic resource tiles per 100 land", "/100"),
    ("luxury_per100", "resources", "Luxury resource tiles per 100 land", "/100"),
    ("bonus_per100", "resources", "Bonus resource tiles per 100 land", "/100"),
    ("strategic_tiles", "resources", "Strategic resource tiles", "n"),
    ("luxury_tiles", "resources", "Luxury resource tiles", "n"),
    ("bonus_tiles", "resources", "Bonus resource tiles", "n"),
    ("luxury_types", "resources", "Distinct luxury types on map", "n"),
    ("luxury_top_share", "resources", "Most common luxury's share of luxury tiles", "%"),
] + [(f"{s.lower()}_qty", "resources", f"{s.title()} total quantity", "n") for s in STRATEGICS] + [
    (f"{s.lower()}_qty_per_civ", "resources", f"{s.title()} quantity per major civ", "n") for s in STRATEGICS] + [
    # capitals
    ("majors", "capitals", "Major civ start plots", "n"),
    ("city_states", "capitals", "City-state start plots", "n"),
    ("cap_nn_mean", "capitals", "Capital nearest-capital distance, mean", "hex"),
    ("cap_nn_min", "capitals", "Capital nearest-capital distance, min", "hex"),
    ("cap_nn_max", "capitals", "Capital nearest-capital distance, max", "hex"),
    ("cap_pair_mean", "capitals", "Capital pairwise distance, mean", "hex"),
    ("cap_cs_mean", "capitals", "Capital to nearest city-state, mean", "hex"),
    ("cap_cs_min", "capitals", "Capital to nearest city-state, min", "hex"),
    ("cap_coastal_pct", "capitals", "Capitals coastal %", "%"),
    ("cap_river_pct", "capitals", "Capitals on a river %", "%"),
    ("cap_fresh_pct", "capitals", "Capitals with fresh water %", "%"),
    ("cap_hills_pct", "capitals", "Capitals on hills %", "%"),
    ("cap_mountain_adj_pct", "capitals", "Capitals adjacent to a mountain %", "%"),
    ("cap_cold_pct", "capitals", "Capitals on tundra or snow %", "%"),
    ("cap_desert_pct", "capitals", "Capitals on desert %", "%"),
    ("cap_land_r3_mean", "capitals", "Land tiles within 3 of capital, mean (of 37)", "n"),
    ("cap_land_r3_min", "capitals", "Land tiles within 3 of capital, min (of 37)", "n"),
    ("cap_lux_r3_mean", "capitals", "Luxury tiles within 3 of capital, mean", "n"),
    ("cap_strat_r3_mean", "capitals", "Strategic tiles within 3 of capital, mean", "n"),
    ("cap_bonus_r3_mean", "capitals", "Bonus tiles within 3 of capital, mean", "n"),
    ("caps_on_largest", "capitals", "Major civs on the largest landmass", "n"),
    ("cap_landmasses", "capitals", "Landmasses holding at least one capital", "n"),
    ("cap_isolated", "capitals", "Capitals alone on their landmass", "n"),
    # city-states
    ("cs_nn_mean", "city-states", "City-state nearest-CS distance, mean", "hex"),
    ("cs_nn_min", "city-states", "City-state nearest-CS distance, min", "hex"),
    ("cs_cap_mean", "city-states", "City-state to nearest capital, mean", "hex"),
    ("cs_cap_min", "city-states", "City-state to nearest capital, min", "hex"),
    ("cs_coastal_pct", "city-states", "City-states coastal %", "%"),
    # landmasses
    ("landmasses_30", "landmasses", "Landmasses >= 30 tiles", "n"),
    ("largest_landmass_pct", "landmasses", "Largest landmass % of land", "%"),
    ("second_landmass_pct", "landmasses", "Second landmass % of land", "%"),
    ("islands_1_5", "landmasses", "Islands of 1-5 tiles", "n"),
    # sanity / climate
    ("polar_land_pct", "sanity", "Land % in the 2 outermost rows (N+S)", "%"),
    ("polar_ice_pct", "sanity", "Ice % of water in the 2 outermost rows", "%"),
    ("cold_lat_mean", "sanity", "Mean latitude of tundra+snow (0 equator..1 pole)", "lat"),
    ("desert_lat_mean", "sanity", "Mean latitude of desert", "lat"),
    ("jungle_lat_mean", "sanity", "Mean latitude of jungle", "lat"),
    ("desert_floodplain_pct", "sanity", "Desert tiles with flood plains %", "%"),
    ("desert_river_pct", "sanity", "Desert tiles on a river %", "%"),
    ("snow_mountain_pct", "sanity", "Snow + mountain % of land (unworkable-ish)", "%"),
    ("bad_starts", "sanity", "Start plots on water or mountain", "n"),
]
METRIC_INFO = {k: {"group": g, "label": lab, "unit": u} for k, g, lab, u in METRICS}
METRIC_KEYS = [k for k, *_ in METRICS]


# ------------------------------------------------------------------------------------------------
# Geometry
# ------------------------------------------------------------------------------------------------
def hex_distance(x1, y1, x2, y2, W=None, H=None, wrap_x=False, wrap_y=False):
    """True hex distance on the odd-r grid (y up, odd rows shifted east), minimised over X/Y wrap."""
    best = None
    xs = (x2 - W, x2, x2 + W) if (wrap_x and W) else (x2,)
    ys = (y2 - H, y2, y2 + H) if (wrap_y and H) else (y2,)
    q1 = x1 - (y1 // 2)
    for yy in ys:
        for xx in xs:
            dq = (xx - (yy // 2)) - q1
            dr = yy - y1
            d = (abs(dq) + abs(dr) + abs(dq + dr)) // 2
            if best is None or d < best:
                best = d
    return best


class Grid:
    def __init__(self, W, H, wrap_x, wrap_y):
        self.W, self.H, self.wrap_x, self.wrap_y = W, H, wrap_x, wrap_y
        n = W * H
        self.nbr = [None] * n      # list of 6 neighbour indices (or -1), DirectionTypes order
        for y in range(H):
            deltas = DIRS_ODD if y & 1 else DIRS_EVEN
            for x in range(W):
                row = []
                for dx, dy in deltas:
                    nx, ny = x + dx, y + dy
                    if wrap_x:
                        nx %= W
                    if wrap_y:
                        ny %= H
                    row.append(ny * W + nx if (0 <= nx < W and 0 <= ny < H) else -1)
                self.nbr[y * W + x] = row

    def dist(self, i, j):
        W = self.W
        return hex_distance(i % W, i // W, j % W, j // W, W, self.H, self.wrap_x, self.wrap_y)

    def within(self, i, r):
        """Plot indices within hex distance r of i (including i), via BFS over neighbours."""
        seen = {i}
        frontier = [i]
        for _ in range(r):
            nxt = []
            for c in frontier:
                for j in self.nbr[c]:
                    if j >= 0 and j not in seen:
                        seen.add(j)
                        nxt.append(j)
            frontier = nxt
        return seen

    def components(self, member):
        """Connected components (6-neighbour, wrap-aware) of plots where member[i] is true.
        Returns (comp_id per plot or -1, list of sizes)."""
        n = len(member)
        comp = [-1] * n
        sizes = []
        for s in range(n):
            if not member[s] or comp[s] != -1:
                continue
            cid = len(sizes)
            comp[s] = cid
            q = deque([s])
            cnt = 0
            while q:
                c = q.popleft()
                cnt += 1
                for j in self.nbr[c]:
                    if j >= 0 and member[j] and comp[j] == -1:
                        comp[j] = cid
                        q.append(j)
            sizes.append(cnt)
        return comp, sizes


# ------------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------------
def _pct(a, b):
    return 100.0 * a / b if b else 0.0


def _mean(v):
    return sum(v) / len(v) if v else None


def _name(lst, idx):
    return lst[idx] if idx is not None and 0 <= idx < len(lst) else None


def resource_kind(name, cls=None):
    """'strategic' | 'luxury' | 'bonus' | 'other' from the dump's resource_class (or the name)."""
    if name in NON_MAP_RESOURCES:
        return "other"
    if cls:
        return {"RESOURCECLASS_LUXURY": "luxury", "RESOURCECLASS_BONUS": "bonus",
                "RESOURCECLASS_RUSH": "strategic", "RESOURCECLASS_MODERN": "strategic"}.get(cls, "other")
    short = name.replace("RESOURCE_", "")
    if short in _FALLBACK_STRATEGIC:
        return "strategic"
    if short in _FALLBACK_BONUS:
        return "bonus"
    return "luxury"


def river_edges_of(d, grid, i):
    """Directions (NE..NW) of plot i's six edges that carry a river flag."""
    out = []
    nb = grid.nbr[i]
    if d["river_w"][i] != -1:
        out.append(E)
    if d["river_nw"][i] != -1:
        out.append(SE)
    if d["river_ne"][i] != -1:
        out.append(SW)
    j = nb[W_]
    if j >= 0 and d["river_w"][j] != -1:
        out.append(W_)
    j = nb[NW]
    if j >= 0 and d["river_nw"][j] != -1:
        out.append(NW)
    j = nb[NE]
    if j >= 0 and d["river_ne"][j] != -1:
        out.append(NE)
    return out


# ------------------------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------------------------
def compute_metrics(d):
    """Flat dict of numeric metrics (see METRICS) plus a few descriptive keys (script, size, seed, w, h).
    Metrics that cannot be computed (e.g. no city-states) are None."""
    W, H = int(d["width"]), int(d["height"])
    n = W * H
    wrap_x, wrap_y = bool(d.get("wrap_x")), bool(d.get("wrap_y"))
    grid = Grid(W, H, wrap_x, wrap_y)
    pt = d["plot_type"]
    tn, fn, rn = d["terrain_types"], d.get("feature_types", []), d.get("resource_types", [])
    terr = [_name(tn, t) for t in d["terrain"]]
    feat = [_name(fn, f) if f is not None and f >= 0 else None for f in d.get("feature", [-1] * n)]
    res = d.get("resource", [-1] * n)
    qty = d.get("resource_qty", [0] * n)
    lake = [bool(v) for v in d.get("lake", [0] * n)]
    for k in ("river_w", "river_nw", "river_ne"):
        d.setdefault(k, [-1] * n)
        d[k] = [-1 if v is None else v for v in d[k]]
    rclass = d.get("resource_class") or []
    nw_flags = d.get("feature_natural_wonder")

    is_water = [p == PLOT_OCEAN for p in pt]
    is_land = [not w for w in is_water]
    sea = [is_water[i] and not lake[i] for i in range(n)]
    land_idx = [i for i in range(n) if is_land[i]]
    L = len(land_idx)
    n_water = n - L
    n_sea = sum(sea)
    m = {"script": d.get("script"), "world_size": d.get("world_size"), "seed": d.get("seed"),
         "width": W, "height": H}

    # ---- land / water -------------------------------------------------------------------------
    m["land_pct"] = _pct(L, n)
    m["water_pct"] = _pct(n_water, n)
    m["coast_pct_of_sea"] = _pct(sum(1 for i in range(n) if sea[i] and terr[i] == "TERRAIN_COAST"), n_sea)
    m["ocean_pct_of_sea"] = _pct(sum(1 for i in range(n) if sea[i] and terr[i] == "TERRAIN_OCEAN"), n_sea)
    lake_member = [is_water[i] and lake[i] for i in range(n)]
    _, lake_sizes = grid.components(lake_member)
    m["lake_tiles"] = sum(lake_sizes)
    m["lake_count"] = len(lake_sizes)
    m["lake_tiles_per100"] = _pct(m["lake_tiles"], L)

    starts = d.get("start_plots") or []
    majors = [s for s in starts if not s.get("minor")]
    minors = [s for s in starts if s.get("minor")]
    n_maj = len(majors)
    m["land_per_civ"] = L / n_maj if n_maj else None
    coastal = [False] * n
    for i in land_idx:
        coastal[i] = any(j >= 0 and sea[j] for j in grid.nbr[i])
    m["coastal_land_pct"] = _pct(sum(coastal), L)

    # ---- terrain ------------------------------------------------------------------------------
    tc = Counter(terr[i] for i in land_idx)
    for key, tname in (("grass", "TERRAIN_GRASS"), ("plains", "TERRAIN_PLAINS"), ("desert", "TERRAIN_DESERT"),
                       ("tundra", "TERRAIN_TUNDRA"), ("snow", "TERRAIN_SNOW")):
        m[key + "_pct"] = _pct(tc.get(tname, 0), L)
    pc = Counter(pt[i] for i in land_idx)
    m["hills_pct"] = _pct(pc.get(PLOT_HILLS, 0), L)
    m["mountain_pct"] = _pct(pc.get(PLOT_MOUNTAIN, 0), L)
    m["flat_pct"] = _pct(pc.get(PLOT_LAND, 0), L)

    # ---- features -----------------------------------------------------------------------------
    fc_land = Counter(feat[i] for i in land_idx if feat[i])
    m["forest_pct"] = _pct(fc_land.get("FEATURE_FOREST", 0), L)
    m["jungle_pct"] = _pct(fc_land.get("FEATURE_JUNGLE", 0), L)
    m["marsh_pct"] = _pct(fc_land.get("FEATURE_MARSH", 0), L)
    m["floodplain_pct"] = _pct(fc_land.get("FEATURE_FLOOD_PLAINS", 0), L)
    m["oasis_count"] = fc_land.get("FEATURE_OASIS", 0)
    m["ice_pct_of_water"] = _pct(sum(1 for i in range(n) if is_water[i] and feat[i] == "FEATURE_ICE"), n_water)
    m["atoll_count"] = sum(1 for f in feat if f == "FEATURE_ATOLL")
    if nw_flags:
        nw_names = {fn[k] for k, v in enumerate(nw_flags) if v}
    else:
        nw_names = {f for f in fn if f not in COMMON_FEATURES}
    m["natural_wonders"] = len({f for f in feat if f in nw_names})
    m["featureless_flat_pct"] = _pct(sum(1 for i in land_idx if pt[i] == PLOT_LAND and not feat[i]), L)

    # ---- rivers / fresh water -----------------------------------------------------------------
    edges = sum(1 for k in ("river_w", "river_nw", "river_ne") for v in d[k] if v != -1)
    m["river_edges_per100"] = _pct(edges, L)
    on_river = [False] * n
    for i in land_idx:
        for dr in river_edges_of(d, grid, i):
            j = grid.nbr[i][dr]
            if j < 0 or is_land[j]:      # engine IsRiver: crossing only between two land plots (or map edge)
                on_river[i] = True
                break
    fresh = [False] * n
    for i in land_idx:
        if on_river[i]:
            fresh[i] = True
            continue
        for j in grid.nbr[i] + [i]:
            if j >= 0 and ((is_water[j] and lake[j]) or feat[j] in FRESH_WATER_FEATURES):
                fresh[i] = True
                break
    m["river_land_pct"] = _pct(sum(on_river), L)
    m["fresh_water_pct"] = _pct(sum(fresh), L)

    # ---- resources ----------------------------------------------------------------------------
    kind = {}
    for r, name in enumerate(rn):
        kind[r] = resource_kind(name, rclass[r] if r < len(rclass) else None)
    kc = Counter()
    lux = Counter()
    sq = Counter()
    res_kind = [None] * n
    for i in range(n):
        r = res[i]
        if r is None or r < 0:
            continue
        k = kind.get(r, "other")
        res_kind[i] = k
        kc[k] += 1
        name = rn[r]
        if k == "luxury":
            lux[name] += 1
        short = name.replace("RESOURCE_", "")
        if short in STRATEGICS:
            sq[short] += qty[i] or 0
    m["strategic_per100"] = _pct(kc["strategic"], L)
    m["luxury_per100"] = _pct(kc["luxury"], L)
    m["bonus_per100"] = _pct(kc["bonus"], L)
    m["strategic_tiles"] = kc["strategic"]
    m["luxury_tiles"] = kc["luxury"]
    m["bonus_tiles"] = kc["bonus"]
    m["luxury_types"] = len(lux)
    m["luxury_top_share"] = _pct(max(lux.values()), kc["luxury"]) if lux else None
    for s in STRATEGICS:
        m[s.lower() + "_qty"] = sq.get(s, 0)
        m[s.lower() + "_qty_per_civ"] = sq.get(s, 0) / n_maj if n_maj else None

    # ---- landmasses ---------------------------------------------------------------------------
    lm, lm_sizes = grid.components(is_land)
    order = sorted(range(len(lm_sizes)), key=lambda c: -lm_sizes[c])
    m["landmasses_30"] = sum(1 for s in lm_sizes if s >= 30)
    m["largest_landmass_pct"] = _pct(lm_sizes[order[0]], L) if order else 0.0
    m["second_landmass_pct"] = _pct(lm_sizes[order[1]], L) if len(order) > 1 else 0.0
    m["islands_1_5"] = sum(1 for s in lm_sizes if 1 <= s <= 5)

    # ---- capitals / city-states ---------------------------------------------------------------
    cap = [s["y"] * W + s["x"] for s in majors]
    cs = [s["y"] * W + s["x"] for s in minors]
    m["majors"] = len(cap)
    m["city_states"] = len(cs)

    def nn(src, dst, same):
        out = []
        for a, i in enumerate(src):
            ds = [grid.dist(i, j) for b, j in enumerate(dst) if not (same and a == b)]
            if ds:
                out.append(min(ds))
        return out

    cap_nn = nn(cap, cap, True)
    m["cap_nn_mean"] = _mean(cap_nn)
    m["cap_nn_min"] = min(cap_nn) if cap_nn else None
    m["cap_nn_max"] = max(cap_nn) if cap_nn else None
    pair = [grid.dist(cap[a], cap[b]) for a in range(len(cap)) for b in range(a + 1, len(cap))]
    m["cap_pair_mean"] = _mean(pair)
    cap_cs = nn(cap, cs, False)
    m["cap_cs_mean"] = _mean(cap_cs)
    m["cap_cs_min"] = min(cap_cs) if cap_cs else None

    def share(idx, pred):
        return _pct(sum(1 for i in idx if pred(i)), len(idx)) if idx else None

    m["cap_coastal_pct"] = share(cap, lambda i: is_land[i] and coastal[i])
    m["cap_river_pct"] = share(cap, lambda i: on_river[i])
    m["cap_fresh_pct"] = share(cap, lambda i: fresh[i])
    m["cap_hills_pct"] = share(cap, lambda i: pt[i] == PLOT_HILLS)
    m["cap_mountain_adj_pct"] = share(cap, lambda i: any(j >= 0 and pt[j] == PLOT_MOUNTAIN for j in grid.nbr[i]))
    m["cap_cold_pct"] = share(cap, lambda i: terr[i] in ("TERRAIN_TUNDRA", "TERRAIN_SNOW"))
    m["cap_desert_pct"] = share(cap, lambda i: terr[i] == "TERRAIN_DESERT")
    r3 = [grid.within(i, 3) for i in cap]
    land_r3 = [sum(1 for j in s if is_land[j]) for s in r3]
    m["cap_land_r3_mean"] = _mean(land_r3)
    m["cap_land_r3_min"] = min(land_r3) if land_r3 else None
    m["cap_lux_r3_mean"] = _mean([sum(1 for j in s if res_kind[j] == "luxury") for s in r3])
    m["cap_strat_r3_mean"] = _mean([sum(1 for j in s if res_kind[j] == "strategic") for s in r3])
    m["cap_bonus_r3_mean"] = _mean([sum(1 for j in s if res_kind[j] == "bonus") for s in r3])
    cap_lm = Counter(lm[i] for i in cap if lm[i] >= 0)
    m["caps_on_largest"] = cap_lm.get(order[0], 0) if order else 0
    m["cap_landmasses"] = len(cap_lm)
    m["cap_isolated"] = sum(1 for v in cap_lm.values() if v == 1) if len(cap) > 1 else 0

    cs_nn = nn(cs, cs, True)
    m["cs_nn_mean"] = _mean(cs_nn)
    m["cs_nn_min"] = min(cs_nn) if cs_nn else None
    cs_cap = nn(cs, cap, False)
    m["cs_cap_mean"] = _mean(cs_cap)
    m["cs_cap_min"] = min(cs_cap) if cs_cap else None
    m["cs_coastal_pct"] = share(cs, lambda i: is_land[i] and coastal[i])

    # ---- sanity / climate ---------------------------------------------------------------------
    polar_rows = [] if wrap_y else [0, 1, H - 2, H - 1]
    polar = [y * W + x for y in sorted(set(r for r in polar_rows if 0 <= r < H)) for x in range(W)]
    m["polar_land_pct"] = _pct(sum(1 for i in polar if is_land[i]), len(polar)) if polar else None
    pw = [i for i in polar if is_water[i]]
    m["polar_ice_pct"] = _pct(sum(1 for i in pw if feat[i] == "FEATURE_ICE"), len(pw)) if pw else None
    half = (H - 1) / 2.0

    def lat(i):
        return abs(i // W - half) / half if half else 0.0

    def mean_lat(pred):
        v = [lat(i) for i in land_idx if pred(i)]
        return _mean(v)

    m["cold_lat_mean"] = mean_lat(lambda i: terr[i] in ("TERRAIN_TUNDRA", "TERRAIN_SNOW"))
    m["desert_lat_mean"] = mean_lat(lambda i: terr[i] == "TERRAIN_DESERT")
    m["jungle_lat_mean"] = mean_lat(lambda i: feat[i] == "FEATURE_JUNGLE")
    deserts = [i for i in land_idx if terr[i] == "TERRAIN_DESERT"]
    m["desert_floodplain_pct"] = share(deserts, lambda i: feat[i] == "FEATURE_FLOOD_PLAINS")
    m["desert_river_pct"] = share(deserts, lambda i: on_river[i])
    m["snow_mountain_pct"] = _pct(sum(1 for i in land_idx if pt[i] == PLOT_MOUNTAIN or terr[i] == "TERRAIN_SNOW"), L)
    m["bad_starts"] = sum(1 for i in cap + cs if pt[i] in (PLOT_OCEAN, PLOT_MOUNTAIN))
    return m


# ------------------------------------------------------------------------------------------------
# Formatting
# ------------------------------------------------------------------------------------------------
def fmt(v, unit=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        if unit == "lat":
            return f"{v:.2f}"
        return f"{v:.1f}" if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def format_metrics(m):
    out = [f"== {m.get('script')}  {m.get('world_size')}  {m.get('width')}x{m.get('height')}  seed={m.get('seed')}"]
    group = None
    for k, g, lab, unit in METRICS:
        if g != group:
            out.append(f"[{g}]")
            group = g
        out.append(f"  {lab:52s} {fmt(m.get(k), unit):>8s}  {unit if unit not in ('n',) else ''}")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------
# Baseline comparison
# ------------------------------------------------------------------------------------------------
SIZE_KEYS = {"WORLDSIZE_DUEL": "duel", "WORLDSIZE_TINY": "tiny", "WORLDSIZE_SMALL": "small",
             "WORLDSIZE_STANDARD": "standard", "WORLDSIZE_LARGE": "large", "WORLDSIZE_HUGE": "huge"}
SIZE_ORDER = ["duel", "tiny", "small", "standard", "large", "huge"]
# size-dependent absolute counts: comparing them across sizes is meaningless
SIZE_DEPENDENT_UNITS = {"n"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace(".lua", ""))


def load_baseline(path=DEFAULT_BASELINE):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    order = b["stat_order"]

    def stats(arr):
        return dict(zip(order, arr)) if arr else None
    return b, stats


def compare(m, baseline, archetype=None):
    """-> dict(size, size_note, rows=[...], verdict, n_out_pooled, n_out_arch, n_far).
    Each row: key, label, value, pooled (p5,p95,median), flag_pooled ('low'/'high'/''), arch(...), flag_arch."""
    b, stats = baseline
    size = SIZE_KEYS.get(m.get("world_size"), None)
    note = ""
    if size not in b["sizes"]:
        avail = list(b["sizes"])
        want = SIZE_ORDER.index(size) if size in SIZE_ORDER else SIZE_ORDER.index("standard")
        size = min(avail, key=lambda s: abs(SIZE_ORDER.index(s) - want))
        note = (f"no baseline for {m.get('world_size')}; using '{size}'. Absolute counts (unit n) are "
                "skipped; densities and shares still compare.")
    sb = b["sizes"][size]
    arch_key = None
    if archetype:
        want = _norm(archetype)
        for k in sb["scripts"]:
            if _norm(k) == want or _norm(k).startswith(want) or want in _norm(k):
                arch_key = k
                break
        if arch_key is None:
            note += (" " if note else "") + f"archetype {archetype!r} not in baselines ({', '.join(sb['scripts'])})."
    rows = []
    for k, g, lab, unit in METRICS:
        v = m.get(k)
        if v is None:
            continue
        if note and unit in SIZE_DEPENDENT_UNITS and "no baseline" in note:
            continue
        ps = stats(sb["pooled"].get(k))
        if not ps:
            continue
        row = {"key": k, "group": g, "label": lab, "unit": unit, "value": v, "pooled": ps, "flag_pooled": ""}
        if v < ps["p5"]:
            row["flag_pooled"] = "low"
        elif v > ps["p95"]:
            row["flag_pooled"] = "high"
        row["far"] = v < ps["min"] or v > ps["max"]
        if arch_key:
            a = stats(sb["scripts"][arch_key].get(k))
            row["arch"] = a
            row["flag_arch"] = ""
            if a:
                if v < a["p5"]:
                    row["flag_arch"] = "low"
                elif v > a["p95"]:
                    row["flag_arch"] = "high"
        rows.append(row)
    n_out = sum(1 for r in rows if r["flag_pooled"])
    n_far = sum(1 for r in rows if r["far"])
    n_arch = sum(1 for r in rows if r.get("flag_arch"))
    frac = n_out / len(rows) if rows else 0
    if n_far == 0 and frac <= 0.10:
        verdict = "looks like a normal map: within the reference archetypes' typical range on almost every metric"
    elif n_far <= 3 and frac <= 0.25:
        verdict = "mostly normal, with some unusual metrics worth a look"
    else:
        verdict = "unusual map: many metrics fall outside what the reference archetypes produce"
    return {"size": size, "note": note, "archetype": arch_key, "rows": rows, "verdict": verdict,
            "n_out_pooled": n_out, "n_out_arch": n_arch, "n_far": n_far}


def format_compare(m, c, show_all=False):
    out = [f"== compare {m.get('script')} {m.get('world_size')} seed={m.get('seed')} against "
           f"'{c['size']}' baselines" + (f" + archetype {c['archetype']}" if c["archetype"] else "")]
    if c["note"]:
        out.append("note: " + c["note"])
    hdr = f"  {'metric':48s} {'value':>8s}   {'pooled p5..p95 (median)':>26s}"
    if c["archetype"]:
        hdr += f"   {'archetype p5..p95':>18s}"
    out.append(hdr)
    for r in c["rows"]:
        flagged = r["flag_pooled"] or r.get("flag_arch")
        if not (flagged or show_all):
            continue
        p = r["pooled"]
        u = r["unit"]
        line = (f"  {r['label'][:48]:48s} {fmt(r['value'], u):>8s}   "
                f"{fmt(p['p5'], u):>7s}..{fmt(p['p95'], u):<7s} ({fmt(p['median'], u):>6s})")
        if c["archetype"]:
            a = r.get("arch")
            line += f"   {(fmt(a['p5'], u) + '..' + fmt(a['p95'], u)) if a else '-':>18s}"
        tags = []
        if r["flag_pooled"]:
            tags.append(("FAR " if r["far"] else "") + r["flag_pooled"].upper())
        if r.get("flag_arch"):
            tags.append("arch " + r["flag_arch"])
        out.append(line + ("   <- " + ", ".join(tags) if tags else ""))
    out.append(f"{c['n_out_pooled']} of {len(c['rows'])} metrics outside pooled p5-p95"
               f" ({c['n_far']} beyond the pooled min/max)"
               + (f"; {c['n_out_arch']} outside {c['archetype']} p5-p95" if c["archetype"] else ""))
    out.append("verdict: " + c["verdict"])
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------------------
def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compare":
        ap = argparse.ArgumentParser(prog="metrics.py compare", description="Compare a dump against baselines.")
        ap.add_argument("dump")
        ap.add_argument("--baseline", default=DEFAULT_BASELINE)
        ap.add_argument("--archetype", default=None)
        ap.add_argument("--all", action="store_true", help="show every metric, not only flagged ones")
        ap.add_argument("--json", action="store_true")
        a = ap.parse_args(argv[1:])
        m = compute_metrics(_load(a.dump))
        try:
            base = load_baseline(a.baseline)
        except OSError as e:
            print(f"metrics: cannot read baseline {a.baseline}: {e}")
            return 0
        c = compare(m, base, a.archetype)
        if a.json:
            print(json.dumps({"metrics": m, "compare": c}, indent=1, default=str))
        else:
            print(format_compare(m, c, a.all))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    m = compute_metrics(_load(a.dump))
    print(json.dumps(m, indent=1) if a.json else format_metrics(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
