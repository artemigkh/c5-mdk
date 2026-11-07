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


def validate_dump(d, warnings=None):
    """Assert the dump follows the DESIGN.md map dump contract; returns the plot count.
    Soft findings (legal in the DLL but suspicious) are appended to `warnings` when a list is given."""
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
    if 3 in d["plot_type"]:
        assert coast in d["terrain"], "map has water but no coast terrain"

    # --- per-plot semantic invariants (sweep hardening) ---
    water_ter = {coast, ocean}
    pt, ter = d["plot_type"], d["terrain"]
    for i in range(n):
        x, y = i % W, i // W
        if pt[i] == 3:
            assert ter[i] in water_ter, "water plot (%d,%d) has non-water terrain %s" % (
                x, y, d["terrain_types"][ter[i]])
        else:
            assert ter[i] not in water_ter, "land plot (%d,%d) has water terrain %s" % (
                x, y, d["terrain_types"][ter[i]])
            assert d["lake"][i] == 0, "lake flag on land plot (%d,%d)" % (x, y)
    starts = set()
    for sp in d["start_plots"]:
        k = (sp["x"], sp["y"])
        assert 0 <= sp["x"] < W and 0 <= sp["y"] < H, "start plot off map %r" % (k,)
        assert k not in starts, "two players share start plot %r" % (k,)
        starts.add(k)
    for i in range(n):
        if d["resource"][i] < 0:
            continue
        if d["resource_qty"][i] < 1:
            # CvPlot::setResourceType stores whatever quantity it is given (Lua nil -> 0), so this is not a
            # DLL invariant; report it softly.
            _warn(warnings, "resource %s at (%d,%d) has quantity %d" % (
                d["resource_types"][d["resource"][i]], i % W, i // W, d["resource_qty"][i]))
    for k in ("river_w", "river_nw", "river_ne"):
        for i, v in enumerate(d[k]):
            if v != -1 and pt[i] == 3:
                # Possible in the DLL (setXOfRiver does not check the plot type, and the CP river code
                # only walks land), so a soft finding: the renderer draws it on a water hex.
                _warn(warnings, "%s flag on water plot (%d,%d)" % (k, i % W, i // W))
    _check_features(d, warnings)
    return n


def _warn(warnings, msg):
    if warnings is not None and len(warnings) < 200:
        warnings.append(msg)


_FEATURE_RULES = None


def _feature_rules():
    """{feature Type: (set of terrain Types, RequiresFlatlands, is natural wonder)} from the game DB."""
    global _FEATURE_RULES
    if _FEATURE_RULES is None:
        _FEATURE_RULES = {}
        try:
            import sqlite3
            sys.path.insert(0, os.path.join(ROOT, "host"))
            import paths
            con = sqlite3.connect("file:" + paths.DB.replace("\\", "/") + "?mode=ro", uri=True)
            tb = {}
            for f, t in con.execute("SELECT FeatureType, TerrainType FROM Feature_TerrainBooleans"):
                tb.setdefault(f, set()).add(t)
            for f, flat, nw, pnw in con.execute(
                    "SELECT Type, RequiresFlatlands, NaturalWonder, PseudoNaturalWonder FROM Features"):
                _FEATURE_RULES[f] = (tb.get(f, set()), bool(flat), bool(nw) or bool(pnw))
            con.close()
        except Exception:   # noqa: BLE001  (no DB: skip the check)
            _FEATURE_RULES = {}
    return _FEATURE_RULES


def _check_features(d, warnings):
    """Soft CanHaveFeature check (terrain booleans, mountains, RequiresFlatlands) for non-wonder features.
    Map scripts call SetFeatureType directly, which does not consult canHaveFeature, so violations are
    reported as warnings, not failures."""
    if warnings is None:
        return
    rules = _feature_rules()
    if not rules:
        return
    W = d["width"]
    for i, f in enumerate(d["feature"]):
        if f < 0:
            continue
        ft = d["feature_types"][f]
        r = rules.get(ft)
        if r is None or r[2]:
            continue
        terrains, flat, _ = r
        tt = d["terrain_types"][d["terrain"][i]]
        why = None
        if d["plot_type"][i] == 0:
            why = "on a mountain"
        elif tt not in terrains:
            why = "on %s" % tt
        elif flat and d["plot_type"][i] == 1:
            why = "on hills (RequiresFlatlands)"
        if why:
            _warn(warnings, "%s at (%d,%d) %s" % (ft, i % W, i // W, why))


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


def test_teams_and_option_warning():
    os.makedirs(OUT, exist_ok=True)
    cmd = [sys.executable, os.path.join(ROOT, "host", "c5gen.py"), "Continents", "--size", "duel", "--seed", "3",
           "--civs", "4", "--teams", "2", "--option", "9=1", "--option", "4=9", "--out", OUT, "--no-render", "--quiet"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "declares no CustomOptions[9]" in r.stderr and "value outside 1..4" in r.stderr, r.stderr
    with open(os.path.join(OUT, "Continents_duel_3.json"), encoding="utf-8") as f:
        d = json.load(f)
    validate_dump(d)
    majors = sorted((s["player"], s["team"]) for s in d["start_plots"] if not s["minor"])
    assert majors == [(0, 0), (1, 1), (2, 0), (3, 1)], majors


def test_validator_soft_warnings():
    d = synthetic_ok_dump()
    w = []
    validate_dump(d, w)
    assert w == [], w
    d["resource_qty"][d["resource"].index(next(r for r in d["resource"] if r >= 0))] = 0
    validate_dump(d, w)
    assert any("quantity 0" in x for x in w), w
    bad = dict(d, lake=list(d["lake"]))
    land = d["plot_type"].index(2)
    bad["lake"][land] = 1
    try:
        validate_dump(bad)
    except AssertionError as e:
        assert "lake flag on land" in str(e)
    else:
        raise AssertionError("lake flag on land not caught")


def synthetic_ok_dump():
    with open(os.path.join(OUT, "Pangaea_duel_7.json"), encoding="utf-8") as f:
        return json.load(f)


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
