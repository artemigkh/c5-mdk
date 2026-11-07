"""Cross-check engine/random.lua + engine/fractal.lua against the real DLL C++ code.

Copies the UNMODIFIED CvRandom.cpp/.h and CvFractal.cpp/.h from the Community-Patch-DLL checkout
next to tests/cpp/stubs/* in a temp dir, compiles them with MSVC (x86, via vcvars32.bat) together
with tests/cpp/harness.cpp, runs a battery of cases through both the exe and the Lua port
(lupa.lua51) and diffs the outputs.

Usage: python tests/cpp/build_and_compare.py [--dll-src DIR] [--keep]
Exit code 0 = identical, 1 = mismatch, 2 = no compiler (skipped).
"""
import argparse
import glob
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(ROOT, "engine")
DEFAULT_DLL_SRC = r"C:\Users\Art\Documents\GitHub\Community-Patch-DLL\CvGameCoreDLL_Expansion2"

LUA_RUNNER = r"""
local Random = require("random")
local F = require("fractal")
local function fmt(v) return string.format("%.0f", v) end
function run_case(line)
  local t = {}
  for w in line:gmatch("%S+") do t[#t + 1] = w end
  local out = {}
  local kind = t[1]
  local r = Random.new(tonumber(t[2]), "map")
  if kind == "RNG" then
    local n, num = tonumber(t[3]), tonumber(t[4])
    local parts = { "RNG" }
    for i = 1, n do parts[#parts + 1] = fmt(r:get(num, "t")) end
    out[#out + 1] = table.concat(parts, " ")
  elseif kind == "FLOAT" then
    local parts = { "FLOAT" }
    for i = 1, tonumber(t[3]) do parts[#parts + 1] = string.format("%.9g", r:getFloat()) end
    out[#out + 1] = table.concat(parts, " ")
  elseif kind == "FRAC" then
    local v = {}
    for i = 3, #t do v[#v + 1] = tonumber(t[i]) end
    local W, H, grain, flags, xe, ye, rg, rs, rf, br, bf, mw, mh, mwx, mwy = unpack(v)
    local mapInfo = { width = mw, height = mh, wrapX = mwx ~= 0, wrapY = mwy ~= 0 }
    local rifts
    if rg > 0 then
      rifts = F.CvFractal.new(mapInfo)
      rifts:fracInit(W, H, rg, r, 0, nil, xe, ye)
    end
    local f = F.CvFractal.new(mapInfo)
    f:fracInit(W, H, grain, r, flags, rifts, xe, ye)
    if rs > 0 then f:ridgeBuilder(r, rs, rf, br, bf) end
    local parts = { "H" }
    for y = 0, H - 1 do for x = 0, W - 1 do parts[#parts + 1] = fmt(f:getHeight(x, y)) end end
    out[#out + 1] = table.concat(parts, " ")
    parts = { "P" }
    for p = 0, 100, 5 do parts[#parts + 1] = fmt(f:getHeightFromPercent(p)) end
    out[#out + 1] = table.concat(parts, " ")
  end
  local hi, lo = r:getSeedParts()
  out[#out + 1] = "SEED " .. fmt(hi) .. " " .. fmt(lo)
  return table.concat(out, "\n")
end
"""


def make_cases():
    rng = random.Random(20261107)
    cases = []
    for seed in (0, 1, 12345, 42, 73637380, 2**31 - 1, 2**32 + 7, 2**40 + 3):
        for num in (2, 3, 7, 100, 256, 1000, 65536, 2**31, 2**32 - 1):
            cases.append(f"RNG {seed} 200 {num}")
        cases.append(f"FLOAT {seed} 200")
    sizes = [(40, 24), (52, 32), (66, 42), (80, 52), (104, 64), (128, 80), (13, 7), (200, 120)]
    exps = [(-1, -1), (7, 6), (6, 6), (7, 7), (5, 5), (6, 5), (7, 8)]
    # hand-picked structurally important combos
    fixed = [
        # seed W H grain flags xe ye riftGrain ridgeSeeds ridgeFlags br bf mapW mapH wx wy
        (1, 80, 52, 2, 8, -1, -1, -1, 20, 1, 1, 2, 80, 52, 1, 0),      # FractalWorld continents, polar, ridges
        (2, 80, 52, 2, 8, -1, -1, 2, 20, 1, 1, 2, 80, 52, 1, 0),       # with rifts
        (3, 80, 52, 3, 1, -1, -1, -1, 24, 1, 1, 2, 80, 52, 1, 0),      # hills frac wrapX + ridges
        (4, 80, 52, 4, 1, -1, -1, -1, 16, 1, 6, 1, 80, 52, 1, 0),      # mountains
        (5, 128, 80, 2, 3, 7, 6, -1, 0, 0, 0, 0, 128, 80, 1, 1),       # wrap both
        (6, 128, 80, 2, 16 + 1, 7, 6, -1, 0, 0, 0, 0, 128, 80, 1, 0),  # center rift wrapX
        (7, 128, 80, 2, 16 + 3, 7, 6, -1, 0, 0, 0, 0, 128, 80, 1, 1),  # center rift wrap both
        (8, 80, 52, 2, 32 + 8, -1, -1, -1, 0, 0, 0, 0, 80, 52, 1, 0),  # invert + polar
        (9, 80, 52, 5, 4 + 1, 6, 6, -1, 0, 0, 0, 0, 80, 52, 1, 0),     # percent
        (10, 80, 52, 0, 0, -1, -1, -1, 5, 1, 1, 2, 80, 52, 0, 0),      # grain 0 (smoothest)
        (11, 80, 52, 9, 1, -1, -1, -1, 3, 0, 0, 1, 80, 52, 1, 0),      # grain > exp (pure random), ridges no flags
        (12, 80, 52, 2, 8, -1, -1, 3, 20, 1, 1, 2, 80, 52, 1, 0),
        (13, 104, 64, 1, 8 + 32, -1, -1, 1, 20, 1, 1, 2, 104, 64, 1, 0),
        (14, 80, 52, 2, 8, 7, 8, -1, 4, 1, 1, 2, 80, 52, 1, 1),        # yexp 8: [x][256] aliases [x+1][0]
    ]
    for c in fixed:
        cases.append("FRAC " + " ".join(map(str, c)))
    for _ in range(60):
        W, H = rng.choice(sizes)
        xe, ye = rng.choice(exps)
        flags = rng.randrange(64)
        rg = rng.choice([-1, -1, 1, 2, 3])
        if rg > 0:
            flags |= 1
        rs = rng.choice([0, 0, 3, 8, 20, 30])
        cases.append("FRAC %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d" % (
            rng.randrange(73637381), W, H, rng.randrange(0, 9), flags, xe, ye, rg, rs,
            rng.choice([0, 1]), rng.randrange(0, 7), rng.randrange(0, 4), W, H,
            rng.choice([0, 1]), rng.choice([0, 0, 1])))
    return cases


def find_vcvars32():
    vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    roots = []
    if os.path.exists(vswhere):
        out = subprocess.run([vswhere, "-all", "-products", "*", "-property", "installationPath"],
                             capture_output=True, text=True).stdout
        roots = [l.strip() for l in out.splitlines() if l.strip()]
    for r in roots:
        p = os.path.join(r, "VC", "Auxiliary", "Build", "vcvars32.bat")
        if os.path.exists(p):
            return p
    return None


def build(dll_src, workdir):
    vcvars = find_vcvars32()
    if not vcvars:
        return None, "no MSVC found (vswhere/vcvars32.bat)"
    for f in glob.glob(os.path.join(HERE, "stubs", "*")):
        shutil.copy(f, workdir)
    shutil.copy(os.path.join(HERE, "harness.cpp"), workdir)
    for f in ("CvRandom.cpp", "CvRandom.h", "CvFractal.cpp", "CvFractal.h"):
        shutil.copy(os.path.join(dll_src, f), workdir)
    bat = os.path.join(workdir, "build.bat")
    with open(bat, "w") as fh:
        fh.write('@echo off\ncall "%s" >nul\ncd /d "%s"\n' % (vcvars, workdir))
        fh.write("cl /nologo /EHsc /O2 /W0 /I. harness.cpp CvRandom.cpp CvFractal.cpp /Fe:harness.exe\n")
    p = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True)
    exe = os.path.join(workdir, "harness.exe")
    if p.returncode != 0 or not os.path.exists(exe):
        return None, "compile failed:\n" + p.stdout + p.stderr
    return exe, None


def run_lua(cases):
    import lupa.lua51 as lupa
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("package.path = [[%s/?.lua;]] .. package.path" % ENGINE.replace("\\", "/"))
    L.execute(LUA_RUNNER)
    run = L.globals().run_case
    return [run(c) for c in cases]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-src", default=DEFAULT_DLL_SRC)
    ap.add_argument("--keep", action="store_true", help="keep the build dir")
    a = ap.parse_args()

    workdir = tempfile.mkdtemp(prefix="c5frac_")
    try:
        exe, err = build(a.dll_src, workdir)
        if not exe:
            print("SKIP:", err)
            return 2
        cases = make_cases()
        p = subprocess.run([exe], input="\n".join(cases) + "\n", capture_output=True, text=True)
        cpp_lines = p.stdout.strip().splitlines()
        lua_lines = "\n".join(run_lua(cases)).splitlines()
        if len(cpp_lines) != len(lua_lines):
            print("line count mismatch: cpp %d lua %d" % (len(cpp_lines), len(lua_lines)))
            return 1
        # regroup per case
        bad = 0
        li = 0
        for c in cases:
            n = 2 if c.startswith(("RNG", "FLOAT")) else 3
            cpp = cpp_lines[li:li + n]
            lua = lua_lines[li:li + n]
            li += n
            if cpp != lua:
                bad += 1
                if bad <= 5:
                    print("MISMATCH:", c)
                    for x, y in zip(cpp, lua):
                        if x != y:
                            xs, ys = x.split(), y.split()
                            k = next((i for i in range(min(len(xs), len(ys))) if xs[i] != ys[i]), None)
                            print("  first diff at token", k, "cpp:", xs[k:k + 8] if k is not None else xs[:8],
                                  "lua:", ys[k:k + 8] if k is not None else ys[:8])
        n_rng = sum(1 for c in cases if not c.startswith("FRAC"))
        print("cases: %d (%d RNG/FLOAT, %d FRAC), mismatches: %d" % (len(cases), n_rng, len(cases) - n_rng, bad))
        return 1 if bad else 0
    finally:
        if a.keep:
            print("build dir:", workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
