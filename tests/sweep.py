"""Full compatibility sweep: run every map script the harness can find through host/c5gen.py.

Usage:
  python tests/sweep.py                 # full sweep (every script x standard x seeds 1,2,3 + reference sizes)
  python tests/sweep.py --only Terra    # restrict to scripts whose spec contains the substring (repeatable)
  python tests/sweep.py --sizes duel --seeds 1 --no-ref
  python tests/sweep.py --report        # only re-print the summary of out/sweep/results.json
  python tests/sweep.py --areas floodfill --tag ff --seeds 1 2 --no-ref   # -> out/sweep/results_ff.json
  python tests/sweep.py --tag teams2 --no-ref --only Hemispheres --extra --teams 2   # extra c5gen args last
  python tests/sweep.py --option-sweep --sizes duel --seeds 1 --no-ref --tag options  # every option value once
  python tests/sweep.py --revalidate    # re-run validate_dump over the stored dumps
  python tests/sweep.py --write-compat  # regenerate docs/script-compat.md from all results*.json

Each run is a separate `c5gen.py` subprocess (fresh Lua state, timeout), driven by a multiprocessing
pool (default 8 workers).  Successful dumps are checked with tests/test_cli.validate_dump.  Results are
merged into out/sweep/results.json keyed by (spec, size, seed, areas), so partial re-runs update rows.

Status values: ok | invalid (ran, dump failed validation) | error (Lua error / nonzero exit) |
               timeout | unsupported (WorldBuilder map: needs a pre-loaded .Civ5Map, not run).
One PNG per script is kept (standard size, first seed); every other run uses --no-render.
"""
import argparse
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, HERE)
import c5gen  # noqa: E402

SWEEP_OUT = os.path.join(ROOT, "out", "sweep")
C5GEN = os.path.join(ROOT, "host", "c5gen.py")

# The seven reference scripts (eight files: Continental_Drift has two copies).
REFERENCE = ["vp:Communitu_79a", "mygames:Continental_Drift", "vp:Continental_Drift", "assets:Continents",
             "assets:SmallContinents", "assets:Terra", "assets:Oval", "assets:Archipelago"]
ALL_SIZES = ["duel", "tiny", "small", "standard", "large", "huge"]

# Triage of every script-side failure (see docs/script-compat.md).  spec -> (class, one-line cause)
#   b = genuine script bug under VP (would fail in game too, proven from the traceback + VP ASP source)
#   c = needs a non-default option / player setup (see WORKAROUND)
_CSD = ("b", "overrides `CanPlaceCityStateAt` and reads `self.cityStateData`; VP's ASP keeps impact layers in "
        "`self.impactData[ImpactLayers.*]` and never creates `cityStateData` (CP's own ASP still has it)")
_NTU = ("b", "overrides `AssignLuxuryRoles` and reads `self.iNumTypesUnassigned`, which VP's ASP no longer has")
_NWD = ("b", "overrides natural-wonder placement and reads `self.naturalWondersData`, which VP's ASP no longer has")
_FERT = ("b", "old Communitu_79a copy: `MeasureStartPlacementFertilityOfPlot` calls `ASP:Plot_GetFertility`, which "
         "exists nowhere (VP/CP provide the global `Plot_GetFertility` in MapmakerUtilities)")
_LUXW = ("b", "overrides `__InitLuxuryWeights` with region types 1-8 only; VP reclassifies a region as "
         "REGION_MOUNTAIN (9) / REGION_SNOW (10) when a civ has that start bias, then `ipairs(nil)` in "
         "`AssignLuxuryToRegion` (fails whenever such a civ is picked)")
KNOWN = {
    "assets:Four_Corners": _CSD, "assets:Highlands": _CSD, "assets:InlandSea": _CSD, "assets:Lakes": _CSD,
    "assets:North_vs_South": _CSD, "assets:Ring": _CSD, "assets:Skirmish": _CSD, "assets:West_vs_East": _CSD,
    "cp:Boreal": _CSD, "cp:Highlands": _CSD, "exp1:Boreal": _CSD, "dlc-sp3:Script_Random_China": _CSD,
    "assets:Great_Plains": _NTU, "dlc-sp1:Amazon": _NTU, "exp1:Amazon_XP": _NTU,
    "exp1:Europe": _NWD, "exp1:Great_Plains_XP": _NWD,
    "mygames:Communitu_79a": _FERT, "assets:Communitu_79a": _FERT,
    "exp1:Arborea": _LUXW, "exp1:Rainforest": _LUXW,
    "exp1:Frontier": ("b", "overrides `PlaceLuxuries` and uses `self.luxury_low_fert_compensation` (a local in VP's "
                      "ASP) and the vanilla `GetIndicesForLuxuryType` lists"),
    "exp1:Hemispheres": ("c", "designed for 2 teams; in a free-for-all it takes its vanilla 'random division' branch, "
                         "sets `self.method = 2` (CONTINENTAL) without `self.bArea`, so VP indexes "
                         "`self.landmass_areas[areaID]` = nil (seed-dependent crash, or duplicate start plots)"),
}
# Extra c5gen args that make a failing script run (verified by the sweep: --tag teams2 / workaround).
WORKAROUND = {
    "exp1:Hemispheres": "--teams 2 (option 6 'Team Setting' = Start Together, the default)",
    "mygames:Communitu_79a": "--option 16=1 (Override AssignStartingPlots = No); or use vp:Communitu_79a",
    "assets:Communitu_79a": "--option 16=1 (Override AssignStartingPlots = No); or use vp:Communitu_79a",
}
# VP replacement copies whose name differs from the original (same-name copies are found automatically)
VP_RENAMED = {"assets:Great_Plains": "vp:Great_Plains_XP", "dlc-sp1:Amazon": "vp:Amazon_XP"}


def worldbuilder_reason(path):
    """-> reason string if the script is a WorldBuilder hybrid (needs a pre-loaded .Civ5Map), else None."""
    name = os.path.basename(path)
    if name.startswith("WB_Script_"):
        return "WorldBuilder map (WB_Script_*: reads plot types from the .Civ5Map the exe pre-loads)"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    if re.search(r"Map\.LoadMap|\.Civ5Map", txt, re.I):
        return "WorldBuilder map (calls Map.LoadMap / references a .Civ5Map)"
    return None


def script_specs():
    """[(spec, tag, file, path)] for every script c5gen can find, spec = 'tag:stem'."""
    out = []
    for tag, f, p in c5gen.list_scripts():
        out.append(("%s:%s" % (tag, os.path.splitext(f)[0]), tag, f, p))
    return out


def safe_name(spec):
    tag, stem = spec.split(":", 1)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem + "." + tag)


def build_jobs(args):
    specs = script_specs()
    if args.only:
        specs = [s for s in specs if any(o.lower() in s[0].lower() for o in args.only)]
    jobs = []
    for spec, tag, f, path in specs:
        wb = worldbuilder_reason(path)
        sizes = list(args.sizes)
        if not args.no_ref and spec in REFERENCE:
            sizes = [s for s in ALL_SIZES if s in set(sizes) | set(args.ref_sizes)]
        for size in sizes:
            for seed in args.seeds:
                png = (size == args.png_size and seed == args.seeds[0]) and not args.no_png
                jobs.append({"spec": spec, "path": path, "size": size, "seed": seed, "areas": args.areas,
                             "png": png, "unsupported": wb, "timeout": args.timeout,
                             "extra": args.extra or [], "validate": not args.no_validate, "tag": args.tag})
    # longest first: big maps and known-slow scripts
    order = {s: i for i, s in enumerate(ALL_SIZES)}
    jobs.sort(key=lambda j: -order[j["size"]])
    return jobs


def list_options(path):
    """[(index, n_values, default)] from `c5gen --list-options`."""
    r = subprocess.run([sys.executable, C5GEN, path, "--list-options"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out, cur = [], None
    for line in r.stdout.splitlines():
        m = re.match(r"\s+option (\d+): .*\(default ([^ )]+)", line)
        if m:
            cur = [int(m.group(1)), 0, m.group(2)]
            out.append(cur)
        elif cur and re.match(r"\s+\d+ = ", line):
            cur[1] += 1
    return [tuple(o) for o in out]


def option_jobs(base_jobs, workers):
    """One job per (script, option, non-default value), on top of the first size/seed of each script."""
    firsts = {}
    for j in base_jobs:
        firsts.setdefault(j["spec"], j)
    specs = [j for j in firsts.values() if not j["unsupported"]]
    with multiprocessing.Pool(workers) as pool:
        opts = pool.map(list_options, [j["path"] for j in specs])
    jobs = []
    for j, ol in zip(specs, opts):
        for idx, nv, default in ol:
            for v in range(1, nv + 1):
                if str(v) == default:
                    continue
                jj = dict(j, extra=list(j["extra"]) + ["--option", "%d=%d" % (idx, v)], png=False,
                          option="%d=%d" % (idx, v))
                jobs.append(jj)
    return jobs


def run_job(job):
    rec = {k: job[k] for k in ("spec", "size", "seed", "areas")}
    if job.get("option"):
        rec["option"] = job["option"]
    rec["path"] = job["path"]
    if job["unsupported"]:
        rec.update(status="unsupported", seconds=0.0, error="unsupported: " + job["unsupported"])
        return rec
    name = safe_name(job["spec"])
    out_dir = os.path.join(SWEEP_OUT, name if job["areas"] == "literal" else name + "_" + job["areas"])
    if job.get("tag"):
        out_dir = os.path.join(SWEEP_OUT, "_" + job["tag"], os.path.basename(out_dir))
    if job.get("option"):
        out_dir = os.path.join(out_dir, "opt" + job["option"].replace("=", "-"))
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, C5GEN, job["path"], "--size", job["size"], "--seed", str(job["seed"]),
           "--areas", job["areas"], "--out", out_dir, "--quiet"] + job["extra"]
    cmd += ["--png"] if job["png"] else ["--no-render"]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=job["timeout"],
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        rec.update(status="timeout", seconds=round(time.perf_counter() - t0, 2),
                   error="timeout after %ds" % job["timeout"])
        return rec
    rec["seconds"] = round(time.perf_counter() - t0, 2)
    stem = os.path.splitext(os.path.basename(job["path"]))[0]
    base = os.path.join(out_dir, "%s_%s_%d" % (re.sub(r"[^A-Za-z0-9_.-]+", "_", stem), job["size"], job["seed"]))
    rec["log"] = os.path.relpath(base + ".log", ROOT)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        rec.update(status="error", error=err[-4000:], error_line=first_error_line(err))
        return rec
    rec["status"] = "ok"
    if job["png"]:
        rec["png"] = os.path.relpath(base + ".png", ROOT)
    rec["json"] = os.path.relpath(base + ".json", ROOT)
    if job["validate"]:
        validate_rec(rec)
    return rec


def validate_rec(rec):
    """Validate rec['json'] with test_cli.validate_dump; sets status/stats/warnings in place."""
    import test_cli
    rec.pop("warnings", None)
    try:
        with open(os.path.join(ROOT, rec["json"]), encoding="utf-8") as f:
            d = json.load(f)
        warnings = []
        test_cli.validate_dump(d, warnings)
        rec["status"] = "ok"
        rec.pop("error", None)
        rec.pop("error_line", None)
        rec["stats"] = dump_stats(d)
        if warnings:
            rec["warnings"] = warnings[:20]
            rec["n_warnings"] = len(warnings)
    except AssertionError as e:
        rec.update(status="invalid", error="validation: %s" % e, error_line="validation: %s" % e)
    except Exception as e:   # noqa: BLE001
        rec.update(status="invalid", error="validation crashed: %r" % e, error_line="validation crashed: %r" % e)
    return rec


def first_error_line(err):
    for line in err.splitlines():
        line = line.strip()
        if not line or line.startswith("c5gen: Lua error") or line.startswith("(log:"):
            continue
        return line[:300]
    return err[:300]


def dump_stats(d):
    n = d["width"] * d["height"]
    land = sum(1 for v in d["plot_type"] if v != 3)
    rivers = sum(1 for k in ("river_w", "river_nw", "river_ne") for v in d[k] if v != -1)
    nw = sum(1 for f in d["feature"] if f >= 0 and d["feature_natural_wonder"][f])
    majors = sum(1 for s in d["start_plots"] if not s["minor"])
    return {"w": d["width"], "h": d["height"], "land_pct": round(100.0 * land / n, 1), "river_edges": rivers,
            "resources": sum(1 for r in d["resource"] if r >= 0), "natural_wonders": nw,
            "lakes": sum(d["lake"]), "starts": len(d["start_plots"]), "majors": majors,
            "areas": len(d["areas"])}


def results_path(tag):
    return os.path.join(SWEEP_OUT, "results%s.json" % ("_" + tag if tag else ""))


def load_results(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def key(r):
    return (r["spec"], r["size"], r["seed"], r["areas"], r.get("option", ""))


def summarize(results, out=sys.stdout):
    by = {}
    for r in results:
        by.setdefault(r["spec"], []).append(r)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("%-40s %-9s %5s %8s  %s" % ("script", "size", "runs", "max s", "status / first error"), file=out)
    for spec in sorted(by):
        rows = by[spec]
        sizes = sorted({r["size"] for r in rows}, key=ALL_SIZES.index)
        for size in sizes:
            rs = [r for r in rows if r["size"] == size]
            sts = sorted({r["status"] for r in rs})
            okn = sum(1 for r in rs if r["status"] == "ok")
            msg = ",".join(sts)
            bad = [r for r in rs if r["status"] != "ok"]
            if bad:
                msg += "  " + (bad[0].get("error_line") or bad[0].get("error") or "")[:110]
            print("%-40s %-9s %2d/%-2d %8.1f  %s" % (spec, size, okn, len(rs),
                  max(r.get("seconds", 0) for r in rs), msg), file=out)
    print("\ntotal runs %d: %s" % (len(results), ", ".join("%s %d" % kv for kv in sorted(counts.items()))),
          file=out)
    nscripts = len(by)
    unsupported = sum(1 for s in by if all(r["status"] == "unsupported" for r in by[s]))
    allok = sum(1 for s in by if all(r["status"] == "ok" for r in by[s]))
    print("scripts %d: all-ok %d, unsupported %d, with failures %d" % (
        nscripts, allok, unsupported, nscripts - allok - unsupported), file=out)


# Hand-written notes appended to docs/script-compat.md (render review and behaviour that is not an error).
OBSERVATIONS = [
    "## Notes from the render review (one PNG per script, standard size, seed 1)",
    "",
    "* No all-ocean maps, no starts in water (validated), every non-WorldBuilder script places rivers, resources and "
    "(where the script allows them) natural wonders.",
    "* `exp1:Tilted_Axis`: every water plot in the northern half is ice. By design: its `AddIceAtPlot` override "
    "sets ice on every plot with `iY >= iH / 2`.",
    "* `vp:Skirmish`: no water at all with the default 'Rivers' water setting (option 2 = 1); the validator only "
    "requires coast terrain when the map has water.",
    "* `vp:Ring`, `assets:Ring`: city-states are forced into the small polar centre; at standard size VP "
    "discards most of them for crowding (2 of 16 placed). Script behaviour, same in game.",
    "* `vp:Four_Corners`, `vp:West_vs_East`: 15 of 16 city-states placed (crowding), not a harness issue.",
    "* `vp:Amazon_XP`, `vp:Script_Random_China`: no natural wonders by design (\"No Natural Wonders available on "
    "this script\").",
    "* Arborea/Rainforest/Sandstorm (exp1, vp-emp, dlc-sp1) produce identical plot types for the same seed: they "
    "share the same plot-type generator code; only terrain/features/resources differ.",
    "* Team scripts (`North_vs_South`, `West_vs_East`, `Hemispheres`, `Four_Corners`, `Europe`, `Frontier`, `Ring`, "
    "`Skirmish`, `Large_Islands`) run in team mode with `--teams 2` (`--teams 4` for Four_Corners); team 0 and "
    "team 1 start on opposite halves as intended.",
    "",
    "## Flags worth knowing",
    "",
    "* `--teams N` groups the major civs round-robin into N teams (needed for Hemispheres).",
    "* `--option IDX=VALUE` now warns on stderr when the script has no option IDX or VALUE is outside its range "
    "(the value is still passed through, as the game would).",
    "* `--list-options` resolves option names from the mods' en_US text XML as well as the localization cache "
    "(the option names of `vp:Communitu_79a` were raw TXT_KEYs before).",
    "* WorldBuilder hybrids (`WB_Script_*`, or scripts that call `Map.LoadMap` / mention `.Civ5Map`) are not run: "
    "they read plot types from a map file the exe loads before the script, so headless they would see an "
    "all-ocean map.",
    "",
]


def vp_copy(spec, specs):
    if spec in VP_RENAMED:
        return VP_RENAMED[spec]
    stem = spec.split(":", 1)[1]
    cand = "vp:" + stem
    return cand if cand in specs and cand != spec else None


def _load_dump(rec):
    path = rec.get("json") or (rec["log"][:-4] + ".json" if rec.get("log") else None)
    if not path:
        return None
    path = os.path.join(ROOT, path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def area_sensitivity(main, ff):
    """spec -> short note comparing --areas literal vs floodfill dumps (same size/seed)."""
    lit = {(r["spec"], r["size"], r["seed"]): r for r in main if r["areas"] == "literal" and not r.get("option")}
    per = {}
    for r in ff:
        a = lit.get((r["spec"], r["size"], r["seed"]))
        if not a or a["status"] == "unsupported":
            continue
        if a["status"] != r["status"]:
            err = (r.get("error_line") or a.get("error_line") or "")[:70]
            per.setdefault(r["spec"], []).append("seed %d: literal %s / floodfill %s (%s)" % (
                r["seed"], a["status"], r["status"], err))
            continue
        if a["status"] != "ok":
            continue
        da, db = _load_dump(a), _load_dump(r)
        if not da or not db:
            continue
        diff = sum(1 for x, y in zip(da["plot_type"], db["plot_type"]) if x != y)
        same = all(da[k] == db[k] for k in ("plot_type", "terrain", "feature", "resource", "river_w", "river_nw",
                                              "river_ne")) and da["start_plots"] == db["start_plots"]
        if same:
            per.setdefault(r["spec"], []).append("identical")
        elif diff > 500:
            per.setdefault(r["spec"], []).append("%d plot types differ (plot-type retry loop: %.1fM vs %.1fM map rands)"
                                                 % (diff, da["map_rand_calls"] / 1e6, db["map_rand_calls"] / 1e6))
        else:
            per.setdefault(r["spec"], []).append("%d plot types differ" % diff)
    notes = {}
    for spec, lst in per.items():
        if all(x == "identical" for x in lst):
            notes[spec] = "insensitive (identical)"
        elif any("retry" in x for x in lst):
            notes[spec] = "**major**: " + "; ".join(lst)
        else:
            notes[spec] = "; ".join(lst)
    return notes


def _cell(rs):
    if not rs:
        return ""
    okn = sum(1 for r in rs if r["status"] == "ok")
    st = sorted({r["status"] for r in rs})
    if st == ["ok"]:
        return "ok %d/%d" % (okn, len(rs))
    if st == ["unsupported"]:
        return "WB"
    return "%s %d/%d" % ("/".join(x for x in st if x != "ok"), okn, len(rs))


def write_compat(path):
    specs = {sp: (tag, f, p) for sp, tag, f, p in script_specs()}
    main = [r for r in load_results(results_path("")) if not r.get("option")]
    ff = load_results(results_path("ff"))
    teams = load_results(results_path("teams2")) + load_results(results_path("teams4"))
    work = load_results(results_path("workaround"))
    opt = load_results(results_path("options"))
    sens = area_sensitivity(main, ff)
    by = {}
    for r in main:
        by.setdefault(r["spec"], []).append(r)
    optfail, optn = {}, {}
    for r in opt:
        optn[r["spec"]] = optn.get(r["spec"], 0) + 1
        if r["status"] not in ("ok", "unsupported"):
            optfail.setdefault(r["spec"], []).append(r["option"])
    teamok, workok = {}, {}
    for r in teams:
        teamok.setdefault(r["spec"], []).append(r["status"] == "ok")
    for r in work:
        workok.setdefault(r["spec"], []).append(r["status"] == "ok")

    rows, counts = [], {}
    for spec in sorted(specs, key=lambda x: (specs[x][0] != "mygames", x)):
        rs = by.get(spec, [])
        stat = {r["status"] for r in rs}
        if stat == {"unsupported"}:
            klass, cause = "unsupported", "WorldBuilder map (needs the .Civ5Map the exe pre-loads)"
        elif stat == {"ok"}:
            klass, cause = "ok", ""
        elif not rs:
            klass, cause = "not run", ""
        else:
            first = next((r.get("error_line") or r.get("error") or "") for r in rs if r["status"] != "ok")
            klass, cause = KNOWN.get(spec, ("?", "UNTRIAGED: " + first[:120]))
            if "ok" in stat:
                klass += " (intermittent)"
        counts[klass.split()[0]] = counts.get(klass.split()[0], 0) + 1
        sizes = [_cell([r for r in rs if r["size"] == z]) for z in ALL_SIZES]
        t = max([r.get("seconds", 0) for r in rs if r["size"] == "standard"] or [0])
        notes = []
        if spec in WORKAROUND:
            ok = workok.get(spec) or teamok.get(spec)
            notes.append("runs with `%s`%s" % (WORKAROUND[spec],
                                               " (verified %d/%d seeds)" % (sum(ok), len(ok)) if ok else ""))
        if not klass.startswith(("ok", "unsupported")):
            vc = vp_copy(spec, specs)
            if vc:
                notes.append("VP copy `%s` works" % vc if all(r["status"] == "ok" for r in by.get(vc, [{"status": "x"}]))
                             else "VP copy `%s`" % vc)
        if spec in teamok and spec not in WORKAROUND and all(teamok[spec]):
            notes.append("team mode ok (`--teams 2`)")
        if klass == "ok":
            if spec in optfail:
                notes.append("fails with options " + ", ".join(optfail[spec]))
            elif spec in optn:
                notes.append("all %d non-default option values ok (duel)" % optn[spec])
        if spec in sens and klass != "unsupported":
            notes.append("areas: " + sens[spec])
        rows.append("| `%s` | %s | %.1f | %s | %s | %s |" % (spec, " | ".join(sizes), t, klass, cause, "; ".join(notes)))
    ran = [r for r in main if r["status"] != "unsupported"]
    lines = [
        "# Map script compatibility (c5maps harness, Vox Populi)",
        "",
        "Generated by `python tests/sweep.py --write-compat` from `out/sweep/results*.json`: full sweep "
        "(`python tests/sweep.py`: every script at standard size, seeds 1-3, the reference scripts also at duel..huge), "
        "`--areas floodfill --tag ff --seeds 1 2 --no-ref`, team runs (`--tag teams2 ... --extra --teams 2`), "
        "workaround runs (`--tag workaround`), and one duel run per non-default map option value "
        "(`--option-sweep --sizes duel --seeds 1 --no-ref --tag options`).",
        "",
        "Status cells: `ok n/m` = n of m seeds ran and the dump validated (`tests/test_cli.validate_dump`); "
        "`error` = Lua error; `invalid` = dump failed validation; `WB` = WorldBuilder map, not run. "
        "`std s` = slowest standard-size run in seconds (wall clock, 8 parallel workers).",
        "",
        "Failure classes: **b** = genuine script bug under VP: the traceback is inside the script's own override of a "
        "VP AssignStartingPlots method and the field/method it needs does not exist in VP's `AssignStartingPlots.lua`, "
        "so the game fails the same way; **c** = needs a non-default option or player setup (notes give the flag); "
        "**a** (harness bug / missing engine symbol) = none left after the sweep.",
        "",
        "Summary: %d scripts; %d runs (+%d WorldBuilder runs skipped): ok %d, failed %d. Scripts by class: %s." % (
            len(specs), len(ran), sum(1 for r in main if r["status"] == "unsupported"),
            sum(1 for r in ran if r["status"] == "ok"), sum(1 for r in ran if r["status"] != "ok"),
            ", ".join("%s %d" % kv for kv in sorted(counts.items()))),
        "",
        "Area mode (`areas:` notes): literal vs floodfill dumps at standard size, seeds 1-2. \"identical\" = the script "
        "never looks at area ids in a way that changes output; a handful of differing plots = ASP start/CS/resource "
        "placement and start-plot normalisation follow area ids; **major** = the script retries its plot-type fractal "
        "until the biggest area is a big enough share of land (vanilla Pangaea family), which literal areas rarely "
        "satisfy (engine-api.md §17 A1, §18).",
        "",
        "| script | duel | tiny | small | standard | large | huge | std s | class | cause | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ] + rows + [""] + OBSERVATIONS
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", help="substring filter on 'tag:stem' (repeatable)")
    ap.add_argument("--sizes", nargs="+", default=["standard"], choices=ALL_SIZES)
    ap.add_argument("--ref-sizes", nargs="+", default=ALL_SIZES, choices=ALL_SIZES,
                    help="extra sizes for the reference scripts")
    ap.add_argument("--no-ref", action="store_true", help="do not add the extra reference sizes")
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--areas", default="literal", choices=["literal", "floodfill"])
    ap.add_argument("--png-size", default="standard")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--tag", default="", help="results file suffix (out/sweep/results_<tag>.json)")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, help="extra c5gen args (must be last)")
    ap.add_argument("--report", action="store_true", help="only print the summary of the results file")
    ap.add_argument("--write-compat", action="store_true", help="(re)generate docs/script-compat.md from results")
    ap.add_argument("--option-sweep", action="store_true",
                    help="run every non-default value of every map option once (first size/seed only)")
    ap.add_argument("--revalidate", action="store_true", help="re-run validate_dump on every stored dump")
    args = ap.parse_args(argv)
    os.makedirs(SWEEP_OUT, exist_ok=True)
    rpath = results_path(args.tag)
    if args.write_compat:
        print(write_compat(os.path.join(ROOT, "docs", "script-compat.md")))
        return 0
    if args.report:
        summarize(load_results(rpath))
        return 0
    if args.revalidate:
        results = load_results(rpath)
        todo = [r for r in results if r["status"] in ("ok", "invalid") and r.get("json")]
        with multiprocessing.Pool(args.workers) as pool:
            done = {key(r): r for r in pool.map(validate_rec, todo)}
        results = [done.get(key(r), r) for r in results]
        with open(rpath, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
        summarize(results)
        return 0

    import gamedb
    gamedb.export(quiet=True)          # once, before the workers race to (re)build the cache
    jobs = build_jobs(args)
    if args.option_sweep:
        jobs = option_jobs(jobs, args.workers)
    print("sweep: %d runs on %d workers -> %s" % (len(jobs), args.workers, rpath), flush=True)
    t0 = time.perf_counter()
    new = []
    with multiprocessing.Pool(args.workers) as pool:
        for i, rec in enumerate(pool.imap_unordered(run_job, jobs)):
            new.append(rec)
            if rec["status"] not in ("ok", "unsupported"):
                print("  [%d/%d] %-8s %s %s %d %s  %s" % (i + 1, len(jobs), rec["status"], rec["spec"], rec["size"],
                      rec["seed"], rec.get("option", ""), (rec.get("error_line") or rec.get("error") or "")[:150]),
                      flush=True)
            elif (i + 1) % 25 == 0:
                print("  [%d/%d] %.0fs" % (i + 1, len(jobs), time.perf_counter() - t0), flush=True)
    merged = {key(r): r for r in load_results(rpath)}
    for r in new:
        merged[key(r)] = r
    results = sorted(merged.values(), key=lambda r: (r["spec"], ALL_SIZES.index(r["size"]), r["seed"], r["areas"]))
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print("sweep done in %.0fs\n" % (time.perf_counter() - t0))
    summarize([r for r in results if key(r) in {key(n) for n in new}])
    return 1 if any(r["status"] in ("error", "invalid", "timeout") for r in new) else 0


if __name__ == "__main__":
    sys.exit(main())
