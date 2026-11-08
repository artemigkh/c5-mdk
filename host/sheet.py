#!/usr/bin/env python3
"""Contact sheet: run a map script several times (seeds, --option / --define values) in parallel and
compose the renders into one labelled PNG with land metrics under each tile.

Contact sheets are for SHAPE review: tiles use the `mask` layer by default (land / hills / mountains /
water only; no resources or features) with a plain white star on each major capital (--no-stars: none;
--starts: full markers + names).  Review capitals, city-states and resources one map at
a time with host/explorer.py, or add --explorer here to build that page from the same runs.

    python host/sheet.py Continents --size duel --seeds 1,2,3
    python host/sheet.py Continents --size standard --seeds 1,2,3,4 --explorer
    python host/sheet.py MyMap.lua --size large --seed 1 --cols 3 --tile-w 640 \\
        --run "thin|--define W=0.18 --define D=120" --run "wide|--define W=0.36" \\
        --common "--define D=300" --grep "\\[MyMap\\] fit"
    python host/sheet.py MyMap.lua --spec sweep.json --out out/sheets/mymap_w.png --reuse

Each --run is "label|<extra c5gen args>" (args split with shlex); --common args are appended to every
run.  --seeds 1,2,3 alone means one run per seed ("seed N"); combined with --run it gives a grid
(rows = runs, columns = seeds).  --spec file.json holds [{"label": ..., "args": [...]}, ...] or
{"runs": [...], "rows": [row headers], "cols": [column headers]} (runs filled row-major).

Output: <out>.png (default out/sheets/<script>_<size>_seed<n>.png), and next to it a folder
<out stem>/ with summary.json and runs/<label>/ (one c5gen --out folder per run); with --explorer also
<out stem>/explorer/explorer.html plus full-size terrain / resources PNGs per run.
Exit status 1 if any run failed.
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "render"))
sys.path.insert(0, HERE)

# Metric keys (metrics.METRIC_KEYS) shown under each tile.
MET_LAND, MET_LM30, MET_LARGEST, MET_TINY = "land_pct", "landmasses_30", "largest_landmass_pct", "islands_1_5"
GREP_LINES = 2          # matching log lines shown per tile
GREP_CHARS = 90         # ... each trimmed to this many characters


# ================================================================================================
# Running (worker process)
# ================================================================================================
def run_one(job):
    """Run c5gen for one cell, compute metrics, render the tile PNG.  Separate process (rendering is
    pure Python and GIL-bound)."""
    run_dir = job["run_dir"]
    os.makedirs(run_dir, exist_ok=True)
    rec = {"label": job["label"], "seed": job["seed"], "args": job["args"], "run_dir": run_dir}
    cmd = [sys.executable, os.path.join(ROOT, "host", "c5gen.py"), job["script"], "--size", job["size"],
           "--seed", str(job["seed"])] + job["args"] + ["--out", run_dir, "--no-render", "--quiet"]
    stamp_path = os.path.join(run_dir, "cmd.json")
    stamp = {"cmd": cmd[2:]}
    found = glob.glob(os.path.join(run_dir, "*.json"))
    found = [p for p in found if os.path.basename(p) != "cmd.json"]
    reused = False
    if job["reuse"] and len(found) == 1 and os.path.exists(stamp_path):
        try:
            with open(stamp_path, encoding="utf-8") as f:
                reused = json.load(f) == stamp
        except (OSError, ValueError):
            reused = False
    t0 = time.perf_counter()
    if not reused:
        for p in glob.glob(os.path.join(run_dir, "*")):
            if os.path.isfile(p):
                os.remove(p)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        found = [p for p in glob.glob(os.path.join(run_dir, "*.json"))]
        if r.returncode != 0 or len(found) != 1:
            rec.update(ok=False, seconds=round(time.perf_counter() - t0, 1),
                       error=(r.stderr or r.stdout or "exit %d, no dump" % r.returncode)[-3000:])
            return rec
        with open(stamp_path, "w", encoding="utf-8") as f:
            json.dump(stamp, f)
    rec["seconds"] = round(time.perf_counter() - t0, 1)
    rec["reused"] = reused
    dump_path = found[0]
    rec["dump"] = os.path.relpath(dump_path, ROOT)
    try:
        import metrics
        import render_map
        with open(dump_path, encoding="utf-8") as f:
            dump = json.load(f)
        m = metrics.compute_metrics(dump)
        rec["metrics"] = {k: m.get(k) for k in (MET_LAND, MET_LM30, MET_LARGEST, MET_TINY)}
        d = render_map.load_dump(dump_path)
        # map width = sqrt(3) * hex * cols, plus a 6 px dark pad on each side (cropped below)
        cols = d["width"] + (0 if d.get("wrap_x") else 0.5)
        img = render_map.render_png(d, None, hex_size=job["tile_w"] / (3 ** 0.5 * cols), layer=job["layer"],
                                    legend=False, title=False, labels=False, starts=job.get("starts", "stars"), grid=False, ss=2)
        pad = 6
        img = img.crop((pad, pad, img.width - pad, img.height - pad))
        png = os.path.join(run_dir, "tile_%s.png" % job["layer"])
        img.save(png)
        rec["png"] = png
        rec["map"] = "%dx%d" % (d["width"], d["height"])
    except Exception:  # metrics/render bug: record and keep going
        import traceback
        rec.update(ok=False, error="post-processing: " + traceback.format_exc()[-2000:])
        return rec
    log_path = os.path.splitext(dump_path)[0] + ".log"
    rec["grep"] = grep_log(log_path, job["grep"])
    rec["warnings"] = [w[len("[c5maps] WARNING: "):] for w in grep_log(log_path, r"\[c5maps\] WARNING: ", 0)]
    rec["ok"] = True
    return rec


def grep_log(log_path, pattern, max_lines=GREP_LINES):
    """First `max_lines` (0 = all) distinct log lines matching `pattern` (from the match on; trimmed
    to GREP_CHARS when max_lines > 0)."""
    if not pattern:
        return []
    rx, out = re.compile(pattern), []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                mt = rx.search(line)
                if not mt:
                    continue
                s = " ".join(line[mt.start():].split())     # tabs / runs of spaces -> one space
                if max_lines and len(s) > GREP_CHARS:
                    s = s[:GREP_CHARS - 3] + "..."
                if s not in out:
                    out.append(s)
                if max_lines and len(out) >= max_lines:
                    break
    except OSError:
        pass
    return out


def error_lines(err, n=6):
    """Most useful n lines of a failure: the error message (text before a Lua 'stack traceback:'),
    then the innermost traceback frames.  Tabs expanded."""
    lines = [ln.replace("\t", "  ").rstrip() for ln in (err or "not run").strip().splitlines()]
    lines = [ln for ln in lines if ln.strip() and not ln.startswith("(log:")]
    if "stack traceback:" in lines:
        k = lines.index("stack traceback:")
        head = [ln for ln in lines[:k] if not ln.startswith("c5gen: Lua error")][-3:] or lines[:k][-1:]
        return (head + lines[k + 1:])[:n]
    errs = [ln for ln in lines if "error:" in ln]     # e.g. argparse "c5gen.py: error: ..."
    return (errs or lines)[-n:]


# ================================================================================================
# Contact sheet
# ================================================================================================
def _font(size, bold=False):
    from PIL import ImageFont
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _fit(dr, s, font, width):
    """Trim `s` with '...' so it fits in `width` px."""
    if dr.textlength(s, font=font) <= width:
        return s
    while s and dr.textlength(s + "...", font=font) > width:
        s = s[:-1]
    return s + "..."


def fmt_metrics(m):
    def g(k, f):
        v = (m or {}).get(k)
        return "?" if v is None else (f % v)
    return (f"land {g(MET_LAND, '%.1f')}%   landmasses(>=30) {g(MET_LM30, '%d')}   "
            f"largest {g(MET_LARGEST, '%.0f')}%   islets(1-5) {g(MET_TINY, '%d')}")


def note_lines(r):
    """Lines under a tile's metrics: --grep matches (grey), then c5gen warnings (orange, max 2)."""
    w = r.get("warnings") or []
    lines = [(g, (90, 90, 90)) for g in (r.get("grep") or [])]
    lines += [("warning: " + x, (200, 100, 0)) for x in w[:2]]
    if len(w) > 2:
        lines[-1] = (lines[-1][0] + f"  (+{len(w) - 2} more)", lines[-1][1])
    return lines


def compose_sheet(plan, recs, path, title, subtitle, tile_w, n_grep):
    from PIL import Image, ImageDraw
    F = {"title": _font(28, True), "sub": _font(16), "head": _font(20, True), "row": _font(20, True),
         "cap": _font(17, True), "args": _font(14), "met": _font(15), "grep": _font(14), "err": _font(13),
         "errb": _font(14, True)}
    cells, cols = plan["cells"], plan["cols"]
    rows = (len(cells) + cols - 1) // cols
    tiles = {}
    for c in cells:
        r = recs.get(c["key"])
        if r and r.get("ok") and r.get("png"):
            im = Image.open(r["png"]).convert("RGB")
            if im.width != tile_w:
                im = im.resize((tile_w, max(1, round(im.height * tile_w / im.width))), Image.LANCZOS)
            tiles[c["key"]] = im
    map_h = max((im.height for im in tiles.values()), default=round(tile_w * 0.6))
    has_args = any(c["show_args"] for c in cells)
    CAP_H = 26 + (18 if has_args else 0)
    MET_H = 24 + 17 * n_grep + 6
    GAP = 16
    LEFT = 40 if plan.get("row_labels") else 0
    head_h = 30 if plan.get("col_labels") else 0
    TOP = 50 + (24 if subtitle else 0) + head_h
    cell_h = CAP_H + map_h + MET_H
    W = LEFT + cols * tile_w + (cols + 1) * GAP
    H = TOP + rows * cell_h + (rows + 1) * GAP
    bg = (250, 250, 248)
    sheet = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(sheet)

    dr.text((GAP, 12), _fit(dr, title, F["title"], W - 2 * GAP), fill=(20, 20, 20), font=F["title"])
    if subtitle:
        dr.text((GAP, 48), _fit(dr, subtitle, F["sub"], W - 2 * GAP), fill=(90, 90, 90), font=F["sub"])
    for ci, name in enumerate(plan.get("col_labels") or []):
        x0 = LEFT + GAP + ci * (tile_w + GAP)
        name = _fit(dr, str(name), F["head"], tile_w)
        tw = dr.textlength(name, font=F["head"])
        dr.text((x0 + (tile_w - tw) / 2, TOP - 28), name, fill=(40, 40, 40), font=F["head"])
    for ri, name in enumerate(plan.get("row_labels") or []):
        if ri >= rows:
            break
        y0 = TOP + GAP + ri * (cell_h + GAP)
        name = _fit(dr, str(name), F["row"], cell_h)
        lab = Image.new("RGB", (int(dr.textlength(name, font=F["row"])) + 8, 28), bg)
        ImageDraw.Draw(lab).text((4, 2), name, fill=(30, 30, 30), font=F["row"])
        lab = lab.rotate(90, expand=True)
        sheet.paste(lab, ((LEFT + GAP - lab.width) // 2, y0 + (cell_h - lab.height) // 2))

    for idx, c in enumerate(cells):
        ri, ci = divmod(idx, cols)
        x0 = LEFT + GAP + ci * (tile_w + GAP)
        y0 = TOP + GAP + ri * (cell_h + GAP)
        r = recs.get(c["key"], {})
        dr.text((x0, y0 + 2), _fit(dr, c["caption"], F["cap"], tile_w), fill=(20, 20, 20), font=F["cap"])
        if c["show_args"]:
            dr.text((x0, y0 + 24), _fit(dr, " ".join(c["args"]) or "(no extra args)", F["args"], tile_w),
                    fill=(110, 110, 110), font=F["args"])
        my = y0 + CAP_H
        if c["key"] in tiles:
            im = tiles[c["key"]]
            sheet.paste(im, (x0, my))
            dr.rectangle([x0 - 1, my - 1, x0 + tile_w, my + im.height], outline=(160, 160, 160))
            dr.text((x0, my + map_h + 4), _fit(dr, fmt_metrics(r.get("metrics")), F["met"], tile_w),
                    fill=(30, 30, 30), font=F["met"])
            for gi, (gl, col) in enumerate(note_lines(r)):
                dr.text((x0, my + map_h + 24 + 17 * gi), _fit(dr, gl, F["grep"], tile_w),
                        fill=col, font=F["grep"])
        else:
            dr.rectangle([x0, my, x0 + tile_w - 1, my + map_h - 1], fill=(200, 45, 45))
            dr.text((x0 + 10, my + 8), _fit(dr, "FAILED  " + c["caption"], F["errb"], tile_w - 20),
                    fill=(255, 255, 255), font=F["errb"])
            yy = my + 34
            wrap = max(20, int((tile_w - 20) / 7.2))
            for li, ln in enumerate(error_lines(r.get("error"))):
                f = F["errb"] if li == 0 else F["err"]
                for part in textwrap.wrap(ln, wrap, subsequent_indent="    ")[:3]:
                    if yy > my + map_h - 18:
                        break
                    dr.text((x0 + 10, yy), part, fill=(255, 240, 240), font=f)
                    yy += 17
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sheet.save(path)
    return sheet.size


# ================================================================================================
# Plan
# ================================================================================================
def parse_seeds(s):
    try:
        return [int(x) for x in s.replace(" ", "").split(",") if x]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--seeds expects a comma list of integers, got {s!r}")


def parse_run(s):
    if "|" not in s:
        raise argparse.ArgumentTypeError(f"--run expects 'label|<c5gen args>', got {s!r}")
    label, args = s.split("|", 1)
    return {"label": label.strip(), "args": shlex.split(args)}


def safe_name(s):
    return re.sub(r"[^\w.=+-]+", "_", s).strip("_") or "run"


def build_plan(a, ap):
    """Return {"cells": [...], "cols": n, "row_labels": [...]|None, "col_labels": [...]|None}.
    Each cell: key (unique run folder name), caption, seed, args (run-specific), show_args."""
    runs, row_labels, col_labels = list(a.run or []), None, None
    if a.spec:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
        if isinstance(spec, dict):
            row_labels, col_labels = spec.get("rows"), spec.get("cols")
            spec = spec.get("runs") or []
        for e in spec:
            if not isinstance(e, dict) or "label" not in e:
                ap.error(f"--spec entries need a 'label' (and 'args'): {e!r}")
            args = e.get("args") or []
            runs.append({"label": str(e["label"]),
                         "args": shlex.split(args) if isinstance(args, str) else [str(x) for x in args],
                         "seed": e.get("seed")})
    cells = []
    if runs and a.seeds:            # grid: rows = runs, columns = seeds
        for rn in runs:
            for sd in a.seeds:
                cells.append({"label": f"{rn['label']} s{sd}", "caption": f"{rn['label']}  seed {sd}",
                              "seed": sd, "args": rn["args"], "show_args": True})
        row_labels = row_labels or [rn["label"] for rn in runs]
        col_labels = col_labels or [f"seed {sd}" for sd in a.seeds]
        cols = len(a.seeds)
    elif runs:
        for rn in runs:
            sd = rn.get("seed") if rn.get("seed") is not None else a.seed
            cells.append({"label": rn["label"], "caption": rn["label"] + ("" if sd == a.seed else f"  seed {sd}"),
                          "seed": sd, "args": rn["args"], "show_args": True})
        cols = len(col_labels) if col_labels else a.cols
    elif a.seeds:
        for sd in a.seeds:
            cells.append({"label": f"seed {sd}", "caption": f"seed {sd}", "seed": sd, "args": [],
                          "show_args": False})
        cols = a.cols
    else:
        ap.error("nothing to run: give --seeds, --run and/or --spec")
    seen = {}
    for c in cells:
        k = safe_name(c["label"])
        seen[k] = seen.get(k, 0) + 1
        c["key"] = k if seen[k] == 1 else f"{k}_{seen[k]}"
    cols = max(1, min(cols, len(cells)))
    return {"cells": cells, "cols": cols, "row_labels": row_labels, "col_labels": col_labels}


# ================================================================================================
# CLI
# ================================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a map script several times and compose a labelled contact sheet.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("script", help="map script, as for c5gen.py (name or path)")
    ap.add_argument("--size", default="standard", choices=["duel", "tiny", "small", "standard", "large", "huge"])
    ap.add_argument("--seed", type=int, default=1, help="seed for --run / --spec cells (default 1)")
    ap.add_argument("--seeds", type=parse_seeds, default=None,
                    help="comma list: one cell per seed; with --run/--spec, a runs x seeds grid")
    ap.add_argument("--run", action="append", type=parse_run, metavar="'LABEL|ARGS'",
                    help="one cell: label and extra c5gen args, e.g. 'thin|--define W=0.18 --option 4=2'")
    ap.add_argument("--spec", help="JSON file with runs (see module doc)")
    ap.add_argument("--common", default="", help="c5gen args appended to every run, e.g. '--define D=300' (a single token: --common=--foo)")
    ap.add_argument("--cols", type=int, default=3, help="tiles per row (default 3)")
    ap.add_argument("--starts", action="store_true",
                    help="draw full start-plot markers with civ / city-state names on the tiles (default: a plain "
                         "star on each major capital; review city-states and names in the explorer)")
    ap.add_argument("--no-stars", action="store_true", help="no capital stars on the tiles (pure shape)")
    ap.add_argument("--layer", default="mask",
                    help="render layer for the tiles (default mask = shape only; grids are for shape review, "
                         "use --explorer / host/explorer.py for starts, city-states and resources)")
    ap.add_argument("--tile-w", type=int, default=640, help="tile width in px (default 640)")
    ap.add_argument("--grep", default=None, metavar="REGEX",
                    help="show the first matching log lines under each tile, e.g. '\\[MyMap\\] fit'")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None, help="sheet PNG (default out/sheets/<script>_<size>_seed<n>.png)")
    ap.add_argument("--reuse", action="store_true",
                    help="skip runs whose folder already holds a dump from the identical c5gen command")
    ap.add_argument("--explorer", action="store_true",
                    help="after the sheet, build <out stem>/explorer/explorer.html (host/explorer.py) from the "
                         "same runs: one map at a time with starts, city-states and resources")
    a = ap.parse_args(argv)

    import render_map
    if a.layer not in render_map.LAYERS:
        ap.error(f"--layer must be one of {', '.join(render_map.LAYERS)}")
    if a.grep:
        try:
            re.compile(a.grep)
        except re.error as e:
            ap.error(f"--grep: {e}")
    common = shlex.split(a.common)
    plan = build_plan(a, ap)

    stem = os.path.splitext(os.path.basename(a.script))[0]
    if a.out:
        out_png = os.path.abspath(a.out)
    else:
        seed_part = ("seeds" + "-".join(map(str, a.seeds))) if (a.seeds and not (a.run or a.spec)) else f"seed{a.seed}"
        out_png = os.path.join(ROOT, "out", "sheets", f"{safe_name(stem)}_{a.size}_{seed_part}.png")
    work = os.path.splitext(out_png)[0]
    os.makedirs(work, exist_ok=True)

    jobs = {}
    for c in plan["cells"]:
        jobs[c["key"]] = {"label": c["label"], "script": a.script, "size": a.size, "seed": c["seed"],
                          "args": c["args"] + common, "layer": a.layer, "tile_w": a.tile_w, "grep": a.grep,
                          "starts": True if a.starts else (False if a.no_stars else "stars"),
                          "reuse": a.reuse, "run_dir": os.path.join(work, "runs", c["key"])}
    print(f"sheet {stem} {a.size}: {len(jobs)} run(s), {a.workers} worker(s) -> {os.path.relpath(out_png, ROOT)}",
          flush=True)
    recs, t0 = {}, time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=max(1, min(a.workers, len(jobs)))) as ex:
        futs = {ex.submit(run_one, j): k for k, j in jobs.items()}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            k = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # worker crash
                r = {"label": jobs[k]["label"], "seed": jobs[k]["seed"], "args": jobs[k]["args"],
                     "ok": False, "error": repr(e)}
            recs[k] = r
            if r.get("ok"):
                land = (r.get("metrics") or {}).get(MET_LAND)
                land = "?" if land is None else "%.1f%%" % land
                note = "reused" if r.get("reused") else f"{r.get('seconds', 0):.0f}s"
                print(f"[{i}/{len(jobs)}] ok   {r['label']:<28} land {land:>6}  ({note})", flush=True)
                for w in r.get("warnings") or []:
                    print(f"      warning: {w}", flush=True)
            else:
                msg = (error_lines(r.get("error"), 1) or [""])[0]
                print(f"[{i}/{len(jobs)}] FAIL {r['label']:<28} {msg[-110:]}", flush=True)

    seeds = sorted({c["seed"] for c in plan["cells"]})
    title = f"{stem}  {a.size}  " + (f"seed {seeds[0]}" if len(seeds) == 1 else "seeds " + ",".join(map(str, seeds)))
    if common:
        title += "   " + " ".join(common)
    subtitle = f"layer {a.layer}" + (f"   grep: {a.grep}" if a.grep else "")
    n_grep = max((len(note_lines(r)) for r in recs.values()), default=0)
    size = compose_sheet(plan, recs, out_png, title, subtitle, a.tile_w, n_grep)
    print(f"wrote {os.path.relpath(out_png, ROOT)} ({size[0]}x{size[1]})")

    print()
    hdr = f"{'label':<24} {'seed':>5} {'land%':>6} {'lm30':>4} {'big%':>4} {'isl':>4} {'sec':>5}  status"
    print(hdr)
    print("-" * len(hdr))
    summary = []
    for c in plan["cells"]:
        r = recs.get(c["key"], {})
        m = r.get("metrics") or {}
        f = lambda k, p: (p % m[k]) if m.get(k) is not None else "-"  # noqa: E731
        print(f"{c['label'][:24]:<24} {c['seed']:>5} {f(MET_LAND, '%.1f'):>6} {f(MET_LM30, '%d'):>4} "
              f"{f(MET_LARGEST, '%.0f'):>4} {f(MET_TINY, '%d'):>4} {r.get('seconds', 0):>5.0f}  "
              f"{'ok' if r.get('ok') else 'FAIL'}")
        e = {k: v for k, v in r.items() if k not in ("run_dir", "png")}
        e.update(key=c["key"], label=c["label"], seed=c["seed"], ok=bool(r.get("ok")))
        if r.get("png"):
            e["png"] = os.path.relpath(r["png"], ROOT)
        summary.append(e)
    summary_path = os.path.join(work, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump({"script": a.script, "size": a.size, "layer": a.layer, "common": common,
                   "sheet": os.path.relpath(out_png, ROOT), "runs": summary}, fh, indent=1)
    n_fail = sum(1 for e in summary if not e["ok"])
    print(f"\n{len(summary) - n_fail}/{len(summary)} runs ok in {time.perf_counter() - t0:.0f}s; "
          f"summary: {os.path.relpath(summary_path, ROOT)}")
    if a.explorer:
        import explorer
        print()
        explorer.build([work], workers=a.workers, grep=explorer.DEFAULT_GREP + ("|" + a.grep if a.grep else ""))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
