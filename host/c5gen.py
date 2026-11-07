"""c5gen -- run a Civ V (Vox Populi) map script headless and render the result.

Usage:
  python host/c5gen.py <script name or path> [--size duel|tiny|small|standard|large|huge] [--seed N]
         [--civs N] [--city-states N] [--civ-list CIVILIZATION_X,CIVILIZATION_Y]
         [--option IDX=VALUE ...] [--list-options] [--era ERA_ANCIENT] [--handicap HANDICAP_PRINCE]
         [--out out/<name>] [--png] [--ascii] [--stats] [--no-render] [--areas literal|floodfill]
         [--runtime lua51|luajit21] [--timing] [--quiet]
  python host/c5gen.py --list-scripts

A bare script name is searched (first match wins) in: My Games\\Maps, Assets\\Maps, DLC\\Expansion\\Maps,
DLC\\Expansion2\\Maps, VP Mapscripts (+EMP), CP Mapscripts, DLC_SP_Maps*.  Prefix with a source tag to pick
a specific copy, e.g. `vp:Communitu_79a` or `mygames:Communitu_79a` (tags: see --list-scripts).

Outputs out/<name>/<name>_<size>_<seed>.json/.png/.txt/.log.  Exit code 1 on a Lua error (traceback printed).
"""
import argparse
import glob
import json
import os
import random
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
import gamedb  # noqa: E402

SIZES = {"duel": "WORLDSIZE_DUEL", "tiny": "WORLDSIZE_TINY", "small": "WORLDSIZE_SMALL",
         "standard": "WORLDSIZE_STANDARD", "large": "WORLDSIZE_LARGE", "huge": "WORLDSIZE_HUGE"}


# ------------------------------------------------------------------------------------------------
# script discovery
# ------------------------------------------------------------------------------------------------
def list_scripts():
    out = []
    for tag, d in paths.SCRIPT_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".lua"):
                    out.append((tag, f, os.path.join(d, f)))
    return out


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace(".lua", ""))


def resolve_script(name):
    """-> (path, source tag, explicit_tag)"""
    if os.path.isfile(name):
        return os.path.abspath(name), "path", False
    tag = None
    if ":" in name and not re.match(r"^[A-Za-z]:[\\/]", name):
        tag, name = name.split(":", 1)
    cands = list_scripts()
    if tag:
        cands = [c for c in cands if c[0] == tag]
    want = name.lower()
    if not want.endswith(".lua"):
        want += ".lua"
    for t, f, p in cands:
        if f.lower() == want:
            return p, t, bool(tag)
    # fuzzy: ignore case/underscores/spaces ("Small_Continents" -> SmallContinents.lua)
    nn = norm_name(name)
    for t, f, p in cands:
        if norm_name(f) == nn:
            return p, t, bool(tag)
    raise SystemExit("c5gen: map script not found: %s (try --list-scripts)" % name)


# ------------------------------------------------------------------------------------------------
# VFS file list (include search path)
# ------------------------------------------------------------------------------------------------
def modinfo_imports(mod_dir):
    files = []
    infos = glob.glob(os.path.join(mod_dir, "*.modinfo"))
    if not infos:
        return None
    with open(infos[0], encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for m in re.finditer(r'<File[^>]*import="1"[^>]*>([^<]+)</File>', txt):
        rel = m.group(1).strip().replace("/", os.sep).replace("\\", os.sep)
        if rel.lower().endswith(".lua"):
            p = os.path.join(mod_dir, rel)
            if os.path.exists(p):
                files.append(p)
    return files


def vfs_files():
    out = []
    for d in paths.LUA_DIRS:
        if os.path.isdir(d):
            for root, _, fs in os.walk(d):
                for f in sorted(fs):
                    if f.lower().endswith(".lua"):
                        out.append({"path": os.path.join(root, f), "source": d})
    for d in paths.MOD_DIRS:
        if not os.path.isdir(d):
            continue
        files = modinfo_imports(d)
        if files is None:
            files = []
            for root, _, fs in os.walk(d):
                for f in sorted(fs):
                    if f.lower().endswith(".lua"):
                        files.append(os.path.join(root, f))
        for p in files:
            out.append({"path": p, "source": os.path.basename(d)})
    return out


# ------------------------------------------------------------------------------------------------
# DB helpers (players, texts)
# ------------------------------------------------------------------------------------------------
def db_connect(db=paths.DB):
    return sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)


def choose_players(con, size_type, n_civs, n_cs, seed, civ_list=None):
    row = con.execute("SELECT DefaultPlayers, DefaultMinorCivs FROM Worlds WHERE Type=?", (size_type,)).fetchone()
    if n_civs is None:
        n_civs = row[0]
    if n_cs is None:
        n_cs = row[1]
    rng = random.Random(seed * 7919 + 17)   # harness RNG, independent of the map RNG
    if civ_list:
        civs = civ_list
    else:
        playable = [r[0] for r in con.execute(
            "SELECT Type FROM Civilizations WHERE Playable=1 AND Type NOT IN ('CIVILIZATION_MINOR','CIVILIZATION_BARBARIAN') ORDER BY ID")]
        civs = rng.sample(playable, min(n_civs, len(playable)))
    minors_all = [r[0] for r in con.execute("SELECT Type FROM MinorCivilizations WHERE Type <> 'MINOR_CIV_BARBARIAN' ORDER BY ID")]
    minors = rng.sample(minors_all, min(n_cs, len(minors_all)))
    return civs, minors


def lookup_texts(script_path):
    """TXT_KEY_* strings referenced by the script, for option names in --list-options."""
    if not os.path.exists(paths.LOC_DB):
        return {}
    try:
        with open(script_path, encoding="utf-8", errors="replace") as f:
            keys = sorted(set(re.findall(r"TXT_KEY_[A-Za-z0-9_]+", f.read())))
        con = sqlite3.connect("file:" + paths.LOC_DB.replace("\\", "/") + "?mode=ro", uri=True)
        out = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = "SELECT Tag, Text FROM LocalizedText WHERE Language='en_US' AND Tag IN (%s)" % ",".join("?" * len(chunk))
            for tag, text in con.execute(q, chunk):
                out[tag] = text
        # generic map option texts (scripts often build keys at runtime)
        for tag, text in con.execute("SELECT Tag, Text FROM LocalizedText WHERE Language='en_US' AND Tag LIKE 'TXT_KEY_MAP%'"):
            out.setdefault(tag, text)
        con.close()
        return out
    except Exception:
        return {}


# ------------------------------------------------------------------------------------------------
def make_runtime(kind):
    if kind == "luajit21":
        import lupa.luajit21 as lupa
    else:
        import lupa.lua51 as lupa
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    eng = paths.ENGINE.replace("\\", "/")
    L.execute("package.path = [[%s/?.lua;]] .. package.path" % eng)
    return L


def to_lua(L, v):
    if isinstance(v, dict):
        t = L.table()
        for k, x in v.items():
            t[k] = to_lua(L, x)
        return t
    if isinstance(v, (list, tuple)):
        t = L.table()
        for i, x in enumerate(v):
            t[i + 1] = to_lua(L, x)
        return t
    return v


def lua_list(t):
    if t is None:
        return []
    out = []
    i = 1
    while t[i] is not None:
        out.append(t[i])
        i += 1
    return out


def run(args):
    script_path, source, explicit = resolve_script(args.script)
    script_file = os.path.basename(script_path)
    stem = os.path.splitext(script_file)[0]
    if explicit:
        stem = stem + "." + source      # e.g. Communitu_79a.vp
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    gamedb.export(quiet=True)
    size_type = SIZES[args.size]
    con = db_connect()
    civ_list = [c.strip() for c in args.civ_list.split(",")] if args.civ_list else None
    civs, minors = choose_players(con, size_type, args.civs, args.city_states, args.seed, civ_list)
    con.close()

    map_options = {}
    for o in args.option or []:
        if "=" not in o:
            raise SystemExit("c5gen: --option expects IDX=VALUE, got %r" % o)
        k, v = o.split("=", 1)
        try:
            v = int(v)
        except ValueError:
            v = float(v)
        map_options[k.strip()] = v

    opts = {
        "data_dir": paths.DATA.replace("\\", "/"),
        "script_path": script_path,
        "script_name": script_file,
        "files": vfs_files(),
        "seed": args.seed,
        "world_size": size_type,
        "era": args.era,
        "handicap": args.handicap,
        "civs": civs,
        "minors": minors,
        "map_options": map_options,
        "areas_mode": args.areas,
        "echo": args.echo,
        "list_options": args.list_options,
        "texts": lookup_texts(script_path),
        "profile": args.profile,
        "rng_trace": args.rng_trace,
    }
    if args.float_to_int:
        opts["float_to_int"] = args.float_to_int

    t0 = time.perf_counter()
    L = make_runtime(args.runtime)
    init = L.eval('require("init")')
    ok, res = init.run(to_lua(L, opts))
    wall = time.perf_counter() - t0

    if args.profile and res.profile:
        print(res.profile)
    timing = []
    for t in lua_list(res.timing):
        timing.append((t["name"], t["seconds"]))
    includes = [(e["name"], e["path"]) for e in lua_list(res.includes)] if res.includes else []

    if args.list_options:
        if not ok:
            print(res.error, file=sys.stderr)
            return 1
        print("%s  [%s]  %s" % (script_file, source, script_path))
        for o in lua_list(res.options):
            vals = lua_list(o["values"])
            d = o["default"]
            print("  option %s: %s  (default %s%s)" % (o["index"], o["name"], d,
                  (" = " + vals[int(d) - 1]) if isinstance(d, (int, float)) and 1 <= int(d) <= len(vals) else ""))
            for i, v in enumerate(vals):
                print("      %d = %s" % (i + 1, v))
        return 0

    out_dir = args.out or os.path.join(paths.OUT, safe)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, "%s_%s_%d" % (safe, args.size, args.seed))
    log_lines = ["# c5gen %s  source=%s  size=%s seed=%d areas=%s runtime=%s" % (
        script_path, source, args.size, args.seed, args.areas, args.runtime)]
    log_lines.append("# civs: " + ", ".join(civs))
    log_lines.append("# city-states: " + ", ".join(minors))
    log_lines.append("# includes:")
    for n, p in includes:
        log_lines.append("#   %s -> %s" % (n, p))
    log_lines.append("# timing:")
    for n, s in timing:
        log_lines.append("#   %-20s %.3fs" % (n, s))
    log_lines.append("#   %-20s %.3fs (python wall, incl. runtime start)" % ("total", wall))
    log_lines.append(res.log_text or "")

    if not ok:
        log_lines.append("\n# LUA ERROR\n" + str(res.error))
        with open(base + ".log", "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        print("c5gen: Lua error while running %s:\n%s" % (script_file, res.error), file=sys.stderr)
        print("(log: %s.log)" % base, file=sys.stderr)
        return 1

    with open(base + ".json", "w", encoding="utf-8") as f:
        f.write(res.json)
    with open(base + ".log", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    if args.timing or not args.quiet:
        print("%s [%s] %s seed %d: %s" % (script_file, source, args.size, args.seed,
              "  ".join("%s %.2fs" % (n, s) for n, s in timing if s >= 0.005)))
        print("  total %.2fs  -> %s.json" % (wall, base))

    if not args.no_render:
        sys.path.insert(0, paths.RENDER)
        import render_map
        d = render_map.load_dump(base + ".json")
        txt = render_map.render_ascii(d) + "\n\n" + render_map.map_stats(d)
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        if args.png:
            render_map.render_png(d, base + ".png")
            print("  png -> %s.png" % base)
        if args.ascii:
            print(txt)
        elif args.stats:
            print(render_map.map_stats(d))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?")
    ap.add_argument("--list-scripts", action="store_true")
    ap.add_argument("--size", default="standard", choices=list(SIZES))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--civs", type=int, default=None)
    ap.add_argument("--city-states", type=int, default=None)
    ap.add_argument("--civ-list", default=None)
    ap.add_argument("--option", action="append", metavar="IDX=VALUE")
    ap.add_argument("--list-options", action="store_true")
    ap.add_argument("--era", default="ERA_ANCIENT")
    ap.add_argument("--handicap", default="HANDICAP_PRINCE")
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--areas", default="literal", choices=["literal", "floodfill"])
    ap.add_argument("--runtime", default="lua51", choices=["lua51", "luajit21"])
    ap.add_argument("--float-to-int", default=None, choices=["round", "trunc"])
    ap.add_argument("--timing", action="store_true")
    ap.add_argument("--echo", action="store_true", help="echo Lua print() output to stdout while running")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--rng-trace", action="store_true", help="prefix every log line with the map RNG call count")
    ap.add_argument("--profile", action="store_true", help="sampling profiler (debug.sethook) report")
    args = ap.parse_args(argv)
    if args.list_scripts:
        for tag, f, p in list_scripts():
            print("%-8s %-40s %s" % (tag, f, p))
        return 0
    if not args.script:
        ap.error("script is required")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
