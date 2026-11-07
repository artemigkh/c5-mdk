"""CLI smoke test: run Pangaea.lua at duel size through host/c5gen.py, validate the dump against the
DESIGN.md contract and render it.  Run: python tests/test_cli.py  (or pytest tests/test_cli.py)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "render"))
import render_map as rm  # noqa: E402

OUT = os.path.join(ROOT, "out", "_test_cli")

PER_PLOT = ("plot_type", "terrain", "feature", "resource", "resource_qty", "river_w", "river_nw", "river_ne",
            "area", "lake", "continent")


def validate_dump(d):
    """Assert the dump follows the DESIGN.md map dump contract; returns the plot count."""
    for k in ("script", "seed", "world_size", "width", "height", "wrap_x", "wrap_y", "terrain_types",
              "feature_types", "resource_types", "resource_class", "feature_natural_wonder", "areas",
              "start_plots", "log") + PER_PLOT:
        assert k in d, "missing key " + k
    W, H = d["width"], d["height"]
    n = W * H
    assert isinstance(W, int) and isinstance(H, int) and n > 0
    assert isinstance(d["wrap_x"], bool) and isinstance(d["wrap_y"], bool)
    for k in PER_PLOT:
        assert len(d[k]) == n, k
        assert all(isinstance(v, int) for v in d[k]), k
    assert set(d["plot_type"]) <= {0, 1, 2, 3}
    nt, nf, nr = len(d["terrain_types"]), len(d["feature_types"]), len(d["resource_types"])
    assert d["terrain_types"][0] == "TERRAIN_GRASS" and d["terrain_types"][5] == "TERRAIN_COAST"
    assert all(0 <= t < nt for t in d["terrain"]), "every plot has a terrain"
    assert all(-1 <= f < nf for f in d["feature"])
    assert all(-1 <= r < nr for r in d["resource"])
    assert len(d["resource_class"]) == nr and len(d["feature_natural_wonder"]) == nf
    assert set(d["resource_class"]) <= {"RESOURCECLASS_LUXURY", "RESOURCECLASS_BONUS", "RESOURCECLASS_RUSH",
                                         "RESOURCECLASS_MODERN", ""}
    assert set(d["feature_natural_wonder"]) <= {0, 1}
    for k in ("river_w", "river_nw", "river_ne"):
        assert all(-1 <= v <= 7 for v in d[k])
    assert set(d["lake"]) <= {0, 1}
    for aid, a in d["areas"].items():
        assert set(a) >= {"water", "size", "lake"}
        assert a["size"] == sum(1 for v in d["area"] if v == int(aid)), "area size matches plots"
    assert all(v >= 0 for v in d["area"]), "every plot has an area after RecalculateAreas"
    for sp in d["start_plots"]:
        assert set(sp) >= {"player", "team", "x", "y", "civ", "name", "minor"}
        i = sp["y"] * W + sp["x"]
        assert d["plot_type"][i] != 3, "start plot on land"
    # engine invariant: no deep ocean next to land after ValidateCoast
    coast = d["terrain_types"].index("TERRAIN_COAST")
    ocean = d["terrain_types"].index("TERRAIN_OCEAN")
    for i in range(n):
        if d["terrain"][i] == ocean:
            x, y = i % W, i // W
            for dx, dy in (((0, 1), (1, 0), (0, -1), (-1, -1), (-1, 0), (-1, 1)) if y % 2 == 0 else
                           ((1, 1), (1, 0), (1, -1), (0, -1), (-1, 0), (0, 1))):
                nx, ny = x + dx, y + dy
                if d["wrap_x"]:
                    nx %= W
                if 0 <= nx < W and 0 <= ny < H:
                    assert d["plot_type"][ny * W + nx] == 3, "ocean at (%d,%d) touches land" % (x, y)
    assert coast in d["terrain"]
    return n


def test_pangaea_duel():
    os.makedirs(OUT, exist_ok=True)
    cmd = [sys.executable, os.path.join(ROOT, "host", "c5gen.py"), "Pangaea", "--size", "duel", "--seed", "7",
           "--out", OUT, "--png", "--quiet"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    path = os.path.join(OUT, "Pangaea_duel_7.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    n = validate_dump(d)
    assert (d["width"], d["height"]) == (40, 24) and n == 960
    assert d["world_size"] == "WORLDSIZE_DUEL" and d["script"] == "Pangaea.lua"
    assert len(d["start_plots"]) == 2 + 4, "2 majors + 4 city-states (Worlds defaults)"
    assert sum(1 for r in d["resource"] if r >= 0) > 20, "resources placed"
    assert any(v != -1 for v in d["river_w"] + d["river_nw"] + d["river_ne"]), "rivers placed"
    for ext in (".png", ".txt", ".log"):
        assert os.path.exists(os.path.join(OUT, "Pangaea_duel_7" + ext)), ext
    dd = rm.load_dump(path)
    img = rm.render_png(dd, os.path.join(OUT, "pangaea_rerender.png"))
    assert img.size[0] > 100
    assert "start plots" in rm.map_stats(dd)


def test_lua_error_exit_code():
    os.makedirs(OUT, exist_ok=True)
    bad = os.path.join(OUT, "bad_script.lua")
    with open(bad, "w") as f:
        f.write('include("MapGenerator")\nfunction GenerateMap() Map.Rand(10) end\n')
    r = subprocess.run([sys.executable, os.path.join(ROOT, "host", "c5gen.py"), bad, "--size", "duel",
                        "--out", OUT, "--no-render", "--quiet"], capture_output=True, text=True)
    assert r.returncode != 0
    assert "bad argument #2 to 'Rand'" in r.stderr and "stack traceback" in r.stderr


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
