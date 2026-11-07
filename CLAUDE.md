# c5maps

Headless harness + Claude Skill for developing Civilization V map scripts compatible with
Vox Populi. Start with the skill: `.claude/skills/c5-mapgen/SKILL.md`. Architecture: `DESIGN.md`.

- Run a script: `python host/c5gen.py <script> --seed 42 --png --ascii` (outputs in `out/`).
- Tests: `python tests/run_lua_tests.py`, `python tests/test_cli.py`, `python tests/test_render.py`,
  `python tests/test_sweep_quick.py`, `python tests/test_metrics.py`.
- `engine/` is pure Lua 5.1 (no goto, no bit ops, doubles only); it must keep running under
  `lupa.lua51`. Port engine behaviour from the Community Patch DLL sources rather than guessing.
- `engine/data/` and `out/` are generated and gitignored (`python host/gamedb.py` rebuilds the DB export).
- Docs: `docs/mapscript-guide.md` (authoring), `docs/engine-api.md` (engine semantics),
  `docs/script-compat.md` (which scripts run), `docs/metrics-baselines.md` (normal map ranges).
