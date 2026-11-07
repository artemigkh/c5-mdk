---
name: c5-mapgen
description: Develop, run, render and sanity-check Civilization V map scripts (Lua) for Vox Populi without launching the game. Use when writing or editing a Civ 5 mapscript, debugging map generation, comparing a map against normal community maps, or when asked about MapGenerator / AssignStartingPlots / FractalWorld / plot, terrain, river, feature or start-plot generation.
---

# Civ 5 / Vox Populi map-script development

Workspace: `C:\Users\Art\Documents\c5maps` (run every command from there).
A headless **fake client** (`engine/`, pure Lua 5.1 under `lupa`) re-implements the engine
surface map scripts touch, loads the real VP Lua libraries (MapGenerator, FeatureGenerator,
TerrainGenerator, VP AssignStartingPlots ...) through a mirror of the game's include order,
runs a script end to end, dumps the map and renders it. A standard map takes 2–8 s.

## 1. Run a script

```bash
python host/c5gen.py <script> --seed 42 --png --ascii
```
- `<script>`: bare name (`Continents`, `Small_Continents`, `vp:Communitu_79a`, `mygames:Tectonic v6 - VI`) or a path.
  `python host/c5gen.py --list-scripts` shows every script found and where (`mygames`, `assets`, `exp1`, `exp2`, `vp`, `cp`, `dlc-sp*`).
  The `tag:` prefix picks a specific copy; VP ships newer copies of Communitu, Continental_Drift, Terra, Lakes, Highlands, Europe, Great_Plains.
- `--size duel|tiny|small|standard|large|huge` (default standard), `--seed N` (default 42),
  `--civs N --city-states N` (default: `Worlds` table), `--civ-list CIVILIZATION_A,...`.
- `--list-options` prints the script's `CustomOptions` with IDs/values; `--option 4=2 --option 1=3` sets them (1-based IDs and values; the last value is usually "Random").
- Outputs in `out/<name>/<name>_<size>_<seed>.{png,txt,json,log}`:
  `.png` = hex render (look at it with the Read tool), `.txt` = ASCII map + stats block,
  `.log` = every `print()` plus include resolution and per-phase timing, `.json` = the dump.
- Other useful flags: `--stats` (print stats to stdout), `--no-render`, `--timing`, `--profile`,
  `--rng-trace`, `--areas literal|floodfill` (see §5), `--runtime luajit21` (7× faster, not
  RNG-identical to the game's Lua 5.1).
- Re-render differently: `python render/render_map.py out/x/x.json --layer areas|continents|elevation|resources|startbias --hex 16`.

A Lua error prints the full traceback and exits 1. "c5maps: unimplemented Map.Foo" means the
fake client lacks a method: add it to `engine/` (port it from
`C:\Users\Art\Documents\GitHub\Community-Patch-DLL\CvGameCoreDLL_Expansion2\Lua\CvLua*.cpp`), do not stub it silently.

## 2. Iteration loop for a script you are writing

1. Start from `templates/Template_Map.lua` (in this skill folder) or an existing script; keep the
   `GenerateMap` phase order (plots → coasts → terrain → rivers → lakes → features → start plots).
2. Run at standard with 3–5 seeds, look at the PNGs and the stats block. Then duel and huge.
3. Check the numbers against community-normal ranges:
   `python host/metrics.py compare out/<name>/<file>.json --archetype Continents`
   (archetypes: Communitu, Continental_Drift, Continents, SmallContinents, Terra, Oval, Archipelago;
   ranges and what they mean: `docs/metrics-baselines.md`).
4. Read the `.log`: VP AssignStartingPlots prints region fertility, start assignments and
   resource placement; warnings there usually mean a layout problem.
5. When happy, copy the script to
   `C:\Users\Art\Documents\My Games\Sid Meier's Civilization 5\Maps\` and test in game.
   The game's print output goes to `...\My Games\Sid Meier's Civilization 5\Logs\Lua.log`.

Regression: `python tests/run_lua_tests.py && python tests/test_cli.py && python tests/test_sweep_quick.py`.

## 3. Where the knowledge is

| Need | Read |
|---|---|
| How to write a script: lifecycle, template, options, plot/terrain/river/feature generation, VP start-plot system, reusable patterns, ~60 gotchas, checklist | `docs/mapscript-guide.md` |
| Exact semantics of every engine call (Map, Plot, Area, Fractal, GameInfo, Game, PreGame), hex math, areas/lakes/rivers algorithms, headless player model | `docs/engine-api.md` |
| Which existing scripts run, which fail and why | `docs/script-compat.md` |
| Normal ranges for land %, capital spacing, resource density, etc. | `docs/metrics-baselines.md` |
| Harness architecture, dump JSON format, paths | `DESIGN.md` |
| The real libraries | `...\Civilization V\Assets\Gameplay\Lua`, `...\Assets\DLC\Expansion2\Gameplay\Lua`, and the overriding VP copies under `...\Community-Patch-DLL\(1) Community Patch\Core Files\Overrides\Includes` and `(2) Vox Populi\Core Files\Overrides` |

## 4. Gotchas that bite most often (full list: guide §10)

- `y = 0` is the **south** row; plot index is `y*W + x`; odd rows are shifted east (odd-r hexes).
  Use `Map.PlotDirection(x, y, dir)` / `Map.PlotXYWithRangeCheck` instead of hand-rolled offsets.
- `Map.Rand(n, "reason")` returns `[0, n)` and the string is mandatory. Never use `math.random`
  for anything that should be reproducible from the map seed.
- `Map.GetCustomOption(i)`: `i` is the 1-based position in **your** `CustomOptions`; values are
  1-based; "Random" is just the last value and you must resolve it yourself.
- `SetPlotTypes(t)` wants a **1-based** table, `SetTerrainTypes(t)` a **0-based** one.
- `SetPlotType` to/from ocean wipes feature, resource and that plot's river edges and auto-sets
  terrain; `SetTerrainType` with a water/land mismatch flips the plot type; `TERRAIN_HILL` is
  marked water in the DB, so assigning it makes ocean. Mountains are `PLOT_MOUNTAIN`, not terrain.
- Rivers live on edges: `IsWOfRiver` = river on the plot's **east** edge, `IsNWOfRiver` = south-east
  edge, `IsNEOfRiver` = south-west edge. River crossings are only recomputed when a river flag
  changes and only for land–land edges: set rivers after plot types are final.
- Areas/landmasses/lakes refresh only on `Map.RecalculateAreas()`; `Map.CalculateAreas()` skips
  landmasses, so freshly added lakes report `IsLake() == false` until the next full recalc.
  In VP, **areas are not continents** (they can be split or merged oddly); use landmasses
  (`plot:GetLandmass()`, `Map.FindBiggestLandmassID()`) for "same continent" logic.
- `plot:GetArea()` returns an **id**; `Map.GetArea(id)` gives the object. `Area:IsLake` does not exist in VP.
- nil or misspelled IDs passed to engine setters silently become 0 (`FEATURE_ICE`, `PLOT_MOUNTAIN`,
  `TERRAIN_GRASS`...). Enum tables return nil for unknown keys, so typos do not error.
- VP ASP is a class with renamed internals: `GenerateRegions{method = RegionDivision.X, resources = n}`;
  old scripts that override `cityStateData`, `naturalWondersData`, `CanBe*` wonder hooks or pass
  `method = 3` for continental division break (see guide §8.9 and `docs/script-compat.md`).
- Arguments written as `x or true` cannot be turned off (`bExpandCoasts=false` is ignored).
- After generation the engine forces every water plot next to land to COAST.
- Everything at top level of the script runs before the map exists; only `GetMapInitData`
  and later see the grid size.

## 5. What the harness is not

- It is a faithful port, not the game: Lua `pairs()` order and `table.sort` ties can differ from
  Havok Script, so RNG sequences are not guaranteed identical to the game for the same seed.
  Fractal, CvRandom and all map/plot semantics are ported line by line (fractal/RNG verified bit-exact).
- **Areas**: VP's `calculateAreas` is ported literally (`--areas literal`, default). Read literally,
  its pathfinder reaches only the start plot, so areas become a greedy scan-order merge; the
  `--areas floodfill` mode is what the C++ author evidently intended. Pangaea's "84 % in one area"
  retry loop needs ~90 attempts under `literal` and 1 under `floodfill`; count the
  "Pangaea landmass generation, Attempt#" lines in the game's `Lua.log` after a real Pangaea
  game to settle which one the shipped DLL does, then set the default accordingly in `host/c5gen.py`.
- Player model: majors in slots 0.., city-states from slot 22, barbarian 63; all `Players[0..63]`
  exist. Start era, handicap and game options are defaults unless passed on the CLI.
- No UI, no WorldBuilder `.Civ5Map` loading, no `Map.DoPlaceNaturalWonders` unless a script needs it.
- DB data comes from the modded game database export (`python host/gamedb.py --force` after a
  VP update or mod change).
