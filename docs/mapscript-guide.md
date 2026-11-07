# Writing Civilization V Map Scripts for Vox Populi

This guide is for a developer, or an AI agent, who knows Lua but not the Civ 5 map generation
pipeline. It is built from the code that actually runs under Vox Populi (VP). Each claim cites
the file (and usually the line) it comes from. Claims marked **(unverified)** come from comments,
naming, or community knowledge and could not be confirmed in source available here (the engine
exe is closed source, and only the DLL is open).

---

## Table of contents

- [Overview: how a map gets made (read this first)](#overview-how-a-map-gets-made-read-this-first) (pipeline order, stock implementations per stage, the seven archetypes compared)
0. [Conventions and source map](#0-conventions-and-source-map)
1. [Lifecycle: what the engine calls, and when](#1-lifecycle-what-the-engine-calls-and-when)
2. [Anatomy of a map script](#2-anatomy-of-a-map-script)
3. [Map options](#3-map-options)
4. [Plot-type generation (land, water, hills, mountains)](#4-plot-type-generation)
5. [Terrain generation](#5-terrain-generation)
6. [Rivers and lakes](#6-rivers-and-lakes)
7. [Features](#7-features)
8. [Start plots, resources, city states, natural wonders (VP AssignStartingPlots)](#8-start-plots-and-resources-under-vp)
9. [Patterns worth stealing](#9-patterns-worth-stealing)
10. [Gotchas and counter-intuitive behaviour](#10-gotchas) (§10.12: lessons from the sweep of every installed script)
11. [Shipping checklist and debugging](#11-shipping-checklist-and-debugging)
12. [Macro metrics: what normal VP maps look like](#12-macro-metrics-what-normal-vp-maps-look-like)
- [Appendix A: API and constants quick reference](#appendix-a-api-and-constants-quick-reference)
- [Appendix B: VP vs vanilla breaking changes](#appendix-b-vp-vs-vanilla-breaking-changes)

---

## Overview: how a map gets made (read this first)

This chapter is the conceptual map of the rest of the guide. It says what the generation stages
are, why they run in that order, which stock implementation each stage has and how far it can be
replaced, and how the seven community reference archetypes differ at each stage. Details, line
references and gotchas live in the numbered sections it points to.

### O.1 The pipeline and why it is in that order

A script normally keeps the default `GenerateMap()` from `CP\MapGenerator.lua` (§1.3) and replaces
the stage functions it calls. The order is fixed by data dependencies, not convention.

| # | Stage | Who provides it | Depends on | Why it sits here |
|---|---|---|---|---|
| 0 | **Script load** | engine | - | All top-level code runs before a map exists. Then `GetMapInitData` sizes the grid, the engine allocates every plot as ocean with no terrain, and only then calls `GenerateMap` (§1.2). |
| 1 | **Plot types** `GeneratePlotTypes` | you | - | Land vs water, and relief on land (flat, hills, mountain). Scripts end it with `GenerateCoasts`, which decides coast vs deep ocean for water (§4, §5.3). |
| 2 | **Terrain** `GenerateTerrain` | you | 1 | Climate on land: grass, plains, desert, tundra, snow. Water keeps its terrain; hills and mountains get a base terrain underneath (§5). |
| 3 | **Area recalculation** `Map.RecalculateAreas` | engine (C++) | 1 | Derived indexes: areas, landmasses, lake flags. Everything later asks "same continent?" through these ids (§10.2). |
| 4 | **Rivers** `AddRivers` | default provided | 1, 3 | Sources on high ground, paths walk toward lower plot types until they reach water. Needs final relief and coastline (§6). |
| 5 | **Lakes** `AddLakes` | default provided | 4 | Inland non-river plots become small water bodies. After rivers so a lake cannot cut a river short (§5.4). |
| 6 | **Features** `AddFeatures` | you | 2, 4, 5 | Forest, jungle, marsh, oasis, flood plains, ice, atolls. Flood plains need rivers, ice needs coast vs ocean, trees need terrain (§7). |
| 7 | **Area recalculation** | engine | 6 | Meant for impassable ice and wonders. Under VP areas ignore passability, but landmass, lake and coastal flags still refresh (§10.2.1). |
| 8 | **Start plot system** `StartPlotSystem` | library (ASP) | everything | Regions, capitals, start normalisation, civ-to-region assignment by start bias, **then** natural wonders kept away from capitals, **then** city states, luxuries, strategics and bonuses placed around all of that. Ends with a final area recalculation (§8). |
| 9 | **Goody huts** `AddGoodies` | default provided | 8 | Avoid resources, wonders and starts. |
| 10 | **Continent art** `DetermineContinents` | default provided | 7 | Cosmetic art-set stamping (§9.16). |
| - | **Coast validation** | engine | - | After the Lua thread ends, any water plot next to land is forced to coast terrain, whatever the script did (§1.2). |

The common misconception is that resources come before starts. They do not. Capitals are chosen on
bare terrain, and luxuries, strategics and wonders are then distributed relative to them (3
luxuries within 3 plots of every capital, strategic balance, wonder exclusion radius). That is why
start-related metrics are invariant across archetypes (§12.3).

**Data model.** The map is a struct of arrays over the plot grid. Each stage writes one layer:
plot type, terrain, three river-edge flags per plot, feature, resource plus quantity, and finally
start plots. Setters have cross-layer side effects: changing a plot's water-ness resets its
terrain, setting a water terrain on land flips the plot type (§10.3), and river crossing flags are
computed only inside the river setter and only count when both sides are land (§6.2). That is the
real reason rivers must wait until relief is final.

**What is C++ and what is Lua.** The engine side is small: the map RNG, the diamond-square
`Fractal` object, plot storage and setters, area and landmass computation, river crossing flags,
`CanHaveFeature` (reads the database), the continent stamper, and the final coast validation.
`FractalWorld`, `TerrainGenerator`, the river walker, `FeatureGenerator`, `MapmakerUtilities` and
the whole start-plot library are Lua you can read, override method by method, or replace.

### O.2 Each stage: stock implementation, knobs, and how far custom goes

Three levels of customisation exist at every stage:

1. **Arguments** to a stock generator.
2. **Method override** on a stock class at file top level. The stock generators are prototype
   tables, so `function FeatureGenerator:AddIceAtPlot(...)` in your script replaces that step for
   every instance created afterwards.
3. **Replace the stage's global function** and write every plot yourself.

**Plot types (stage 1).**
- `FractalWorld` (§4.2): one fractal thresholded at a water percentile for land, two more with
  Voronoi ridgelines for hills and mountains, a shift so the emptiest column sits on the map seam,
  optional center rift. Knobs: continent grain, rift grain, three sea-level percentiles, world age,
  extra mountains, plate multiplier, tectonic islands. Subclass it to add a reject-and-retry loop
  (Continents, Pangaea).
- `MultilayeredFractal` (§4.4): rectangular regions, each with its own fractal, then one
  tectonics pass over the whole world. Regions can also be filled analytically (Oval's ellipse).
- `IslandMaker` (§4.5): island-chain stencils you stamp in.
- Fully custom: plates (§4.7), Perlin heightmaps (§4.8). The only contract is a plot type for every
  plot and a coast pass afterwards.
- Hard limits: fractal grids are capped at 255, and the engine's coast validation always runs.

**Terrain (stage 2).**
- `TerrainGenerator` (§5.2): latitude bands roughened by a fractal, with desert and plains fractals
  inside the temperate band. Knobs: temperature, desert and plains percent, band latitudes.
- Override `GetLatitudeAtPlot` for a bent climate, `GenerateTerrainAtPlot` for a different band
  rule, or discard it for a temperature-times-rainfall model (Communitu, §9.1).
- Hard limit: never assign the graphical hill or mountain terrains (§5.1).

**Rivers (stage 4).**
- Default `AddRivers` (§6.3): four passes pick sources on hills and mountains, then in river-poor
  areas. The walker turns left or right by a plot-type score plus noise and stops at water or an
  existing river.
- Steer it by overriding the global `GetRiverValueAtPlot` (§9.5). Replace it with your own
  edge-flag writer when you have an elevation model (Communitu's junction-based `RiverMap`, §9.4).

**Lakes (stage 5).**
- Default `AddLakes`: each eligible inland plot has a 1 in 160 chance (§5.4).
- A lake is not a terrain. Any water landmass under 10 plots is a lake, so a script makes lakes by
  writing small water blobs (Continental Drift) or by filling and later restoring small seas
  (Communitu). Disable the default by defining an empty `AddLakes`.

**Features (stage 6).**
- `FeatureGenerator` (§7.1): visits each plot in a fixed order (flood plains, oasis, ice, marsh,
  jungle, forest) driven by rainfall and grain-controlled fractals, ices the polar rows, converts
  coastal mountains to hills unless told not to, places atolls, softens terrain under jungle.
  Knobs: rainfall and the per-feature percents and grains.
- Override single methods (`AddIceAtPlot`, `AddAtolls`) or replace the stage.
- Hard limit: the database decides which features may sit on which terrain (§7.2); the raw setter
  does no checking at all, which is how natural wonders get placed.

**Starts and resources (stage 8).** This is a library you configure, not a stage you rewrite.
Six calls in a fixed order on one instance (§8.1):

| Call | What it decides | Main arguments / hooks |
|---|---|---|
| `Create()` | resource ids, impact layers, config constants | `__CustomInit` (instance-level overrides) |
| `GenerateRegions(args)` | one region per civ by method: biggest landmass, continental (with automatic fallbacks), one rectangle, self-defined rectangle; resource density | `method`, `resources`, Communitu-style split settings; `CustomOverride()` runs at the end (§8.2) |
| `ChooseLocations(args)` | a start per region, poorest regions first | `mustBeCoast`, food/production thresholds (§8.3) |
| `BalanceAndAssign()` | normalises each start, then an optimal assignment of civs to regions by database start bias | geography only (§8.4) |
| `PlaceNaturalWonders()` | count by map size, candidates from a database table, outside the start impact radius | `GetNumNaturalWondersToPlace` (§8.5) |
| `PlaceResourcesAndCityStates()` | luxury roles per region, city states split between civ regions and empty land, luxuries, strategics, bonuses, tile fix-ups, final area recalculation | per-step methods (`PlaceFish`, `PlaceBonusResources`, ...), `__InitLuxuryWeights`, city-state count methods (§8.6, §8.7) |

Customisation hooks, broad to narrow, are in §8.8. The one hard rule: nothing may recalculate
areas while the library runs, because regions are keyed by area or landmass id.

### O.3 The seven reference archetypes, stage by stage

| Script | Plot types | Terrain | Rivers and lakes | Features | Starts and resources |
|---|---|---|---|---|---|
| **Continents** | FractalWorld subclass. Grain 1 or 2 rerolled per attempt, optional rift grain, center rift carved, rejects until the biggest area is at most 58 % of land. Sea 67/72/76. | Stock | Stock | Stock. Calls the feature pass with no argument, so under VP coastal mountains become hills. | Continental method, default thresholds. |
| **Small Continents** | FractalWorld, grain 3, sea 69/75/80, extra mountains, 1.5x plates, tectonic islands. No retry. | Stock | Stock | Stock, coastal mountains removed. | Continental method, coastal starts forced, offshore-expansion AI hint. |
| **Archipelago** | FractalWorld, grain 4, sea 72/78/83, 2x plates, tectonic islands. Coast expansion dice 10/4/4 for wide shelves. | Stock | Stock | Stock, coastal mountains removed. | Rectangular method ignoring landmasses, coastal starts forced, lowered food and production thresholds, naval AI hint. |
| **Oval** | Own smaller grid. MultilayeredFractal with an analytic ellipse for land, a bays fractal eroding outside a cohesion ellipse, one tectonics pass. | Stock | Stock | Stock, coastal mountains removed. | Biggest-landmass method. |
| **Terra** (VP) | Own larger grid. MultilayeredFractal with a hand-laid world plan: a big Old World rectangle, a New World, a third continent, two subcontinents, hemispheres flipped by dice, then tectonics with islands. | Stock | Stock | Stock, coastal mountains removed. | Biggest-landmass method so every civ starts on the Old World. Class overrides put up to two thirds of city states in empty land and raise random and world luxury targets for the bigger map. |
| **Continental Drift** (VP) | Own grid. Replaces the FractalWorld generator wholesale: about 40 Voronoi plates with mass and velocity, two polar plates filled with water, plates typed continental, fractal, island, ocean or deep ocean to hit a land target, boundaries classified as collision, rift or transform, optional deep-ocean rift columns, map seam moved to a water column, value-noise heightmaps. Fills every lake it produced back to land. Custom coast pass. | Stock, plus a recalculation and debug dumps. | Stock rivers. Custom blob lakes of one to five plots, count scaled by size and rainfall, kept out of the polar fifths. | FeatureGenerator with heavy settings: jungle 67, forest 45, marsh 18, oasis 15, coarser grains. Keeps coastal mountains. Overrides ice to thin it out and overrides atolls. | Method chosen by option, default continental. Coastal forcing by option. AI hint from the biggest area's share. |
| **Communitu_79a** (VP) | Own grid. Everything is computed up front here: twisted Perlin elevation plus a mountain map, arctic rows cleared, vertical ocean rifts in an Atlantic and Pacific pattern, a guaranteed circumnavigation channel, sea-to-ocean connections, small seas filled, Terra-style continent linking, then temperature and rainfall maps and the whole river network. Plot types by percentile thresholds, then island groups stamped from IslandMaker stencils, then coasts. | Own model. Temperature bands times rainfall thresholds give snow, tundra, plains, grass and desert, then a blending pass. | Rivers copied from its junction model, with a plot demoted to hills when a river runs between mountains. Stock lakes disabled. Lakes filled during plot types are restored here, and every river edge touching water is stripped. | Fully custom. Trees and jungle by rainfall percentiles, oasis, extra forest, own ice and atoll rules, polar seas reconnected, flood plains re-added after rivers are final. | Terra-style or continental by option, with split density settings for strategic count, deposit size, bonus and luxury. An instance-level init replaces fertility measurement, wonder count, city states in empty land, strategic and bonus placement, fish, and the top-level resource driver, and adds an island-buffing pass. Own continent art stamping. |

Three patterns fall out of the table:

- **The four vanilla scripts differ only in stage 1 and in the start-plot arguments.** Terrain,
  rivers, lakes and features are stock for all of them. Their very different feel comes from grain,
  sea level and the region method alone.
- **The VP scripts re-author stages in proportion to how much geography they model.** Terra changes
  only the land plan and a few city-state and luxury numbers. Continental Drift rewrites landform
  and lakes and tunes features. Communitu replaces every geography stage with one coherent model,
  computed in a single pass before any plot is written, and reaches deep into the start-plot library.
- **Nobody rewrites the start-plot pipeline's order.** Even Communitu keeps the six calls and swaps
  individual methods. That library encodes the spacing, luxury and wonder invariants measured in
  §12, which is why those metrics barely move between archetypes while land share, landmass count
  and coastline do.

The archetype signatures in §12.4 map directly onto these choices: Archipelago's high coast share
comes from its coast dice, Terra's distant city states from the two-thirds-in-empty-land override,
Continental Drift's forest and marsh from its feature percents, and Communitu's river density from
its junction model.

---

## 0. Conventions and source map

Short names used throughout:

| Alias | Path |
|---|---|
| `CIV5` | `C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V` |
| `BASE` | `CIV5\Assets\Gameplay\Lua\` (vanilla libraries) |
| `BNW` | `CIV5\Assets\DLC\Expansion2\Gameplay\Lua\` (Brave New World overrides) |
| `REPO` | `C:\Users\Art\Documents\GitHub\Community-Patch-DLL\` |
| `CP` | `REPO\(1) Community Patch\Core Files\Overrides\Includes\` |
| `VPO` | `REPO\(2) Vox Populi\Core Files\Overrides\` |
| `VPMS` | `REPO\(2) Vox Populi\Mapscripts\` (VP-adapted map scripts, including Communitu_79a) |
| `DLL` | `REPO\CvGameCoreDLL_Expansion2\` |
| `MYMAPS` | `C:\Users\Art\Documents\My Games\Sid Meier's Civilization 5\Maps\` |

**Which library files run under VP.** Mods import files into the virtual file system (VFS), and a
later-loaded mod replaces a same-named file from an earlier one. VP depends on CP, so with both
enabled the active files are:

| File | Active copy under VP | Notes |
|---|---|---|
| `MapGenerator.lua` | `CP\MapGenerator.lua` (799 lines) | Adds the `PreMapGenScript` hook. `Plots()` and `Shuffle()` moved out of it. |
| `MapmakerUtilities.lua` | `CP\MapmakerUtilities.lua` (1052 lines) | Now defines `Plots`, `Shuffle`, and many VP helpers. It includes `VPUI_core` and `CPK.lua`. |
| `AssignStartingPlots.lua` | `VPO\AssignStartingPlots.lua` (9336 lines) | A class rewrite. `CP\AssignStartingPlots.lua` (10436 lines, vanilla-style) runs only in Community-Patch-only mode. |
| `FeatureGenerator.lua` | `VPO\FeatureGenerator.lua` | Behaviour changes are listed in §7. |
| `NaturalWondersCustomMethods.lua` | `VPO\NaturalWondersCustomMethods.lua` | Custom NW eligibility and placement. |
| `TerrainGenerator.lua`, `FractalWorld.lua`, `MultilayeredFractal.lua`, `IslandMaker.lua` | `BASE\...` | Not overridden. |
| `HintedWorld.lua` | `BASE\HintedWorld.lua` is a **0-byte file** in this install | Also, `Fractal` exposes no hinted constructor to Lua (§4.6). |
| `MapUtilities.lua` | `BASE` | Front-end UI helper (map browser). Not part of map generation. |

The modinfo files confirm the VFS import (`import="1"`) for each override:
`REPO\(1) Community Patch\(1) Community Patch (v 151).modinfo:501-505` and
`REPO\(2) Vox Populi\(2) Vox Populi (v 17).modinfo:1074,1099,1110`.

VP also ships VP-adapted copies of many stock scripts in `VPMS` (Amazon_XP, Arborea, Boreal,
Communitu_79a, Continental_Drift, Europe, Four_Corners, Frontier, Great_Plains_XP, Highlands,
InlandSea, Lakes, Large_Islands, North_vs_South, Rainforest, Ring, Script_Random_China, Skirmish,
Terra, West_vs_East, and EMP/*). They register as `<EntryPoint type="MapScript">` (VP modinfo
around line 1688). **Study the VPMS copies, not the vanilla `CIV5\Assets\Maps` ones.** Several
vanilla scripts override ASP methods that VP removed or re-signatured (Appendix B); the full list of
installed scripts that fail under VP, and why, is in §10.12 and `docs/script-compat.md`.

The `MapScripts` table in the game database lists the same `Communitu_79a.lua` three times on this
machine: under `Assets\Maps`, under `MYMAPS`, and from the VP mod folder. They are different
versions: `MYMAPS` has 7152 lines and `VPMS` has 7663. Make sure you test the copy you think you
are testing: the older one fails under current VP (§10.12.6).

For what a "normal" map looks like in numbers (land %, resource densities, capital spacing, climate bands)
and how to check a new script against that, see §12.

---

## 1. Lifecycle: what the engine calls, and when

### 1.1 Front end (game setup screen)

The setup screens read script metadata from database tables, not by calling the script directly.
`CIV5\Assets\UI\FrontEnd\GameSetup\AdvancedSetup.lua:50` and `:189` query `MapScriptOptions` and
`MapScriptOptionPossibleValues`, filtered by `FileName`. Those tables, and `MapScripts`, are filled
by the engine when it scans map scripts and calls the global `GetMapScriptInfo()`. **(The scanning
itself happens in the exe and is unverified. The tables and their columns are verified in
`Civ5DebugDatabase.db`.)**

- `MapScripts` columns: `FileName, Name, Description, IsAdvancedMap, SupportsSinglePlayer,
  SupportsMultiplayer, DefaultCityStates, Hidden, IconIndex, IconAtlas, FolderType`.
- `MapScriptOptions` columns: `FileName, OptionID, Name, Description, ReadOnly, Hidden,
  DefaultValue, SortPriority`.

Practical consequence: if you edit `GetMapScriptInfo` (option lists, names), the game may need a
restart, or a refresh of the database cache, before the UI shows the change **(unverified;
inferred from the DB-backed UI)**.

> The entry point is **`GetMapScriptInfo()`**, not `GetMapScriptOptions()`. Options go in its
> `CustomOptions` field (§3).

### 1.2 In-game generation (`DLL\CvGame.cpp:576-605`, `DLL\CvMapGenerator.cpp`)

```
CvGame map init (not a WorldBuilder map):
  1. new CvMapGenerator(scriptName)
       -> creates a Lua thread named "Map Script" and LoadFile()s the script
       -> ALL TOP-LEVEL CODE OF YOUR SCRIPT RUNS NOW (includes, global definitions,
          top-level ASP overrides). The new map does not exist yet.
  2. GetMapInitData(worldSize)      [optional global]   CvMapGenerator.cpp:48, 104
       -> if it returns a table: Width, Height, WrapX, WrapY, TopLatitude, BottomLatitude
          override the defaults (each field is optional)
       -> otherwise defaults: Worlds.GridWidth/GridHeight, WrapX=true, WrapY=false,
          TopLatitude=90, BottomLatitude=-90   (CvGameCoreDLLUtil\include\CvStructs.h:147-163)
  3. kMap.init(&data)               (the plot array now exists)
  4. GenerateMap()                  [required global]   CvMapGenerator.cpp:277-289
       -> luaL_error "Cannot find map script entry point GenerateMap()" if missing
       -> MapGenerator.lua provides a default GenerateMap; you normally don't define it
  5. GetGameInitialItemsOverrides() [optional global]   CvMapGenerator.cpp:91, 152
       -> table of per-team/per-player booleans: GrantInitialFreeTechsPerTeam,
          GrantInitialGoldPerPlayer, GrantInitialCulturePerPlayer,
          ClearResearchQueuePerPlayer, GrantInitialUnitsPerPlayer (used by scenarios)
  6. Lua thread freed. Then, in C++, for EVERY map (CvGame.cpp:600):
       CvWorldBuilderMapLoader::ValidateCoast()  -- any water plot that is not COAST and is
          adjacent to land becomes TERRAIN_COAST  (CvWorldBuilderMapLoader.cpp:1779-1806)
       CvMap::updateAdjacency()
```

Consequences:

- **Do not query the map at file top level.** `Map.GetGridSize()` and `Map.GetPlot()` run before
  `kMap.init`. Communitu defers everything into `MapGlobals:New()`, which it calls from
  `GeneratePlotTypes()` (`VPMS\Communitu_79a.lua:1743`).
- `GetMapInitData` *can* call `Map.GetCustomOption` and `GameInfo` (pregame data). Communitu and
  Tectonic use this to change the map size based on an option (`VPMS\Communitu_79a.lua:1404`,
  `MYMAPS\Tectonic v6 - VI.lua:308`).
- `GetMapInitData` must return integers. Tectonic returns `grid_size[1] * 0.95 * 1.05`, which is
  fractional. The engine reads it with `lua_tointeger`. On x86 builds, Lua 5.1 may round or
  truncate depending on `luaconf.h` **(unverified)**. Apply `math.floor` yourself.

### 1.3 The default `GenerateMap()` (`CP\MapGenerator.lua:742-797`)

```lua
function GenerateMap()
  -- VP/CP: include every activated mod's "PreMapGenScript" entry point (ASP override hook)
  for entryPoint in Modding.GetActivatedModEntryPoints("PreMapGenScript") do ... include(file) end
  GeneratePlotTypes();      -- you override
  GenerateTerrain();        -- you override
  Map.RecalculateAreas();   -- C++: areas, landmasses, continents, rivers
  AddRivers();              -- default provided; override for custom rivers
  AddLakes();               -- default provided (random 1-plot lakes); override to disable
  AddFeatures();            -- you override (usually FeatureGenerator)
  Map.RecalculateAreas();   -- ice/NW impassability changes areas
  StartPlotSystem();        -- ASP: regions, starts, NWs, resources, city states
  AddGoodies();             -- goody huts
  DetermineContinents();    -- art sets; default calls Map.DefaultContinentStamper()
end
```

Everything above runs in Lua except the `Map.*` calls into C++ (`RecalculateAreas`,
`DefaultContinentStamper`, `Fractal`, and the plot setters). ASP's `PlaceResourcesAndCityStates()`
ends with another `Map.RecalculateAreas()` (`VPO\AssignStartingPlots.lua:8661`).

### 1.4 `include` and file resolution

- `include("MapGenerator")` takes the bare file name, with no path and no `.lua`. The engine
  resolves it through the VFS, so a mod's VFS copy wins over the base asset **(resolution rules are
  engine-side and unverified; VFS override behaviour is consistent with every file in this repo)**.
- `include` re-executes the file each time. The VP ASP header comment relies on this (*"every time
  this file is called, the AssignStartingPlots (ASP) table would be reset"*,
  `VPO\AssignStartingPlots.lua:75-80`). So if you `include("AssignStartingPlots")` again after
  overriding ASP methods at top level, your overrides are wiped.
- `MapGenerator.lua` includes `AssignStartingPlots`, which includes `MapmakerUtilities`,
  `NaturalWondersCustomMethods` and `VPUI_core`. `MapmakerUtilities` includes `VPUI_core` and
  `CPK.lua`. A headless harness must provide all of these.
- The usual header in stock scripts: `include("MapGenerator")`, then `FractalWorld` or
  `MultilayeredFractal`, `FeatureGenerator`, `TerrainGenerator`, and optionally `IslandMaker`,
  `MapmakerUtilities` or `FLuaVector`.

---

## 2. Anatomy of a map script

### 2.1 Which globals you define and which `MapGenerator.lua` provides

| Global | Who calls it | Default in `CP\MapGenerator.lua` | Do you define it? |
|---|---|---|---|
| `GetMapScriptInfo()` | front end / DB scan | none | **Yes** (or the script has no name or options) |
| `GetMapInitData(worldSize)` | engine | none (engine defaults) | Optional |
| `GenerateMap()` | engine | yes (:742) | Rarely. You can wrap it (§9.15). |
| `GeneratePlotTypes()` | GenerateMap | all-land shell (:191), plus an off-by-one (§10) | **Yes** |
| `GenerateTerrain()` | GenerateMap | all-grass shell (:207) | **Yes** |
| `AddRivers()` | GenerateMap | yes, `DoRiver` based (:462) | Optional |
| `AddLakes()` | GenerateMap | yes (:518) | Optional (Communitu disables it) |
| `AddFeatures()` | GenerateMap | naive shell (:546), very slow | **Yes** (call FeatureGenerator) |
| `StartPlotSystem()` | GenerateMap | yes (:709), no args, so method 2 and resources 2 | Usually (to pass `method` and `resources`) |
| `AddGoodies()` | GenerateMap | yes (:634) | Rarely |
| `DetermineContinents()` | GenerateMap | yes (:678) | Optional (art sets) |
| `GetRiverValueAtPlot(plot)` | DoRiver | yes (:227) | Optional (steer rivers) |
| `GetGameInitialItemsOverrides()` | engine | none | Scenarios only |

Helper globals you get for free: `SetPlotTypes(t)`, `SetTerrainTypes(t)`, `GenerateCoasts(args)`,
`GetCoreMapOptions()`, `DoRiver(...)`, `TurnRightFlowDirections` and `TurnLeftFlowDirections`
(from `MapGenerator`), plus `Plots()`, `Shuffle()`, `GetShuffledCopyOfTable()`,
`Plot_GetPlotsInCircle()`, `GetLandmassBoundaries()`, `GetRandomFromRangeInclusive()` and the rest
of `MapmakerUtilities`.

### 2.2 The smallest valid script

```lua
include("MapGenerator");   -- brings default GenerateMap, ASP, MapmakerUtilities

function GetMapScriptInfo()
  return { Name = "Minimal", Description = "", IsAdvancedMap = false, IconIndex = 0,
           CustomOptions = {} };
end

function GeneratePlotTypes()
  local w, h = Map.GetGridSize();
  for y = 0, h - 1 do
    for x = 0, w - 1 do
      local plot = Map.GetPlot(x, y);
      local land = (x > 3 and x < w - 4 and y > 3 and y < h - 4);
      plot:SetPlotType(land and PlotTypes.PLOT_LAND or PlotTypes.PLOT_OCEAN, false, false);
    end
  end
  GenerateCoasts();          -- sets COAST/OCEAN terrain on water
end

function GenerateTerrain()
  for _, plot in Plots() do
    if not plot:IsWater() then plot:SetTerrainType(TerrainTypes.TERRAIN_GRASS, false, false) end
  end
end
-- AddFeatures/StartPlotSystem etc. fall back to MapGenerator defaults.
```

This is valid but poor: the default `AddFeatures` iterates `GameInfo.Features()` for every plot.

### 2.3 The standard template (VP-friendly)

This mirrors `Continents.lua` and the VPMS scripts. Verify option indices against your own
`CustomOptions` order.

```lua
include("MapGenerator");
include("FractalWorld");
include("FeatureGenerator");
include("TerrainGenerator");

function GetMapScriptInfo()
  local world_age, temperature, rainfall, sea_level, resources = GetCoreMapOptions();
  return {
    Name = "TXT_KEY_MAP_MYSCRIPT", Description = "TXT_KEY_MAP_MYSCRIPT_HELP",
    IsAdvancedMap = false, SupportsMultiplayer = true, IconIndex = 1, SortIndex = 2,
    CustomOptions = {world_age, temperature, rainfall, sea_level, resources}, -- ids 1..5
  };
end

local function Opt(id, numReal)            -- resolve "Random" (= last value) deterministically
  local v = Map.GetCustomOption(id) or 2;  -- nil if option missing
  if v > numReal then v = 1 + Map.Rand(numReal, "Random option " .. id) end
  return v;
end

function GeneratePlotTypes()
  local fw = FractalWorld.Create();
  fw:InitFractal{continent_grain = 2};
  local plotTypes = fw:GeneratePlotTypes{sea_level = Opt(4, 3), world_age = Opt(1, 3)};
  SetPlotTypes(plotTypes);                 -- expects 1-based table (index = y*W+x+1)
  GenerateCoasts();
end

function GenerateTerrain()
  local tg = TerrainGenerator.Create{temperature = Opt(2, 3)};
  SetTerrainTypes(tg:GenerateTerrain());   -- expects 0-based table (index = y*W+x)
end

function AddFeatures()
  FeatureGenerator.Create{rainfall = Opt(3, 3)}:AddFeatures();
end

function StartPlotSystem()
  local res = Map.GetCustomOption(5) or 2; -- 1..3 density, 4 legendary, 5 strat balance, 6 random
  local asp = AssignStartingPlots.Create();
  asp:GenerateRegions{method = RegionDivision.CONTINENTAL, resources = res};
  asp:ChooseLocations();
  asp:BalanceAndAssign();
  asp:PlaceNaturalWonders();
  asp:PlaceResourcesAndCityStates();
end
```

Order is mandatory. `MapGenerator.lua:713-721` says: *"They are all interwoven and
interdependent. Do not change this order of operations."*

---

## 3. Map options

### 3.1 Shape of `CustomOptions`

Each entry is a table:

```lua
{
  Name = "TXT_KEY_...",            -- or a literal string
  Description = "TXT_KEY_...",     -- tooltip (optional)
  Values = { "TXT_KEY_A", "TXT_KEY_B", "TXT_KEY_RANDOM" },  -- omit Values => checkbox
  DefaultValue = 2,                -- 1-based index into Values (checkbox: 0/1)
  SortPriority = -99,              -- lower shows first; ties sort alphabetically
}
```

Other top-level keys seen in `GetMapScriptInfo` returns: `Name`, `Description`, `IsAdvancedMap`,
`SupportsMultiplayer`, `SupportsSinglePlayer`, `DefaultCityStates`, `IconIndex`, `IconAtlas`
(for example `"WORLDTYPE_ATLAS_3"`), `SortIndex`, and `Folder` (for example
`"MAP_FOLDER_SP_DLC_1"`). These map onto the `MapScripts` columns.

Options without `Values` show as checkboxes, and their value is `0` or `1`
(`AdvancedSetup.lua:189-203`). The DB also supports `ReadOnly` and `Hidden` per option.

### 3.2 `Map.GetCustomOption(i)`: indexing rules

- **`i` is the 1-based position in your `CustomOptions` array.** `Continents.lua` uses `1` for
  world age, `2` temperature, `3` rainfall, `4` sea level, `5` resources (`Continents.lua:79-83,
  263, 280, 295`). Another script's numbering differs. VP's `Terra.lua` reads resources from
  option `4` (`VPMS\Terra.lua:597`).
- **The returned value is the 1-based index into `Values`.**
- Internally the binding calls `luaL_checkstring(L, 1)` and looks the option up by name
  (`DLL\Lua\CvLuaMap.cpp:447-457`). The numeric index is coerced to the string `"1"`, `"2"`, and so
  on, matched against `OptionID`. If it is not set, the engine falls back to the DB `DefaultValue`
  for this script's file name (`DLL\CvPreGame.cpp:1490-1519`). If neither exists, **the call
  returns nothing (nil)**. Always write `Map.GetCustomOption(n) or default`.
- **"Random" is not a sentinel.** It is just the last entry in `Values`, and every script must
  resolve it itself, as `Continents.lua:80` does: `if sea_level == 4 then sea_level = 1 +
  Map.Rand(3, ...) end`. For the core resources option, Random is value `6`.
- The core options from `GetCoreMapOptions()` (`CP\MapGenerator.lua:15-78`) are:

| Option | Values (1-based) | Default |
|---|---|---|
| world_age | 3 Byr, 4 Byr, 5 Byr, Random | 2 |
| temperature | Cool, Temperate, Hot, Random | 2 |
| rainfall | Arid, Normal, Wet, Random | 2 |
| sea_level | Low, Medium, High, Random | 2 |
| resources | Sparse, Standard, Abundant, Legendary Start, Strategic Balance, Random | 2 |

Their `SortPriority` values are -99 to -95, so they appear first.

> **World age mapping is easy to get backwards.** Value `1` means **3 billion years**, a *young*
> world with *more* mountains. In `FractalWorld:GeneratePlotTypes`, `world_age == 1` uses
> `world_age_new` (5), meaning more hills and peaks, and `world_age == 3` uses `world_age_old`
> (2) (`BASE\FractalWorld.lua:614-623`).

### 3.3 How VP and Communitu expose options

- `VPO\AssignStartingPlots.lua:1444-1467`: `GenerateRegions(args)` reads `args.resources`
  (1-3 density, 4 legendary, 5 strategic balance, 6 random, which it resolves to 1-3 itself).
  With `args.comm = true`, it instead takes separate `args.resources` (strategic density),
  `args.size` (deposit size), `args.bonus`, `args.lux`, `args.legend`, and `args.balance`.
- Communitu defines 16 options, documented at `VPMS\Communitu_79a.lua:193-211`. It reads them in
  `MapGlobals:New()` and `StartPlotSystem()`, and option 16 toggles its ASP overrides.
- **Communitu bug found while writing this:** `StartPlotSystem` passes `legendary = legStart`
  (`VPMS\Communitu_79a.lua:1711`), but ASP reads `args.legend` (`VPO\...ASP.lua:1466`). Also, with
  the default override option (16 = 2), a Strategic Density of "Random" (4) is passed unresolved as
  `resources = 4`, and ASP then treats it as **Legendary Start**
  (`self.legStart = args.legend or (args.resources == 4)`).
- `IsTropical(y)` in `CP\MapmakerUtilities.lua:776-800` reads `Map.GetCustomOption(2)` and assumes
  it is *rainfall*. In every script that uses `GetCoreMapOptions()`, option 2 is *temperature*.

### 3.4 `GetMapInitData(worldSize)`

`worldSize` is the `Worlds.ID` (0 Duel to 5 Huge). Default grid sizes in the current DB:

| ID | Type | Grid W×H | DefaultPlayers | DefaultMinorCivs | FeatureGrainChange |
|---|---|---|---|---|---|
| 0 | WORLDSIZE_DUEL | 40×24 | 2 | 4 | -1 |
| 1 | WORLDSIZE_TINY | 56×36 | 4 | 8 | -1 |
| 2 | WORLDSIZE_SMALL | 66×42 | 6 | 12 | 0 |
| 3 | WORLDSIZE_STANDARD | 80×52 | 8 | 16 | 0 |
| 4 | WORLDSIZE_LARGE | 104×64 | 10 | 20 | 1 |
| 5 | WORLDSIZE_HUGE | 128×80 | 12 | 24 | 1 |

Typical override (`VPMS\Highlands.lua:66-85`):

```lua
function GetMapInitData(worldSize)
  local sizes = { [GameInfo.Worlds.WORLDSIZE_DUEL.ID] = {32, 20}, --[[ ... ]] };
  local s = sizes[worldSize];
  if GameInfo.Worlds[worldSize] then
    return { Width = s[1], Height = s[2], WrapX = false };   -- omit fields to keep defaults
  end
end
```

`TopLatitude` and `BottomLatitude` (clamped to ±90, `DLL\CvMap.cpp:866-873`) only affect
`plot:GetLatitude()` (`DLL\CvPlot.cpp:5644-5660`). That in turn feeds resource
`MinLatitude`/`MaxLatitude` checks in `CanHaveResource` (`CvPlot.cpp:2519-2527`). The stock
Terrain and Feature generators **ignore them** and compute latitude from `y` alone (§5).

Odd widths are fine. Communitu uses 79×53 and 69×46 (`VPMS\Communitu_79a.lua:1395-1402`).

### 3.5 Harness-only numeric overrides (`--define`)

`CustomOptions` are discrete menu entries, which is the wrong shape for tuning a continuous knob
(a land fraction, a fractal grain, a ridge weight). The c5maps harness has a side channel for that:
`python host/c5gen.py MyMap --define W=0.25 --define name=abc` sets a global table
`C5MAPS_DEFINES` (here `{ W = 0.25, name = "abc" }`) before the script's top-level code runs.
Values parse as int, else float, else `true`/`false` → boolean, else string; the run log records
`[c5maps] defines: W=0.25, name=abc` (keys in byte order). Without `--define` the global is nil.
(The `and ... or` idiom below cannot carry a `false` define; test `~= nil` for boolean knobs.)

This is a c5maps convenience, not a game feature: in Civ V `C5MAPS_DEFINES` is always nil. So the
script must always fall back to its option-derived value, and then the same file ships unchanged:

```lua
local landPct = ({ 0.30, 0.38, 0.46 })[Map.GetCustomOption(2)] or 0.38
local W = (C5MAPS_DEFINES and C5MAPS_DEFINES.W) or landPct
```

Read it inside the generation functions (or at top level; it is set before the chunk loads). Use it
to sweep a parameter numerically while tuning (`for w in 0.2 0.25 0.3 ...`, compare metrics per run;
`host/sheet.py --run "w=0.2|--define W=0.2" ...` puts the runs side by side, §11.2),
then bake the chosen value into the options table. Do not use it for anything a player should pick.

---

## 4. Plot-type generation

Plot types are the base layer: `PLOT_MOUNTAIN = 0`, `PLOT_HILLS = 1`, `PLOT_LAND = 2`,
`PLOT_OCEAN = 3` (`REPO\LuaCATS\enum\PlotTypes.d.lua`). Hills and mountains are *plot types*, not
terrains. A hill plot still has a base terrain (grass, plains, and so on).

### 4.1 Writing plot types: two styles

1. **Table, then `SetPlotTypes(t)`** (`CP\MapGenerator.lua:130-139`). The table must be
   **1-based**: `t[y*W + x + 1]`. The function iterates `Plots()` (0-based index `i`) and reads
   `plotTypes[i + 1]`. It calls `SetPlotType(v, false, false)`, so no area recalculation happens.
2. **Direct writes**: `plot:SetPlotType(PlotTypes.PLOT_HILLS, false, false)`. The Lua signature is
   `SetPlotType(type, bRecalculate, bRebuildGraphics, bEraseUnitsIfWater)`
   (`DLL\CvPlot.cpp:7225`). Missing booleans are `false`
   (`REPO\CvGameCoreDLLUtil\include\CvLuaArgTemplates.h:22-25`). During map generation, always pass
   `false` for `bRecalculate` and call `Map.RecalculateAreas()` once at the end. With `true`, each
   call can trigger a full area recalculation (`CvPlot.cpp:7330-7425`).

**Side effects of `SetPlotType`** (`CvPlot.cpp:7246-7262`, verified):
- If the current terrain is `NO_TERRAIN`, or its water-ness disagrees with the new plot type, the
  terrain is reset. Water becomes COAST if adjacent to land, else OCEAN. Land becomes
  `LAND_TERRAIN` (= 0, grassland). Land-to-land changes (flat, hills, mountain) keep the terrain.
- Changing to or from `PLOT_OCEAN` calls `erase()` on the plot (`:7233-7236`), which removes
  units and improvements.

### 4.2 `FractalWorld` (`BASE\FractalWorld.lua`)

This is the workhorse of Fractal, Continents, Pangaea, Archipelago, SmallContinents and most VPMS
scripts.

```lua
local fw = FractalWorld.Create(fracXExp, fracYExp);        -- exps optional (-1 => 7/6)
fw:InitFractal{continent_grain = 2, rift_grain = -1};      -- builds self.continentsFrac
local plotTypes = fw:GeneratePlotTypes{ sea_level = 2, world_age = 2,
   sea_level_low = 65, sea_level_normal = 72, sea_level_high = 78,  -- % of map that is WATER
   extra_mountains = 0, adjust_plates = 1.0, tectonic_islands = false,
   has_center_rift = false };
SetPlotTypes(plotTypes);
```

How it works (`:575-761`). Three fractals: `continentsFrac` (land/water), `hillsFrac`, and
`mountainsFrac`. The last two are seeded with `BuildRidges` Voronoi ridgelines. Land is
`height > continentsFrac:GetHeight(water_percent)`. Mountains are `mountainVal >=
mountainsFrac:GetHeight(97 - adj)`, unless `hillVal >= pass threshold`, which makes a "mountain
pass" of hills. Hills come from two bands of `hillsFrac` (28±adj and 72±adj percentiles) plus
foothills next to ridges. It then shifts plot types so the emptiest column or row lands on the map
edge (`ShiftPlotTypes`, `:94-226`). If `has_center_rift` is set, it also carves an Atlantic-style
rift (`GenerateCenterRift`, `:228-573`).

Two **arg defaults that cannot be turned off**, because of the `x or true` idiom:
- `InitFractal`: `local polar = args.polar or true` (`:46`). `FRAC_POLAR` is always on.
- `GeneratePlotTypes`: `local shift_plot_types = args.shift_plot_types or true` (`:599`). Shifting
  always happens. To avoid shifting, override `FractalWorld:ShiftPlotTypes` (Tectonic does this to
  shift on X only: `MYMAPS\Tectonic v6 - VI.lua:284-292`) or write your own main loop.

Scripts subclass by building their own `data` table that reuses `FractalWorld.*` functions and
replaces `GeneratePlotTypes` (`Continents.lua:33-58`, `Pangaea.lua`). A common addition is a
**reject-and-retry loop** around `InitFractal`. Continents rerolls until the biggest landmass is at
most 58% of land (`Continents.lua:147-206`), and Pangaea until it is at least 84%
(`Pangaea.lua:148-184`). Vanilla measures with `Map.FindBiggestArea`. In VP, measure **landmass**,
not area (§10.2). VP's own scripts made that fix (`VPMS\Arborea.lua:194-201`):

```lua
SetPlotTypes(self.plotTypes);
Map.RecalculateAreas();
local iBiggestID = Map.FindBiggestLandmassID(false);
if Map.GetNumTilesOfLandmass(iBiggestID) >= iNumTotalLandTiles * 0.84 then done = true; end
```

### 4.3 The `Fractal` C++ object (`DLL\Lua\CvLuaFractal.cpp`, `DLL\CvFractal.cpp`)

| Call | Meaning |
|---|---|
| `Fractal.Create(w, h, grain, flags, fracXExp, fracYExp)` | Diamond-square fractal on a 2^xExp × 2^yExp grid (default 7×6 = 128×64), sampled bilinearly onto w×h. Uses the **map RNG**. |
| `Fractal.CreateRifts(w, h, grain, flags, riftsFrac, xExp, yExp)` | As above, then carves rifts from another fractal (assumes wrap X). |
| `frac:GetHeight(x, y)` | Height 0..255 (0..99 with `FRAC_PERCENT`). Out-of-range coordinates return 0. |
| `frac:GetHeight(pct)` | **One-argument form**: the height value at percentile `pct` (0..100), via binary search over the fractal grid (`getHeightFromPercent`). Use it to turn "72% water" into a threshold. |
| `frac:BuildRidges(numSeeds, flags, blendRidge, blendFract)` | Voronoi "tectonic" ridges blended in. At least 3 seeds, kept at least 7 hexes apart. |

- **Flags are a table of booleans**, not bits: `{FRAC_WRAP_X = true, FRAC_POLAR = true}`.
  Recognised keys: `FRAC_WRAP_X`, `FRAC_WRAP_Y`, `FRAC_PERCENT`, `FRAC_POLAR`, `FRAC_CENTER_RIFT`,
  `FRAC_INVERT_HEIGHTS` (`CvLuaFractal.cpp:45-61`, `CvFractal.h:25-30`).
- `Map.GetFractalFlags()` returns `{FRAC_WRAP_X = true}` on a wrap-X map, and `FRAC_WRAP_Y` on a
  wrap-Y map, nothing else (`CvLuaMap.cpp:161-178`). **Passing `{}` on a wrapping map gives a
  fractal that does not tile across the seam**, which shows up as a visible straight cut at x=0.
- `FRAC_POLAR` zeroes the fractal's **non-wrapping** edges (the "else if FRAC_POLAR" branches in
  `fracInitInternal`). On a wrap-X map that means the top and bottom rows: water at the poles. On a
  non-wrapping map, the east and west edges also become water.
- **Grain**: `iSmooth = clamp(min(xExp, yExp) - grain, 0, ...)`. Higher grain means more, smaller
  features. Grain 1-2 gives continents, 3-4 islands and hill clumps, 5-6 feature speckle.
- Fractal dimensions are capped at 255 (`FRACTAL_MAX_DIMS`, `CvFractal.h:15`).

### 4.4 `MultilayeredFractal` (`BASE\MultilayeredFractal.lua`)

Use this for compositions of rectangular regions (Terra, Lakes, InlandSea, Oval, Ring, Europe,
North_vs_South, Hemispheres). The usage contract is in the file header (`:12-23`):

```lua
function MultilayeredFractal:GeneratePlotsByRegion()
  local iW, iH = Map.GetGridSize();
  self.wholeworldPlotTypes = table.fill(PlotTypes.PLOT_OCEAN, iW * iH);   -- 1-based
  self:GenerateFractalLayer{ iRegionWidth = 30, iRegionHeight = 20, iRegionWestX = 5,
    iRegionSouthY = 8, iRegionGrain = 1, iWaterPercent = 55, iRegionPlotFlags = self.iRoundFlags,
    iRegionFracXExp = 6, iRegionFracYExp = 5 };
  -- or GenerateFractalLayerWithoutHills{...} repeatedly, then:
  self:ApplyTectonics{ world_age = 2 };   -- whole-world ridge pass (:608)
  return self.wholeworldPlotTypes;
end
function GeneratePlotTypes()
  SetPlotTypes(MultilayeredFractal.Create():GeneratePlotsByRegion());
  GenerateCoasts();
end
```

Layers overwrite with land only, and water is ignored (`:410-428`). Region coordinates are **not
wrapped**: `wholeworldX = x + iRegionWestX`, so keep regions inside the map. Flag presets from
`Create()` (`:127-172`): `iNoFlags`, `iTerrainFlags` (map wrap, polar off), `iRoundFlags` (`{}`),
`iHorzFlags`, `iVertFlags`, `iXYFlags`. Oval shows the purely analytic variant: an ellipse test
fills `wholeworldPlotTypes`, then a bays fractal erodes it (`Oval.lua:55-124`).

Hidden bug: `GenerateFractalLayer` assigns `PlotTypes.PLOT_PEAK` (around `:391`), which **does not
exist**. The value is `nil`. It works by accident. The nil entry passes the `~= PLOT_OCEAN` test
when layering, and `SetPlotType(nil)` reads `lua_tointeger(nil) = 0`, which is `PLOT_MOUNTAIN`
(§10.6). Don't copy this.

`bShift = args.bShift or true` (`:323`) has the same always-true problem as FractalWorld.

### 4.5 `IslandMaker` (`BASE\IslandMaker.lua`)

`CreateSingleAxisIslandChain(w, h, tiltDegrees)` and its `...WithDots`, `...WithShiftedDots`,
`...WithDoubleDots` variants return a **local 1-based boolean table** (`true` = land) for a w×h
cell, or `nil` if the cell is smaller than 4×4 or 24 plots (`:20-30`). You stamp it into your plot
array yourself (`VPMS\Large_Islands.lua:556-640`, Communitu `GenerateIslands`).

### 4.6 Hinted fractals and `HintedWorld`

The C++ class has `fracInitHinted` (`CvFractal.h:43`), but **no Lua binding exists**. `CvLuaFractal`
registers only `Create` and `CreateRifts` (`CvLuaFractal.cpp:85-89`). `BASE\HintedWorld.lua` is
0 bytes in this install. Write your own noise for hinted or template-driven generation (Communitu's
Perlin `FloatMap` is the reference, §9.1).

### 4.7 Voronoi and tectonic approaches

- **Tectonic v6 / Continental Drift** (`MYMAPS\Tectonic v6 - VI.lua`,
  `VPMS\Continental_Drift.lua`). Random plates (`x`, `y`, `mass`, `velocity`). Each plot is
  assigned to the nearest plate (`PartOfPlate`, `Tectonic:1072-1110`), with sinusoidal
  "skew/fuddle" coordinate warping so boundaries aren't straight. Plate pairs are classified by
  relative velocity: Collision (dot < -0.5) gives mountains, Rift (> 0.5) gives sea, otherwise
  Transform (`:589-628`). Base elevation is a hand-rolled multi-octave value noise driven by
  `Map.Rand` (`InitHeightmaps` / `GetHeight`, `:388-451`).
- Continental Drift improves on this. It **caches the plate map** (`CachePartOfPlate`,
  `:1754-1784`) instead of recomputing Voronoi distances per query. It uses **great-circle
  distance**, with longitude taken from x, so plates wrap correctly across the seam (`:1764-1772`).
- Both keep most of their state in **undeclared globals** (`ft`, `f`, `q`, `xAdj`, ...). This works
  but is slow and fragile (§10.9).

### 4.8 Hand-rolled heightmaps (Communitu)

Communitu builds a float elevation map from twisted Perlin noise plus a separate mountain map. It
carves oceans and rifts into the elevation data, then thresholds:

```lua
-- VPMS\Communitu_79a.lua:1777-1800
local hillsThreshold = DiffMap:FindThresholdFromPercent(MG.flatPercent, false, true);
local mountainsThreshold = DiffMap:FindThresholdFromPercent(MG.belowMountainPercent, false, true);
...
if elevationMap:IsBelowSeaLevel(x, y) then plot:SetPlotType(PlotTypes.PLOT_OCEAN, false, true);
elseif DiffMap.data[i] < hillsThreshold then plot:SetPlotType(PlotTypes.PLOT_LAND, false, true);
elseif x == 0 or x == 1 or x == mapW - 1 or x == mapW - 2 then   -- keep the seam flat
  plot:SetPlotType(PlotTypes.PLOT_LAND, false, true);
elseif DiffMap.data[i] < mountainsThreshold then plot:SetPlotType(PlotTypes.PLOT_HILLS, false, true);
else plot:SetPlotType(PlotTypes.PLOT_MOUNTAIN, false, true); end
```

`FindThresholdFromPercent` (`:5632`) is the float-map equivalent of `Fractal:GetHeight(pct)`.
**Percentile thresholds are how good scripts control proportions** (sea level, hills %, mountain %)
independently of noise amplitude.

### 4.9 Sea level and polar water

Sea level is just the water percentile you threshold at. FractalWorld's defaults are 65/72/78 %
water for low/medium/high (`FractalWorld.lua:589-591`). Continents uses 67/72/76. Communitu uses
`landPercent` (0.40 base, ×1.25 or ÷1.25). Polar water comes from `FRAC_POLAR` (§4.3), from explicit
row clearing (Communitu `CreateArcticOceans`), or from feature ice placed later (§7).

---

## 5. Terrain generation

### 5.1 Writing terrain

`plot:SetTerrainType(id, bRecalculate, bRebuildGraphics)` (`CvLuaPlot.cpp:475-486`,
`CvPlot.cpp:7446`). Side effect (verified, `CvPlot.cpp:7509-7513`): **if the new terrain's `Water`
flag differs from the plot's water-ness, the plot type flips** to `PLOT_OCEAN` or `PLOT_LAND`.
Setting COAST on a land plot makes it water, and setting GRASS on an ocean plot makes it flat land.

Never assign `TERRAIN_HILL` (8) or `TERRAIN_MOUNTAIN` (7). They are `GraphicalOnly`, and in the
current DB **`TERRAIN_HILL` has `Water = 1`**, so assigning it turns the plot into ocean.

`SetTerrainTypes(t)` (`CP\MapGenerator.lua:182-189`) expects a **0-based** table (`t[y*W + x]`),
and it skips water plots. This is the opposite convention from `SetPlotTypes`.

### 5.2 `TerrainGenerator` (`BASE\TerrainGenerator.lua`)

```lua
local tg = TerrainGenerator.Create{ temperature = 2,   -- 1 cool, 2 temperate, 3 hot
  iDesertPercent = 32, iPlainsPercent = 50, fSnowLatitude = 0.75, fTundraLatitude = 0.6,
  fGrassLatitude = 0.1, fDesertBottomLatitude = 0.2, fDesertTopLatitude = 0.5,
  temperature_shift = 0.1, desert_shift = 16, grain_amount = 3 };
SetTerrainTypes(tg:GenerateTerrain());
```

- Latitude is `|H/2 - y| / (H/2)`, roughened by a variation fractal (±0.1), and clamped to [0,1]
  with the Firaxis extension `math.clamp` (`:134-145`). 0 is the equator and 1 the poles.
  **`TopLatitude` and `BottomLatitude` are ignored.** To bend climate (a tilted axis, or Highlands'
  cold-north/cold-south), override `TerrainGenerator:GetLatitudeAtPlot` (`VPMS\Highlands.lua`,
  `Four_Corners.lua`, `Tilted_Axis.lua`).
- Bands: snow if `lat ≥ fSnowLatitude`, tundra if `≥ fTundraLatitude`, all grass if
  `< fGrassLatitude`. In between, desert where the desert fractal is in its top `iDesertPercent`
  and lat is within [desertBottom, desertTop). Otherwise plains where the plains fractal is in its
  top `iPlainsPercent`. Otherwise grass (`:161-198`).
- Water plots keep their terrain, so coasts must already be set. Hills and mountains get a normal
  base terrain.
- For a different climate model, replace `GenerateTerrainAtPlot` (North_vs_South, Ring, Skirmish)
  or skip TerrainGenerator entirely (Communitu: temperature + rainfall maps, §9.1).

### 5.3 Coast vs ocean (`GenerateCoasts`, `CP\MapGenerator.lua:141-180`)

```lua
GenerateCoasts{ bExpandCoasts = true, expansion_diceroll_table = {4, 4} };
```

1. Every water plot becomes COAST if `IsAdjacentToLand()`, else OCEAN.
2. For each entry `n` in `expansion_diceroll_table`: each OCEAN plot adjacent to COAST becomes
   COAST with probability 1/n. Candidates are collected first and applied afterwards, so each pass
   grows at most one ring.

Bug: `local bExpandCoasts = args.bExpandCoasts or true` (`:144`) is **always true**. Oval passes
`{bExpandCoasts = false}` (`Oval.lua:145`) and still gets expansion. To disable it, pass
`expansion_diceroll_table = {}`.

After generation the engine's `ValidateCoast` forces any non-COAST water next to land to COAST
(§1.2). Other water terrain next to land cannot survive.

### 5.4 Lakes and lake terrain

- **What makes a lake:** `CvLandmass::isLake()` is water landmass size `< MIN_WATER_SIZE_FOR_OCEAN`
  (= **10** in the current DB) (`DLL\CvMap.cpp:122-125`). `plot:IsLake()` reads the plot's landmass
  flag, and landmasses only update on `Map.RecalculateAreas()` (§10.2). Lakes use ordinary COAST
  terrain (or OCEAN in the middle of a large lake that does not touch land). There is no lake
  terrain.
- `LAKE_MAX_AREA_SIZE` is a Civ 4 concept. In Civ 5/VP the only size knob is
  `MIN_WATER_SIZE_FOR_OCEAN`, and a script cannot change it. Communitu notes
  `mglobal.lakeSize = GameDefines.MIN_WATER_SIZE_FOR_OCEAN -- read-only`
  (`VPMS\Communitu_79a.lua:162`).
- Default `AddLakes` (`CP\MapGenerator.lua:518-544`): each inland, non-river land plot has a
  1/`LAKE_PLOT_RAND` (1/160) chance to become a 1-plot lake (`SetArea(-1)` then
  `SetPlotType(PLOT_OCEAN)`). It then calls `Map.CalculateAreas()`, which recomputes **areas only,
  not landmasses**. The new lakes report `IsLake() == false` until the next `RecalculateAreas`
  (§10.2).
- Custom lakes: pick candidates (not coastal, not river, not mountain), grow blobs of 1-5 plots
  using row-parity neighbour offsets, set `PLOT_OCEAN`, and recalculate at the end
  (`VPMS\Continental_Drift.lua:1352-1530`, based on Random Scandinavia). Communitu's approach: fill
  sub-10-plot seas in the elevation map (`FillInLakes`, `:2094`), then restore them as COAST after
  rivers (`RestoreLakes`, `:2117`), and disable `AddLakes` (`:2177-2179`).

### 5.5 Hills and mountain adjustments after terrain

- VP's FeatureGenerator turns **coastal mountains into hills** by default (§7.1).
- River between two mountains: Communitu demotes the plot to hills (`AddRivers`, `:4176-4178`).
- Start normalisation may add hills, forest, grass conversion or bonus resources near starts
  (`VPO\AssignStartingPlots.lua:3396-3610`).

---

## 6. Rivers and lakes

### 6.1 Edge ownership: the three river flags

Each plot owns three of its six edges. The flag names describe where the plot lies relative to the
river (`CvPlot.cpp:6290-6420`, `CvPlot.cpp:11845-11900`):

| Setter | River runs along this plot's... | Shared with | Valid flow directions |
|---|---|---|---|
| `SetWOfRiver(b, flow)` | **East** edge | E neighbour | `FLOWDIRECTION_NORTH` / `_SOUTH` |
| `SetNWOfRiver(b, flow)` | **South-east** edge | SE neighbour | `_NORTHEAST` / `_SOUTHWEST` |
| `SetNEOfRiver(b, flow)` | **South-west** edge | SW neighbour | `_SOUTHEAST` / `_NORTHWEST` |

The readers are `IsWOfRiver()` / `GetRiverEFlowDirection()`, `IsNWOfRiver()` /
`GetRiverSEFlowDirection()`, and `IsNEOfRiver()` / `GetRiverSWFlowDirection()`. To set the W, NW
or NE edge of plot P, set the corresponding flag on the neighbour in that direction. Communitu's
`Plot_SetRiver(plot, edgeDirection, flowDirection)` (`VPMS\Communitu_79a.lua:5106-5128`) wraps this
(§9.4).

Enums (`REPO\LuaCATS\enum\FlowDirectionTypes.d.lua`, `DirectionTypes.d.lua`): flow NORTH 0,
NORTHEAST 1, SOUTHEAST 2, SOUTH 3, SOUTHWEST 4, NORTHWEST 5, NO_FLOWDIRECTION 7. Directions NE 0,
E 1, SE 2, SW 3, W 4, NW 5, NO_DIRECTION 7.

### 6.2 What makes `plot:IsRiver()` true

`isRiver()` is `m_iRiverCrossingCount > 0` (`CvPlot.h:452-455`). The crossing bit for an edge is
recomputed **only inside the `Set*OfRiver` call that changes that edge**, for the plot and the plot
across the edge, and **only counts if both plots are land** (`CvPlot.cpp:11853`). In the DLL, the
all-edges `updateRiverCrossing()` has no callers. Consequences:

- **Set rivers after plot types are final.** If you later turn a riverside plot into water, or the
  reverse, the cached crossing flags go stale.
- A river flag on an edge facing water is stored, but it is not a river for gameplay: no
  fresh-water bonus from it, and no flood plains.
- `Set*OfRiver` returns early if both the boolean and the flow are unchanged (`:6293`). If only the
  flow changes, the crossing is not recomputed. To force a refresh, set `false` and then `true`.
- Fresh water (`isFreshWater`) = river, lake or oasis nearby. It is computed in `updateWaterFlags`
  (`CvPlot.cpp:1231-1300`).

### 6.3 The default river generator (`CP\MapGenerator.lua:227-516`)

- `AddRivers()` makes 4 passes over land plots. The pass conditions (`:466-486`) are: hills or
  mountains; non-coastal with a 1/8 chance; hills or mountains in areas with few river edges; then
  any plot in areas with few river edges (`area:GetNumRiverEdges() < tiles/PLOTS_PER_RIVER_EDGE + 1`,
  where `PLOTS_PER_RIVER_EDGE` = 12).
- A source is skipped if fresh water lies within `RIVER_SOURCE_MIN_RIVER_RANGE` (4), or sea water
  within `RIVER_SOURCE_MIN_SEAWATER_RANGE` (2). Passes 3-4 halve those ranges (`:493-499`).
- `plot:GetInlandCorner()` (C++, `CvPlot.cpp:6450-6485`) picks, from {self, NE, NW, W} in random
  order, a plot whose SE corner does not touch water. **It consumes map RNG.**
- `DoRiver(startPlot, thisFlow, originalFlow, riverID)` (`:252-460`) walks corner to corner. At
  each step it may only turn left or right (`TurnRightFlowDirections` /
  `TurnLeftFlowDirections`). It picks the lowest `GetRiverValueAtPlot(adjacent)`, dampens the
  original direction by ×3/4, and stops at water, at the map edge, or on hitting an existing river.
  `GetRiverValueAtPlot` (`:227-248`) is `(4 - plotType) * 20` plus neighbour terms plus
  `Map.Rand(10)`, so rivers seek **lower** plot types (ocean 3 beats land 2 beats hills 1 beats
  mountain 0, and lower values win). Override the global `GetRiverValueAtPlot` to steer rivers
  (Great Plains' Mississippi, Amazon). It is looked up at call time.
- `_rivers` is keyed by **plot objects**. That works because the DLL caches one Lua table per plot
  pointer (`DLL\Lua\CvLuaScopedInstance.h:125-170`), so `plotA == plotB` and table-key lookups by
  plot are stable within one generation.

### 6.4 Common river mistakes

- Setting a river flag where either side is water. It is silently not a river (§6.2).
- Inconsistent flows along a path, where consecutive edges disagree in direction. The `DoRiver`
  turn tables guarantee consistency, and hand-rolled code must too. **(Exactly how the renderer
  handles inconsistent flows is unverified.)** Communitu's `RiverMap` models junctions (hex corners)
  and derives the three flags per plot with `RiverMap:GetFlowDirections(x, y)` (`:7236`). Its
  `AddRivers` (`:4162-4205`) just copies them in.
- Adding lakes after rivers without re-validating. `AddLakes` skips `IsRiver()` plots, but custom
  code may not. Communitu strips every river edge that borders water after lakes are restored
  (`:2134-2141`, `:3798-3805`).
- Forgetting that `FeatureGenerator` places flood plains from `IsRiver()`, so features must run
  **after** rivers. Communitu re-adds flood plains after it finalises rivers (`:3807-3812`).

---

## 7. Features

### 7.1 VP `FeatureGenerator` (`VPO\FeatureGenerator.lua`)

```lua
local fg = FeatureGenerator.Create{ rainfall = 2,       -- 1 arid, 2 normal, 3 wet
  iJunglePercent = 65, iForestPercent = 31, iClumpHeight = 90, fMarshPercent = 8,
  iOasisPercent = 6, jungle_grain = 5, forest_grain = 6, clump_grain = 3 };
fg:AddFeatures(allow_mountains_on_coast);   -- optional bool, see below
```

Per-plot order in `AddFeaturesAtPlot` (`:201-230`): flood plains (any plot that
`CanHaveFeature(FLOOD_PLAINS)`, meaning flat river desert), then oasis, ice, marsh, jungle, and
forest. Each step runs only if the plot is still featureless. Jungle and forest grains get
`Worlds.FeatureGrainChange` added (`:76-78`).

- **Ice** (`:242-255`): on wrap-X maps, every eligible water plot in rows 0 and H-1 gets ice.
  Elsewhere it is random, ramping in from latitude 0.75 (FeatureGenerator latitude is
  `|H/2 - y| / (H/2)`, with no fractal roughening, `:193-198`). Ice is only allowed on COAST and
  OCEAN.
- **Allowed terrains** (current DB, `Feature_TerrainBooleans` and `Features`): jungle on grass and
  plains; forest on grass, plains and tundra; marsh on grass, flat only (`RequiresFlatlands`);
  oasis on desert (`NoCoast`, `NoRiver`, flat); flood plains on desert (`RequiresRiver`, flat);
  atoll on coast and ocean. Natural wonders have `NaturalWonder = 1`, and many are `Impassable`.
- **VP changes vs BNW** (diff of `BNW\FeatureGenerator.lua` and `VPO\FeatureGenerator.lua`):
  - `AddFeatures(allow_mountains_on_coast)`: vanilla removed coastal mountains only when the
    argument was explicitly `false`. VP removes them when it is **falsy**, so **calling
    `AddFeatures()` with no argument converts every coastal mountain into hills** (`:165-178`).
    Pass `true` to keep them.
  - `AdjustTerrainTypes` (`:287-308`): vanilla turned the terrain under **every** jungle into
    plains. VP does it for only **half** (`Map.Rand(2) == 1`). It still softens river tundra to
    plains and river snow to tundra.
  - `AddAtolls` now measures the biggest ocean as a **landmass** (`FindBiggestLandmassID(true)`)
    instead of an area.
  - Some methods dropped unused parameters: `AddOasisAtPlot(plot)`, `AddMarshAtPlot(plot, x, y)`,
    `AddForestsAtPlot(plot, x, y)`. Old overrides with the longer signatures still work, because
    Lua ignores extra arguments.

Customise by overriding methods on the class at file top level, for example
`function FeatureGenerator:AddIceAtPlot(plot, iX, iY, lat) ... end` (many VPMS scripts). Or build a
derived instance with replaced members (`Ice_Age.lua`'s `Ice_AgeFeatureGenerator.Create`).

### 7.2 Rules enforced by `plot:CanHaveFeature(f)` (`CvPlot.cpp:5506-5600`)

It returns false if the plot **already has any feature**, is a mountain or a city, if the feature
does not list the plot's terrain, for `NoCoast` on coastal land, `NoRiver` on a river,
`RequiresFlatlands` on hills, for `NoAdjacent` violations, and more. To replace a feature, first
call `SetFeatureType(FeatureTypes.NO_FEATURE)` (-1).

`plot:SetFeatureType(f)` does **no validity check**: anything goes, which is how natural wonders
are placed. One VP twist (`CvPlot.cpp:7551-7556`): clearing the feature on a **river desert** plot
silently puts `FEATURE_FLOOD_PLAINS` back.

### 7.3 Atolls

`AddAtolls` runs only if the biggest water landmass is more than 1/4 of the map. Candidates are COAST
next to **exactly one** land plot, not next to ice, tundra or snow, and not lakes. They are bucketed
by the adjacent landmass size (1-2, 3-7, 8-16, 17-40, 41-75; 76+ is discarded) and drawn with
weighted dice. The target is a per-size number plus a random addition (2 for Duel up to 12 for Huge)
(`VPO\FeatureGenerator.lua:311-543`). Communitu uses its own latitude-limited `PlacePossibleAtoll`
(`:4126`).

### 7.4 Feature-related area recalculation

Ice and impassable natural wonders were meant to change **areas** in VP (§10.2.1: in practice areas ignore passability, but landmasses, lakes and coastal flags still refresh). This is why `GenerateMap` calls
`Map.RecalculateAreas()` after `AddFeatures` (`CP\MapGenerator.lua:779-780`), and why ASP must not
trigger a recalculation mid-run (§8.8).

---

## 8. Start plots and resources under VP

Everything here is `VPO\AssignStartingPlots.lua` (abbreviated **ASP**) unless noted.

### 8.1 The pipeline

`StartPlotSystem()` must call these in order (`CP\MapGenerator.lua:709-740`):

| Step | What it does | Key outputs on `self` |
|---|---|---|
| `AssignStartingPlots.Create()` (:240) | `__Init` (:257), `__InitLuxuryWeights` (:482), `__CustomInit` (:805) | resource IDs (`self.iron_ID` ...), `impactData[layer]`, `landmass_areas`, config constants |
| `:GenerateRegions(args)` (:1439) | Counts civs and CS (`GetPlayerAndTeamInfo`), measures fertility, divides land into one region per civ, then calls `CustomOverride()` (:1847) | `regionData[i] = {westX, southY, width, height, areaOrLandmassID, fertility, plotCount, avgFert}`, `method`, `bArea`, `iNumCivs`, `iNumCityStates`, `player_ID_list`, resource settings |
| `:ChooseLocations(args)` (:2837) | Measures terrain per region, classifies region types, finds a start per region (lowest-fertility regions first) | `regionTypes[i]`, `startingPlots[i] = {x, y, score}`, impact layers |
| `:BalanceAndAssign()` (:3654) | `NormalizeStartLocation` per region, then assigns players to regions by **start bias**, solved as an optimal assignment (Kuhn-Munkres `GetMinMatching`, `CP\MapmakerUtilities.lua:924`), or randomly if `GAMEOPTION_DISABLE_START_BIAS` | `Players[p]:SetStartingPlot(plot)` |
| `:PlaceNaturalWonders()` (:4524) | Picks NWs from `Natural_Wonder_Placement`, eligibility per plot, places them | NW features, NW impact layer |
| `:PlaceResourcesAndCityStates()` (:8621) | `AssignLuxuryRoles`, `PlaceCityStates`, `GenerateGlobalResourcePlotLists`, `PlaceLuxuries`, `PlaceStrategicAndBonusResources`, `NormalizeCityStateLocations`, `AdjustTiles`, then **`Map.RecalculateAreas()`**, then `PrintFinalResourceTotalsToLog` | resources, CS start plots |

### 8.2 `GenerateRegions(args)`: methods and args

`RegionDivision` is a global enum (:112-117). Plain numbers also work, and stock scripts pass
`method = 1/2/3/4`:

| Value | Name | Behaviour in VP |
|---|---|---|
| 1 | `BIGGEST_LANDMASS` | All civs on `Map.FindBiggestLandmassID(false)`. In VP this is the **landmass**, so it spans mountain ranges and isthmuses (header note :58-71). `bArea = false`. |
| 2 | `CONTINENTAL` (default) | Landmasses with at least `0.25 × fertility(biggest)` are candidates. Their **areas** are ranked by fertility and civs are assigned greedily. Each area is divided separately. `bArea = true`. **Automatic fallbacks**: if at most one landmass qualifies, it retries with lower thresholds (up to 5 times), then falls back to method 1. If total fertility is too low, it retries (up to 4 times), then falls back to method 3 (:1614-1624, :1722-1732). |
| 3 | `RECTANGULAR` | One rectangle (whole map by default) divided by fertility, ignoring landmass. Use for archipelagos (`Archipelago.lua`: `method = 3` and `mustBeCoast = true`). |
| 4 | `RECTANGULAR_SELF_DEFINED` | As 3, with `args.iWestX, iSouthY, iWidth, iHeight`. City states may then use land outside the rectangle. |

Other args (:1444-1489):
- `resources`: 1-3 = sparse/standard/abundant density for all categories; 4 = Legendary Start;
  5 = Strategic Balance; 6 = random 1-3.
- `comm = true` with `resources` (strategic density), `size`, `bonus`, `lux`, `legend`, `balance`:
  the Communitu-style split settings.
- `addEmptyRegions = true`: Frontier's "empty regions" (extra unpopulated regions, up to 22 civs).
- `retryCount1`, `retryCount2`: internal recursion counters.

Region division algorithm (`DivideIntoRegions`, :1144-1190): recursive chopping into 3 or 2
fertility-balanced slices (prime counts get an uneven chop), along the longer axis of the bounding
rectangle. `bArea` decides whether membership tests in later steps compare `plot:GetArea()` or
`plot:GetLandmass()` with `regionData[i][5]` (for example :1927, :2560, :4847-4851). **If you
replace `GenerateRegions`, you must set `self.method`, `self.bArea`, `self.iNumCivs`,
`self.iNumCityStates`, `self.iNumCityStatesUnassigned`, `self.player_ID_list` and the resource
settings, and fill `self.regionData` consistently with `bArea`.** (VP's `North_vs_South.lua`,
`West_vs_East.lua`, `Ring.lua` and `Europe.lua` do this. Copy from them, not from vanilla.)

### 8.3 `ChooseLocations(args)` and start evaluation

- Args: `mustBeCoast` (force salt-water coastal starts where the region has at least 3 coastal
  candidates, :2494); `centerBias` (34) and `middleBias` (67), the % of the region radius searched
  first and second; and the `minFood/minProd/minGood` thresholds for the inner, middle and outer
  zones (defaults at :398-408).
- The CENTER BIAS method: candidate plots in the region centre are evaluated first
  (`EvaluateCandidatePlot`, :2368, using `WEIGHTED_FOOD_SCORE`, `WEIGHTED_PROD_SCORE`,
  `GOOD_TILE_MULTIPLIER`, `JUNK_TILE_MULTIPLIER`, :447-463), and collisions are avoided via
  `playerCollisionData` and impact layers. `FindStartWithoutRegardToAreaID` is used for methods 3
  and 4.
- Region types (`DetermineRegionTypes`, :2068) are `GameInfoTypes.REGION_*` from the DB `Regions`
  table: UNDEFINED 0, TUNDRA 1, JUNGLE 2, FOREST 3, DESERT 4, HILLS 5, PLAINS 6, GRASS 7,
  HYBRID 8, MOUNTAIN 9, SNOW 10. Thresholds are in `self.REGION_TYPE_MIN_REQ` (:466-474).

### 8.4 Start bias (`BalanceAndAssign`)

Biases come from DB tables, queried by `CP\MapmakerUtilities.lua:414-533`:
`Civilization_Start_Along_Ocean`, `Civilization_Start_Along_River`,
`Civilization_Start_Prefer_Mountain`, `Civilization_Start_Prefer_Snow`,
`Civilization_Start_Place_First_Along_Ocean`, `Civilization_Start_Region_Priority`, and
`Civilization_Start_Region_Avoid`. VP builds a cost matrix (0 = perfect match, 1 = no match;
priority coast, snow and mountain biases are absolute at -99; coastal misses get +0.5) and solves
the assignment optimally (:3686 onwards). The disable-bias game option is read with
`Game.GetCustomOption("GAMEOPTION_DISABLE_START_BIAS") == 1` (:3664).

Your map influences bias satisfaction only through geography. Make sure there are enough coastal,
river, mountain-adjacent and snow-adjacent candidate starts if you expect such civs.
`ChooseLocations` counts mountain and snow bias civs up front (:2856-2867).

### 8.5 Natural wonders

- How many: `ASP:GetNumNaturalWondersToPlace(iWorldSize)` returns 2/3/4/5/6/7 for Duel to Huge
  (:4512-4522). Override it to change the count (Communitu: `(size + 1) * 2`, ×1.25 for Terra-style).
- Which: rows of the DB table **`Natural_Wonder_Placement`** (17 rows; its columns include
  `OccurrenceFrequency`, `RequireBiggestLandmass`, `AvoidBiggestLandmass`, `RequireFreshWater`,
  `LandBased`, `CoreTileCanBe*`, `AdjacentTilesRequire*` / `Avoid*`, `TileChangesMethodNumber`,
  `ChangeCoreTileTo*`, `SetAdjacentTilesToShallowWater`). This replaces vanilla's hard-coded
  `CanBeGeyser`, `CanBeFuji`, and so on. Vanilla scripts that override those methods
  (`Great_Plains.lua`, `Terra.lua`) are **silently ignored** under VP.
- Eligibility (`ExaminePlotForNaturalWondersEligibility`, :3819-3847): not inside the NW impact
  layer (which is set around civ starts), at least one flat land plot within 3, and
  `Plot_GetFertilityInRange(plot, 3)` of 28 or more (20-27 only qualifies as a fallback). Then
  `CanBeThisNaturalWonderType` (:3859): **all 6 neighbours must exist**, so no NWs on the edge rows
  of the map or on the east/west edge of non-wrapping maps. Custom checks come from
  `NWCustomEligibility(x, y, methodNumber)` in `VPO\NaturalWondersCustomMethods.lua`.
- Biggest-landmass rules apply only when `self.bWorldHasOceans` (:4321-4330).

### 8.6 City states

- `AssignCityStatesToRegionsOrToUninhabited` (:4639) splits CS between civ regions
  (`GetNumCityStatesPerRegion`, :4587, ratio-based) and uninhabited landmasses
  (`GetNumCityStatesInUninhabitedRegion`, :4608). Override both freely (VP `Terra.lua:544-558`,
  Communitu `:560-565`).
- `CanPlaceCityStateAt(x, y, area_ID, force_it, ignore_collisions)` (:4844) compares area or
  landmass depending on `bArea` (:4847-4851). Several vanilla scripts override it (Lakes,
  InlandSea, Four_Corners, Highlands). The VPMS versions are the reference.

### 8.7 Resources

- **Settings on `self`**: `resDensity`, `resSize`, `bonusDensity`, `luxuryDensity` (1-3), plus
  `legStart` and `resBalance` (:343-348, set in `GenerateRegions`).
- **Impact layers** (`ImpactLayers`, :121-137): `self.impactData[ImpactLayers.LAYER_LUXURY]`, and
  so on. Each is a 1-based table over plots (`index = y*W + x + 1`). Vanilla and CP-only used named
  tables (`self.luxuryData`, `self.strategicData`, `self.bonusData`, `self.fishData`, ...;
  `CP\AssignStartingPlots.lua:249-261`). **Code written against those names breaks under VP.**
- **Plot lists**: `self.global_resource_plot_lists[PlotListTypes.X]` (:141-214), built by
  `GenerateGlobalResourcePlotLists` (:5556) from every plot without a start, CS, NW or existing
  resource. Entries are **1-based plot indices**. Vanilla had `self.coast_list`, `self.grass_flat_no_feature`,
  and so on (`BNW\AssignStartingPlots.lua:7306`).
- **Placement primitives**:
  - `ProcessResourceList(frequency, impactLayer, plotList, {{resID, amount, weightPct, minRadius, maxRadius}, ...})`
    (:5702): roughly one resource per `frequency` plots of the list.
  - `PlaceSpecificNumberOfResources(resID, quantity, amount, ratio, impactLayer, minRadius, maxRadius, plotList)`
    (:5791): exactly N, used for luxuries.
  - Bookkeeping: `self.amounts_of_resources_placed[resID + 1]`. Note the **+1**.
- **Luxuries**: `__InitLuxuryWeights` fills `self.luxury_region_weights[regionType] = {{resID, weight}, ...}`,
  plus `self.luxury_fallback_weights` and `self.luxury_city_state_weights` (:482-801). `AssignLuxuryRoles` (:6064) gives each
  region a luxury (at most `MAX_REGIONS_PER_LUXURY` = 3 regions per type, at most
  `MAX_LUXURIES_ASSIGNED_TO_REGION` = 16 types), then CS luxuries, randoms, and disabled ones.
  `PlaceLuxuries` (:6845) uses `GenerateLuxuryPlotListsAtCitySite(x, y, radius, bRemoveIce)`
  (:6340) and `GenerateLuxuryPlotListsInRegion(region)` (:6364), whose return values are the
  "luxury_plot_lists" (indexed by `GetIndicesForLuxuryType`, :6428). Water luxuries are only
  assigned to a region if its start is coastal and it has at least `NUM_WATER_NEEDED_PER_REGIONAL_LUXURY`
  coast tiles (:443).
- **Strategic and bonus**: `PlaceStrategicAndBonusResources` (:8215),
  `GetMajorStrategicResourceQuantityValues` / `GetSmallStrategicResourceQuantityValues`
  (:8178/:8197), `PlaceFish`, `PlaceSexyBonusAtCivStarts`, `AddExtraBonusesToHillsRegions`,
  `PlaceOilInTheSea`, `PlaceMarble`, `PlaceIvory`, `PlaceBonusResources` (:8369).
- **`AdjustTiles`** (:7894; formerly `FixSugarJungles` / `FixResourceGraphics`): removes or adds
  features so resource graphics make sense (mined resources lose their feature, tree resources get
  forest or jungle, and silver on snow becomes tundra).
- **Mod awareness**: `self:IsModActive("EvenMoreResources" | "AloeVera" | "AdditionalLuxuries" |
  "ReducedSupply")` (:8672-8718).

### 8.8 How a map script customises ASP

VP's ASP is a **class**: `ASP.__index = ASP`, and `Create()` returns `setmetatable({}, ASP)`
(:236-251). The global is exported as `AssignStartingPlots = ASP` (:8721). That gives five hook
levels, from broad to narrow:

1. **Override a method on the class at file top level.** This applies to every instance created
   later:
   ```lua
   -- VPMS\Terra.lua:544
   function AssignStartingPlots:GetNumCityStatesPerRegion() return 2 end
   ```
   This works because your script runs after `include("MapGenerator")` has loaded ASP.
2. **`__CustomInit`**, which runs at the end of `Create()` with the instance as `self`. Assign it
   before `Create`. Use it to replace methods *on the instance* or to change config constants:
   ```lua
   -- VPMS\Communitu_79a.lua:530-546, 1664-1666 (trimmed)
   function __CustomInit(ASP)            -- ASP here is the instance
     ASP.GetNumNaturalWondersToPlace = GetNumNaturalWondersToPlace;
     ASP.PlaceResourcesAndCityStates = PlaceResourcesAndCityStates;
     ASP.BuffIslands = BuffIslands;      -- brand-new method, available as ASP:BuffIslands()
   end
   function StartPlotSystem()
     if __CustomInit then AssignStartingPlots.__CustomInit = __CustomInit; end
     local start_plot_database = AssignStartingPlots.Create();
     ...
   ```
   Tunables you can set here (:397-474): `centerBias`, `middleBias`, `minFood*`/`minProd*`/`minGood*`,
   `MAX_LUXURIES_ASSIGNED_TO_REGION` (do not go below 8), `MAX_REGIONS_PER_LUXURY`,
   `NUM_WATER_NEEDED_PER_REGIONAL_LUXURY`, `WEIGHTED_FOOD_SCORE`, `WEIGHTED_PROD_SCORE`,
   `GOOD_TILE_MULTIPLIER`, `JUNK_TILE_MULTIPLIER`, `REGION_TYPE_MIN_REQ`.
   `MIN_LANDMASS_FERTILITY` (:437) is **defined but never read** in this version.
3. **`__InitLuxuryWeights`**: override it (on the class) to change luxury affinities. Examples:
   `Great_Plains_XP`, `Amazon_XP`, `Arborea`, `Rainforest`, `Boreal`.
4. **`CustomOverride()`** (:1424): a hook called at the end of `GenerateRegions`, after regions
   exist and before anything else.
5. **Override on the instance after `Create`**: `local asp = AssignStartingPlots.Create();
   asp.PlaceFish = MyPlaceFish;`.

Mods (not map scripts) can add a **`PreMapGenScript`** entry point (VFS file). `GenerateMap`
includes it before `GeneratePlotTypes` (`CP\MapGenerator.lua:750-759`), so it runs **after** the
map script's top-level code. Its class overrides therefore win over the script's top-level
overrides, while instance-level (`__CustomInit`) overrides still win over both.

**CP-only mode differs.** `CP\AssignStartingPlots.lua:74-120` builds the instance as a literal table
copying `AssignStartingPlots.X` **at Create time**. Overriding before `Create` works, but a *new*
method name added to the class is not visible on the instance. Instance-level assignment works in
both modes, which makes it the most portable choice.

**Do not recalculate areas inside ASP.** The header warning (:228-234) says that recalculating area
IDs mid-run "will destroy Regional definitions". Your overrides must not call `Map.RecalculateAreas()`
or `SetPlotType(..., true)` until the final recalculation in `PlaceResourcesAndCityStates`.

### 8.9 What VP changed that breaks old scripts

See Appendix B for the table. The top items: method signatures (NW placement, fertility by
landmass), removed methods (`GenerateLocalVersionsOfDataFromXML`, `FixSugarJungles`,
`ApplyHexAdjustment` as a method, the `CanBe<Wonder>` family), renamed data
(`impactData[ImpactLayers.*]`, `global_resource_plot_lists[PlotListTypes.*]`), landmass-vs-area
semantics, and the unused hooks (`GetCityStateLuxuriesTargetNumber`,
`GetDisabledLuxuriesTargetNumber`, :6008-6037). The fields whose absence actually crashes shipped
vanilla scripts (`cityStateData`, `iNumTypesUnassigned`, `naturalWondersData`,
`luxury_low_fert_compensation`, region types 9/10) are listed with the affected scripts in §10.12.

---

## 9. Patterns worth stealing

Each pattern lists its purpose, source, and a trimmed excerpt.

### 9.1 Climate model: temperature × rainfall → terrain (Communitu)

- **Purpose:** realistic biomes instead of latitude bands.
- **Source:** `VPMS\Communitu_79a.lua` `GenerateTempMaps` (:4465), `GenerateRainfallMap` (:4545),
  `DistributeRain` (:4686), `GenerateTerrain` (:2185-2265), `BlendTerrain` (:3014).
- **Model:** summer and winter temperature maps (latitude plus a land/sea contrast between
  `minWaterTemp` and `maxWaterTemp`). Wind zones by latitude (`FloatMap:GetZone`, :5676;
  `GetGeostrophicWindDirections`, :5713). Moisture is advected downwind and dropped on uplift
  (`GetRainCost` uses elevation differences, :4749). Terrain then comes from rainfall percentiles
  inside temperature bands:
  ```lua
  local desertThreshold = rainfallMap:FindThresholdFromPercent(MG.desertPercent, false, true);
  local plainsThreshold = rainfallMap:FindThresholdFromPercent(MG.plainsPercent, false, true);
  if temperatureMap.data[i] < MG.snowTemperature then
    plot:SetTerrainType(rain < desertThreshold and TERRAIN_SNOW or TERRAIN_TUNDRA, false, true)
  elseif temperatureMap.data[i] < MG.tundraTemperature then ... -- tundra/plains
  elseif temperatureMap.data[i] < MG.jungleMinTemperature then ... -- desert/plains/grass
  ...
  ```
- Options adjust the thresholds with `ModifyOdds(p, mult) = 1 - (1 - p)^mult` (:5456), a neat way
  to scale probabilities without leaving [0,1].

### 9.2 FloatMap: a 2D float grid with hex neighbours, wrap, and percentiles (Communitu)

- **Source:** `VPMS\Communitu_79a.lua:5483-5918`.
- Zero-based `data[i]` with `GetIndex(x, y)` handling wrap. `GetNeighbor(x, y, dir)` uses odd-r
  offsets. Also `Normalize`, `Smooth(radius)`, `Deviate`, `FindThresholdFromPercent(pct,
  greaterThan, excludeZeros)`, `GetLatitudeForY`, and `Save(name)` (CSV dump for debugging).
  ```lua
  function FloatMap:GetNeighbor(x, y, dir)          -- :5510
    local odd = y % 2;
    if dir == MG.W then return x - 1, y
    elseif dir == MG.NW then return x - 1 + odd, y + 1
    elseif dir == MG.NE then return x + odd, y + 1
    elseif dir == MG.E then return x + 1, y
    elseif dir == MG.SE then return x + odd, y - 1
    elseif dir == MG.SW then return x - 1 + odd, y - 1 end
  end
  ```
- `PWAreaMap` (:5920-6100) is a scanline flood-fill that labels connected regions with an arbitrary
  match function. Use it for your own "areas" *before* the engine has plot data, for example to
  find seas smaller than a lake.

### 9.3 Neighbour iteration with engine helpers

```lua
for dir = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do         -- 0..5 = NE,E,SE,SW,W,NW
  local adj = Map.PlotDirection(x, y, dir)                     -- nil off-map; wraps X
  if adj and adj:IsWater() then ... end
end
-- Ring/disc iteration (MapmakerUtilities; coroutine-based, so slow in hot loops):
for p, dist in Plot_GetPlotsInCircle(plot, 1, 3) do ... end    -- rings 1..3, centre excluded
-- Hex-space disc via range check (dx, dy are AXIAL offsets, not x/y offsets):
for dx = -r, r do for dy = -r, r do
  local p = Map.PlotXYWithRangeCheck(x, y, dx, dy, r)          -- nil if outside radius/map
end end
```
Hand-rolled offset tables (`CP\MapmakerUtilities.lua:627-628`; Continental Drift `:1394-1395`):
```lua
local even = {{0,1},{1,0},{0,-1},{-1,-1},{-1,0},{-1,1}}   -- NE,E,SE,SW,W,NW for even y
local odd  = {{1,1},{1,0},{1,-1},{0,-1},{-1,0},{0,1}}     -- for odd y
```

### 9.4 River edge helpers (Communitu)

- **Purpose:** treat all six edges uniformly.
- **Source:** `VPMS\Communitu_79a.lua:5006-5128`: `Plot_IsRiver(plot, edge)`,
  `Plot_GetRiverFlowDirection`, `Plot_SetRiver(plot, edge, flow)`, `Plot_GetNextRiverPlot`,
  `Plot_GetPreviousRiverPlot`.
  ```lua
  function Plot_SetRiver(plot, edgeDirection, flowDirection)
    local isRiver = (flowDirection ~= FlowDirectionTypes.NO_FLOWDIRECTION);
    if edgeDirection == E then plot:SetWOfRiver(isRiver, flowDirection);
    elseif edgeDirection == SE then plot:SetNWOfRiver(isRiver, flowDirection);
    elseif edgeDirection == SW then plot:SetNEOfRiver(isRiver, flowDirection);
    else
      plot = Map.PlotDirection(plot:GetX(), plot:GetY(), edgeDirection); if not plot then return false end
      if edgeDirection == W then plot:SetWOfRiver(isRiver, flowDirection);
      elseif edgeDirection == NW then plot:SetNWOfRiver(isRiver, flowDirection);
      elseif edgeDirection == NE then plot:SetNEOfRiver(isRiver, flowDirection); end
    end
    return true;
  end
  ```
- **Elevation-driven rivers** (`RiverMap`, :6157-7280): junctions at hex corners get altitudes,
  lakes are silted, each junction flows to its lowest neighbour, and rivers are sized by watershed.
  Short rivers and tributaries are pruned (`PruneShortRivers`, `PruneShortTributaries`), and each
  lake keeps a single outflow (`EnsureSingleLakeOutflows`).

### 9.5 Steering the default river generator

Override the global `GetRiverValueAtPlot(plot)` (lower value = preferred) or `AddRivers()`.
Great Plains biases rivers toward a single "Mississippi" (`GetMississippiRiverValueAtPlot`,
`DoMississippiRiver`). InlandSea adds `(|x - W/2| + |y - H/2|) * Map.Rand(3)` to the score, so
rivers flow toward the central sea (`VPMS\InlandSea.lua:162-180`). Highlands, Four_Corners and
West_vs_East also override it.

### 9.6 Coastal expansion passes

`GenerateCoasts{expansion_diceroll_table = {4, 4}}` gives two 25 % rings (§5.3). For a shallower
shelf use `{2, 3, 4}`; for none use `{}`. Custom: collect OCEAN plots with
`plot:IsAdjacentToShallowWater()` first, then set them, so a pass does not chain.

### 9.7 Lakes: fill, then restore

Communitu `FillInLakes` (:2094-2115): label water regions in the elevation map, raise any region
smaller than `MIN_WATER_SIZE_FOR_OCEAN` to sea level (or above it near the poles), and remember the
plots. `RestoreLakes` (:2117-2175) sets them back to COAST after rivers, removes river edges that
border water, and adds an outflow river from each lake. This keeps lakes from blocking river
tracing.

### 9.8 Connecting landmasses and seas

- `ConnectSeasToOceans` (:1806-1842): for each enclosed sea at least lake-size, find a cheapest path
  (`GetPathBetweenAreas`, :1984) to the main ocean and lower those plots below sea level.
- `ConnectTerraContinents` (:1901-1982): in Terra mode, if the main continent is too small, bridge
  sub-continents to it, weighted by size/distance (`terraConnectWeight`).
- `CreateMagallanes` (:3529): guarantees a circumnavigation path.
- A common general pattern (not specific to Communitu): flood-fill plot types, then remove tiny
  islands (convert landmasses of 1-2 plots to water) **before** `GenerateCoasts`.

### 9.9 Plot iteration helpers (`CP\MapmakerUtilities.lua`)

```lua
for i, plot in Plots() do ... end             -- i = 0-based plot index, y*W+x
for i, plot in Plots(Shuffle) do ... end      -- random order (consumes Map.Rand)
local x, y = GetCoordinatesFromLuaPlotIndex(luaIdx)   -- luaIdx 1-based
local luaIdx = GetLuaPlotIndexFromCoordinates(x, y)   -- y*W+x+1
local t = GetShuffledCopyOfTable(list)        -- in-place Fisher-Yates on a copy
local v = GetRandomFromRangeInclusive(a, b)
local opt = GetRandomFromWeightedList({"a","b"}, {3, 1}, "log tag")
```

### 9.10 `table.fill` and `table.count` (Firaxis extensions)

`table.fill(value, n)` returns a new table with `t[1..n] = value`. `table.fill(t, value, n)`
overwrites `t[1..n]`. `table.count(t)` counts all non-nil entries, including index 0 and string
keys (`REPO\LuaCATS\table.d.lua`). `math.clamp(v, lo, hi)` is also a Firaxis extension
(`LuaCATS\Global.d.lua:357`).

### 9.11 `Map.Rand` idioms

```lua
local r = Map.Rand(100, "Ice roll")            -- 0..99; second arg REQUIRED (string)
local v = 1 + Map.Rand(3, "Random sea level")  -- 1..3
if Map.Rand(4, "Coin") == 0 then ... end       -- 25 %
local f = Map.Rand(10000, "float") / 10000     -- [0,1) float (Communitu PWRand)
-- Seed math.random once, deterministically, if you need lots of floats (Communitu :5439):
math.randomseed(Map.Rand(32767, "") * 65536 + Map.Rand(65535, ""))
```

### 9.12 Logging

`print(...)` writes to `Lua.log` (§11.2). Communitu wraps optional timing with
`os.clock()` (:2187, :2263) and dumps float maps to CSV with `FloatMap:Save` (:5905). In
`__CustomInit` it silences ASP's chatter by replacing `print` with a no-op when `debugPrint` is
false (:531-533).

### 9.13 Region-aware resource placement

Communitu's `PlaceStrategicAndBonusResources` override (`VPMS\Communitu_79a.lua` around :720-1157)
drives the VP primitives with its own frequencies:
```lua
local tPlotList = ASP.global_resource_plot_lists;
resources_to_place = { {ASP.horse_ID, horse_amt, 100, 1, 2} };   -- {id, amt, weight%, minR, maxR}
ASP:ProcessResourceList(24 * resMultiplier, ImpactLayers.LAYER_HORSE, tPlotList[PlotListTypes.FLAT_GRASS_NO_FEATURE], resources_to_place);
ASP:ProcessResourceList(36 * resMultiplier, ImpactLayers.LAYER_HORSE, tPlotList[PlotListTypes.FLAT_PLAINS_NO_FEATURE], resources_to_place);
-- top-ups until each civ has enough (:812 onwards):
while ASP.amounts_of_resources_placed[ASP.iron_ID + 1] < 4 * ASP.iNumCivs and iLoop < 999 do ... end
```
`BuffIslands` (:567, added through `__CustomInit`) seeds small landmasses with weighted strategics
(stone, coal, oil, aluminum, uranium) so islands are worth settling. It is skipped when the biggest
landmass has fewer than 20 tiles.

### 9.14 Map-size tables and world-size keyed config

```lua
local sizes = {
  [GameInfo.Worlds.WORLDSIZE_DUEL.ID] = 4, [GameInfo.Worlds.WORLDSIZE_TINY.ID] = 8,
  [GameInfo.Worlds.WORLDSIZE_SMALL.ID] = 16, [GameInfo.Worlds.WORLDSIZE_STANDARD.ID] = 20,
  [GameInfo.Worlds.WORLDSIZE_LARGE.ID] = 24, [GameInfo.Worlds.WORLDSIZE_HUGE.ID] = 32 };
local n = sizes[Map.GetWorldSize()] or 4;   -- always provide a fallback for modded sizes
```
(`FractalWorld.lua:74-88`.) VP ASP uses `GameInfoTypes.WORLDSIZE_*` the same way.

### 9.15 Wrapping `GenerateMap` instead of replacing it

```lua
-- VPMS\Highlands.lua:91-104
local baseGenerateMap = GenerateMap;
function GenerateMap()
  ShiftMultiplier = (Map.Rand(2, "North or South climate shift") == 0) and 0 or 1;
  baseGenerateMap();
end
```
This is the cleanest way to do work before or after the standard pipeline, for example a final
validation pass.

### 9.16 Art sets (`DetermineContinents`)

Communitu replaces `DetermineContinents` (:1426-1605) to assign continent art per landmass
(`plot:SetContinentArtType(n)`; 0 ocean, 1 America, 2 Asia, 3 Africa, 4 Europe;
`CP\MapGenerator.lua:686-692`), forcing snow to the Europe set. The default calls the C++
`Map.DefaultContinentStamper()`.

---

## 10. Gotchas

Every item was checked in code unless it says **(unverified)**. They are grouped by topic, and the
most damaging come first.

### 10.1 Coordinates, hex geometry, indexing

1. **y = 0 is the south row.** `FeatureGenerator` itself says *"(0, 0) is in the SW"*
   (`VPO\FeatureGenerator.lua:202`). North is +y. Renderers must flip.
2. **Odd-r offset layout: odd rows are shifted half a hex east.** Neighbour offsets depend on row
   parity (`CP\MapmakerUtilities.lua:627-628`):
   even y: NE (0,+1), E (+1,0), SE (0,-1), SW (-1,-1), W (-1,0), NW (-1,+1).
   odd y: NE (+1,+1), E (+1,0), SE (+1,-1), SW (0,-1), W (-1,0), NW (0,+1).
   Use `Map.PlotDirection(x, y, dir)` and you never need these.
3. **`DirectionTypes` start at NE = 0 and go clockwise** (NE, E, SE, SW, W, NW). There is no N
   or S direction for hexes. **`FlowDirectionTypes` start at NORTH = 0** (N, NE, SE, S, SW, NW). The
   two enums use the same numbers with different meanings. `NO_DIRECTION` and `NO_FLOWDIRECTION`
   are both 7, not -1.
4. **Plot index = `y*W + x`** (0-based C++). `Map.GetPlotByIndex(i)` and `Plots()` use that.
   **Lua tables from `table.fill` are 1-based**, so `t[y*W + x + 1]`.
   - `SetPlotTypes(t)` reads `t[i+1]` (1-based). `SetTerrainTypes(t)` reads `t[i]` (0-based)
     (`CP\MapGenerator.lua:136-138, 184-187`).
   - `TerrainGenerator:GenerateTerrain()` returns 0-based, and `FractalWorld:GeneratePlotTypes()`
     returns 1-based.
   - The default `GeneratePlotTypes` builds a 0-based table and passes it to the 1-based
     `SetPlotTypes` (`:196-202`). The last plot then gets `nil`, which becomes `PLOT_MOUNTAIN`
     (item 10.6.1). `Continents.lua:169` and `FractalWorld:ShiftPlotTypesBy` (`:113-121`) also mix
     0-based writes into 1-based tables. The net effect is a harmless 1-plot offset, but don't
     imitate it.
   - VP ASP's plot lists and impact layers use 1-based plot indices
     (`GetLuaPlotIndexFromCoordinates(x, y) = y*W + x + 1`).
   - `amounts_of_resources_placed[resID + 1]`, but `luxury_assignment_count[resID]` (no +1)
     (`VPO\ASP:377-378`).
5. **`Map.GetPlot(x, y)` wraps x on wrap-X maps** (and y on wrap-Y) via `coordRange`
   (`DLL\CvMap.h:315-324`), so `Map.GetPlot(-1, y)` is the last column. Out-of-range y returns
   **nothing**, so check for nil. `Map.PlotDirection` also normalises its input coordinates
   (`CvLuaMap.cpp:411-431`). `Map.IsPlot(x, y)` does **not** wrap.
6. **`Map.PlotXYWithRangeCheck(x, y, dx, dy, r)` and `Map.GetPlotXY` take hex-space (axial) offsets,
   not offset-coordinate deltas.** `plotXY` converts x to hex space with `x - floor(y/2)`, adds
   `dx`, and converts back (`DLL\CvGameCoreUtils.cpp:410-426`). Looping `dx, dy` over `[-r, r]` with
   the range check gives exactly the hex disc of radius `r`. Treating `dx` as a plain x offset gives
   a skewed shape.
7. `Map.PlotDistance` is hex distance, with a source comment admitting *"wrapping does not work
   correctly for large distances"* (`CvGameCoreUtils.cpp:463`).
8. `Plot_GetPlotsInCircle(plot, minR, maxR)` **never yields the centre plot**, even with
   `minR = 0` (the radius-0 ring yields nothing), and with one argument it means `1..r`
   (`CP\MapmakerUtilities.lua:636-683`). It is a coroutine iterator: correct but slow.

### 10.2 Areas, landmasses, continents, lakes (VP DLL semantics)

1. **In VP, an "area" is not a connected component.** `CvMap::calculateAreas`
   (`DLL\CvMap.cpp:1879-2010`) *looks* like it groups plots by water-ness and passability with a
   "wide connection" rule (`AreaValid`, `DLL\CvAStar.cpp:2784-2829`), but the step pathfinder it
   calls refuses every step when `iMaxTurns` is 0 or 1 (`CvAStar::LinkChild`, `:625-630`), which is
   what `calculateAreas` passes. What actually runs (verified against a real game, see
   `docs/engine-api.md` §17 A1): plots are visited in index order (y=0 first), and each unassigned
   plot joins the **largest already-assigned neighbouring area of the same water/land kind**, or
   opens a new area. Results:
   - **Impassability is ignored**: mountains merge into the surrounding land area, ice into the ocean.
   - **Concave shapes split**: an n-shaped continent becomes two areas that never re-merge; a long
     east-west coastline can produce several areas on the same continent.
   - Area shapes depend on scan order, so the biggest area is often much smaller than the biggest
     landmass. Vanilla Pangaea's "84 % in one area" loop needed 26 attempts in a real VP game.
2. **A "landmass" is the plain connected component** of land or water (`LandmassValid`,
   `CvAStar.cpp:2834-2841`). A **"continent"** groups plots by deep-water connectivity
   (`ContinentValid`, `:2845-2852`) and is used for art and naming.
3. **Use landmass for "which continent is this?"**: `plot:GetLandmass()`,
   `Map.FindBiggestLandmassID(bWater)`, `Map.GetNumTilesOfLandmass(id)`,
   `plot:IsAdjacentToLandmass(id)`, `GetLandmassBoundaries(id)`. The area API is still there
   (`plot:GetArea()` returns an **ID**, `plot:Area()` an object, `Map.GetArea(id)`,
   `Map.FindBiggestArea(bWater)` an object, `for _, area in Map.Areas() do`), but it means
   something different from vanilla. Vanilla Pangaea and Continents test
   `Map.FindBiggestArea(false)` against 84% / 58% of all land. In VP that can retry many more times
   or accept a different shape. VP's own copies switched to landmass (§4.2).
4. **`Area:IsLake()` does not exist in VP**. Its registration is commented out
   (`DLL\Lua\CvLuaArea.cpp:30`), so old code fails with *attempt to call method 'IsLake'*. Use
   `plot:IsLake()`.
5. **`plot:IsLake()` is landmass-based**: a water landmass smaller than `MIN_WATER_SIZE_FOR_OCEAN`
   (10) (`CvMap.cpp:122-125`, `CvPlot.cpp:1231-1237`).
6. **Area, landmass and lake data only update when you call `Map.RecalculateAreas()`**
   (`CvMap.cpp:1757-1763`: areas, then landmasses, continents and rivers). `Map.CalculateAreas()`
   recomputes **areas only, not landmasses** (`CvLuaMap.cpp:373-378`), so after the default
   `AddLakes`, the new 1-plot lakes still say `IsLake() == false`. `SetPlotType(..., false, ...)`
   leaves the plot's area and landmass IDs unchanged.
7. **`plot:IsCoastalLand()` reads a cached flag** (`CvLuaPlot.cpp:587-593` calls
   `isCoastalLand(-1, true, false)`). The flag is refreshed by `Map.RecalculateAreas()` (through
   `recalculateLandmasses`, `CvMap.cpp:2600-2606`) or as a side effect of `plot:IsLake()`,
   `plot:IsAdjacentToLand()` and `plot:IsFreshWater()` on that same plot. Those three pass
   `bUseCachedValue = false`, because a missing Lua boolean is `false`. During plot generation,
   **`IsCoastalLand()` can be stale.** Recalculate first, or test neighbours yourself. Also, land
   next to *ice-covered* water does not count as coastal (`CvPlot.cpp:1262`).
8. `IsAdjacentToShallowWater()` is computed live (`CvPlot.cpp:969-986`). `IsAdjacentToLand()` is
   refreshed live when called from Lua (item 7).
9. **ASP must not see a recalculation mid-run** (`VPO\ASP:228-234`). Regions store area or landmass
   IDs.
10. Area IDs are not contiguous (`addArea` / `deleteArea`). Iterate with `Map.Areas()`, not
    `for id = 0, Map.GetNumAreas() - 1`.

### 10.3 Plot setters: side effects and silent conversions

1. **`SetPlotType` can change terrain** (to coast, ocean or grass when water-ness flips), and
   to/from ocean it erases the plot (§4.1). **`SetTerrainType` can change the plot type** (a water
   terrain makes the plot ocean, and vice versa) (§5.1).
2. **`TERRAIN_HILL` is `Water = 1`** in the DB, and both it and `TERRAIN_MOUNTAIN` are
   `GraphicalOnly`. Never assign either.
3. **`CanHaveFeature` is false whenever the plot already has a feature**, and it is always false on
   mountains (`CvPlot.cpp:5506-5525`). `SetFeatureType` itself has **no validity check**.
4. **Clearing the feature on a river desert plot puts flood plains back** (`CvPlot.cpp:7551-7556`).
5. **River crossings are computed only when a river flag changes**, and only for land-land edges
   (§6.2). Change plot types first, then rivers.
6. **The engine converts any water next to land into COAST after generation** (`ValidateCoast`,
   §1.2). Deep ocean hugging a coastline will not survive.
7. **`SetPlotType(PLOT_OCEAN)` keeps the old (land) landmass and area IDs until recalculation**
   (default `AddLakes` even calls `SetArea(-1)` first, `CP\MapGenerator.lua:530`).

### 10.4 Options, randomness, determinism

1. **`Map.GetCustomOption(i)`: `i` is the 1-based position in *your* `CustomOptions`, and the value
   is the 1-based index into `Values`.** "Random" is just the last value, which you must resolve.
   A missing option returns `nil` (§3.2).
2. **`Map.Rand(n, "tag")` returns [0, n)**. The **string is mandatory**
   (`luaL_checkstring`, `CvLuaMap.cpp:363-371`). Without it: *bad argument #2 to 'Rand'*. For
   `n < 2` it returns 0 **without advancing the RNG** (`DLL\CvRandom.cpp:104-105`). Negative `n`
   returns a non-positive number (`CvGame.cpp:10066-10072`).
3. **Use `Map.Rand` (the synchronous map RNG), not `math.random`**, for anything that shapes the
   map. Reproducibility of a map seed depends on it. Multiplayer clients are believed to generate
   the map independently from the same seed **(unverified)**. If you want `math.random`, seed it
   once from `Map.Rand`, as Communitu does (`:5439-5448`).
4. **Hidden RNG consumers**: `Fractal.Create` / `CreateRifts` / `BuildRidges`,
   `plot:GetInlandCorner()` (shuffle), `Plots(Shuffle)`, `GetShuffledCopyOfTable`, and
   `GetRandomMultiplier`. Adding or removing any of these changes everything generated afterwards.
5. **`pairs()` order over tables keyed by tables or plots depends on memory addresses.** If the loop
   body consumes `Map.Rand`, the map stops being reproducible. Use arrays with `ipairs`, or sort the
   keys first. (Lua 5.1 semantics; the fix is cheap.)
6. **`args.x or true` cannot be switched off**: `GenerateCoasts{bExpandCoasts=false}`,
   `InitFractal{polar=false}`, `GeneratePlotTypes{shift_plot_types=false}`, and
   `GenerateFractalLayer{bShift=false}` are all ignored (§4.2, §4.4, §5.3).
7. **World age: value 1 = 3 billion years (young, more mountains)** (§3.2).
8. `IsTropical(y)` reads option 2 as rainfall, but option 2 is temperature in standard scripts
   (`CP\MapmakerUtilities.lua:785`).
8. **The first `Map.Rand` after seeding with a small seed is 0.** `CvRandom::get` computes
   `((A*seed + C) >> 16) * n / 2^32` with `A = 1103515245`; for seed < ~1e5 the first draw is below
   `n` for every realistic `n`, so it floors to 0. The game seeds with a large random number and
   never shows this; the harness's `--seed 1..50` does (every script's first random decision is
   deterministic there). Use seeds like 100001 under c5maps when the first draw matters, or draw
   something unimportant first.

### 10.5 Lifecycle and environment

1. **Top-level code runs before the map exists** (§1.2). Do map queries inside your functions.
2. **`GetMapInitData` sizes must be integers** (`lua_tointeger`). Floor them yourself.
3. **`include` re-executes the file**, so re-including ASP after overriding it wipes your top-level
   overrides (§1.4).
4. A `PreMapGenScript` from another mod runs after your script's top-level code and can override
   your class-level ASP overrides (§8.8).
5. **`Map.ChangeAIMapHint(n)` does nothing in VP.** The DLL stores the value but never reads it
   (`DLL\CvMap.h:452`: *"unused on DLL side but exposed to lua"*, and no Lua reader exists in the
   repo). Scripts still call it (Archipelago, Terra, Communitu). It is harmless, but don't rely on
   it to make the AI naval.
6. There can be several copies of the same script in the map list (game assets, `MYMAPS`, mod
   folder), each with its own `FileName` key in `MapScripts` and `MapScriptOptions`.

### 10.6 Lua-to-C++ argument coercion

1. **Missing or nil numeric arguments become 0, and missing booleans become false**
   (`CvGameCoreDLLUtil\include\CvLuaArgTemplates.h:9-25`, used by every `BasicLuaMethod` binding).
   A typo in an enum name is therefore silent:
   - `plot:SetFeatureType(FeatureTypes.FEATURE_FORRESt)` gives `0` = **`FEATURE_ICE`**.
   - `plot:SetPlotType(PlotTypes.PLOT_PEAK)` gives `0` = **`PLOT_MOUNTAIN`** (the
     MultilayeredFractal accident, §4.4).
   - `plot:SetTerrainType(nil)` gives `0` = **`TERRAIN_GRASS`**.
   - `plot:SetResourceType(GameInfoTypes.RESOURCE_TYPO, 1)` gives `0` = **`RESOURCE_IRON`**.
   Assert that your IDs are not nil.
2. `Fractal:GetHeight` with 1 argument is a **percentile lookup**, and with 2 it is a **height
   sample**. Any other count raises *"Invalid number of arguments."* (`CvLuaFractal.cpp:193-219`).
3. Fractal flags must be a **table of booleans**. A number is ignored (§4.3).

### 10.7 GameInfo, enums, defines

1. `TerrainTypes`, `FeatureTypes`, `PlotTypes`, `DirectionTypes`, `FlowDirectionTypes` and
   `YieldTypes` are DLL-exported enums. `GameInfoTypes.X` covers every DB row type by name
   (including modded resources, features and regions). `GameInfo.Terrains.TERRAIN_GRASS.ID` and
   `GameInfo.Terrains[id]` give full rows. For modded content use `GameInfoTypes`, because
   `FeatureTypes` is a closed enum (`LuaCATS\enum\FeatureTypes.d.lua` header).
2. `GameDefines.NAME` reads `Defines`. Values in the current DB: `MIN_WATER_SIZE_FOR_OCEAN` 10,
   `LAKE_PLOT_RAND` 160, `PLOTS_PER_RIVER_EDGE` 12, `RIVER_SOURCE_MIN_RIVER_RANGE` 4,
   `RIVER_SOURCE_MIN_SEAWATER_RANGE` 2, `SHALLOW_WATER_TERRAIN` 5, `DEEP_WATER_TERRAIN` 6,
   `LAND_TERRAIN` 0, `MAX_MAJOR_CIVS` 22, `MAX_MINOR_CIVS` 41, `MAX_CIV_PLAYERS` 63,
   `MAX_PLAYERS` 64.
3. **Player IDs are 0-based**: majors `0..MAX_MAJOR_CIVS-1`, city states
   `MAX_MAJOR_CIVS..MAX_CIV_PLAYERS-1`, barbarians last. In MP there can be **gaps**. Use
   `GetPlayerAndTeamInfo()` (`CP\MapmakerUtilities.lua:131`) and `self.player_ID_list`.
4. `#t` only counts the 1..n sequence. It misses `t[0]` and stops at the first hole. Use
   `table.count(t)` (Firaxis) or `table.maxn(t)` (Lua 5.1).
5. **Per-plot `GameInfo` queries are slow** (each `GameInfo.X()` iteration runs a DB query). The
   default `AddFeatures` iterates `GameInfo.Features()` for every plot (`CP\MapGenerator.lua:550-551`).
   Cache IDs in locals up front.

### 10.8 VP ASP assumptions

1. ASP needs `GenerateRegions` to have set `method`, `bArea`, `iNumCivs`, `iNumCityStates`,
   `player_ID_list`, and `regionData` (8 fields, with field 5 interpreted by `bArea`) (§8.2).
2. Continental division silently falls back to Biggest Landmass or Rectangular when land is too
   fragmented or infertile (§8.2). Check `Lua.log` for "Switching to use".
3. **NWs never sit on a plot with a missing neighbour** (edge rows, and edge columns on non-wrap
   maps), and they need nearby fertile land (§8.5).
4. Old vanilla overrides that **silently do nothing** under VP: the `CanBe<Wonder>` family,
   `GetDisabledLuxuriesTargetNumber` and `GetCityStateLuxuriesTargetNumber` (marked UNUSED,
   :6008-6037), `FixSugarJungles` (renamed `AdjustTiles`), and anything that writes
   `self.luxuryData` / `self.strategicData` (now `impactData[...]`).
5. **`MeasureStartPlacementFertilityOfLandmass` now takes a landmass ID.** The area version is
   `MeasureStartPlacementFertilityOfArea` (Appendix B). Passing an area ID returns plausible but
   wrong numbers.
6. `self.resource_setting` is set but unused. Use `resDensity` and friends (:1445).
7. `RegionDivision`, `ImpactLayers` and `PlotListTypes` are **globals created by VP's ASP**. Code
   that uses them won't run in CP-only mode.
8. Communitu's `legendary` arg is ignored, and its Random strategic density becomes Legendary Start
   (§3.3).

### 10.9 Performance

1. Map scripts run once, but Huge maps have 10,240 plots (128×80) and Communitu-size maps 7,000+.
   O(plots × neighbours × radius) code is fine. O(plots²) is not.
2. **Undeclared variables are globals.** Each access is a hash lookup in `_G`, and they leak
   between functions (Tectonic: `ft`, `f`, `q`, `xAdj`, `yAdj`, `mag`, ...). Use `local`.
3. Cache `Map.GetPlot` results in a flat array, or use `Plots()`, which memoizes
   (`CP\MapmakerUtilities.lua:91-128`).
4. Coroutine iterators (`Plot_GetPlotsInCircle`) and per-plot closures cost more than plain
   loops with offset tables.
5. Caching the Voronoi (Continental Drift's `CachePartOfPlate`) rather than recomputing distances
   per query is the single biggest win in plate-style scripts.
6. String concatenation in hot loops builds a new string each time. Collect pieces in a table and
   call `table.concat` once, or don't build log strings unless debugging (Communitu's `debugPrint`
   flag).
7. Communitu's header says: *"Try reducing these slightly if you experience crashes on huge maps"*
   (smoothing ranges `tempBlendMaxRange`, `elevationBlendRange`, `:186-191`). Memory and time limits
   are real.

### 10.10 Map edges, wrap, latitude

1. **The wrap seam (x = 0 / W-1).** Fractals need `Map.GetFractalFlags()` to tile (§4.3), your own
   noise needs `x % W`, and plate distances need wrap-aware metrics. Communitu forces flat land in
   the 2 columns each side of the seam *"to prevent issues with tiles that don't look like what they
   are"* (`:1787-1790`) **(graphical issue unverified)**.
2. **Latitude has two definitions.** `TerrainGenerator` and `FeatureGenerator` use `|H/2 - y| / (H/2)`
   and ignore `TopLatitude` / `BottomLatitude`. `plot:GetLatitude()` (integer degrees, absolute) uses
   them, and resource `MinLatitude` / `MaxLatitude` use that (`CvPlot.cpp:5644-5660`). With defaults
   (90/-90), y = 0 is 90 degrees and y = H/2 is about 0.
3. FRAC_POLAR on a non-wrapping map waters the east and west edges too (§4.3).
4. VP ice: wrap-X maps get **ice on every water plot of rows 0 and H-1**
   (`VPO\FeatureGenerator.lua:244-245`). Polar land rows stay land (snow), so strip land from the
   edge rows if you want navigable poles to stay closed.

### 10.11 Hills, mountains, coasts

1. VP's `FeatureGenerator:AddFeatures()` **with no argument turns coastal mountains into hills**
   (§7.1). Pass `true` to keep sea cliffs.
2. Mountains stay impassable for units but do not split areas (item 10.2.1). Long ranges can strand
   start regions in Continental mode.
3. Hills on the coast are fine. Mountains can't take features, and NW placement can convert core
   tiles (`ChangeCoreTileToMountain` and so on in `Natural_Wonder_Placement`).

### 10.12 Lessons from the headless sweep of every installed script

These come from running all 87 installed scripts through the harness (`docs/script-compat.md`) and the
700-run metrics benchmark (§12, `docs/metrics-baselines.md`). Failures listed here are script bugs that
happen the same way in game, not harness artefacts.

1. **The luxury tile count is fixed per world size, not per land area.** `GetWorldLuxuryTargetNumbers`
   is a table keyed by `WORLDSIZE_*` and luxury density (`VPO\ASP:6798`). Measured: 103–122 luxury tiles at
   standard and 191–204 at huge on every reference script, so luxury *density* runs from 7 per 100 land
   (Terra, big grid) to 14 (Archipelago, little land). A land-heavy script dilutes luxuries; a water-heavy
   one concentrates them. Strategic density, by contrast, stays at 9–14 per 100 land.
2. **Scripts commonly override the grid size** in `GetMapInitData`, so "standard" is not always 80×52:
   Communitu 79×53 at standard but only **97×66 at huge** (vs the default 128×80), Continental_Drift 88×58,
   Terra **104×64 at standard** (152×96 at huge), Oval 64×40. Land per civ and absolute resource counts
   follow the grid, so compare densities, not counts, across scripts.
3. **VP region types 9 and 10 break luxury tables that cover only 1–8.** VP re-classifies one region per
   civ with a mountain or snow start bias as `REGION_MOUNTAIN` (9) or `REGION_SNOW` (10)
   (`VPO\ASP:2128-2175`); `AssignLuxuryToRegion` then looks up `self.luxury_region_weights[region_type]`
   (`VPO\ASP:5935-5949`). Expansion `Arborea` and `Rainforest` override `__InitLuxuryWeights`
   (`Arborea.lua:765`) with entries for types 1–8 only, so `ipairs(nil)` fails, but only when such a civ is
   in the game (2 of 3 seeds failed). If you override `__InitLuxuryWeights` (VP's is `VPO\ASP:482`), cover
   every `Regions` row, including 9 and 10.
4. **Team-based scripts need teams.** Scripts with team branches (Hemispheres, North_vs_South, West_vs_East,
   Four_Corners, Europe, Frontier, Ring, Skirmish, Large_Islands) read `bTeamGame` from
   `GetPlayerAndTeamInfo()` (`CP\MapmakerUtilities.lua:131`). Expansion `Hemispheres` in a free-for-all
   takes its vanilla branch, sets `self.method = 2` (continental) without `self.bArea`, and either crashes
   indexing `self.landmass_areas[areaID]` or gives two regions the same start plot. Headless, pass
   `--teams 2` (`--teams 4` for Four_Corners); in your own script, test both team and free-for-all setups.
5. **ASP fields that no longer exist in VP.** VP's ASP is a rewrite (§8.9, Appendix B); these vanilla
   fields are gone, so any override that reads them fails under VP (CP-only mode still has them):
   - `self.cityStateData`, read by `CanPlaceCityStateAt` overrides (VP: `self.impactData[ImpactLayers.LAYER_CITY_STATE]`,
     `VPO\ASP:382, 4879`). Affected: Assets `Four_Corners`, `Highlands`, `InlandSea`, `Lakes`
     (`Lakes.lua:215`), `North_vs_South`, `Ring`, `Skirmish`, `West_vs_East`; Expansion and CP `Boreal`;
     CP `Highlands`; DLC_SP_Maps_3 `Script_Random_China`.
   - `self.iNumTypesUnassigned`, read by `AssignLuxuryRoles` overrides (VP's version, `VPO\ASP:6064`, has
     no such counter). Affected: Assets `Great_Plains` (`Great_Plains.lua:1265`), DLC_SP_Maps `Amazon`,
     Expansion `Amazon_XP`.
   - `self.naturalWondersData`, read by NW placement overrides. Affected: Expansion `Europe`
     (`Europe.lua:899`), `Great_Plains_XP`.
   - `self.luxury_low_fert_compensation`, used by Expansion `Frontier`'s `PlaceLuxuries`
     (`Frontier.lua:1540`); in VP it is a local of `PlaceLuxuries` (`VPO\ASP:6841-6847`).

   **VP ships fixed copies of every one of these in `VPMS`** (`vp:Lakes`, `vp:Great_Plains_XP`, `vp:Amazon_XP`,
   `vp:Europe`, `vp:Frontier`, `vp:Arborea`, `vp:Rainforest`, `vp:Script_Random_China`, ...), and all of
   them run. Players with VP see both copies in the map list; only the VP one works.
6. **The old Communitu in `MYMAPS` is broken under current VP.** `MYMAPS\Communitu_79a.lua` (v3.1.0,
   `:1236`) calls `ASP:Plot_GetFertility(...)` (`:547, 885`), a method that exists nowhere; CP/VP provide
   the *global* `Plot_GetFertility` (`CP\MapmakerUtilities.lua:717`). The same file sits in `CIV5\Assets\Maps`.
   VP's v3.2.0 copy (`VPMS\Communitu_79a.lua:549, 887, 1238`) calls the global and works. The old copy
   also runs with option 16 = 1 ("Override AssignStartingPlots" = No), which skips its ASP overrides. Note
   that a bare `Communitu_79a` in the harness resolves to the `MYMAPS` copy first; use `vp:Communitu_79a`.
7. **Scripts that retry until the biggest *area* is big enough are sensitive to the whole area
   algorithm.** Vanilla Pangaea, PangaeaPlus, Sandstorm, Shuffle, Tilted_Axis, Expansion Arborea and
   Rainforest, and Continents / ContinentsPlus on some seeds regenerate the plot-type fractal until
   `Map.FindBiggestArea(false)` covers a target share of land. Under VP's real area semantics
   (§10.2.1, verified in-game: the harness default `--areas literal` reproduces the DLL's areas exactly)
   these loops retry many times (26 attempts for a real standard Pangaea) and can accept odd shapes.
   The harness's `--areas floodfill` is only a what-if and changes the whole map for these scripts; every
   other script differs by 10-60 plots between the modes. Use landmass APIs (§10.2.3) in new scripts
   and the problem disappears.

---

## 11. Shipping checklist and debugging

### 11.1 Checklist for a VP-compatible map script

**Structure**
- [ ] `include("MapGenerator")` first, then only the libraries you use.
- [ ] No map queries at top level. All state is created inside `GeneratePlotTypes` and later.
- [ ] `GetMapScriptInfo()` returns `Name`, `Description`, `IsAdvancedMap`, `SupportsMultiplayer`,
      `IconIndex`, and `CustomOptions`. Its option order is documented in a comment, and every
      `Map.GetCustomOption(i)` matches it.
- [ ] Every "Random" value is resolved with `Map.Rand`, and every `GetCustomOption` has an `or default`.
- [ ] `GetMapInitData` returns integer `Width` and `Height`, sets `WrapX` explicitly, and has sizes
      for all six `WORLDSIZE_*` plus a fallback.

**Plots, terrain, water**
- [ ] Fractals get `Map.GetFractalFlags()` (wrap) unless you deliberately want edges.
- [ ] 1-based tables go to `SetPlotTypes`, and 0-based tables to `SetTerrainTypes`.
- [ ] `SetPlotType` / `SetTerrainType` use `bRecalculate = false`, with one `Map.RecalculateAreas()`
      per phase.
- [ ] Coasts are generated, and remember that `bExpandCoasts=false` is ignored.
- [ ] Lakes are fewer than 10 plots, unless you intend inland seas. `IsLake` is checked only after
      `RecalculateAreas`.
- [ ] Never `TERRAIN_HILL` / `TERRAIN_MOUNTAIN`. Every ID is validated as non-nil.

**Rivers and features**
- [ ] Rivers are set after plot types are final, on land-land edges only, with flows that are
      consistent along each path.
- [ ] Features come after rivers (flood plains need `IsRiver`). Clear an existing feature before
      replacing it.
- [ ] Decide `FeatureGenerator:AddFeatures(true or false)` (coastal mountains).

**Start plots and resources**
- [ ] `StartPlotSystem` passes `method` and `resources` (resolved), and optionally `ChooseLocations{mustBeCoast=...}`.
- [ ] Biggest-landmass logic uses **landmass** APIs, not area.
- [ ] Every ASP override uses VP signatures and data names (Appendix B), and is installed through a
      class override, `__CustomInit`, or an instance assignment. None recalculates areas mid-ASP.
- [ ] There is enough coastal, river, mountain and snow start terrain for biased civs, and enough
      fertile land per civ. Otherwise Continental falls back.
- [ ] Not relying on `Map.ChangeAIMapHint` to change AI behaviour.

**Determinism and performance**
- [ ] No unseeded `math.random`. No `pairs()` over object-keyed tables feeding `Map.Rand`.
- [ ] No accidental globals in hot loops. No per-plot `GameInfo` iteration.
- [ ] Huge maps with 22 civs and 41 city states complete within a reasonable time.

**Testing matrix**
- [ ] All world sizes; extreme options (low and high sea level, arid and wet, every custom option);
      many seeds; few and many civs; with VP extras (EvenMoreResources) on and off. Confirm in
      `Lua.log` that no "Switching to use" fallback or "FAILED" messages appear unexpectedly.
- [ ] Team games (2 and 4 teams) as well as free-for-all, if the script has team logic (§10.12.4).
- [ ] `host/metrics.py compare` on several seeds at standard and huge: no flags on the invariant
      metrics (§12.3), and archetype-dependent flags only where they are the design.

### 11.2 Debugging

- **Logging.** In `Documents\My Games\Sid Meier's Civilization 5\config.ini` set
  `LoggingEnabled = 1` (line 248 in this install), and optionally `EnableLuaDebugLibrary = 1`
  (line 40) and `EnableTuner = 1` (line 4, for FireTuner). Logs go to
  `Documents\My Games\Sid Meier's Civilization 5\Logs\`:
  - `Lua.log`: every `print()`. Lines look like `[722876.515] VP_LUAAPI: ...`, prefixed with the
    Lua state's name. The map script state is created as `"Map Script"` (`CvMapGenerator.cpp:36`),
    so expect a `Map Script:` prefix **(prefix inferred, not observed in the current log)**.
  - `Database.log`: SQL and XML errors (option text keys, missing rows).
  - `RandCalls.csv`: each RNG call with its log string, when `RandLog = 1` in `[Debug]`
    (config.ini line 215: *"bit 0 = on/off, bit 1 = log callstacks, bit 2 = log pregame calls,
    bit 3 = log asynchronous RNGs"*). This is why `Map.Rand`'s second argument matters: it labels
    the call. Diffing two runs' RandCalls is the quickest way to find a determinism break.
- **ASP prints a lot** by default: resource settings, region table, civ-per-area assignment,
  fallbacks, NW choices, and final resource totals (`PrintFinalResourceTotalsToLog`, :8053).
- **Typical errors and what they mean:**

| Message | Likely cause |
|---|---|
| `Cannot find map script entry point GenerateMap()` | `include("MapGenerator")` missing or failed, or a syntax error earlier in the file. |
| `bad argument #2 to 'Rand' (string expected, got no value)` | `Map.Rand(n)` without a log string. |
| `attempt to call method 'IsLake' (a nil value)` | `area:IsLake()` (removed in VP). Use `plot:IsLake()`. |
| `attempt to call method 'X' (a nil value)` on an ASP object | A removed or renamed ASP method (Appendix B), or a new method added to the class in CP-only mode. |
| `attempt to index a nil value` right after `Map.GetPlot` | y out of range (x wraps, y doesn't), or the map isn't initialised yet (top-level code). |
| `attempt to perform arithmetic on a nil value` / `compare number with nil` | `Map.GetCustomOption(i)` for a nonexistent option, a 0-based read of a 1-based `table.fill` table, or a worldsize lookup without a fallback. |
| `Invalid number of arguments.` | `frac:GetHeight()` with 0 or 3+ arguments. |
| Map full of ice / mountains / iron where unexpected | A nil enum coerced to 0 (§10.6). |
| Rivers missing next to lakes | A river set before the plot became water, or vice versa (stale crossing, §6.2). |
| All civs crammed on one continent | Biggest-area vs biggest-landmass mix-up, or a Continental â†’ Biggest Landmass fallback (look for "Switching to use"). |

- **Headless iteration.** This repo's harness (`DESIGN.md`) runs scripts outside the game with the
  same VP Lua libraries and renders PNG/ASCII. Use it for fast loops, then confirm in game. The game
  is the source of truth for anything the harness only approximates.
- **Contact sheets.** `python host/sheet.py <script> --size standard --seeds 1,2,3,4,5 --layer mask`
  runs the script once per seed in parallel and composes one labelled PNG (default
  `out/sheets/<script>_<size>_seeds1-2-3-4-5.png`) with land %, landmasses >= 30 tiles, largest
  landmass % and 1-5 tile islets under each tile. To compare option or `--define` values (§3.5) use
  `--run "label|<c5gen args>"` per tile (`--common "<args>"` is appended to every run); `--run`
  together with `--seeds` gives a runs x seeds grid; `--spec file.json` takes
  `[{"label": ..., "args": [...]}, ...]`. `--grep REGEX` prints the first matching `.log` lines
  under each tile (e.g. your script's own diagnostic print), c5gen warnings are shown in orange, and a
  failed run becomes a red tile with the Lua error. Each run keeps its dump in
  `<sheet stem>/runs/<label>/`, `summary.json` sits beside them, `--reuse` skips unchanged runs, and
  the exit status is 1 if any run failed. Tiles use the `plain` layer by default; `--layer mask`
  (water / flat / hills / mountains only) is the one to judge landmass shape. The same layer and
  `--no-starts` (hide start markers and civ names) are available in `render/render_map.py`.
- **Numeric sanity check.** `python host/metrics.py compare <dump>.json --archetype <closest>`
  compares a harness dump against the measured ranges of seven community scripts (§12). Run it on
  several seeds before testing in game.
- **Old or third-party scripts.** If a script fails with a traceback inside its own ASP override,
  check §10.12 and `docs/script-compat.md` first: most stock scripts that fail under VP have a fixed
  copy in `VPMS`.

---

## 12. Macro metrics: what normal VP maps look like

Source: `docs/metrics-baselines.md` (tables) and `docs/metrics-baselines.json` (raw percentiles).

### 12.1 Methodology

Seven reference scripts (`vp:Communitu_79a`, `vp:Continental_Drift`, `Continents`, `SmallContinents`,
`vp:Terra`, `Oval`, `Archipelago`) were run headless through the harness at standard and huge size, seeds
1–50 each, with default options and the `Worlds` civ / city-state counts (700 runs, 0 failures), and
`host/metrics.py` measured each dump. "Pooled p5–p95" weights the seven archetypes equally: a value inside it
is something one of the community's standard scripts produces.

### 12.2 Metrics a new script must respect

| Metric | Standard p5–p95 (median) | Huge p5–p95 (median) | Notes |
|---|---|---|---|
| Land % of all plots | 19.4–42.9 (25.1) | 20.2–42.6 (24.7) | Archipelago ≈ 20, Oval ≈ 42, continent scripts 23–26. Archetype-dependent. |
| Hills % of land | 19.6–35.5 (27.3) | 19.6–34.1 (25.8) | VP maps are hillier than most people expect. |
| Mountains % of land | 1.0–5.4 (2.6) | 1.3–6.5 (2.8) | No reference script exceeds 9 %. |
| Strategic tiles per 100 land | 9.3–13.8 (11.9) | 8.8–11.6 (10.6) | The most stable resource density. |
| Luxury tiles per 100 land | 7.2–14.2 (10.4) | 5.6–9.7 (7.6) | Moves *inversely* with land: the tile count is fixed per size (103–122 / 191–204) (§10.12.1). |
| Land tiles on a river % | 11.9–24.9 (17.9) | 13.8–26.2 (20.7) | Rivers are never absent. |
| Land tiles with fresh water % | 14.7–33.0 (24.8) | 17.9–33.9 (27.2) | |
| Nearest-capital distance, min | 8–11 (9) | 9–12 (9) | 9 is VP ASP's normal spacing; below 7 is a red flag. |
| Nearest-capital distance, mean | 9.4–15.1 (11.2) | 10.5–17.1 (13.2) | |
| Capital â†’ nearest city-state, min | exactly 7 | exactly 7 | CS impact radius 6 around every start (`VPO\ASP:2228-2229`). |
| Luxury tiles within 3 of capital, mean | exactly 3.0 | 2.92–3.0 (3.0) | Enforced by VP `PlaceLuxuries` (`VPO\ASP:6845`). Anything else means ASP's luxury pass did not run normally. |
| Capitals coastal % | 25–100 (50) | 16.7–100 (41.7) | Archipelago / SmallContinents 100 %, continent maps 35–50 %. Archetype-dependent. |
| Mean latitude of tundra+snow / desert / jungle (0 = equator, 1 = pole) | 0.69–0.80 / 0.31–0.40 / 0.06–0.13 | 0.67–0.81 / 0.31–0.41 / 0.06–0.14 | The climate bands: cold is polar, desert subtropical, jungle equatorial. |
| Polar rows: land % / ice % of their water | 0–4.7 / 83.6–100 | 0–1.3 / 85.1–100 | VP ices every water plot of rows 0 and H-1 on wrap-X maps (§10.10.4). |

Also invariant in every run: start plots never on water or a mountain, city-state → city-state minimum 5–6,
natural wonders 5 at standard and 7 at huge (Communitu places its own: 8 / 12), 18 luxury types at standard
and 26 at huge (Terra 20 / 27).

### 12.3 Archetype-dependent vs invariant

**Invariant** (the spread between script medians is small next to the pooled range; missing them means the
script is wrong, not different): ASP placement constraints (capital spacing, capital–CS 7, CS–CS 5, 3
luxuries at each capital, no bad starts), strategic density, the luxury and natural-wonder counts, the
climate-band latitudes, plains 25–39 % / desert 7–20 % / jungle 5–13 % of land, relief (hills, mountains,
flat land 60–78 %), and fresh water. **Archetype-dependent** (compare with `--archetype`, not against the
pooled range): land %, largest and second landmass share, number of landmasses and tiny islands, coast vs
deep-ocean share of the sea, coastal land %, how capitals share landmasses (isolated capitals, coastal
capitals), land per civ and with it the absolute strategic quantities per civ, snow %, marsh and forest,
atolls, oases and lakes.

### 12.4 Archetype signatures (standard size)

- **Archipelago**: land 20 %, half the sea is coast; ≈ 7 landmasses of ≥ 30 tiles, the largest only 16 % of
  land, ≈ 43 islets. Every capital coastal, 6 of 8 alone on their island, ≈ 20 land tiles within radius 3.
  Fewest rivers (9 edges / 100 land, fresh water on 15 % of land), most snow (15 %), highest bonus (34 / 100)
  and luxury (14 / 100) densities, capitals farthest apart (mean 14).
- **Communitu_79a (VP)**: own grid (79×53; huge 97×66). Land 33 %, the hilliest map (34 % hills, 4 %
  mountains), most tundra and desert, richest rivers (21.5 edges / 100 land, 31 % fresh water, 62 % of
  capitals on a river). Only ≈ 37 % coastal capitals, extra natural wonders (8 / 12), most atolls and oases,
  lowest strategic density (9.4 / 100), fully iced polar rows.
- **Continental_Drift (VP)**: grid 88×58. Land 24 %, largest landmass ≈ 39 %. The forest-and-wetland map
  (28 % forest, 5 % marsh), fewest hills (21 %), most lakes, least ice (10 % of water, 7 % at huge), many
  small islands.
- **Continents**: two big continents (≈ 52 % and ≈ 32 % of land), capitals split about 4/4, few islets (≈ 5),
  the most deep ocean (78 % of the sea), least cold terrain (tundra 9 %, snow 2.7 %).
- **Oval**: one landmass with 99.4 % of the land on a small grid (64×40), land 42 %. Short coastline (27 % of
  land coastal), the lowest share of coastal city-states (75 %), packed city-states, lowest bonus density
  (17 / 100), highest ice share of water (23 %).
- **SmallContinents**: ≈ 6 landmasses of ≥ 30 tiles, largest ≈ 37 % (but 24–63 %). Every capital coastal,
  only 12 % on a river and 25 % with fresh water, most mountains (4.4 %, 6 % at huge), ≈ 25 land tiles
  within radius 3, capital spacing hits 7 more often than elsewhere.
- **Terra (VP)**: largest grid (104×64). All civs start on the Old World (≈ 56 % of land); the New World is
  empty plus ≈ 52 islets. Highest land per civ (209) so highest strategic quantities per civ, lowest
  luxury density (7.2 / 100), city-states far from capitals (mean 18), 20 luxury types.

### 12.5 Workflow

```
python host/c5gen.py MyMap --seed 1 --png            # repeat for seeds 1..5, then --size huge
python host/metrics.py out/MyMap/MyMap_standard_1.json             # every metric for one map
python host/metrics.py compare out/MyMap/MyMap_standard_1.json --archetype Continents
python host/metrics.py compare out/MyMap/MyMap_standard_1.json --all   # include unflagged metrics
```

`compare` picks the baseline for the dump's world size (standard or huge; other sizes fall back to standard
and skip absolute counts, so duel/tiny runs flag spacing metrics by design). It marks each metric outside the
pooled p5–p95 (`LOW` / `HIGH`, or `FAR` beyond the pooled min/max), with `--archetype` also outside that
script's own p5–p95 (`arch low/high`), and ends with a one-line verdict. Archetype names: `Communitu`,
`Continental_Drift`, `Continents`, `SmallContinents`, `Terra`, `Oval`, `Archipelago`. It is advisory and
always exits 0. Read flags against §12.3: an archetype-dependent flag may be your design; an invariant flag
is a bug. To re-measure the baselines after a VP update: `python host/benchmark.py --seeds 50 --workers 10`
(then `--report` for the tables, `--recompute` after changing `host/metrics.py`).

---

## Appendix A: API and constants quick reference

### A.1 `Map` (`DLL\Lua\CvLuaMap.cpp:44-81`)

| Function | Notes |
|---|---|
| `GetGridSize()` â†’ `w, h` | |
| `GetNumPlots()`, `GetPlot(x, y)`, `GetPlotByIndex(i)` | `GetPlot` wraps x. Returns nil off-map. Index = `y*w + x`. |
| `GetPlotXY(x, y, dx, dy)`, `PlotXYWithRangeCheck(x, y, dx, dy, r)` | dx and dy are **hex-space** (axial). |
| `PlotDirection(x, y, dir)` | `dir % 6`. Returns nil off-map. |
| `PlotDistance(x1, y1, x2, y2)` | Hex distance. |
| `IsPlot(x, y)`, `IsWrapX()`, `IsWrapY()` | `IsPlot` doesn't wrap. |
| `Rand(n, "log")` | [0, n). The string is required. |
| `GetCustomOption(i)` | 1-based option and value, nil if missing. |
| `GetFractalFlags()` | `{FRAC_WRAP_X = true}` and/or `FRAC_WRAP_Y`. |
| `GetWorldSize()`, `GetClimate()`, `GetSeaLevel()` | IDs. |
| `RecalculateAreas()` | Areas, landmasses, continents and rivers. |
| `CalculateAreas()` | Areas only. |
| `GetArea(id)`, `Areas()`, `FindBiggestArea(bWater)`, `GetNumAreas()`, `GetNumLandAreas()`, `GetIndexAfterLastArea()` | Area = scan-order greedy merge by water/land in VP (§10.2.1), not a connected component. |
| `FindBiggestLandmassID(bWater)`, `GetNumTilesOfLandmass(id)` | Landmass = connected component. |
| `GetLandPlots()`, `GetNumResources(id)`, `GetNumResourcesOnLand(id)`, `GetRandomResourceQuantity(id)` | |
| `FindWater(plot, range, bFresh)` | Used by river sources. |
| `DefaultContinentStamper()`, `DoPlaceNaturalWonders()` | C++ helpers. |
| `ChangeAIMapHint(bits)`, `GetAIMapHint()` | Stored, unused by the VP DLL. |
| `MaxPlotDistance()`, `UpdateDeferredFog()` | |

### A.2 `Plot` (map-gen relevant subset; full list in `DLL\Lua\CvLuaPlot.cpp`)

- **Read:** `GetX`, `GetY`, `GetIndex`, `GetPlotType`, `GetTerrainType`, `GetFeatureType`,
  `GetResourceType([team])`, `GetNumResource`, `IsWater`, `IsLake`, `IsMountain`, `IsHills`,
  `IsFlatlands`, `IsImpassable`, `IsRiver`, `IsRiverSide`, `IsFreshWater`, `IsCoastalLand`
  (cached), `IsAdjacentToLand`, `IsAdjacentToShallowWater`, `IsAdjacentToIce`, `GetArea`, `Area`,
  `GetLandmass`, `GetContinent`, `IsAdjacentToArea(area)`, `IsAdjacentToLandmass(id)`,
  `GetLatitude`, `IsWOfRiver` / `IsNWOfRiver` / `IsNEOfRiver`, `GetRiverEFlowDirection` /
  `GetRiverSEFlowDirection` / `GetRiverSWFlowDirection`, `GetInlandCorner` (uses RNG),
  `CanHaveFeature(f)`, `CanHaveResource(r, bIgnoreLatitude, bIgnoreCiv)`,
  `CalculateYield(yield)`, `IsStartingPlot`, `IsNaturalWonder`, `GetContinentArtType`.
- **Write:** `SetPlotType(t, bRecalc, bGraphics)`, `SetTerrainType(t, bRecalc, bGraphics)`,
  `SetFeatureType(f)`, `SetResourceType(r, num)`, `SetNumResource(n)`,
  `SetWOfRiver(b, flow)` / `SetNWOfRiver(b, flow)` / `SetNEOfRiver(b, flow)`, `SetArea(id)`,
  `SetContinentArtType(n)`, `SetImprovementType(i)`, `SetStartingPlot(b)`.
- Plot objects are cached per pointer (`CvLuaScopedInstance.h:125-170`), so `==` and table keys
  work.

### A.3 `Fractal` (`DLL\Lua\CvLuaFractal.cpp`)

`Fractal.Create(w, h, grain, flagsTable, xExp, yExp)`,
`Fractal.CreateRifts(w, h, grain, flagsTable, riftsFrac, xExp, yExp)`,
`f:GetHeight(x, y)` (0-255), `f:GetHeight(pct)` (threshold),
`f:BuildRidges(seeds, flagsTable, blendRidge, blendFract)`.

### A.4 Enum values (`REPO\LuaCATS\enum\*.d.lua`, current DB)

| Enum | Values |
|---|---|
| PlotTypes | MOUNTAIN 0, HILLS 1, LAND 2, OCEAN 3 |
| TerrainTypes | GRASS 0, PLAINS 1, DESERT 2, TUNDRA 3, SNOW 4, COAST 5, OCEAN 6, (MOUNTAIN 7, HILL 8: graphical only) |
| FeatureTypes | ICE 0, JUNGLE 1, MARSH 2, OASIS 3, FLOOD_PLAINS 4, FOREST 5, FALLOUT 6, ATOLL 17; natural wonders 7-16 and 18-24 |
| DirectionTypes | NE 0, E 1, SE 2, SW 3, W 4, NW 5, NUM 6, NO 7 |
| FlowDirectionTypes | N 0, NE 1, SE 2, S 3, SW 4, NW 5, NUM 6, NO 7 |
| Regions (`GameInfoTypes.REGION_*`) | UNDEFINED 0, TUNDRA 1, JUNGLE 2, FOREST 3, DESERT 4, HILLS 5, PLAINS 6, GRASS 7, HYBRID 8, MOUNTAIN 9, SNOW 10 |
| RegionDivision (VP global) | BIGGEST_LANDMASS 1, CONTINENTAL 2, RECTANGULAR 3, RECTANGULAR_SELF_DEFINED 4 |
| ImpactLayers (VP global) | IRON 1, LUXURY 2, BONUS 3, FISH 4, CITY_STATE 5, NATURAL_WONDER 6, MARBLE 7, IVORY 8, HORSE 9, COAL 10, OIL 11, ALUMINUM 12, URANIUM 13, MAJOR 14 (NONE -1) |

### A.5 `MapmakerUtilities` helpers (`CP\MapmakerUtilities.lua`)

`Shuffle(t)`, `Plots([Shuffle])`, `GetPlayerAndTeamInfo()`, `ObtainLandmassBoundaries(areaID)`
(despite its name it takes an **area** ID; the accurately named alias is `GetAreaBoundaries`), `GetLandmassBoundaries(id)`,
`GetContinentBoundaries(id)` (each returns `{westX, southY, eastX, northY, width, height, wrapsX,
wrapsY}`), `AdjacentToSaltWater(x, y)`, `GenerateCoastalLandDataTable()`,
`GenerateNextToCoastalLandDataTables()`, `CivNeeds*Start(civType)`, `TestMembership`,
`GetShuffledCopyOfTable`, `IdentifyTableIndex`, `PrintContentsOfTable`,
`ApplyHexAdjustment(x, y, {dx, dy})`, `GetLuaPlotIndexFromCoordinates`,
`GetCoordinatesFromLuaPlotIndex`, `Plot_GetPlotsInCircle`, `Plot_GetPlotCoordinatesInCircle`,
`Plot_GetFertility`, `Plot_GetFertilityInRange`, `IsTropical`, `IsBetween`, `Constrain`,
`GetRandomMultiplier`, `GetRandomFromRangeInclusive`, `GetRandomFromList`,
`GetRandomFromWeightedList`, `GetRandomFromWeightedTable`, `GetMinMatching`.

---

## Appendix B: VP vs vanilla breaking changes

Derived from diffing `BNW\AssignStartingPlots.lua` against `VPO\AssignStartingPlots.lua` (method
names and signatures), and `BNW\FeatureGenerator.lua` / `BNW\MapGenerator.lua` against the VP/CP
copies.

| Area | Vanilla / BNW | VP | Impact on old scripts |
|---|---|---|---|
| ASP object model | `Create()` returns a literal table of copied method refs | Class with `__index` metatable (:236-251) | Class overrides work before or after Create, and new methods are visible. CP-only mode still copies. |
| Areas | Connected components | Scan-order greedy merge by water/land (`CvMap.cpp:1879`; the passability pathfinder never expands) | "Biggest area" ≠ "biggest continent". Use landmass APIs. |
| `Area:IsLake()` | Available | Not bound (`CvLuaArea.cpp:30`) | Runtime error. |
| `MeasureStartPlacementFertilityOfLandmass(id, ...)` | Takes an **area** ID | Takes a **landmass** ID. A new `MeasureStartPlacementFertilityOfArea` takes the area | Silent wrong numbers. |
| `AttemptToPlaceNaturalWonder` | `(wonder_number, row_number)` | `(kPlacementInfo, tEligibilityList)` | Calls break. |
| `CanBeThisNaturalWonderType` | `(x, y, wn, rn)` | `(x, y, kPlacementInfo)` | Calls break. |
| `GenerateNaturalWondersCandidatePlotLists` | `()` | `(target_number)` | |
| NW eligibility | `CanBe<Wonder>` methods plus XML columns | `Natural_Wonder_Placement` table plus `NWCustomEligibility` | Old `CanBe*` overrides are ignored. |
| `GetNumNaturalWondersToPlace(iWorldSize)` | n/a | New override point (:4512) | |
| `GenerateLocalVersionsOfDataFromXML` | Exists | Removed | Calls break. |
| `FixSugarJungles` | Exists | Renamed `AdjustTiles` (:7894) | Overrides ignored, calls break. |
| `ApplyHexAdjustment` | ASP method | Global function in MapmakerUtilities | `self:ApplyHexAdjustment` breaks. |
| Impact data | `self.luxuryData`, `self.strategicData`, `self.bonusData`, `self.fishData`, `self.marbleData`, `self.sheepData`, ... | `self.impactData[ImpactLayers.*]` | Reads return nil. |
| Resource plot lists | Named lists such as `self.coast_list` | `self.global_resource_plot_lists[PlotListTypes.*]` (1-based plot indices) | Reads return nil. |
| `PlaceSpecificNumberOfResources` | `impact_table_number` was a vanilla layer number | `ImpactLayers.*` enum | Must use the enum. |
| `AssignCityStatesToRegionsOrToUninhabited(args)` | Took args | No args. Counts via `GetNumCityStatesPerRegion` and `GetNumCityStatesInUninhabitedRegion` | Override those instead. |
| `ChopIntoThreeRegions(..., chopPercent)` | 4 args | 3 args | |
| `FindStart(region)` | `(region_number)` | `(iRegionID, bForcedCoastal)` | |
| Luxury target hooks | `GetDisabledLuxuriesTargetNumber`, `GetCityStateLuxuriesTargetNumber` used | Marked UNUSED (:6008-6037). `GetRandomLuxuriesTargetNumber` and `GetWorldLuxuryTargetNumbers` are used | Old overrides are inert. |
| Start bias | Greedy assignment | Optimal assignment (Kuhn-Munkres) over a cost matrix (:3686) | Better matches. Same DB tables. |
| `GenerateRegions` fallbacks | None | Continental â†’ Biggest Landmass or Rectangular (:1614-1732) | Behaviour changes on fragmented maps. |
| Resource settings | `self.resource_setting` | `resDensity`, `resSize`, `bonusDensity`, `luxuryDensity`, `legStart`, `resBalance` (`comm` split args) | |
| `MapGenerator.lua` | Defines `Plots()` and `Shuffle()` | Moved to `MapmakerUtilities`. Adds the `PreMapGenScript` hook | Same API through includes. |
| `FeatureGenerator:AddFeatures()` | Keeps coastal mountains unless arg == false | Removes them unless arg is truthy | Fewer sea cliffs. |
| `FeatureGenerator:AdjustTerrainTypes` | All jungle terrain â†’ plains | 50 % | More grassland jungle. |
| `FeatureGenerator:AddAtolls` | Biggest ocean area | Biggest ocean landmass | |
| `Map.ChangeAIMapHint` | Read by the vanilla AI **(unverified)** | Unused by the VP DLL | No effect. |
