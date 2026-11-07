# c5maps

Headless harness and Claude Skill for developing Civilization V map scripts for Vox Populi (VP).

A fake game client written in pure Lua 5.1 (`engine/`, run through `lupa`) re-implements the engine
API that map scripts use (`Map`, `Plot`, `Area`, `Fractal`, `GameInfo`, players and teams). It loads
the real VP / Community Patch Lua libraries in the game's include order, runs any map script end to
end, dumps the result to JSON and renders it as a PNG and as ASCII. A standard map takes 2–8 s, so you
can iterate on a script without launching the game. Generated maps can be checked numerically against
measured ranges from seven common community scripts.

Requirements: Python 3.11 with `lupa` and `Pillow`, a Civ V install with Vox Populi installed in
`My Games\...\MODS`, and a game database cache from a VP game (`cache\Civ5DebugDatabase.db`). Paths
are set in `host/paths.py` (overridable with `C5MAPS_*` environment variables).
`python host/gamedb.py --force` rebuilds the database export in `engine/data/` after a VP or mod update.
The Community-Patch-DLL source repo is only needed as a reference when porting engine behaviour.

## Quickstart

```bash
python host/c5gen.py --list-scripts                                  # every script found, with its source tag
python host/c5gen.py Continents --seed 42 --png --ascii              # -> out/Continents/Continents_standard_42.*
python host/c5gen.py vp:Communitu_79a --size huge --seed 3 --png     # tag picks a specific copy
python host/c5gen.py vp:Terra --list-options                         # the script's CustomOptions
python host/c5gen.py vp:Terra --option 4=1 --png                     # set option 4 to value 1 (1-based)
python host/c5gen.py exp1:Hemispheres --teams 2 --png                # team scripts need teams
python host/metrics.py compare out/Continents/Continents_standard_42.json --archetype Continents
python render/render_map.py out/Continents/Continents_standard_42.json --layer areas
```

To write a new script, start from `.claude/skills/c5-mapgen/templates/Template_Map.lua`.
The workflow, flags and top gotchas are in the skill: `.claude/skills/c5-mapgen/SKILL.md`.

## Layout

| Path | Contents |
|---|---|
| `host/` | `c5gen.py` (CLI runner), `metrics.py` (map metrics and baseline compare), `benchmark.py` (multi-seed baselines), `gamedb.py` (DB export), `paths.py` |
| `engine/` | The fake client in pure Lua 5.1; `engine/data/` is the generated DB export |
| `render/` | `render_map.py`: PNG and ASCII renders of a dump, several layers |
| `tests/` | Engine unit tests (Lua), CLI, render and metrics tests, quick and full script sweeps |
| `docs/` | Reference documentation (below) |
| `.claude/skills/c5-mapgen/` | The Claude Skill and the script template |
| `out/` | Generated maps, logs and renders (gitignored) |

## Documentation

| File | What it covers |
|---|---|
| `docs/mapscript-guide.md` | How to write a VP map script: lifecycle, options, plot/terrain/river/feature generation, VP start plots and resources, patterns, gotchas, checklist, normal metric ranges |
| `docs/engine-api.md` | Exact semantics of every engine call scripts use, hex math, area/lake/river algorithms, open questions |
| `docs/script-compat.md` | Which of the 87 installed scripts run under VP, which fail and why, and workarounds |
| `docs/metrics-baselines.md` | Measured metric ranges for 7 reference scripts at standard and huge (data in `.json`) |
| `docs/api-usage-matrix.md` | Which engine API each script uses |
| `DESIGN.md` | Harness architecture, dump JSON format, paths |

## Tests

```bash
python tests/run_lua_tests.py && python tests/test_cli.py && python tests/test_sweep_quick.py
python tests/test_metrics.py
python tests/test_render.py
python tests/sweep.py                 # full compatibility sweep (slow); --write-compat regenerates docs/script-compat.md
python host/benchmark.py --seeds 50 --workers 10   # re-measure docs/metrics-baselines.json (~7 min)
```

## Limits

The harness ports the engine's map logic line by line, but Lua `pairs()` order and `table.sort`
ties can differ from the game's Havok Script, so the same seed is not guaranteed to give the same map
as in game. VP's area algorithm has two readings (`--areas literal`, the default, and `floodfill`);
see `docs/engine-api.md` §17–18. WorldBuilder-based scripts (`WB_Script_*`) are not supported. Always
confirm a finished script in game.
