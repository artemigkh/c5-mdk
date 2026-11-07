"""Civ 5 map dump renderer (PNG via Pillow + ASCII).

Reads the map dump JSON described in DESIGN.md ("Map dump format") and renders:
  * a hex-grid PNG (odd-r offset rows, y=0 is the south row -> drawn at the bottom), and
  * an ASCII view plus a statistics block.

CLI:
  python render/render_map.py out/foo.json [--png out/foo.png] [--ascii] [--hex 12]
         [--layer terrain|plain|areas|continents|elevation|resources|startbias]
         [--no-legend] [--no-title] [--labels/--no-labels] [--ss 2] [--stats]

Importable API:
  load_dump(path) -> dict
  render_png(dump, path=None, hex_size=None, layer="terrain", legend=True, ...) -> PIL.Image
  render_ascii(dump, spaced=True) -> str
  map_stats(dump) -> str

Geometry (verified against CvGameCoreDLL_Expansion2):
  * hexes are "pointy-top": rows are horizontal, neighbours are E/W/NE/NW/SE/SW.
  * odd rows are shifted half a hex east (xToHexspaceX = x - floor(y/2)).
  * river flags (CvPlot::updateRiverCrossing):
      river_w  != -1  -> river along this plot's EAST edge
      river_nw != -1  -> river along this plot's SOUTH-EAST edge
      river_ne != -1  -> river along this plot's SOUTH-WEST edge
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------------------------
# Constants / classification
# --------------------------------------------------------------------------------------------
PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN = 0, 1, 2, 3
PLOT_NAMES = {0: "mountain", 1: "hills", 2: "flat", 3: "water"}

COMMON_FEATURES = {
    "FEATURE_ICE", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_OASIS",
    "FEATURE_FLOOD_PLAINS", "FEATURE_FOREST", "FEATURE_FALLOUT", "FEATURE_ATOLL",
}

STRATEGIC = {"IRON", "HORSE", "COAL", "ALUMINUM", "OIL", "URANIUM", "PAPER"}
BONUS = {"WHEAT", "COW", "SHEEP", "DEER", "BANANA", "BANANAS", "FISH", "STONE", "BISON",
         "MAIZE", "RICE", "FIGS"}
OTHER_RES = {"ARTIFACTS", "HIDDEN_ARTIFACTS"}


def resource_class(name: str) -> str:
    """'strategic' | 'bonus' | 'luxury' | 'other' from a RESOURCE_* type name."""
    short = name.replace("RESOURCE_", "")
    if short in STRATEGIC:
        return "strategic"
    if short in BONUS:
        return "bonus"
    if short in OTHER_RES:
        return "other"
    return "luxury"


def is_natural_wonder(feature_name: str) -> bool:
    return bool(feature_name) and feature_name not in COMMON_FEATURES


def short_name(type_name: str, prefix: str) -> str:
    s = type_name[len(prefix):] if type_name.startswith(prefix) else type_name
    return s.replace("_", " ").title()


# --------------------------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------------------------
TERRAIN_COLORS = {
    "TERRAIN_GRASS": (96, 146, 56),
    "TERRAIN_PLAINS": (178, 170, 88),
    "TERRAIN_DESERT": (230, 208, 140),
    "TERRAIN_TUNDRA": (142, 146, 118),
    "TERRAIN_SNOW": (242, 244, 248),
    "TERRAIN_COAST": (104, 168, 214),
    "TERRAIN_OCEAN": (34, 76, 148),
    "TERRAIN_MOUNTAIN": (118, 106, 94),
    "TERRAIN_HILL": (150, 140, 90),
}
LAKE_COLOR = (62, 190, 196)
UNKNOWN_COLOR = (200, 120, 200)
MOUNTAIN_FILL = (116, 104, 92)
MOUNTAIN_DARK = (66, 58, 50)
MOUNTAIN_SNOW = (245, 245, 250)
RIVER_COLOR = (30, 96, 230)
FOREST_COLOR = (28, 86, 36)
JUNGLE_COLOR = (12, 104, 46)
MARSH_COLOR = (70, 120, 120)
FLOOD_COLOR = (170, 196, 84)
ICE_COLOR = (226, 240, 250)
FALLOUT_COLOR = (172, 190, 40)
OASIS_COLOR = (50, 150, 225)
WONDER_FILL = (255, 204, 0)
WONDER_EDGE = (200, 0, 160)
RES_COLORS = {
    "strategic": (220, 30, 30),
    "luxury": (255, 196, 0),
    "bonus": (255, 255, 255),
    "other": (160, 160, 160),
}
START_MAJOR = (255, 255, 255)
START_MAJOR_EDGE = (200, 20, 20)
START_MINOR = (190, 150, 230)
START_MINOR_EDGE = (70, 30, 110)
BG = (24, 26, 30)
TEXT = (235, 235, 235)

CONTINENT_COLORS = {
    0: (90, 90, 90),        # none
    1: (214, 130, 60),      # America
    2: (200, 70, 80),       # Asia
    3: (220, 200, 80),      # Africa
    4: (90, 160, 90),       # Europe
}
CONTINENT_NAMES = {0: "none", 1: "America", 2: "Asia", 3: "Africa", 4: "Europe"}
ELEV_COLORS = {
    PLOT_MOUNTAIN: (90, 70, 55),
    PLOT_HILLS: (160, 125, 85),
    PLOT_LAND: (200, 200, 160),
    PLOT_OCEAN: (40, 80, 150),
}


def mix(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def shade(c, f):
    return tuple(max(0, min(255, int(round(v * f)))) for v in c)


def area_color(aid: int):
    # deterministic, well-spread hue per id (golden ratio)
    import colorsys
    h = (aid * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.55 + 0.35 * ((aid * 7) % 3) / 2, 0.85)
    return int(r * 255), int(g * 255), int(b * 255)


# --------------------------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------------------------
_FONT_CACHE = {}


def get_font(size: int, bold=False):
    size = max(6, int(size))
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else []) + [
        "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    font = None
    for n in names:
        for cand in (n, os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", n)):
            try:
                font = ImageFont.truetype(cand, size)
                break
            except (OSError, IOError):
                continue
        if font:
            break
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def text_size(draw, text, font, stroke=0):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        return r - l, b - t, l, t
    except (TypeError, ValueError, AttributeError):
        w, h = font.getsize(text)
        return w, h, 0, 0


def draw_text_centered(draw, cx, cy, text, font, fill, stroke=0, stroke_fill=(0, 0, 0)):
    w, h, l, t = text_size(draw, text, font, stroke)
    x = cx - w / 2 - l
    y = cy - h / 2 - t
    try:
        draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    except TypeError:
        draw.text((x, y), text, font=font, fill=fill)


# --------------------------------------------------------------------------------------------
# Dump loading / normalisation
# --------------------------------------------------------------------------------------------
def load_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        return normalize_dump(json.load(f))


def normalize_dump(d):
    """Fill optional fields with defaults and convert None to -1 so the renderers can rely on them."""
    W, H = int(d["width"]), int(d["height"])
    n = W * H
    for k in ("plot_type", "terrain"):
        if len(d[k]) != n:
            raise ValueError(f"dump field {k!r} has {len(d[k])} entries, expected {n} ({W}x{H})")
    defaults = {"feature": -1, "resource": -1, "resource_qty": 0, "river_w": -1, "river_nw": -1,
                "river_ne": -1, "area": -1, "lake": 0, "continent": 0}
    for k, dv in defaults.items():
        arr = d.get(k)
        if arr is None:
            d[k] = [dv] * n
        else:
            if len(arr) != n:
                raise ValueError(f"dump field {k!r} has {len(arr)} entries, expected {n}")
            d[k] = [dv if v is None else int(v) for v in arr]
    d.setdefault("terrain_types", list(TERRAIN_COLORS))
    d.setdefault("feature_types", [])
    d.setdefault("resource_types", [])
    d.setdefault("start_plots", [])
    d.setdefault("wrap_x", False)
    d.setdefault("wrap_y", False)
    return d


def _name(lst, idx):
    if idx is None or idx < 0 or idx >= len(lst):
        return None
    return lst[idx]


# --------------------------------------------------------------------------------------------
# Hex geometry
# --------------------------------------------------------------------------------------------
class HexGeom:
    """Pointy-top odd-r layout. size = circumradius in (supersampled) pixels."""

    def __init__(self, W, H, size, ox, oy):
        self.W, self.H, self.s = W, H, size
        self.w = math.sqrt(3) * size          # hex width (flat side to flat side)
        self.ox, self.oy = ox, oy             # top-left of map area

    def center(self, x, y):
        row = self.H - 1 - y                  # y=0 is the south row -> bottom of the image
        cx = self.ox + self.w * (x + 0.5 * (y & 1)) + self.w / 2
        cy = self.oy + self.s + row * 1.5 * self.s
        return cx, cy

    def corners(self, cx, cy, scale=1.0):
        s, hw = self.s * scale, self.w / 2 * scale
        # top, upper-right, lower-right, bottom, lower-left, upper-left
        return [(cx, cy - s), (cx + hw, cy - s / 2), (cx + hw, cy + s / 2),
                (cx, cy + s), (cx - hw, cy + s / 2), (cx - hw, cy - s / 2)]

    # edge -> corner indices
    EDGE = {"NE": (0, 1), "E": (1, 2), "SE": (2, 3), "SW": (3, 4), "W": (4, 5), "NW": (5, 0)}

    @property
    def map_w(self):
        return self.w * (self.W + 0.5)

    @property
    def map_h(self):
        return self.s * (1.5 * self.H + 0.5)


def hex_distance(x1, y1, x2, y2, W=None):
    def ax(x, y):
        return x - (y - (y & 1)) // 2, y
    best = None
    xs = [x2] if not W else [x2 - W, x2, x2 + W]
    q1, r1 = ax(x1, y1)
    for xx in xs:
        q2, r2 = ax(xx, y2)
        dq, dr = q2 - q1, r2 - r1
        d = (abs(dq) + abs(dr) + abs(dq + dr)) // 2
        best = d if best is None else min(best, d)
    return best


# --------------------------------------------------------------------------------------------
# PNG renderer
# --------------------------------------------------------------------------------------------
LAYERS = ("terrain", "plain", "areas", "continents", "elevation", "resources", "startbias")


def default_hex_size(W):
    # circumradius so that the map is ~2000 px wide, clamped for tiny / huge maps
    s = 2000.0 / (math.sqrt(3) * (W + 0.5))
    return max(4.0, min(28.0, s))


def base_color(d, i, layer):
    pt = d["plot_type"][i]
    tname = _name(d["terrain_types"], d["terrain"][i])
    water = pt == PLOT_OCEAN
    if layer == "areas":
        return area_color(d["area"][i]) if not water else shade(area_color(d["area"][i]), 0.55)
    if layer == "continents":
        if water:
            return LAKE_COLOR if d["lake"][i] else TERRAIN_COLORS["TERRAIN_OCEAN"]
        return CONTINENT_COLORS.get(d["continent"][i], UNKNOWN_COLOR)
    if layer == "elevation":
        if water and d["lake"][i]:
            return LAKE_COLOR
        return ELEV_COLORS.get(pt, UNKNOWN_COLOR)
    if water and d["lake"][i]:
        c = LAKE_COLOR
    else:
        c = TERRAIN_COLORS.get(tname, UNKNOWN_COLOR)
    if pt == PLOT_MOUNTAIN:
        c = MOUNTAIN_FILL
    elif pt == PLOT_HILLS:
        c = shade(c, 0.86)
    if layer in ("resources", "startbias"):
        c = mix(c, (128, 128, 128), 0.45)
    return c


def feature_tint(fname, c):
    if fname == "FEATURE_FOREST":
        return mix(c, FOREST_COLOR, 0.25)
    if fname == "FEATURE_JUNGLE":
        return mix(c, JUNGLE_COLOR, 0.45)
    if fname == "FEATURE_MARSH":
        return mix(c, MARSH_COLOR, 0.35)
    if fname == "FEATURE_FLOOD_PLAINS":
        return mix(c, FLOOD_COLOR, 0.45)
    if fname == "FEATURE_ICE":
        return ICE_COLOR
    if fname == "FEATURE_FALLOUT":
        return mix(c, FALLOUT_COLOR, 0.5)
    return c


def _star(cx, cy, r_out, r_in, n=5):
    pts = []
    for k in range(2 * n):
        r = r_out if k % 2 == 0 else r_in
        a = -math.pi / 2 + k * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def render_png(d, path=None, hex_size=None, layer="terrain", legend=True, title=True,
               labels=None, ss=2, grid=True):
    """Render the dump to a PIL image (and save it if `path`). Returns the image."""
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}; choose from {LAYERS}")
    W, H = d["width"], d["height"]
    wrap = bool(d.get("wrap_x"))
    s_final = float(hex_size) if hex_size else default_hex_size(W)
    if labels is None:
        labels = s_final >= 14
    S = s_final * ss

    title_h = int(round(max(22, s_final * 1.4) * ss)) if title else 0
    pad = int(round(6 * ss))
    geom_probe = HexGeom(W, H, S, 0, 0)
    map_w = int(math.ceil(W * geom_probe.w if wrap else geom_probe.map_w))
    map_h = int(math.ceil(geom_probe.map_h))
    img_w = map_w + 2 * pad

    # Map is drawn onto its own layer so wrap duplicates can be clipped by cropping.
    extra = int(math.ceil(geom_probe.w)) if wrap else 0
    mlayer = Image.new("RGB", (map_w + 2 * extra, map_h), BG)
    g = HexGeom(W, H, S, extra, 0)
    dr = ImageDraw.Draw(mlayer)
    offsets = [0.0, -W * g.w, W * g.w] if wrap else [0.0]

    def visible(cx):
        return -g.w <= cx <= mlayer.width + g.w

    feat_types, res_types, ter_types = d["feature_types"], d["resource_types"], d["terrain_types"]
    show_features = layer in ("terrain", "resources", "startbias")
    show_relief = layer in ("terrain", "plain", "resources", "startbias", "areas", "continents")
    show_resources = layer in ("terrain", "resources")
    show_rivers = layer in ("terrain", "plain", "resources", "startbias", "elevation", "continents")
    line_w = max(1, int(round(S / 12)))

    centers = {}
    for y in range(H):
        for x in range(W):
            centers[(x, y)] = g.center(x, y)

    # ---- pass 1: hex fills + outline -------------------------------------------------------
    fills = [None] * (W * H)
    for y in range(H):
        for x in range(W):
            i = y * W + x
            c = base_color(d, i, layer)
            fname = _name(feat_types, d["feature"][i])
            if show_features and fname and not is_natural_wonder(fname) and d["plot_type"][i] != PLOT_MOUNTAIN:
                c = feature_tint(fname, c)
                if layer in ("resources", "startbias"):
                    c = mix(c, (128, 128, 128), 0.3)
            fills[i] = c
            cx0, cy = centers[(x, y)]
            for off in offsets:
                cx = cx0 + off
                if not visible(cx):
                    continue
                poly = g.corners(cx, cy, 1.0)
                outline = shade(c, 0.78) if grid else c
                dr.polygon(poly, fill=c, outline=outline)
                if grid and ss > 1:
                    dr.line(poly + [poly[0]], fill=outline, width=max(1, ss // 2))

    # ---- pass 2: relief + feature glyphs ----------------------------------------------------
    for y in range(H):
        for x in range(W):
            i = y * W + x
            pt = d["plot_type"][i]
            fname = _name(feat_types, d["feature"][i])
            c = fills[i]
            cx0, cy = centers[(x, y)]
            for off in offsets:
                cx = cx0 + off
                if not visible(cx):
                    continue
                if show_relief and pt == PLOT_MOUNTAIN:
                    _draw_mountain(dr, cx, cy, S, layer)
                elif show_relief and pt == PLOT_HILLS:
                    _draw_hills(dr, cx, cy, S, shade(c, 0.62), line_w)
                if show_features and fname:
                    _draw_feature(dr, cx, cy, S, fname, c, pt, line_w)

    # ---- pass 3: rivers ----------------------------------------------------------------------
    if show_rivers:
        rw = max(2, int(round(S / 6)))
        for y in range(H):
            for x in range(W):
                i = y * W + x
                edges = []
                if d["river_w"][i] != -1:
                    edges.append("E")
                if d["river_nw"][i] != -1:
                    edges.append("SE")
                if d["river_ne"][i] != -1:
                    edges.append("SW")
                if not edges:
                    continue
                cx0, cy = centers[(x, y)]
                for off in offsets:
                    cx = cx0 + off
                    if not visible(cx):
                        continue
                    cs = g.corners(cx, cy)
                    for e in edges:
                        a, b = g.EDGE[e]
                        dr.line([cs[a], cs[b]], fill=RIVER_COLOR, width=rw)
                        r = rw / 2
                        for p in (cs[a], cs[b]):
                            dr.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=RIVER_COLOR)

    # ---- pass 4: start-bias rings -----------------------------------------------------------
    if layer == "startbias":
        for sp in d["start_plots"]:
            col = START_MINOR_EDGE if sp.get("minor") else START_MAJOR_EDGE
            rad = 2 if sp.get("minor") else 3
            sx, sy = sp["x"], sp["y"]
            for yy in range(max(0, sy - rad), min(H, sy + rad + 1)):
                for xx in range(sx - rad - 1, sx + rad + 2):
                    if not wrap and not (0 <= xx < W):
                        continue
                    xm = xx % W
                    if hex_distance(sx, sy, xm, yy, W if wrap else None) > rad:
                        continue
                    cx0, cy = centers[(xm, yy)]
                    for off in offsets:
                        cx = cx0 + off
                        if visible(cx):
                            dr.polygon(g.corners(cx, cy, 0.86), outline=col)
                            dr.line(g.corners(cx, cy, 0.86) + [g.corners(cx, cy, 0.86)[0]],
                                    fill=col, width=max(1, int(S / 10)))

    # ---- pass 5: resources ------------------------------------------------------------------
    res_font = get_font(max(7, s_final * 0.55) * ss)
    start_xy = {(sp["x"], sp["y"]) for sp in d["start_plots"]}
    if show_resources:
        big = layer == "resources"
        for y in range(H):
            for x in range(W):
                i = y * W + x
                rname = _name(res_types, d["resource"][i])
                if not rname:
                    continue
                cls = resource_class(rname)
                col = RES_COLORS[cls]
                cx0, cy = centers[(x, y)]
                for off in offsets:
                    cx = cx0 + off
                    if not visible(cx):
                        continue
                    r = S * (0.26 if big else 0.2)
                    px, py = (cx, cy) if big else (cx + S * 0.38, cy + S * 0.32)
                    dr.ellipse([px - r, py - r, px + r, py + r], fill=col, outline=(0, 0, 0),
                               width=max(1, ss))
                    if (labels or big) and (x, y) not in start_xy:
                        lab = short_name(rname, "RESOURCE_")[:4]
                        q = d["resource_qty"][i]
                        if cls == "strategic" and q and q > 0:
                            lab += str(q)
                        draw_text_centered(dr, px, py - r - S * 0.28, lab, res_font, (255, 255, 255),
                                           stroke=max(1, ss), stroke_fill=(0, 0, 0))

    # ---- pass 6: natural wonder labels, area labels ----------------------------------------
    lab_font = get_font(max(9, s_final * 0.62) * ss, bold=True)
    if show_features:
        for y in range(H):
            for x in range(W):
                i = y * W + x
                fname = _name(feat_types, d["feature"][i])
                if fname and is_natural_wonder(fname):
                    cx0, cy = centers[(x, y)]
                    for off in offsets:
                        cx = cx0 + off
                        if visible(cx):
                            lab = short_name(fname, "FEATURE_")
                            lab = lab if len(lab) <= 10 else lab[:9] + "."
                            draw_text_centered(dr, cx, cy + S * 1.0, lab, lab_font, WONDER_FILL,
                                               stroke=max(1, ss), stroke_fill=(60, 0, 50))

    if layer == "areas":
        _draw_area_labels(d, dr, centers, offsets, visible, S, ss, s_final)

    # ---- pass 7: start plots ----------------------------------------------------------------
    if layer != "areas" or True:
        num_font = get_font(max(7, s_final * 0.7) * ss, bold=True)
        name_font = get_font(max(9, s_final * 0.75) * ss, bold=True)
        for sp in d["start_plots"]:
            sx, sy = sp["x"], sp["y"]
            if not (0 <= sx < W and 0 <= sy < H):
                continue
            minor = bool(sp.get("minor"))
            cx0, cy = centers[(sx, sy)]
            civ = short_name(sp.get("civ") or "", "CIVILIZATION_") or f"P{sp.get('player')}"
            for pre in ("Minor Civ ", "Minor "):
                if civ.startswith(pre):
                    civ = civ[len(pre):]
            for off in offsets:
                cx = cx0 + off
                if not visible(cx):
                    continue
                r = max(S * (0.42 if minor else 0.58), (4.5 if minor else 6.5) * ss)
                fill, edge = (START_MINOR, START_MINOR_EDGE) if minor else (START_MAJOR, START_MAJOR_EDGE)
                if minor:
                    dr.rectangle([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=edge,
                                 width=max(1, int(r / 4)))
                else:
                    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=edge,
                               width=max(2, int(r / 4)))
                draw_text_centered(dr, cx, cy, str(sp.get("player", "?")), num_font, (0, 0, 0))
                if not minor or labels:
                    nf = name_font if not minor else get_font(max(8, s_final * 0.6) * ss)
                    draw_text_centered(dr, cx, cy - r - S * 0.55, civ, nf,
                                       (255, 255, 255) if not minor else (225, 205, 255),
                                       stroke=max(2, ss + 1), stroke_fill=(0, 0, 0))

    # ---- compose ----------------------------------------------------------------------------
    mcrop = mlayer.crop((extra, 0, extra + map_w, map_h))
    legend_img = _legend(d, layer, img_w, ss, s_final) if legend else None
    total_h = title_h + pad + map_h + pad + (legend_img.height if legend_img else 0)
    out = Image.new("RGB", (img_w, total_h), BG)
    od = ImageDraw.Draw(out)
    if title:
        t = (f"{d.get('script', '?')}  |  {d.get('world_size', '?')}  {W}x{H}"
             f"{'  wrapX' if wrap else ''}{'  wrapY' if d.get('wrap_y') else ''}"
             f"  |  seed {d.get('seed', '?')}  |  layer: {layer}")
        tf = get_font(max(11, min(20, title_h / ss * 0.6)) * ss, bold=True)
        tw, th, tl, tt = text_size(od, t, tf)
        od.text((pad - tl, (title_h - th) / 2 - tt + pad / 2), t, font=tf, fill=TEXT)
    out.paste(mcrop, (pad, title_h + pad))
    if wrap:
        # small wrap markers just outside the map edges
        mk = (150, 150, 160)
        y0, y1 = title_h + pad, title_h + pad + map_h
        for xx in (pad - max(2, ss * 2), pad + map_w + max(1, ss)):
            for yy in range(int(y0), int(y1), int(8 * ss)):
                od.line([(xx, yy), (xx, yy + 4 * ss)], fill=mk, width=max(1, ss))
    if legend_img:
        out.paste(legend_img, (0, title_h + pad + map_h + pad))
    if ss > 1:
        out = out.resize((max(1, round(out.width / ss)), max(1, round(out.height / ss))),
                         Image.LANCZOS)
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        out.save(path)
    return out


def _draw_hills(dr, cx, cy, S, col, lw):
    # two humps as arcs, slightly below centre
    r = S * 0.30
    for dx, rr in ((-S * 0.22, r), (S * 0.22, r * 0.8)):
        box = [cx + dx - rr, cy + S * 0.18 - rr, cx + dx + rr, cy + S * 0.18 + rr]
        dr.arc(box, 200, 340, fill=col, width=max(1, lw))


def _draw_mountain(dr, cx, cy, S, layer):
    h, b = S * 0.62, S * 0.48
    base_y = cy + S * 0.36
    peak = (cx, base_y - h)
    dark = MOUNTAIN_DARK if layer != "elevation" else (50, 40, 30)
    dr.polygon([(cx - b, base_y), peak, (cx + b, base_y)], fill=dark)
    # lit face
    dr.polygon([(cx - b * 0.15, base_y), peak, (cx + b, base_y)], fill=shade(dark, 1.35))
    # snow cap
    k = 0.36
    dr.polygon([(cx - b * k, base_y - h * (1 - k)), peak, (cx + b * k, base_y - h * (1 - k))],
               fill=MOUNTAIN_SNOW)


def _draw_feature(dr, cx, cy, S, fname, c, pt, lw):
    if fname == "FEATURE_FOREST":
        for dx, dy in ((-0.3, 0.05), (0.3, 0.05), (0.0, -0.3), (0.0, 0.35)):
            if pt == PLOT_HILLS and dy > 0.3:
                continue
            tx, ty = cx + dx * S, cy + dy * S
            hh, bb = S * 0.26, S * 0.15
            dr.polygon([(tx - bb, ty + hh / 2), (tx, ty - hh / 2), (tx + bb, ty + hh / 2)],
                       fill=FOREST_COLOR)
    elif fname == "FEATURE_JUNGLE":
        r = S * 0.12
        for dx, dy in ((-0.3, -0.1), (0.3, -0.1), (0.0, -0.38), (-0.15, 0.3), (0.18, 0.28)):
            tx, ty = cx + dx * S, cy + dy * S
            dr.ellipse([tx - r, ty - r, tx + r, ty + r], fill=JUNGLE_COLOR, outline=(4, 60, 24))
    elif fname == "FEATURE_MARSH":
        for dy in (-0.25, 0.05, 0.35):
            for dx in (-0.25, 0.2):
                xx = cx + (dx + (0.1 if dy == 0.05 else 0)) * S
                dr.line([(xx - S * 0.14, cy + dy * S), (xx + S * 0.14, cy + dy * S)],
                        fill=(40, 90, 110), width=max(1, lw))
    elif fname == "FEATURE_FLOOD_PLAINS":
        for dy in (-0.3, 0.0, 0.3):
            dr.line([(cx - S * 0.45, cy + dy * S), (cx + S * 0.45, cy + dy * S)],
                    fill=shade(FLOOD_COLOR, 0.75), width=max(1, lw // 2 or 1))
    elif fname == "FEATURE_OASIS":
        r = S * 0.36
        dr.ellipse([cx - r, cy - r * 0.65, cx + r, cy + r * 0.65], fill=OASIS_COLOR, outline=(30, 120, 40),
                   width=max(1, lw))
    elif fname == "FEATURE_ICE":
        for k in (-0.4, 0.0, 0.4):
            dr.line([(cx + (k - 0.25) * S, cy + 0.35 * S), (cx + (k + 0.25) * S, cy - 0.35 * S)],
                    fill=(170, 200, 225), width=max(1, lw // 2 or 1))
    elif fname == "FEATURE_ATOLL":
        r = S * 0.32
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(236, 220, 160), width=max(2, lw + 1))
        dr.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=(90, 160, 80))
    elif fname == "FEATURE_FALLOUT":
        r = S * 0.08
        for dx, dy in ((-0.25, -0.2), (0.25, -0.2), (0.0, 0.25)):
            tx, ty = cx + dx * S, cy + dy * S
            dr.ellipse([tx - r, ty - r, tx + r, ty + r], fill=(30, 30, 10))
    elif is_natural_wonder(fname):
        dr.polygon(_star(cx, cy, S * 0.62, S * 0.26), fill=WONDER_FILL, outline=WONDER_EDGE)
        dr.line(_star(cx, cy, S * 0.62, S * 0.26) + [_star(cx, cy, S * 0.62, S * 0.26)[0]],
                fill=WONDER_EDGE, width=max(1, lw))


def _draw_area_labels(d, dr, centers, offsets, visible, S, ss, s_final):
    W, H = d["width"], d["height"]
    members = defaultdict(list)
    for i, a in enumerate(d["area"]):
        members[a].append(i)
    n = W * H
    thresh = max(6, n // 150)
    font = get_font(max(9, s_final * 0.8) * ss, bold=True)
    for aid, idxs in members.items():
        if len(idxs) < thresh:
            continue
        # circular mean on x for wrapped maps
        ang = [2 * math.pi * (i % W) / W for i in idxs]
        mx = (math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang))
              / (2 * math.pi) * W) % W if d.get("wrap_x") else sum(i % W for i in idxs) / len(idxs)
        my = sum(i // W for i in idxs) / len(idxs)
        best = min(idxs, key=lambda i: (min(abs(i % W - mx), W - abs(i % W - mx))
                                        if d.get("wrap_x") else abs(i % W - mx)) ** 2 + (i // W - my) ** 2)
        cx0, cy = centers[(best % W, best // W)]
        for off in offsets:
            if visible(cx0 + off):
                draw_text_centered(dr, cx0 + off, cy, f"{aid} ({len(idxs)})", font, (255, 255, 255),
                                   stroke=max(2, ss + 1), stroke_fill=(0, 0, 0))


def _legend(d, layer, img_w, ss, s_final):
    """Build the legend strip (supersampled coordinates)."""
    items = []  # (kind, colour/extra, label)
    W, H = d["width"], d["height"]
    ter_names = d["terrain_types"]
    feat_names = d["feature_types"]
    if layer in ("terrain", "plain", "resources", "startbias"):
        present_t = Counter(_name(ter_names, t) for t, p in zip(d["terrain"], d["plot_type"]))
        for tname in TERRAIN_COLORS:
            if tname in ("TERRAIN_MOUNTAIN", "TERRAIN_HILL"):
                continue
            if present_t.get(tname):
                items.append(("hex", TERRAIN_COLORS[tname], short_name(tname, "TERRAIN_")))
        if any(d["lake"]):
            items.append(("hex", LAKE_COLOR, "Lake"))
        items.append(("hills", None, "Hills"))
        items.append(("mountain", None, "Mountain"))
        if layer != "plain":
            fpresent = Counter(_name(feat_names, f) for f in d["feature"] if f is not None and f >= 0)
            for fname in ("FEATURE_FOREST", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_FLOOD_PLAINS",
                          "FEATURE_OASIS", "FEATURE_ICE", "FEATURE_ATOLL", "FEATURE_FALLOUT"):
                if fpresent.get(fname):
                    items.append(("feature", fname, short_name(fname, "FEATURE_")))
            if any(is_natural_wonder(f) for f in fpresent if f):
                items.append(("wonder", None, "Natural wonder"))
        items.append(("river", None, "River"))
        if layer in ("terrain", "resources"):
            for cls in ("strategic", "luxury", "bonus"):
                items.append(("res", RES_COLORS[cls], cls.capitalize()))
    elif layer == "continents":
        for k, nm in CONTINENT_NAMES.items():
            items.append(("hex", CONTINENT_COLORS[k], f"{k} {nm}"))
        items.append(("river", None, "River"))
    elif layer == "elevation":
        for k in (PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN):
            items.append(("hex", ELEV_COLORS[k], PLOT_NAMES[k].capitalize()))
        items.append(("hex", LAKE_COLOR, "Lake"))
        items.append(("river", None, "River"))
    elif layer == "areas":
        na = len(set(d["area"]))
        items.append(("text", None, f"colour = area id ({na} areas); labels: id (plots), water darker"))
    items.append(("major", None, "Major start"))
    items.append(("minor", None, "City-state"))

    fs = max(10, min(16, s_final * 0.9)) * ss
    font = get_font(fs)
    sw = fs * 1.2  # swatch size
    pad = 8 * ss
    gap = 18 * ss
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # layout
    rows, cur, x = [], [], pad
    for it in items:
        tw = text_size(tmp, it[2], font)[0]
        need = (0 if it[0] == "text" else sw + 6 * ss) + tw + gap
        if cur and x + need > img_w - pad:
            rows.append(cur)
            cur, x = [], pad
        cur.append((it, x))
        x += need
    if cur:
        rows.append(cur)
    row_h = sw + 8 * ss
    img = Image.new("RGB", (img_w, int(pad * 2 + row_h * len(rows))), (34, 36, 42))
    dr = ImageDraw.Draw(img)
    for r_i, row in enumerate(rows):
        cy = pad + r_i * row_h + row_h / 2
        for (kind, extra, label), x0 in row:
            cx = x0 + sw / 2
            hs = sw / 2
            hg = HexGeom(1, 1, hs, 0, 0)
            if kind == "hex":
                dr.polygon(hg.corners(cx, cy), fill=extra, outline=shade(extra, 0.7))
            elif kind == "hills":
                base = shade(TERRAIN_COLORS["TERRAIN_PLAINS"], 0.86)
                dr.polygon(hg.corners(cx, cy), fill=base)
                _draw_hills(dr, cx, cy - hs * 0.15, hs, shade(base, 0.6), max(1, int(hs / 6)))
            elif kind == "mountain":
                dr.polygon(hg.corners(cx, cy), fill=MOUNTAIN_FILL)
                _draw_mountain(dr, cx, cy, hs, "terrain")
            elif kind == "feature":
                base = TERRAIN_COLORS["TERRAIN_COAST" if extra == "FEATURE_ATOLL" else
                                      ("TERRAIN_DESERT" if extra in ("FEATURE_OASIS", "FEATURE_FLOOD_PLAINS")
                                       else "TERRAIN_GRASS")]
                fc = feature_tint(extra, base)
                dr.polygon(hg.corners(cx, cy), fill=fc)
                _draw_feature(dr, cx, cy, hs, extra, fc, PLOT_LAND, max(1, int(hs / 6)))
            elif kind == "wonder":
                dr.polygon(hg.corners(cx, cy), fill=TERRAIN_COLORS["TERRAIN_GRASS"])
                _draw_feature(dr, cx, cy, hs, "FEATURE_XWONDER", None, PLOT_LAND, max(1, int(hs / 6)))
            elif kind == "river":
                dr.line([(x0, cy + hs * 0.6), (x0 + sw, cy - hs * 0.6)], fill=RIVER_COLOR,
                        width=max(2, int(hs / 3)))
            elif kind == "res":
                r = hs * 0.55
                dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=extra, outline=(0, 0, 0), width=ss)
            elif kind == "major":
                r = hs * 0.8
                dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=START_MAJOR, outline=START_MAJOR_EDGE,
                           width=max(2, int(r / 4)))
            elif kind == "minor":
                r = hs * 0.6
                dr.rectangle([cx - r, cy - r, cx + r, cy + r], fill=START_MINOR, outline=START_MINOR_EDGE,
                             width=max(1, int(r / 4)))
            tx = x0 if kind == "text" else x0 + sw + 6 * ss
            tw, th, tl, tt = text_size(dr, label, font)
            dr.text((tx - tl, cy - th / 2 - tt), label, font=font, fill=TEXT)
    return img


# --------------------------------------------------------------------------------------------
# ASCII
# --------------------------------------------------------------------------------------------
TERRAIN_CHARS = {"TERRAIN_GRASS": "g", "TERRAIN_PLAINS": "p", "TERRAIN_DESERT": "d",
                 "TERRAIN_TUNDRA": "t", "TERRAIN_SNOW": "s", "TERRAIN_COAST": ".",
                 "TERRAIN_OCEAN": "~", "TERRAIN_MOUNTAIN": "^", "TERRAIN_HILL": "h"}
# start-plot symbols for majors: avoid letters used by terrain/hills/features
START_SYMBOLS = "0123456789ABCEHIKMNOQRUVWXYZ"
MINOR_SYMBOL = "&"


def _start_symbols(d):
    sym = {}
    k = 0
    for sp in sorted(d["start_plots"], key=lambda s: (bool(s.get("minor")), s.get("player", 0))):
        if sp.get("minor"):
            sym[(sp["x"], sp["y"])] = (MINOR_SYMBOL, sp)
        else:
            sym[(sp["x"], sp["y"])] = (START_SYMBOLS[k % len(START_SYMBOLS)], sp)
            k += 1
    return sym


def plot_char(d, i):
    pt = d["plot_type"][i]
    tname = _name(d["terrain_types"], d["terrain"][i])
    fname = _name(d["feature_types"], d["feature"][i])
    if fname and is_natural_wonder(fname):
        return "*"
    if fname == "FEATURE_ICE":
        return "#"
    if pt == PLOT_OCEAN:
        if d["lake"][i]:
            return "l"
        return "~" if tname == "TERRAIN_OCEAN" else "."
    if pt == PLOT_MOUNTAIN:
        return "^"
    if fname == "FEATURE_FOREST":
        return "F"
    if fname == "FEATURE_JUNGLE":
        return "J"
    ch = TERRAIN_CHARS.get(tname, "?")
    if pt == PLOT_HILLS:
        ch = ch.upper()
    return ch


def render_ascii(d, spaced=True):
    """One char per plot, north up, odd rows indented by one space (hex stagger)."""
    W, H = d["width"], d["height"]
    starts = _start_symbols(d)
    lines = []
    for y in range(H - 1, -1, -1):
        chars = []
        for x in range(W):
            if (x, y) in starts:
                chars.append(starts[(x, y)][0])
            else:
                chars.append(plot_char(d, y * W + x))
        indent = " " if (y & 1) else ""
        body = (" " if spaced else "").join(chars)
        lines.append(f"{y:3d} {indent}{body}")
    key = ("key: ~ ocean  . coast  l lake  g/p/d/t/s grass/plains/desert/tundra/snow (UPPER = hills)  "
           "^ mountain  F forest  J jungle  # ice  * natural wonder  0-9.. major start  & city-state")
    return "\n".join(lines + [key])


def map_stats(d):
    W, H = d["width"], d["height"]
    n = W * H
    tn, fn, rn = d["terrain_types"], d["feature_types"], d["resource_types"]
    out = []
    pct = lambda k: f"{k:6d} ({100.0 * k / n:5.1f}%)"
    water = sum(1 for p in d["plot_type"] if p == PLOT_OCEAN)
    lakes = sum(1 for i in range(n) if d["plot_type"][i] == PLOT_OCEAN and d["lake"][i])
    land = n - water
    out.append(f"== {d.get('script', '?')}  {d.get('world_size', '?')}  {W}x{H}  seed={d.get('seed', '?')}"
               f"  wrap_x={d.get('wrap_x')} wrap_y={d.get('wrap_y')}")
    out.append(f"plots {n}: land {pct(land)}  water {pct(water)}  (lake plots {lakes})")
    pc = Counter(d["plot_type"])
    out.append("plot types: " + "  ".join(f"{PLOT_NAMES.get(k, k)} {pct(v).strip()}" for k, v in sorted(pc.items())))
    if land:
        out.append(f"  hills {100.0 * pc.get(1, 0) / land:.1f}% of land, mountains {100.0 * pc.get(0, 0) / land:.1f}% of land")
    tc = Counter(_name(tn, t) for t in d["terrain"])
    out.append("terrain:")
    for k, v in tc.most_common():
        out.append(f"  {str(k):22s} {pct(v)}")
    fc = Counter(_name(fn, f) for f in d["feature"] if f >= 0)
    out.append("features:" + ("" if fc else " none"))
    for k, v in fc.most_common():
        tag = "  [natural wonder]" if is_natural_wonder(k) else ""
        out.append(f"  {str(k):22s} {v:6d}{tag}")
    rc = Counter(_name(rn, r) for r in d["resource"] if r >= 0)
    qty = Counter()
    for r, q in zip(d["resource"], d["resource_qty"]):
        if r >= 0:
            qty[_name(rn, r)] += q or 0
    out.append(f"resources: {sum(rc.values())} plots")
    for cls in ("strategic", "luxury", "bonus", "other"):
        items = [(k, v) for k, v in rc.most_common() if resource_class(k) == cls]
        if items:
            out.append(f"  {cls:9s} " + ", ".join(
                f"{short_name(k, 'RESOURCE_')} {v}" + (f" (qty {qty[k]})" if cls == "strategic" else "")
                for k, v in items))
    rw = sum(1 for v in d["river_w"] if v != -1)
    rnw = sum(1 for v in d["river_nw"] if v != -1)
    rne = sum(1 for v in d["river_ne"] if v != -1)
    river_plots = sum(1 for i in range(n) if d["river_w"][i] != -1 or d["river_nw"][i] != -1 or d["river_ne"][i] != -1)
    out.append(f"rivers: {rw + rnw + rne} edges (E {rw}, SE {rnw}, SW {rne}); plots flagged {river_plots}")
    ac = Counter(d["area"])
    land_areas = Counter(a for a, p in zip(d["area"], d["plot_type"]) if p != PLOT_OCEAN)
    water_areas = Counter(a for a, p in zip(d["area"], d["plot_type"]) if p == PLOT_OCEAN)
    out.append(f"areas: {len(ac)} total ({len(land_areas)} land, {len(water_areas)} water)")
    out.append("  biggest land:  " + ", ".join(f"#{a}:{v}" for a, v in land_areas.most_common(8)))
    out.append("  biggest water: " + ", ".join(f"#{a}:{v}" for a, v in water_areas.most_common(6)))
    cc = Counter(c for c, p in zip(d["continent"], d["plot_type"]) if p != PLOT_OCEAN)
    if cc:
        out.append("continent art (land): " + ", ".join(f"{CONTINENT_NAMES.get(k, k)} {v}" for k, v in sorted(cc.items())))
    syms = _start_symbols(d)
    out.append(f"start plots: {len(d['start_plots'])}")
    for (x, y), (sym, sp) in sorted(syms.items(), key=lambda kv: (bool(kv[1][1].get('minor')), kv[1][1].get('player', 0))):
        i = y * W + x
        desc = plot_char(d, i)
        out.append(f"  [{sym}] player {sp.get('player')!s:>2} {short_name(sp.get('civ') or '?', 'CIVILIZATION_'):18s}"
                   f" ({x},{y}) {'minor' if sp.get('minor') else 'major'}  plot '{desc}' area #{d['area'][i]}")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a c5maps dump JSON to PNG / ASCII.")
    ap.add_argument("dump", help="path to dump JSON")
    ap.add_argument("--png", help="output PNG path (default: <dump stem>.png, or <stem>_<layer>.png)")
    ap.add_argument("--no-png", action="store_true", help="skip PNG output")
    ap.add_argument("--ascii", action="store_true", help="print ASCII map + stats to stdout")
    ap.add_argument("--stats", action="store_true", help="print the stats block only")
    ap.add_argument("--compact", action="store_true", help="ASCII without spaces between plots")
    ap.add_argument("--hex", type=float, default=None,
                    help="hex circumradius in px (default: auto, ~2000px wide, max 28)")
    ap.add_argument("--layer", default="terrain", choices=LAYERS)
    ap.add_argument("--no-legend", action="store_true")
    ap.add_argument("--no-title", action="store_true")
    ap.add_argument("--labels", dest="labels", action="store_true", default=None,
                    help="force resource/city-state labels on (default: on when hex >= 14)")
    ap.add_argument("--no-labels", dest="labels", action="store_false")
    ap.add_argument("--no-grid", action="store_true", help="no hex outlines")
    ap.add_argument("--ss", type=int, default=2, help="supersampling factor (1 = fastest)")
    a = ap.parse_args(argv)

    d = load_dump(a.dump)
    if a.ascii:
        print(render_ascii(d, spaced=not a.compact))
        print()
    if a.ascii or a.stats:
        print(map_stats(d))
    if not a.no_png:
        out = a.png
        if not out:
            stem = os.path.splitext(a.dump)[0]
            out = stem + (".png" if a.layer == "terrain" else f"_{a.layer}.png")
        t0 = time.time()
        img = render_png(d, out, hex_size=a.hex, layer=a.layer, legend=not a.no_legend,
                         title=not a.no_title, labels=a.labels, ss=max(1, a.ss), grid=not a.no_grid)
        print(f"wrote {out} ({img.width}x{img.height}, {time.time() - t0:.2f}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
