"""Export the Civ5 debug database (read-only) to pure-Lua data files for the engine.

Output (engine/data/):
  gameinfo.lua          index: every table's columns + boolean columns + row count,
                        GameInfoTypes (Type -> ID for every table with ID and Type, sqlite_master order,
                        later tables overwrite earlier ones like CvDllDatabaseUtility)
  tables/<Table>.lua    one file per table: `return { {v1, v2, ...}, ... }` in rowid order;
                        loaded lazily by engine/gameinfo.lua on first access
  stamp.txt             cache key (db path + mtime + size + exporter version)

Columns declared `boolean` become Lua true/false; SQL NULL becomes nil (field absent).

Usage: python host/gamedb.py [--db PATH] [--force]
"""
import argparse
import math
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

EXPORTER_VERSION = "3"


def lua_str(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif o < 32 or o == 127:
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def lua_num(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if math.isnan(v):
        return "(0/0)"
    if math.isinf(v):
        return "math.huge" if v > 0 else "-math.huge"
    r = repr(float(v))
    return r


def lua_val(v, is_bool):
    if v is None:
        return "nil"
    if is_bool:
        if isinstance(v, (int, float)):
            return "true" if v != 0 else "false"
        if isinstance(v, str):
            return "false" if v.strip().lower() in ("0", "false", "") else "true"
        return "true"
    if isinstance(v, (int, float)):
        return lua_num(v)
    if isinstance(v, bytes):
        return lua_str(v.decode("utf-8", "replace"))
    return lua_str(str(v))


def lua_key(k):
    import re
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) and k not in LUA_KEYWORDS:
        return k
    return "[" + lua_str(k) + "]"


LUA_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
                "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}


def stamp_for(db):
    st = os.stat(db)
    return "%s|%d|%d|%s" % (os.path.abspath(db), int(st.st_mtime), st.st_size, EXPORTER_VERSION)


def is_current(db, data_dir=paths.DATA):
    sp = os.path.join(data_dir, "stamp.txt")
    if not os.path.exists(sp) or not os.path.exists(os.path.join(data_dir, "gameinfo.lua")):
        return False
    with open(sp, encoding="utf-8") as f:
        return f.read().strip() == stamp_for(db)


def export(db=paths.DB, data_dir=paths.DATA, force=False, quiet=False):
    if not os.path.exists(db):
        raise SystemExit("game database not found: %s (set C5MAPS_DB)" % db)
    if not force and is_current(db, data_dir):
        if not quiet:
            print("gamedb: up to date (%s)" % data_dir)
        return False
    uri = "file:" + db.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    tdir = os.path.join(data_dir, "tables")
    tmp = tdir + ".tmp"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)

    index = []
    types = {}
    used_files = set()
    for t in tables:
        if t.startswith("sqlite_"):
            continue
        info = list(con.execute('PRAGMA table_info("%s")' % t))
        cols = [r[1] for r in info]
        decl = [(r[2] or "").strip().lower() for r in info]
        isbool = [d == "boolean" for d in decl]
        try:
            rows = list(con.execute('SELECT * FROM "%s" ORDER BY rowid' % t))
        except sqlite3.OperationalError:   # WITHOUT ROWID tables / views
            rows = list(con.execute('SELECT * FROM "%s"' % t))
        fname = t
        n = 1
        while fname.lower() in used_files:
            n += 1
            fname = "%s__%d" % (t, n)
        used_files.add(fname.lower())
        with open(os.path.join(tmp, fname + ".lua"), "w", encoding="utf-8", newline="\n") as f:
            f.write("return {\n")
            for r in rows:
                f.write("{" + ",".join(lua_val(v, isbool[i]) for i, v in enumerate(r)) + "},\n")
            f.write("}\n")
        has_id = "ID" in cols
        has_type = "Type" in cols
        if has_id and has_type and rows:
            iid, ity = cols.index("ID"), cols.index("Type")
            for r in rows:
                if r[ity] is not None and r[iid] is not None:
                    types[r[ity]] = r[iid]
        index.append((t, fname, cols, decl, isbool, len(rows), has_id, has_type))

    out = ["-- generated by host/gamedb.py from %s -- do not edit\n" % lua_str(db), "return {\n"]
    out.append("db = %s,\n" % lua_str(db))
    out.append("order = {" + ",".join(lua_str(t[0]) for t in index) + "},\n")
    out.append("tables = {\n")
    for (t, fname, cols, decl, isbool, nrows, has_id, has_type) in index:
        out.append("%s = {file=%s, n=%d, id=%s, type=%s, cols={%s}, decl={%s}},\n" % (
            lua_key(t), lua_str(fname), nrows, "true" if has_id else "false", "true" if has_type else "false",
            ",".join(lua_str(c) for c in cols), ",".join(lua_str(d) for d in decl)))
    out.append("},\n")
    out.append("types = {\n")
    for k, v in types.items():
        out.append("%s=%s,\n" % (lua_key(k), lua_num(v)))
    out.append("},\n}\n")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "gameinfo.lua"), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))
    if os.path.exists(tdir):
        shutil.rmtree(tdir)
    os.replace(tmp, tdir)
    with open(os.path.join(data_dir, "stamp.txt"), "w", encoding="utf-8") as f:
        f.write(stamp_for(db))
    con.close()
    if not quiet:
        print("gamedb: exported %d tables, %d types -> %s" % (len(index), len(types), data_dir))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=paths.DB)
    ap.add_argument("--out", default=paths.DATA)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    export(a.db, a.out, a.force)


if __name__ == "__main__":
    main()
