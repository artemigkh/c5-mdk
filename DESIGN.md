# c5maps — Civ 5 / Vox Populi mapscript development harness

## Goal
Iterate on Civilization V map scripts (Lua) without launching the game. A **fake client**
re-implements the slice of the game engine that mapscripts touch (Map, Plot, Area, Fractal,
GameInfo, Game, PreGame, enums, include()) so a script runs headless in seconds and the result
is rendered to PNG/ASCII for review.

Target: latest Vox Populi (VP). The VP Lua overrides (MapGenerator.lua, AssignStartingPlots.lua,
FeatureGenerator.lua ...) are loaded exactly as the game would load them.

## Key facts (verified)
- Civ 5 embeds **Lua 5.1** (`lua51_Win32.dll` in the game folder; Havok Script, 5.1 semantics).
- Runtime: Python 3.11 + `lupa` 2.8 (`lupa.lua51`, also `lupa.luajit21`). Installed via pip.
  The engine shim is **pure Lua** so it also runs under a standalone lua5.1/luajit binary.
- Game database (modded, reflects currently enabled mods incl. VP):
  `C:\Users\Art\Documents\My Games\Sid Meier's Civilization 5\cache\Civ5DebugDatabase.db` (SQLite).
  Tables of interest: Terrains(9), Features(25), Resources(57), Worlds(6), Climates, SeaLevels,
  Defines(2631), Civilizations, MinorCivilizations, Eras, Improvements, HandicapInfos, ...
- Engine source of truth: `C:\Users\Art\Documents\GitHub\Community-Patch-DLL\CvGameCoreDLL_Expansion2`
  - Lua bindings: `Lua/CvLuaMap.cpp`, `CvLuaPlot.cpp`, `CvLuaArea.cpp`, `CvLuaFractal.cpp`,
    `CvLuaGame.cpp`, `CvLuaGameInfo.cpp`, `CvLuaEnums.cpp`, `CvLuaPlayer.cpp`, `CvLuaTeam.cpp`
  - Algorithms to port faithfully: `CvFractal.cpp/.h`, `CvRandom.cpp/.h`, area/lake/landmass
    computation in `CvMap.cpp` (`recalculateAreas`, `calculateAreas`, lakes), `CvPlot.cpp`
    (river flags, coastal/fresh-water/adjacency semantics), `CvMapGenerator.cpp` (driver flow).
  - Type annotations: `LuaCATS/*.d.lua` (Map, Plot, Area, Game, GameInfo, enums).
- Driver flow (CvMapGenerator.cpp): load script file -> call global `GetMapInitData(worldSize)`
  (returns {Width,Height,WrapX,WrapY,TopLatitude,BottomLatitude}) -> call global `GenerateMap()`
  -> call `GetGameInitialItemsOverrides()` (optional). Map options come from
  `GetMapScriptOptions()` / `Map.GetCustomOption(i)`.
- Lua include search order (later overrides earlier, mirrors game VFS):
  1. `<Civ5>\Assets\Gameplay\Lua`
  2. `<Civ5>\Assets\DLC\Expansion\Gameplay\Lua` (if present)
  3. `<Civ5>\Assets\DLC\Expansion2\Gameplay\Lua`
  4. `<MODS>\(1) Community Patch\**\*.lua` (Core Files/Overrides/Includes/...)
  5. `<MODS>\(2) Vox Populi\**\*.lua`
  Map script dirs: `<Civ5>\Assets\Maps`, `<Civ5>\Assets\DLC\Expansion*\Maps`, `<MyGames>\Maps`.
  Civ5 = `C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V`
  MODS = `C:\Users\Art\Documents\My Games\Sid Meier's Civilization 5\MODS`

## Layout
```
engine/        pure-Lua fake client (no host dependency except gameinfo data file)
  random.lua     CvRandom port (LCG; exact)
  fractal.lua    CvFractal port (fracInit, fracInitHinted, GetHeight, GetHeightFromPercent, ridges)
  map.lua        Map.* + plot/area storage, RecalculateAreas, lakes, rivers
  plot.lua       Plot methods (metatable-based objects)
  area.lua       Area methods
  gameinfo.lua   GameInfo.<Table>() / [] semantics backed by exported data
  game.lua       Game, PreGame, Players/Teams stubs, GameDefines, Locale, enums
  include.lua    include() over the VFS search path, print/log capture
  init.lua       bootstraps globals; entry `run_mapscript(path, opts)`
host/          Python side
  c5gen.py       CLI: --script, --size, --seed, --option k=v, --civs N, --out dir, --png, --ascii
  gamedb.py      exports needed SQLite tables -> engine/data/gameinfo.lua (cached by db mtime)
  metrics.py     numeric map metrics from a dump + `compare` against docs/metrics-baselines.json
  benchmark.py   runs scripts x sizes x seeds in parallel -> out/bench/runs.jsonl + docs/metrics-baselines.json
render/        PIL hex renderer + ASCII renderer from the map dump
docs/          engine-api.md (catalog/spec), mapscript-guide.md (authoring guide), gotchas
tests/         Lua + Python tests (fractal determinism, area calc, run smoke tests on all scripts)
.claude/skills/c5-mapgen/SKILL.md   the Claude Skill
out/           generated dumps and images (gitignored)
```

## Map dump format (contract between engine and renderer) — `out/<name>.json`
```json
{
  "script": "Pangaea.lua", "seed": 12345, "world_size": "WORLDSIZE_STANDARD",
  "width": 80, "height": 52, "wrap_x": true, "wrap_y": false,
  "terrain_types": ["TERRAIN_GRASS", ...],   // index == type id
  "feature_types": ["FEATURE_ICE", ...],
  "resource_types": ["RESOURCE_IRON", ...],
  "plot_type":   [ ... ],   // per plot index i = y*width + x; 0 MOUNTAIN 1 HILLS 2 LAND 3 OCEAN
  "terrain":     [ ... ],   // terrain id
  "feature":     [ ... ],   // feature id or -1
  "resource":    [ ... ],   // resource id or -1
  "resource_qty":[ ... ],
  "river_w":  [ ... ], "river_nw": [ ... ], "river_ne": [ ... ],  // flow direction id or -1 (plot is W / NW / NE of a river edge)
  "area":        [ ... ],   // area id
  "lake":        [ ... ],   // 0/1
  "continent":   [ ... ],   // continent art type
  "resource_class": [ ... ],   // per resource id: "RESOURCECLASS_LUXURY" | "RESOURCECLASS_BONUS" | "RESOURCECLASS_RUSH" | "RESOURCECLASS_MODERN" (from Resources.ResourceClassType)
  "feature_natural_wonder": [ ... ],   // per feature id: 0/1 (Features.NaturalWonder)
  "areas": { "<id>": {"water": 0/1, "size": N, "lake": 0/1} },
  "start_plots": [ {"player":0, "team":0, "x":10, "y":20, "civ":"CIVILIZATION_ROME", "name":"Rome", "minor":false}, ... ],
  "log": "captured print() output"
}
```
Geometry: Civ5 hex grid, x along rows, **y=0 is the south/bottom row**, odd rows are shifted
half a hex to the east (odd-r offset). Renderers must draw y increasing upward.

## Rendering
- PNG via PIL: hex per plot colored by terrain, hills/mountain shading, feature glyph/tint,
  rivers as blue edge lines (W / NW / NE edges), resources as small dots, start plots as labeled
  markers, lakes distinguished from coast. Optional legend + title (script, size, seed).
- ASCII: one char per plot for quick terminal checks.

## Conventions
- Pure Lua 5.1 in `engine/` (no goto, no integer division, no bit library beyond what lupa.lua51
  provides; implement bit ops arithmetically).
- Faithfulness first: port C++ algorithms line-by-line where behavior is observable (fractal,
  random, areas, lakes), stub where not (UI, players beyond what ASP needs).
- Unknown engine call => raise a clear error naming the missing method so it can be added.
- Commit regularly; `out/` is gitignored.
