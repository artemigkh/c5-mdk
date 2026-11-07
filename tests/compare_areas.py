"""Replay the engine's area algorithms over a real game's plot dump and compare partitions.

Usage: python tests/compare_areas.py real_dump.json
real_dump.json comes from tests/probes/dump-areas.lua run in civ5-headless (parsed from Lua.log):
{w,h,wrapx, plot[], terrain[], feature[], area[], landmass[], lake[], impassable[]} per plot index y*w+x.
"""
import collections
import json
import os
import sys

import lupa.lua51 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "engine").replace("\\", "/")

LUA = r"""
local mode, w, h, wrapx, plot, terrain, feature = ...
local gameinfo = require("gameinfo")
local mapmod = require("map")
local GI = gameinfo.new(ENGINE .. "/data")
local S = mapmod.newState(GI, { seed = 1, areas_mode = mode, world_size = "WORLDSIZE_STANDARD" })
mapmod.initMap(S, w, h, wrapx, false, 90, -90)
local Map = S.Map
for y = 0, h - 1 do
  for x = 0, w - 1 do
    local i = y * w + x + 1
    local p = Map.GetPlot(x, y)
    p:SetPlotType(plot[i], false, false)
    p:SetTerrainType(terrain[i], false, false)
  end
end
Map.RecalculateAreas()   -- natural wonders need an area to exist (CvPlot::setFeatureType dereferences it)
for y = 0, h - 1 do
  for x = 0, w - 1 do
    local i = y * w + x + 1
    if feature[i] >= 0 then Map.GetPlot(x, y):SetFeatureType(feature[i], -1) end
  end
end
Map.RecalculateAreas()
local areas, lm, imp, lake = {}, {}, {}, {}
for y = 0, h - 1 do
  for x = 0, w - 1 do
    local p = Map.GetPlot(x, y)
    local i = y * w + x + 1
    areas[i] = p:GetArea(); lm[i] = p:GetLandmass(); imp[i] = p:IsImpassable() and 1 or 0; lake[i] = p:IsLake() and 1 or 0
  end
end
return areas, lm, imp, lake
"""


def partition_stats(real, mine):
    pairs = collections.Counter(zip(real, mine))
    real_ids, mine_ids = set(real), set(mine)
    # plots whose real area maps to exactly one harness area and vice versa
    r2m = collections.defaultdict(set)
    m2r = collections.defaultdict(set)
    for (r, m), n in pairs.items():
        r2m[r].add(m)
        m2r[m].add(r)
    exact = sum(n for (r, m), n in pairs.items() if len(r2m[r]) == 1 and len(m2r[m]) == 1)
    # pairwise agreement (Rand index) on a sample of all plot pairs is O(n^2); use contingency formula
    def comb2(n):
        return n * (n - 1) // 2
    n = len(real)
    sum_pairs = sum(comb2(v) for v in pairs.values())
    sum_r = sum(comb2(v) for v in collections.Counter(real).values())
    sum_m = sum(comb2(v) for v in collections.Counter(mine).values())
    total = comb2(n)
    agree = total + 2 * sum_pairs - sum_r - sum_m
    return dict(real_areas=len(real_ids), harness_areas=len(mine_ids), distinct_pairs=len(pairs),
                plots_in_exactly_matching_areas=exact, plots=n, rand_index=agree / total)


def main(path):
    d = json.load(open(path))
    w, h = d["w"], d["h"]
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("package.path = [[%s/?.lua;]] .. package.path; ENGINE = [[%s]]" % (ENGINE, ENGINE))
    fn = L.eval("function(...) " + LUA.replace("local mode, w, h, wrapx, plot, terrain, feature = ...", "local mode, w, h, wrapx, plot, terrain, feature = ...") + " end")
    out = {}
    for mode in ("literal", "floodfill"):
        areas, lm, imp, lake = fn(mode, w, h, d["wrapx"], L.table_from(d["plot"]), L.table_from(d["terrain"]), L.table_from(d["feature"]))
        mine = [int(areas[i + 1]) for i in range(w * h)]
        st = partition_stats(d["area"], mine)
        st["landmass_rand_index"] = partition_stats(d["landmass"], [int(lm[i + 1]) for i in range(w * h)])["rand_index"]
        st["impassable_match"] = sum(1 for i in range(w * h) if int(imp[i + 1]) == d["impassable"][i]) / (w * h)
        st["lake_match"] = sum(1 for i in range(w * h) if int(lake[i + 1]) == d["lake"][i]) / (w * h)
        out[mode] = st
        print("== areas_mode=%s" % mode)
        for k, v in st.items():
            print("   %-36s %s" % (k, ("%.5f" % v) if isinstance(v, float) else v))
    return out


if __name__ == "__main__":
    main(sys.argv[1])
