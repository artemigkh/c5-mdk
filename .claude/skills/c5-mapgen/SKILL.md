---
name: c5-mapgen
description: Write, run, debug, render and sanity-check Civilization V (Civ 5) map scripts / mapscripts (Lua) for Vox Populi (VP) or Community Patch headlessly, without launching the game; use for any Civ 5 map generation work (MapGenerator, AssignStartingPlots, FractalWorld, plot/terrain/river/feature/resource/start-plot generation), fixing old or broken map scripts, or comparing a map's land, resources and start spacing against normal community maps.
---

# Civ 5 / Vox Populi map-script development

Workspace: `C:\Users\Art\Documents\c5maps` (run every command from there).
A headless **fake client** (`engine/`, pure Lua 5.1 under `lupa`) re-implements the engine
surface map scripts touch, loads the real VP Lua libraries (MapGenerator, FeatureGenerator,
TerrainGenerator, VP AssignStartingPlots ...) through a mirror of the game's include order,
runs a script end to end, dumps the map and renders it. A standard map takes 2–8 s, duel < 1 s.

## 1. Run a script

```bash
python host/c5gen.py <script> --seed 42 --png --ascii
```
- `<script>`: bare name (`Continents`, `SmallContinents`, `vp:Communitu_79a`, `"mygames:Tectonic v6 - VI"`) or a path.
  `python host/c5gen.py --list-scripts` shows every script found and its tag (`mygames`, `assets`, `exp1`,
  `exp2`, `vp`, `vp-emp`, `cp`, `dlc-sp1..3`). A bare name takes the first match in that order, so
  `Communitu_79a` is the **old My Games copy** (broken under VP); write `vp:Communitu_79a`.
- `--size duel|tiny|small|standard|large|huge` (default standard), `--seed N` (default 42),
  `--civs N --city-states N` (default: `Worlds` table), `--civ-list CIVILIZATION_A,...`,
  `--teams N` (major civs round-robin into N teams; team scripts such as Hemispheres, North_vs_South,
  West_vs_East need `--teams 2`, Four_Corners `--teams 4`), `--era`, `--handicap`.
- `--list-options` prints the script's `CustomOptions` with IDs, values and defaults;
  `--option 4=2 --option 1=3` sets them (1-based IDs and values; the last value is usually "Random").
  A bad ID or out-of-range value prints `c5gen: warning: ...` on stderr and is still passed
  through (the run continues, as the game would), so read stderr after typing option numbers.
- Outputs in `out/<name>/<name>_<size>_<seed>.{json,txt,log}` plus `.png` with `--png`:
  `.png` = hex render (look at it with the Read tool), `.txt` = ASCII map + stats block,
  `.log` = every `print()` plus include resolution and per-phase timing, `.json` = the dump.
- Other flags: `--stats` (stats to stdout), `--no-render` (dump + log only), `--quiet`, `--echo`
  (stream `print()` live), `--timing`, `--profile`, `--rng-trace`, `--areas literal|floodfill` (§6),
  `--runtime luajit21` (≈7× faster, not RNG-identical to the game's Lua 5.1), `--out DIR`.
- Re-render a dump: `python render/render_map.py out/x/x_standard_42.json --layer areas --hex 16`
  (layers: terrain, plain, areas, continents, elevation, resources, startbias; writes `<stem>_<layer>.png`).

A Lua error prints the full traceback and exits 1 (the `.log` is still written). "c5maps:
unimplemented Map.Foo" means the fake client lacks a method: add it to `engine/` (port it from
`C:\Users\Art\Documents\GitHub\Community-Patch-DLL\CvGameCoreDLL_Expansion2\Lua\CvLua*.cpp`), do not
stub it silently. No shipped script hits one today.

## 2. Iteration loop for a script you are writing

1. Start from `templates/Template_Map.lua` (in this skill folder) or an existing VP script; keep the
   `GenerateMap` phase order (plots → coasts → terrain → rivers → lakes → features → start plots).
   `python host/c5gen.py .claude/skills/c5-mapgen/templates/Template_Map.lua --size duel --png` runs as is.
2. Run at standard with 3–5 seeds, look at the PNGs and the stats block. Then duel and huge.
3. Check the numbers against community-normal ranges:
   `python host/metrics.py compare out/<name>/<name>_standard_1.json --archetype Continents`
   (archetypes: Communitu, Continental_Drift, Continents, SmallContinents, Terra, Oval, Archipelago).
   Flags: `LOW/HIGH` = outside pooled p5–p95, `FAR` = outside every reference run, `arch low/high` =
   outside that archetype. `--all` lists every metric; `python host/metrics.py <dump>.json` prints
   them without comparing. Baselines exist for standard and huge only; duel/tiny fall back to
   standard and flag capital spacing by design. Advisory, always exits 0.
   What to respect vs what may differ by design: guide §12 (`docs/mapscript-guide.md`).
4. Read the `.log`: VP AssignStartingPlots prints region fertility, start assignments and
   resource placement; "Switching to use" means the region method fell back.
5. Test teams (`--teams 2`) if the script has team logic, and every option value at duel
   (`--list-options`, then one run per `--option`).
6. When happy, copy the script to
   `C:\Users\Art\Documents\My Games\Sid Meier's Civilization 5\Maps\` and test in game.
   The game's print output goes to `...\My Games\Sid Meier's Civilization 5\Logs\Lua.log`.

## 3. Checking an existing or old script

1. Run it: `python host/c5gen.py <tag:name> --seed 1 --png` (seeds 1–3; some failures are
   seed-dependent because they depend on which civs are picked).
2. Read the traceback. If it ends inside the script's own override of an `AssignStartingPlots`
   method, it is almost always a VP incompatibility, not a harness bug, and fails in game too.
3. Look the script up in `docs/script-compat.md` (status, cause and workaround for all 87 installed
   scripts) and guide §10.12 / Appendix B (which ASP fields and methods VP removed).
4. VP ships fixed copies of most stock scripts (`--list-scripts`, tag `vp:`). If a `vp:` copy
   exists, that is the one players with VP should use; the `assets:` / `exp1:` copy is vanilla.
   Diff the two to see the VP port pattern.
5. "Needs setup" failures: team scripts want `--teams N`; old Communitu wants `--option 16=1`.
6. WorldBuilder hybrids (`WB_Script_*`) cannot run headless (they read a `.Civ5Map` the exe loads).

## 4. Where the knowledge is

| Need | Read |
|---|---|
| How to write a script: lifecycle, template, options, plot/terrain/river/feature generation, VP start-plot system, reusable patterns, gotchas, checklist, normal metric ranges (§12) | `docs/mapscript-guide.md` |
| Exact semantics of every engine call (Map, Plot, Area, Fractal, GameInfo, Game, PreGame), hex math, areas/lakes/rivers algorithms, headless player model, open questions (§17–18) | `docs/engine-api.md` |
| Which installed scripts run, which fail and why, workarounds | `docs/script-compat.md` |
| Full metric tables per archetype and size, methodology | `docs/metrics-baselines.md` (+ `.json`) |
| Which engine API each script uses | `docs/api-usage-matrix.md` |
| Harness architecture, dump JSON format, paths | `DESIGN.md` |
| The real libraries | `...\Civilization V\Assets\Gameplay\Lua`, `...\Assets\DLC\Expansion2\Gameplay\Lua`, and the overriding VP copies under `...\Community-Patch-DLL\(1) Community Patch\Core Files\Overrides\Includes` and `(2) Vox Populi\Core Files\Overrides` |

## 5. Gotchas that bite most often (full list: guide §10)

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
- In VP, **areas are not connected components**: the DLL assigns each plot, in scan order, to the
  largest already-assigned neighbouring area of the same water/land kind, so concave shapes split
  and never re-merge (verified against a real game). Use landmasses (`plot:GetLandmass()`,
  `Map.FindBiggestLandmassID()`) for "same continent" logic; `Map.FindBiggestArea` retry loops
  (vanilla Pangaea) are unreliable under VP.
- `plot:GetArea()` returns an **id**; `Map.GetArea(id)` gives the object. `Area:IsLake` does not exist in VP.
- nil or misspelled IDs passed to engine setters silently become 0 (`FEATURE_ICE`, `PLOT_MOUNTAIN`,
  `TERRAIN_GRASS`...). Enum tables return nil for unknown keys, so typos do not error.
- VP ASP is a class with renamed internals: `GenerateRegions{method = RegionDivision.X, resources = n}`.
  `self.cityStateData`, `self.iNumTypesUnassigned`, `self.naturalWondersData` and
  `self.luxury_low_fert_compensation` no longer exist; overrides that read them crash (guide §10.12).
- VP adds region types 9 (mountain) and 10 (snow) for civs with those start biases: an
  `__InitLuxuryWeights` override must cover them, or the map fails only when such a civ is picked.
- The luxury tile count is fixed per world size, so luxury density falls as land rises; scripts
  often override grid size (Terra standard is 104×64, Communitu huge only 97×66): compare densities.
- Arguments written as `x or true` cannot be turned off (`bExpandCoasts=false` is ignored).
- After generation the engine forces every water plot next to land to COAST.
- Everything at top level of the script runs before the map exists; only `GetMapInitData`
  and later see the grid size.

## 6. What the harness is not

- It is a faithful port, not the game: Lua `pairs()` order and `table.sort` ties can differ from
  Havok Script, so RNG sequences are not guaranteed identical to the game for the same seed.
  Fractal, CvRandom and all map/plot semantics are ported line by line (fractal/RNG verified bit-exact).
- **Areas**: VP's `calculateAreas` is ported literally (`--areas literal`, default) and this was
  verified against a real game: replaying a real Pangaea's plots reproduces every area id
  (`tests/test_areas_real.py`). `--areas floodfill` is only a what-if (the algorithm the C++ reads
  as intended but does not execute). To re-check after a DLL update: run `tests/probes/dump-areas.lua`
  as a `--lua-probe` in civ5-headless and feed the parsed rows to `tests/compare_areas.py`.
- Player model: majors in slots 0.., city-states from slot 22, barbarian 63; all `Players[0..63]`
  exist. Start era, handicap and game options are defaults unless passed on the CLI.
- No UI, no WorldBuilder `.Civ5Map` loading, no `Map.DoPlaceNaturalWonders`.
- DB data comes from the modded game database export (`python host/gamedb.py --force` after a
  VP update or mod change).

## 7. Tests and benchmarks

- Regression (bash; in PowerShell 5.1 replace `&&` with `;`):
  `python tests/run_lua_tests.py && python tests/test_cli.py && python tests/test_sweep_quick.py`
  (≈ 1 min). Also `python tests/test_metrics.py` and `python tests/test_render.py`.
- Full compatibility sweep (slow, rewrites `docs/script-compat.md`): `python tests/sweep.py`, then
  `python tests/sweep.py --write-compat`.
- Re-baseline the metrics after a VP update (≈ 7 min with 10 workers, 700 runs):
  `python host/benchmark.py --seeds 50 --workers 10` (defaults: the 7 reference scripts, standard and
  huge, writes `out/bench/runs.jsonl` and `docs/metrics-baselines.json`). `--scripts a,b --sizes
  standard --seed-list 1,2,3` narrows it, `--resume` skips finished runs, `--recompute` re-measures
  kept dumps after editing `host/metrics.py`, `--report` prints the markdown tables for
  `docs/metrics-baselines.md`.
