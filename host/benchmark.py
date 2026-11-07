"""benchmark -- run a matrix of map scripts x sizes x seeds headless and aggregate host/metrics.py metrics.

  python host/benchmark.py [--scripts vp:Communitu_79a,Continents,...] [--sizes standard,huge]
         [--seeds 50 | --seed-list 1,2,3] [--workers 10] [--out out/bench] [--resume]
         [--baseline docs/metrics-baselines.json] [--no-keep-dumps]
  python host/benchmark.py --aggregate-only      # re-aggregate out/bench/runs.jsonl -> baseline JSON
  python host/benchmark.py --recompute           # recompute metrics from kept dumps, then aggregate
  python host/benchmark.py --report              # print markdown tables from the baseline JSON

Each run is `c5gen.py <script> --size S --seed N --no-render --quiet` (script default options, Worlds
default civ / city-state counts).  Per-run metrics go to <out>/runs.jsonl (one JSON object per line,
including failures); dumps are kept in <out>/dumps/<label>/ unless --no-keep-dumps.  Aggregates
(n, mean, median, p5, p10, p90, p95, min, max per metric, per script x size and pooled per size) are
written to the baseline JSON, rounded to 3 significant digits.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import metrics  # noqa: E402

DEFAULT_SCRIPTS = ["vp:Communitu_79a", "vp:Continental_Drift", "Continents", "SmallContinents", "vp:Terra",
                   "Oval", "Archipelago"]
STAT_ORDER = ["n", "mean", "median", "p5", "p10", "p90", "p95", "min", "max"]


def label_of(script):
    s = script.split(":", 1)[1] if ":" in script and not os.path.isabs(script) else script
    return os.path.splitext(os.path.basename(s))[0]


def run_one(script, size, seed, out_dir, keep):
    label = label_of(script)
    d = os.path.join(out_dir, "dumps", label)
    os.makedirs(d, exist_ok=True)
    cmd = [sys.executable, os.path.join(HERE, "c5gen.py"), script, "--size", size, "--seed", str(seed),
           "--out", d, "--no-render", "--quiet"]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    wall = time.perf_counter() - t0
    rec = {"script": script, "label": label, "size": size, "seed": seed, "seconds": round(wall, 2)}
    found = glob.glob(os.path.join(d, f"*_{size}_{seed}.json"))
    if r.returncode != 0 or not found:
        rec["ok"] = False
        rec["error"] = (r.stderr or r.stdout)[-1500:]
        return rec
    path = found[0]
    try:
        with open(path, encoding="utf-8") as f:
            dump = json.load(f)
        m = metrics.compute_metrics(dump)
    except Exception as e:  # metric bug or unreadable dump: record, keep going
        rec["ok"] = False
        rec["error"] = "metrics: %r" % (e,)
        return rec
    rec["ok"] = True
    rec["dump"] = os.path.relpath(path, ROOT)
    rec["metrics"] = {k: m.get(k) for k in metrics.METRIC_KEYS}
    rec["dims"] = [m["width"], m["height"]]
    if not keep:
        for ext in (".json", ".log"):
            try:
                os.remove(os.path.splitext(path)[0] + ext)
            except OSError:
                pass
    return rec


def _metrics_of_file(path):
    with open(path, encoding="utf-8") as f:
        m = metrics.compute_metrics(json.load(f))
    return {k: m.get(k) for k in metrics.METRIC_KEYS}


# ------------------------------------------------------------------------------------------------
# aggregation
# ------------------------------------------------------------------------------------------------
def percentile(sorted_v, p):
    """Linear interpolation (numpy default)."""
    if not sorted_v:
        return None
    k = (len(sorted_v) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (k - lo)


def sig(v):
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if v == 0:
        return 0
    if abs(v) >= 100:
        return round(v, 1) if abs(v) < 1000 else round(v)
    return float(f"{v:.3g}")


def summarize(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    st = {"n": len(v), "mean": sum(v) / len(v), "median": percentile(v, 50), "p5": percentile(v, 5),
          "p10": percentile(v, 10), "p90": percentile(v, 90), "p95": percentile(v, 95), "min": v[0], "max": v[-1]}
    return [st["n"]] + [sig(float(st[k])) for k in STAT_ORDER[1:]]


def read_runs(path):
    recs = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def latest_by_key(recs):
    out = {}
    for r in recs:
        out[(r["script"], r["size"], r["seed"])] = r
    return out


def aggregate(recs, meta):
    sizes = {}
    by_cell = {}
    for r in recs:
        if not r.get("ok"):
            continue
        by_cell.setdefault(r["size"], {}).setdefault(r["label"], []).append(r)
    for size, scripts in by_cell.items():
        sb = {"scripts": {}, "pooled": {}, "dims": {}}
        pooled_vals = {k: [] for k in metrics.METRIC_KEYS}
        for label, rs in sorted(scripts.items()):
            cell = {}
            for k in metrics.METRIC_KEYS:
                vals = [r["metrics"].get(k) for r in rs]
                cell[k] = summarize(vals)
                pooled_vals[k].extend(vals)
            sb["scripts"][label] = cell
            sb["dims"][label] = sorted({tuple(r.get("dims") or ()) for r in rs})
        # pooled: every archetype weighted equally (same seed count per script in the default matrix)
        for k in metrics.METRIC_KEYS:
            sb["pooled"][k] = summarize(pooled_vals[k])
        sizes[size] = sb
    fails = [{"script": r["script"], "size": r["size"], "seed": r["seed"], "error": (r.get("error") or "")[-300:]}
             for r in recs if not r.get("ok")]
    meta = dict(meta)
    meta["failures"] = fails
    meta["n_runs_ok"] = sum(1 for r in recs if r.get("ok"))
    return {"meta": meta, "stat_order": STAT_ORDER,
            "metrics": {k: metrics.METRIC_INFO[k] for k in metrics.METRIC_KEYS}, "sizes": sizes}


def write_baseline(b, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # compact: one line per metric array
    txt = json.dumps(b, indent=1, separators=(",", ": "))
    import re
    txt = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda mm: "[" + re.sub(r"\s+", " ", mm.group(1)) + "]", txt)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt + "\n")


# ------------------------------------------------------------------------------------------------
# markdown report helper
# ------------------------------------------------------------------------------------------------
REPORT_KEYS = ["land_pct", "coast_pct_of_sea", "land_per_civ", "largest_landmass_pct", "landmasses_30",
               "islands_1_5", "grass_pct", "plains_pct", "desert_pct", "tundra_pct", "snow_pct", "hills_pct",
               "mountain_pct", "forest_pct", "jungle_pct", "marsh_pct", "ice_pct_of_water",
               "river_edges_per100", "river_land_pct", "fresh_water_pct", "lake_tiles_per100",
               "strategic_per100", "luxury_per100", "bonus_per100", "luxury_types",
               "iron_qty_per_civ", "horse_qty_per_civ", "coal_qty_per_civ", "oil_qty_per_civ",
               "aluminum_qty_per_civ", "uranium_qty_per_civ", "natural_wonders",
               "cap_nn_mean", "cap_nn_min", "cap_cs_min", "cap_coastal_pct", "cap_river_pct", "cap_fresh_pct",
               "cap_hills_pct", "cap_land_r3_mean", "cap_lux_r3_mean", "caps_on_largest", "cap_landmasses",
               "cap_isolated", "cs_nn_min", "cs_cap_min", "cs_coastal_pct",
               "polar_land_pct", "cold_lat_mean", "desert_lat_mean", "desert_floodplain_pct"]


def md_report(b, keys=None):
    keys = keys or REPORT_KEYS
    order = b["stat_order"]
    ix = {k: i for i, k in enumerate(order)}
    out = []
    for size in metrics.SIZE_ORDER:
        if size not in b["sizes"]:
            continue
        sb = b["sizes"][size]
        labels = list(sb["scripts"])
        out.append(f"### {size}\n")
        dims = ", ".join(f"{lab} " + "/".join(f"{w}x{h}" for w, h in sb["dims"][lab]) for lab in labels)
        out.append(f"Map dimensions: {dims}.\n")
        out.append("| metric | " + " | ".join(labels) + " | **pooled** |")
        out.append("|---|" + "---|" * (len(labels) + 1))
        for k in keys:
            info = b["metrics"][k]
            cells = []
            for lab in labels + ["__pooled__"]:
                a = sb["pooled"][k] if lab == "__pooled__" else sb["scripts"][lab].get(k)
                if not a:
                    cells.append("-")
                    continue
                med, p10, p90 = a[ix["median"]], a[ix["p10"]], a[ix["p90"]]
                c = f"{metrics.fmt(float(med), info['unit'])} [{metrics.fmt(float(p10), info['unit'])}–{metrics.fmt(float(p90), info['unit'])}]"
                cells.append(f"**{c}**" if lab == "__pooled__" else c)
            out.append(f"| {info['label']} | " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scripts", default=",".join(DEFAULT_SCRIPTS))
    ap.add_argument("--sizes", default="standard,huge")
    ap.add_argument("--seeds", type=int, default=30, help="seeds 1..N")
    ap.add_argument("--seed-list", default=None)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "bench"))
    ap.add_argument("--baseline", default=metrics.DEFAULT_BASELINE)
    ap.add_argument("--resume", action="store_true", help="skip runs already ok in runs.jsonl")
    ap.add_argument("--no-keep-dumps", action="store_true")
    ap.add_argument("--aggregate-only", action="store_true")
    ap.add_argument("--recompute", action="store_true", help="recompute metrics from kept dumps")
    ap.add_argument("--report", action="store_true", help="print markdown tables from the baseline JSON")
    a = ap.parse_args(argv)

    if a.report:
        with open(a.baseline, encoding="utf-8") as f:
            print(md_report(json.load(f)))
        return 0

    runs_path = os.path.join(a.out, "runs.jsonl")
    scripts = [s.strip() for s in a.scripts.split(",") if s.strip()]
    sizes = [s.strip() for s in a.sizes.split(",") if s.strip()]
    seeds = [int(s) for s in a.seed_list.split(",")] if a.seed_list else list(range(1, a.seeds + 1))
    meta = {"generated": datetime.date.today().isoformat(), "scripts": scripts, "sizes": sizes,
            "seeds": f"{seeds[0]}..{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) else seeds,
            "options": "script defaults; Worlds default civ/city-state counts; areas=literal; runtime=lua51",
            "percentiles": "linear interpolation; pooled = all scripts of that size, equal seeds per script"}

    if a.recompute:
        recs = list(latest_by_key(read_runs(runs_path)).values())
        todo = [r for r in recs if r.get("ok") and r.get("dump") and os.path.exists(os.path.join(ROOT, r["dump"]))]
        with ProcessPoolExecutor(max_workers=a.workers) as ex:
            for r, m in zip(todo, ex.map(_metrics_of_file, [os.path.join(ROOT, r["dump"]) for r in todo],
                                         chunksize=8)):
                r["metrics"] = m
        print(f"benchmark: recomputed metrics for {len(todo)} kept dumps")
        with open(runs_path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        a.aggregate_only = True

    if not a.aggregate_only:
        os.makedirs(a.out, exist_ok=True)
        done = latest_by_key(read_runs(runs_path)) if a.resume else {}
        if not a.resume and os.path.exists(runs_path):
            os.remove(runs_path)
        jobs = [(s, z, n) for z in sizes for s in scripts for n in seeds
                if not (done.get((s, z, n)) or {}).get("ok")]
        # longest first (huge before standard) for better packing
        jobs.sort(key=lambda j: (j[1] != "huge", j[0], j[2]))
        print(f"benchmark: {len(jobs)} runs, {a.workers} workers -> {runs_path}", flush=True)
        t0 = time.perf_counter()
        nfail = 0
        with ProcessPoolExecutor(max_workers=a.workers) as ex, open(runs_path, "a", encoding="utf-8") as fo:
            futs = [ex.submit(run_one, s, z, n, a.out, not a.no_keep_dumps) for s, z, n in jobs]
            for k, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                fo.write(json.dumps(r) + "\n")
                fo.flush()
                if not r["ok"]:
                    nfail += 1
                    print(f"  FAIL {r['script']} {r['size']} seed {r['seed']}: {r['error'][-200:]}", flush=True)
                if k % 25 == 0 or k == len(jobs):
                    print(f"  {k}/{len(jobs)} done, {nfail} failed, {time.perf_counter() - t0:.0f}s", flush=True)
        meta["wall_seconds"] = round(time.perf_counter() - t0)
        meta["workers"] = a.workers

    recs = list(latest_by_key(read_runs(runs_path)).values())
    recs = [r for r in recs if r["script"] in scripts and r["size"] in sizes and r["seed"] in seeds]
    if a.aggregate_only and os.path.exists(a.baseline):
        try:
            with open(a.baseline, encoding="utf-8") as f:
                old = json.load(f)["meta"]
            for k in ("wall_seconds", "workers"):
                if k in old:
                    meta[k] = old[k]
        except (OSError, ValueError, KeyError):
            pass
    secs = {}
    for r in recs:
        secs.setdefault(f"{r['label']}/{r['size']}", []).append(r.get("seconds", 0))
    meta["run_seconds_mean"] = {k: round(sum(v) / len(v), 1) for k, v in sorted(secs.items())}
    b = aggregate(recs, meta)
    write_baseline(b, a.baseline)
    print(f"benchmark: {b['meta']['n_runs_ok']} ok runs, {len(b['meta']['failures'])} failures -> {a.baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
