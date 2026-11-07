"""Unit tests for host/metrics.py on the synthetic dump (no benchmark / game data needed).
Run: python tests/test_metrics.py  (or pytest tests/test_metrics.py)
"""
import json
import os
import random
import subprocess
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
import make_synthetic_dump as syn  # noqa: E402
import metrics  # noqa: E402

D = syn.build(1234)
W, H = D["width"], D["height"]


def bfs_dist(grid, a, b):
    seen = {a: 0}
    q = deque([a])
    while q:
        c = q.popleft()
        if c == b:
            return seen[c]
        for j in grid.nbr[c]:
            if j >= 0 and j not in seen:
                seen[j] = seen[c] + 1
                q.append(j)
    return None


def test_hex_distance_known_cases():
    hd = metrics.hex_distance
    assert hd(0, 0, 0, 0, W, H, True) == 0
    assert hd(0, 0, 39, 0, W, H, True) == 1, "wraps across the X seam"
    assert hd(0, 0, 39, 0, W, H, False) == 39, "no wrap"
    assert hd(0, 0, 0, 1, W, H, True) == 1, "NE of an even row is (x, y+1)"
    assert hd(0, 0, 39, 1, W, H, True) == 1, "NW of (0,0) is (-1,1) -> (39,1) with wrap"
    assert hd(0, 1, 1, 2, W, H, True) == 1, "NE of an odd row is (x+1, y+1)"
    assert hd(0, 0, 1, 2, W, H, True) == 2
    assert hd(8, 7, 21, 8, W, H, True) == 13
    assert hd(5, 3, 25, 3, W, H, True) == 20, "half the map either way"
    assert hd(2, 0, 37, 10, W, H, True) == hd(37, 10, 2, 0, W, H, True), "symmetric"


def test_hex_distance_matches_neighbour_bfs():
    for wrap in (True, False):
        g = metrics.Grid(W, H, wrap, False)
        rnd = random.Random(7)
        for _ in range(300):
            a, b = rnd.randrange(W * H), rnd.randrange(W * H)
            assert g.dist(a, b) == bfs_dist(g, a, b), (wrap, a, b)


def test_neighbours_are_symmetric():
    g = metrics.Grid(W, H, True, False)
    for i in range(W * H):
        nb = [j for j in g.nbr[i] if j >= 0]
        assert len(set(nb)) == len(nb)
        for j in nb:
            assert i in g.nbr[j]
        assert len(g.within(i, 3)) <= 37
    assert len(g.within(10 * W + 10, 3)) == 37


def test_land_water_and_terrain():
    m = metrics.compute_metrics(json.loads(json.dumps(D)))
    n = W * H
    land = sum(1 for p in D["plot_type"] if p != 3)
    assert abs(m["land_pct"] - 100.0 * land / n) < 1e-9
    assert abs(m["land_pct"] + m["water_pct"] - 100) < 1e-9
    assert abs(m["coast_pct_of_sea"] + m["ocean_pct_of_sea"] - 100) < 1e-9
    assert m["lake_tiles"] == sum(1 for i in range(n) if D["lake"][i] and D["plot_type"][i] == 3)
    assert m["lake_count"] >= 1
    assert abs(m["flat_pct"] + m["hills_pct"] + m["mountain_pct"] - 100) < 1e-9
    assert m["snow_pct"] > 0 and m["tundra_pct"] > 0
    assert m["cold_lat_mean"] > 0.6 > m["desert_lat_mean"]
    assert m["natural_wonders"] == 2, "Fuji + Crater"
    assert m["atoll_count"] <= 1 and m["oasis_count"] == 1
    assert m["landmasses_30"] == 2, "continent + island"
    assert m["largest_landmass_pct"] > m["second_landmass_pct"] > 0
    assert m["land_per_civ"] == land / 4


def test_rivers_and_fresh_water():
    m = metrics.compute_metrics(json.loads(json.dumps(D)))
    edges = sum(1 for k in ("river_w", "river_nw", "river_ne") for v in D[k] if v != -1)
    land = sum(1 for p in D["plot_type"] if p != 3)
    assert abs(m["river_edges_per100"] - 100.0 * edges / land) < 1e-9
    assert 0 < m["river_land_pct"] <= m["fresh_water_pct"]
    # a plot gets fresh water from the synthetic lake at (8,14),(9,14),(8,15): its land neighbours count
    d2 = json.loads(json.dumps(D))
    for k in ("river_w", "river_nw", "river_ne"):
        d2[k] = [-1] * (W * H)
    m2 = metrics.compute_metrics(d2)
    assert m2["river_land_pct"] == 0 and m2["fresh_water_pct"] > 0


def test_capital_distances():
    m = metrics.compute_metrics(json.loads(json.dumps(D)))
    g = metrics.Grid(W, H, True, False)
    caps = [s["y"] * W + s["x"] for s in D["start_plots"] if not s["minor"]]
    cs = [s["y"] * W + s["x"] for s in D["start_plots"] if s["minor"]]
    nn = [min(bfs_dist(g, a, b) for b in caps if b != a) for a in caps]
    assert m["majors"] == 4 and m["city_states"] == 1
    assert abs(m["cap_nn_mean"] - sum(nn) / 4) < 1e-9
    assert m["cap_nn_min"] == min(nn) and m["cap_nn_max"] == max(nn)
    pairs = [bfs_dist(g, caps[a], caps[b]) for a in range(4) for b in range(a + 1, 4)]
    assert abs(m["cap_pair_mean"] - sum(pairs) / len(pairs)) < 1e-9
    assert m["cap_cs_min"] == min(bfs_dist(g, a, cs[0]) for a in caps)
    assert m["cs_cap_min"] == m["cap_cs_min"]
    assert m["cs_nn_mean"] is None, "single city-state has no CS neighbour"
    # Japan (33,12) sits alone on the island; the other three share the continent
    assert m["caps_on_largest"] == 3 and m["cap_landmasses"] == 2 and m["cap_isolated"] == 1
    assert 0 < m["cap_land_r3_mean"] <= 37


def test_resource_density():
    m = metrics.compute_metrics(json.loads(json.dumps(D)))
    names = D["resource_types"]
    land = sum(1 for p in D["plot_type"] if p != 3)
    strat = [names[r] for r in D["resource"] if r >= 0 and names[r].replace("RESOURCE_", "") in metrics.STRATEGICS]
    bonus = [r for r in D["resource"] if r >= 0 and metrics.resource_kind(names[r]) == "bonus"]
    lux = [r for r in D["resource"] if r >= 0 and metrics.resource_kind(names[r]) == "luxury"]
    assert m["strategic_tiles"] == len(strat) > 0
    assert abs(m["strategic_per100"] - 100.0 * len(strat) / land) < 1e-9
    assert abs(m["bonus_per100"] - 100.0 * len(bonus) / land) < 1e-9
    assert m["luxury_types"] == len(set(lux))
    iron = sum(q for r, q in zip(D["resource"], D["resource_qty"]) if r >= 0 and names[r] == "RESOURCE_IRON")
    assert m["iron_qty"] == iron and abs(m["iron_qty_per_civ"] - iron / 4) < 1e-9
    # dump resource_class wins over the name fallback; artifacts never count
    d2 = json.loads(json.dumps(D))
    d2["resource_types"] = names + ["RESOURCE_ARTIFACTS"]
    d2["resource_class"] = ["RESOURCECLASS_BONUS"] * len(names) + ["RESOURCECLASS_RUSH"]
    d2["resource"][0] = len(names)
    m2 = metrics.compute_metrics(d2)
    assert m2["strategic_tiles"] == 0 and m2["luxury_tiles"] == 0


def _fake_baseline(m):
    order = ["n", "mean", "median", "p5", "p10", "p90", "p95", "min", "max"]
    pooled = {k: [10, 50, 50, 40, 42, 58, 60, 30, 70] for k in metrics.METRIC_KEYS}
    pooled["land_pct"] = [10, m["land_pct"], m["land_pct"], m["land_pct"] - 1, 0, 0, m["land_pct"] + 1, 0, 100]
    return {"stat_order": order, "sizes": {"duel": {"pooled": pooled, "scripts": {"Synthetic": pooled}}}}


def test_compare_flags():
    m = metrics.compute_metrics(json.loads(json.dumps(D)))
    b = _fake_baseline(m)
    order = b["stat_order"]
    c = metrics.compare(m, (b, lambda arr: dict(zip(order, arr)) if arr else None), "synthetic")
    rows = {r["key"]: r for r in c["rows"]}
    assert rows["land_pct"]["flag_pooled"] == ""
    assert rows["majors"]["flag_pooled"] == "low" and rows["majors"]["far"], "4 majors vs 30..70"
    assert c["archetype"] == "Synthetic" and rows["majors"]["flag_arch"] == "low"
    assert "unusual" in c["verdict"]
    assert "verdict:" in metrics.format_compare(m, c)


def test_cli_exit_codes():
    out = os.path.join(ROOT, "out", "_test_metrics")
    os.makedirs(out, exist_ok=True)
    dump = os.path.join(out, "synthetic.json")
    with open(dump, "w", encoding="utf-8") as f:
        json.dump(D, f)
    base = os.path.join(out, "base.json")
    with open(base, "w", encoding="utf-8") as f:
        json.dump(_fake_baseline(metrics.compute_metrics(json.loads(json.dumps(D)))), f)
    py = [sys.executable, os.path.join(ROOT, "host", "metrics.py")]
    r = subprocess.run(py + [dump, "--json"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["majors"] == 4, r.stderr
    r = subprocess.run(py + ["compare", dump, "--baseline", base], capture_output=True, text=True)
    assert r.returncode == 0 and "verdict" in r.stdout, r.stdout + r.stderr
    r = subprocess.run(py + ["compare", dump, "--baseline", os.path.join(out, "missing.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "advisory: always exit 0"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    sys.exit(1 if failed else 0)
