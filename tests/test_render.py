"""Renderer smoke/invariant tests. Run: python tests/test_render.py  (or pytest tests/test_render.py)

Outputs go to out/ (gitignored): out/test_synthetic.json, .png, _<layer>.png, .txt
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "render"))
sys.path.insert(0, HERE)

import json  # noqa: E402

import make_synthetic_dump  # noqa: E402
import render_map as rm  # noqa: E402

OUT = os.path.join(ROOT, "out")


def _dump():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "test_synthetic.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(make_synthetic_dump.build(1234), f)
    return path, rm.load_dump(path)


def test_dump_uses_every_field():
    _, d = _dump()
    n = d["width"] * d["height"]
    assert (d["width"], d["height"]) == (40, 24)
    for k in ("plot_type", "terrain", "feature", "resource", "resource_qty", "river_w", "river_nw",
              "river_ne", "area", "lake", "continent"):
        assert len(d[k]) == n, k
    assert all(any(v != -1 for v in d[k]) for k in ("river_w", "river_nw", "river_ne"))
    assert any(d["lake"]) and len(d["start_plots"]) >= 4
    assert {0, 1, 2, 3} <= set(d["plot_type"])
    feats = {d["feature_types"][f] for f in d["feature"] if f >= 0}
    assert any(rm.is_natural_wonder(f) for f in feats)
    classes = {rm.resource_class(d["resource_types"][r]) for r in d["resource"] if r >= 0}
    assert {"strategic", "luxury", "bonus"} <= classes


def test_png_size_and_colors():
    path, d = _dump()
    W, H = d["width"], d["height"]
    hex_size = 14
    img = rm.render_png(d, os.path.join(OUT, "test_synthetic_raw.png"), hex_size=hex_size,
                        legend=False, title=False, ss=1, grid=False)
    w = math.sqrt(3) * hex_size
    exp_w = math.ceil(W * w) + 2 * 6            # wrap_x: exactly W hexes wide + padding
    exp_h = math.ceil(hex_size * (1.5 * H + 0.5)) + 2 * 6
    assert abs(img.width - exp_w) <= 1 and abs(img.height - exp_h) <= 1, (img.size, exp_w, exp_h)
    colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}
    want = {k: rm.TERRAIN_COLORS[k] for k in ("TERRAIN_GRASS", "TERRAIN_PLAINS", "TERRAIN_DESERT",
                                              "TERRAIN_TUNDRA", "TERRAIN_SNOW", "TERRAIN_COAST",
                                              "TERRAIN_OCEAN")}
    want.update(lake=rm.LAKE_COLOR, river=rm.RIVER_COLOR, mountain=rm.MOUNTAIN_FILL,
                wonder=rm.WONDER_FILL, ice=rm.ICE_COLOR, strategic=rm.RES_COLORS["strategic"],
                luxury=rm.RES_COLORS["luxury"])
    missing = [k for k, c in want.items() if c not in colors]
    assert not missing, f"colours not found in render: {missing}"

    # full default render (legend/title, supersampled) plus every layer must not raise
    full = rm.render_png(d, os.path.splitext(path)[0] + ".png")
    assert full.width > img.width and full.height > img.height
    for layer in rm.LAYERS:
        im = rm.render_png(d, os.path.splitext(path)[0] + f"_{layer}.png", layer=layer)
        assert im.width == full.width


def test_png_nonwrap_and_tiny_hex():
    _, d = _dump()
    d["wrap_x"] = False
    img = rm.render_png(d, None, hex_size=5, ss=1)
    assert img.width >= math.ceil(math.sqrt(3) * 5 * (d["width"] + 0.5))


def test_ascii_and_stats():
    path, d = _dump()
    txt = rm.render_ascii(d)
    lines = txt.splitlines()
    rows = lines[:d["height"]]
    assert len(rows) == d["height"]
    # north first: first printed row is y=H-1; odd rows are indented by one extra space
    assert rows[0].startswith(f"{d['height'] - 1:3d} ")
    top, south = rows[0][4:], rows[-1][4:]
    assert top.startswith(" ") != south.startswith(" ")      # y=23 odd (indented), y=0 even
    body = "".join(r[4:] for r in rows).replace(" ", "")
    assert len(body) == d["width"] * d["height"]
    for ch in "~.lgpdt^FJ*#0123&":
        assert ch in body, ch
    stats = rm.map_stats(d)
    for key in ("land", "water", "terrain:", "features:", "resources:", "rivers:", "areas:", "start plots:"):
        assert key in stats, key
    with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as f:
        f.write(txt + "\n\n" + stats + "\n")


def test_cli():
    path, _ = _dump()
    png = os.path.join(OUT, "test_cli.png")
    assert rm.main([path, "--png", png, "--hex", "10", "--layer", "elevation", "--no-legend"]) == 0
    assert os.path.exists(png)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
