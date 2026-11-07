# Engine API spec for the c5maps fake client

This is the full list of engine globals, enums and object methods that Civ V / Vox Populi mapscripts and their support libraries actually call. Semantics are taken from the VP DLL source. For which file uses which symbol, see `api-usage-matrix.md`.

* **Provider (source of truth):** `C:\Users\Art\Documents\GitHub\Community-Patch-DLL\CvGameCoreDLL_Expansion2\` (paths below are relative to that folder unless noted). Line numbers refer to the checkout read on 2026-11-07.
* **Consumers scanned:** 123 Lua files. These are the base, Expansion and Expansion2 `Gameplay\Lua` folders; the CP/VP overrides (`MapGenerator`, `AssignStartingPlots`, `MapmakerUtilities`, `FLuaVector`, `FeatureGenerator`, `NaturalWondersCustomMethods`, `VPUI_core`); every `*.lua` mapscript in `Assets\Maps`, `DLC\Expansion\Maps`, `DLC\DLC_SP_Maps*\Maps`, `(1) Community Patch\Mapscripts`, `(2) Vox Populi\Mapscripts` (+`EMP`); and the 3 user scripts in `My Games\...\Maps`.

**Priority tags**

| Tag | Meaning |
|---|---|
| **P0** | Needed by the code that actually runs for the 3 user scripts: CP `MapGenerator`, VP `FeatureGenerator`, base `TerrainGenerator`, `FractalWorld`, `IslandMaker`, CP `FLuaVector`, `Communitu_79a`, `Continental_Drift`, `Tectonic v6 - VI`. Also anything executed at **include time** by the libraries those load (VP ASP / CP MMU / VPUI_core top-level code). |
| **P1** | Needed by VP `AssignStartingPlots` (ASP) and what it pulls in: CP `MapmakerUtilities` (MMU), VP `NaturalWondersCustomMethods` (NWC), CP `VPUI_core`. |
| **P2** | Only other effective mapscripts and libraries need it (`MultilayeredFractal`, `ContinentsWorld`, `Pangaea*`, VP/base/DLC scripts). |
| **P3** | Seen only in dead or overridden files, or on unreachable code paths. A stub is enough (it may error with a clear message). |

---

## 0. Which files actually run (VFS resolution)

`include("X")` finds the last `X.lua` in the search order given in DESIGN.md. This is what that resolves to today:

| include name | Effective file | Notes |
|---|---|---|
| `MapGenerator` | `(1) Community Patch\Core Files\Overrides\Includes\MapGenerator.lua` | Includes `AssignStartingPlots` at load time. **No longer defines `Plots()`/`Shuffle()`**; those now live in CP MMU. |
| `AssignStartingPlots` | `(2) Vox Populi\Core Files\Overrides\AssignStartingPlots.lua` | Includes `MapmakerUtilities`, `NaturalWondersCustomMethods` and `VPUI_core`, in that order. |
| `MapmakerUtilities` | `(1) Community Patch\...\Includes\MapmakerUtilities.lua` | Defines `Plots(Sort)`, `Shuffle(t)`, `GetPlayerAndTeamInfo`, `Plot_GetFertility`, `Plot_GetPlotsInCircle` (uses `coroutine.wrap`). |
| `NaturalWondersCustomMethods` | `(2) Vox Populi\Core Files\Overrides\NaturalWondersCustomMethods.lua` | |
| `VPUI_core` | `(1) Community Patch\Core Files\VPUI\VPUI_core.lua` | Runs DB/GameInfo/Game code **at include time** (see §11.5). |
| `FeatureGenerator` | `(2) Vox Populi\Core Files\Overrides\FeatureGenerator.lua` | |
| `FLuaVector` | `(1) Community Patch\...\Includes\FLuaVector.lua` | Pure Lua. Reads `MapModData.FLuaVector` if present. |
| `TerrainGenerator`, `FractalWorld`, `MultilayeredFractal`, `IslandMaker`, `ContinentsWorld`, `PangaeaWorld`, `FourContinentsWorld`, `HintedWorld`, `MapUtilities` | base `Assets\Gameplay\Lua\*.lua` | Not overridden. |
| `WorldBuilderRandomItems` | `DLC\Expansion2\Gameplay\Lua` | Only used for WB maps (`.Civ5Map`), never by mapscripts → P3. |

`include` forms seen: `include("Name")`, `include("Name.lua")`, and a regex form with a second argument `true` (`GameCalendarUtilities_Overrides_%w+.lua`, P3). The CP `MapGenerator.GenerateMap` also includes every file listed by `Modding.GetActivatedModEntryPoints("PreMapGenScript")`, by bare file name.

---

## 1. Runtime model: globals, objects, argument coercion

### 1.1 Globals present before the mapscript runs (P0)

`Map`, `Fractal`, `Game`, `PreGame` (P3 only), `GameInfo`, `GameInfoTypes`, `GameDefines`, `Players`, `Teams` (not called by consumers but should exist), `Locale`, `DB`, `Modding`, `MapModData` (see §11.6), `LuaTypes` (created lazily by the object system), `include`, `print`, plus the enum tables in §13.

`ContextPtr`, `UI`, `Events`, `Controls`: `VPUI_core` guards `ContextPtr` with `if ... and ContextPtr`, so **leave `ContextPtr` nil**. `Events.SerialEventHexHighlight` is referenced by Communitu but never reached during generation, so stub it (P3).

`WorldSizeTypes` is **not** registered by the DLL (it isn't in `Lua/CvLuaEnums.cpp`); the exe provides it. Fill it from the `Worlds` table (Type→ID). The values match `CvEnums.h:1196` (DUEL=0 … HUGE=5).

### 1.2 Object model for Plot / Area / Player / Team (all P0)

`CvLuaScopedInstance::Push` (`Lua/CvLuaScopedInstance.h`, `Push`):

* Each C++ object becomes a **plain Lua table** `{__instance = <lightuserdata>}`.
* Its metatable is the per-type method table `LuaTypes[<TypeName>]`, whose `__index` points to itself.
* Instances are cached in `LuaTypes[T].__instances` (weak values, `__mode="v"`). So **the same plot always gives back the same table** while it is referenced. `type(plot) == "table"`.
* Identity matters: CP `MapGenerator.CanPlaceGoodyAt` does `if otherPlot == playerStartPlot then`. **Plot objects must be canonical, one Lua table per plot index**, or carry an `__eq`.
* `Push(nil)` pushes `nil`. That is how "no plot" comes back from `GetPlotXY`, `PlotDirection`, `PlotXYWithRangeCheck` and `GetInlandCorner`.
* Calling a method with a non-instance `self` raises a Lua error (`GetInstance`, `bErrorOnFail`).

For plot methods, `CHECK_PLOT_VALID` (`Lua/CvLuaPlot.cpp:34`) makes the method **return nothing** if the instance pointer is not a valid map plot.

### 1.3 Argument and return coercion (applies everywhere)

* **Integers** come from `lua_tointeger`. `nil` or a non-number gives **0**. Examples: `Map.GetPlot(nil,nil)` → plot (0,0). `plot:SetPlotType(nil)` → `PLOT_MOUNTAIN` (0). `plot:SetFeatureType(nil)` → `FEATURE_ICE` (0). `plot:SetTerrainType(nil)` → `TERRAIN_GRASS`.
* **Float to integer conversion** (`lua_tointeger` / `lua_number2integer`): stock Lua 5.1 on MSVC/x86 uses `fld/fistp`, which **rounds to nearest, ties to even**, not truncation. Havok Script is 32-bit x86 and almost certainly matches. lupa x64 and LuaJIT truncate.
  * The shim is pure Lua, so implement `toint(x)` explicitly as round-half-even.
  * This affects for example `Tectonic`/`Continental_Drift` `GetMapInitData`, which returns fractional `Width`/`Height`, and any script that passes `iW/2`.
  * This is unverified for Havok; see Ambiguity A3.
* **Booleans** come from `lua_toboolean`. Only `nil`/`false` are false, so `0` is **true**.
* **Methods wrapped with `BasicLuaMethod`** (`CvGameCoreDLLUtil/include/CvLuaMethodWrapper.h`, `CvLuaArgTemplates.h`): every C++ parameter is read positionally with `lua_tointeger`/`lua_toboolean`. **C++ default arguments are NOT applied; a missing argument becomes 0/false.** This changes behaviour in several places:
  * `plot:IsLake()`, `plot:IsFreshWater()`, `plot:IsAdjacentToLand()` call the C++ function with `bUseCachedValue=false`, so they **recompute**.
  * `plot:SetResourceType(id)` with no quantity sets quantity **0**. The C++ also gets `bIgnoreMinorCivRestrictions=false`.
  * `plot:SetImprovementType(id)` passes `eBuilder = 0` (player 0).
  * `plot:SetPlotType(t)` passes `bRecalculate=false, bRebuildGraphics=false, bEraseUnitsIfWater=false`.
  * `plot:IsNaturalWonder()` passes `orPseudoNatural=false`.
* `luaL_check*` arguments raise a Lua error when missing or of the wrong type. This applies to `Map.Rand(n, "log")`: **both** arguments are required, but a number is accepted for the string. It also applies to `Map.GetCustomOption`, `Game.GetCustomOption` and `Map.FindWater(range)`.
* **"Returns nothing"** (`return 0`) and **"returns nil"** are both `nil` in Lua. Several functions return *nothing* rather than -1 for "not found". This is noted per function.

---

## 2. Driver protocol (P0)

Source: `CvMapGenerator.cpp`, `CvGame.cpp:521-603`, `CvGame.cpp:190-202`.

1. **RNG seeding happens before map init.** `CvGame::init` → `m_mapRand.init(CvPreGame::mapRandomSeed() % 73637381)` (`CvGame.cpp:201`). The harness `--seed` stands in for `mapRandomSeed`. Nothing consumes map RNG before the script loads.
2. **Load the script.** `CvMapGenerator` constructor (`CvMapGenerator.cpp:32`) runs `CreateLuaThread("Map Script")` and `LoadFile(mapscript)`. Top-level code runs now, including every `include` chain (MapGenerator → ASP → MMU, NWC, VPUI_core; FeatureGenerator; TerrainGenerator; ...). Include-time code already needs `GameInfo`, `GameDefines`, `DB.CreateQuery`, `Game.GetNumYieldTypes` and `Locale` (§11.5).
3. **Call `GetMapInitData(worldSize)`** (`CvMapGenerator.cpp:48-149`).
   * `worldSize` is the `Worlds.ID` of `PreGame.worldSize`.
   * The defaults are `Width=Worlds.GridWidth`, `Height=Worlds.GridHeight`, `WrapX=true`, `WrapY=false`, `TopLatitude=90`, `BottomLatitude=-90` (`CvGameCoreDLLUtil/include/CvStructs.h:147`).
   * If the global function exists **and returns a table**, each non-nil field overrides its default. `Width`/`Height`/`*Latitude` go through `lua_tointeger` (round-half-even, §1.3) and `WrapX`/`WrapY` through `lua_toboolean`.
   * If the function is missing or returns a non-table, `kMap.init()` uses the world-size grid. In that case latitudes are **not** set from init data: the `reset` in `CvMap.cpp:837-874` keeps the previous values, 0/0 on a fresh `CvMap`, clamped to ±90.
   * **Map RNG can be consumed here.** Communitu calls `Map.GetCustomOption`; Tectonic/Continental Drift call `Map.Rand` for "random" options.
   * So `Map.Rand` and `Map.GetCustomOption` must work before the grid exists. Calls that need the grid (`GetPlot` etc.) are undefined at this point.
4. **`CvMap::init`** (`CvMap.cpp:699`). Every plot is reset (`CvPlot::reset`, `CvPlot.cpp:163`):
   * `PLOT_OCEAN`, **`NO_TERRAIN` (-1)**, `NO_FEATURE`, `NO_RESOURCE`, `NO_IMPROVEMENT`
   * area/landmass/continent = -1, all river flags false, flows `NO_FLOWDIRECTION`
   * `m_bPotentialCityWork=false`, all cached water flags false
   * `getLandPlots()=0`, no areas
   * neighbour table precomputed (§3.3)
5. **Call global `GenerateMap()`** (`CvMapGenerator.cpp:277`). If it is missing, the engine raises `luaL_error "Cannot find map script entry point GenerateMap()"`. Afterwards `lua_gc(COLLECT)` runs.
6. **Call `GetGameInitialItemsOverrides()`** if present (`CvMapGenerator.cpp:152`). It returns a table whose keys `GrantInitialFreeTechsPerTeam`, `GrantInitialGoldPerPlayer`, `GrantInitialCulturePerPlayer`, `ClearResearchQueuePerPlayer` and `GrantInitialUnitsPerPlayer` each map {id → bool}. The harness should just log it.
7. **Engine post-processing that changes the map** (`CvGame.cpp:599-603`):
   * `CvWorldBuilderMapLoader::ValidateCoast()` (`CvWorldBuilderMapLoader.cpp:1779`): for every plot in y-then-x order, if its terrain is a water terrain other than COAST and `isAdjacentToLand(false)` → `setTerrainType(COAST)`. The dump should reflect this.
   * Then `updateAdjacency()` (cache bookkeeping only).

**Map script options.**
* `Map.GetCustomOption(n)` (`Lua/CvLuaMap.cpp:447`) reads its argument with `luaL_checkstring`, so the number `n` becomes the string `"n"`. It then calls `CvPreGame::GetMapOption` (`CvPreGame.cpp:1490`):
  * It searches the options set by the front-end, keyed by `OptionID` string.
  * If that fails, it falls back to `MapScriptOptions.DefaultValue WHERE FileName=<script> AND OptionID=n`.
  * If both fail it **returns nothing** (nil).
* The front-end (`Assets\UI\FrontEnd\GameSetup\AdvancedSetup.lua:122`) stores `PreGame.SetMapOption(option.ID, value)`. `option.ID` is the **1-based position in `GetMapScriptInfo().CustomOptions`**; holes are skipped (Tectonic's option 1 is `nil` and its DB IDs start at "2"). The value is the **1-based index into `Values`**.
* Headless rule: build `{[tostring(i)] = opt.DefaultValue}` for each non-nil `CustomOptions[i]`, then apply CLI overrides `--option i=v`. Unknown `i` returns nil.
* Values meaning "Random" are resolved by the script itself, using `Map.Rand`.

**`Map.GetWorldSize / GetClimate / GetSeaLevel`** read `CvPreGame::worldSize()/climate()/seaLevel()` (`CvMap.cpp:1545-1575`) and return `Worlds/Climates/SeaLevels.ID`. Headless defaults: CLI size, `CLIMATE_TEMPERATE` (0), `SEALEVEL_MEDIUM` (1).

---

## 3. Hex geometry and indexing (P0)

### 3.1 Coordinates

* The grid is `W × H` and the plot index is **`i = y*W + x`** (`CvMap.h:247`). `plotX(i)=i%W` and `plotY(i)=i/W` (`CvMap.cpp:1482-1493`).
* **y=0 is the south row. Odd rows are shifted half a hex EAST ("odd-r").**
* Hex space: `hx = x - floor(y/2)`, which is `xToHexspaceX` (`CvGameCoreUtils.h:100`). The C code `(y>=0)?(y>>1):((y-1)/2)` equals `floor(y/2)` for all integer `y`. The inverse is `x = hx + floor(y/2)` (`hexspaceXToX`, `:106`).
* `coordRange(c, range, wrap)` (`CvMap.h:164`):
  * With wrap: `c<0 → range + (c % range)` using **C truncating `%`**; `c>=range → c % range`. Otherwise `c` is returned unchanged.
  * Quirk: with wrap, `c = -range` (or any negative multiple of `range`) maps to `range`, which is out of bounds, so `plot()` returns nil. Port this literally: in Lua, `math.fmod(c, range)` gives the C sign semantics.
* `CvMap::plot(x,y)` (`CvMap.h:315`): `INVALID_PLOT_COORD` (= `-INT_MAX`) → nil. Otherwise apply `coordRange` to x (wrapX) and y (wrapY), then `isPlot` (0≤x<W, 0≤y<H) → plot or nil.

### 3.2 Directions (exact enum order, `CvGameCoreDLLUtil/include/CvEnums.h:632`)

| Name | Value | Hex delta (dhx, dy) (`CvGlobals.cpp:3058-3080`) | Even row y: (dx,dy) | Odd row y: (dx,dy) |
|---|---|---|---|---|
| DIRECTION_NORTHEAST | 0 | (0,+1) | (0,+1) | (+1,+1) |
| DIRECTION_EAST | 1 | (+1,0) | (+1,0) | (+1,0) |
| DIRECTION_SOUTHEAST | 2 | (+1,-1) | (0,-1) | (+1,-1) |
| DIRECTION_SOUTHWEST | 3 | (0,-1) | (-1,-1) | (0,-1) |
| DIRECTION_WEST | 4 | (-1,0) | (-1,0) | (-1,0) |
| DIRECTION_NORTHWEST | 5 | (-1,+1) | (-1,+1) | (0,+1) |
| NUM_DIRECTION_TYPES | 6 | (0,0) "DUMMY" | self | self |
| NO_DIRECTION | 7 | (0,0) | self | self |

The DLL's neighbour table has 8 slots per plot (`CvMap.cpp:738-775`, `InitPlots`): for slot `d` it computes `hx+dhx[d]`, `y+dy[d]`, converts back, applies `coordRange` to x and y, and stores `isPlot ? plot : NULL`. Slots 6 and 7 are the plot itself. `updateWaterFlags` uses `NUM_DIRECTION_TYPES+1` slots on purpose, to include the plot itself.

### 3.3 Distance and related helpers

* **`plotDistance(x1,y1,x2,y2)`** (`CvGameCoreUtils.cpp:454`), cube distance with wrap:
  ```
  hx1=x1-floor(y1/2); hx2=x2-floor(y2/2); z1=-hx1-y1; z2=-hx2-y2
  dx=dxWrap(hx2-hx1); dy=dyWrap(y2-y1); dz=dxWrap(z2-z1)
  return (|dx|+|dy|+|dz|) / 2      -- C integer division
  ```
  * `dxWrap(d)` = `wrapCoordDifference(d, W, wrapX)` (`CvGameCoreUtils.h:79`): when wrapping, `d > W>>1 → d-W`, `d < -(W>>1) → d+W`. `dyWrap` is the same with `H`/`wrapY`.
  * Note `dz` uses the X wrap. The source says "todo: fixme. wrapping does not work correctly for large distances": it can return an odd sum divided by 2 near the seam. Port literally.
  * Inputs are **not** range-checked.
* **`hexDistance(dhx, dy)`** (`CvGameCoreUtils.h:111`): if the signs match → `|dhx|+|dy|`, else `max(|dhx|,|dy|)`. `0` counts as non-negative.
* **`plotXY(x,y,dhx,dy)`** (`CvGameCoreUtils.cpp:410`): returns nil for `INVALID_PLOT_COORD`. Otherwise `hx = xToHexspaceX(x,y)+dhx`, `y' = y+dy`, `x' = hexspaceXToX(hx, y')`, then `CvMap::plot(x',y')` (wraps). **`dhx` is a hex-space offset, not an offset-grid offset.**
* **`plotXYWithRangeCheck(x,y,dhx,dy,r)`** (`:428`): returns nil if `hexDistance(dhx,dy) > r`, else `plotXY(...)`.
* **`directionXY(from,to)`** (`:492`), used internally by `isRiverSide` and `AreaValid`: with wrapped `dhx`,`dy`:
  * `dy>0`: NE if `dhx>=0` else NW
  * `dy==0`: E if `dhx>0`, NO_DIRECTION if 0, else W
  * `dy<0`: SE if `dhx>0` else SW
* `iterateRingPlots(x,y,i)` (`CvGameCoreUtils.cpp:553`) uses the hex offsets in `CvGlobals.cpp:3084`. Ring 1 (i=1..6) is in direction order NE,E,SE,SW,W,NW. `MAX_CITY_PLOTS = 91` (radius 5, `CvDefines.h:19`).

---

## 4. Map RNG and RNG-consuming engine calls (P0)

**`Map.Rand(max, log)`** (`Lua/CvLuaMap.cpp:363`)
* Implementation: `luaL_checkinteger(1)`, `luaL_checkstring(2)`, then `CvGame::getMapRandNum` (`CvGame.cpp:10066`):
  * `max > 0` → `mapRand.get(max)`
  * `max <= 0` → `-mapRand.get(-max)`
* `CvRandom::get(n)` (`CvRandom.cpp:94-142`, constants `:18-20`):
  ```
  if n < 2: return 0                      -- does NOT advance the state
  seed = (1103515245 * seed + 12345) mod 2^64   -- seed is unsigned 64-bit
  r = (((seed >> 16) & 0xFFFFFFFF) * n) / 2^32   -- exact integer math, result in [0, n-1]
  ```
* Initial `seed = mapRandomSeed % 73637381` (`CvRandom::reset` assigns it; a fresh `CvRandom` starts at 0).
* **The 64-bit state needs exact multi-precision arithmetic in pure Lua.** Use 16-bit limbs. The product `(32-bit) × n` also exceeds 2^53. Map.Rand results are integers in `[0, max-1]`.

**Who else draws from the map RNG** (they all share the same stream, so ordering must be exact):
* `Fractal.Create`, `Fractal.CreateRifts` and `fractal:BuildRidges` use `GC.getGame().getMapRand()` (`Lua/CvLuaFractal.cpp:99,147,168`). See the separate fractal port.
* `plot:GetInlandCorner()` calls `shuffleArray({0,1,2,3}, mapRand)` (`CvPlot.cpp:6450`, `CvGameCoreUtils.h:295`): `for i=0..3: j = get(4-i)+i; swap`. That is 3 state advances; the last `get(1)` doesn't advance.
* `Map.DefaultContinentStamper()` shuffles 4 art styles the same way (`CvMap.cpp:2478`).
* `Map.GetRandomResourceQuantity` uses **`getJonRandNum`, the game RNG, not the map RNG** (`CvMap.cpp:1602`). P3.

---

## 5. `Map.*` catalog (`Lua/CvLuaMap.cpp`, singleton over `CvMap`)

| Symbol (line) | Signature → returns | Semantics / edge cases | Pri |
|---|---|---|---|
| `Map.GetGridSize()` (180) | → `W, H` | Two integers. | P0 |
| `Map.GetNumPlots()` (191) | → int | `W*H`. | P0 |
| `Map.GetPlot(x, y)` (215) | → Plot \| *nothing* | `CvMap::plot`: wraps x/y per map flags (§3.1). Out of range on a non-wrapped axis → nothing. `nil` args become 0. | P0 |
| `Map.GetPlotByIndex(i)` (230) | → Plot \| *nothing* | `0 <= i < W*H`, no wrapping. | P0 |
| `Map.PlotDirection(x, y, dir)` (411) | → Plot \| nil | `dir = abs(dir % 6)` with C `%`, so `NO_DIRECTION`(7)→1=**EAST**, 6→0, -1→1. Returns nil if x or y is `INVALID_PLOT_COORD`. x and y are `coordRange`'d, then the neighbour table is read with no further check. **A y outside [0,H) on a non-wrapped map reads out of bounds in C++ (garbage or crash).** The shim should raise an error naming the call. | P0 |
| `Map.PlotXYWithRangeCheck(x, y, dhx, dy, r)` (399) | → Plot \| nil | §3.3. **`dhx` is in hex space.** | P0 |
| `Map.GetPlotXY(x,y,dx,dy)` / `(dx,dy)` (245) | → Plot \| nil | `plotXY`. With exactly 2 args it means x=y=0. | P3 |
| `Map.PlotDistance(x1,y1,x2,y2)` (386) | → int | §3.3. | P0 |
| `Map.MaxPlotDistance()` (356) | → int | `max(1, plotDistance(0,0, wrapX?W/2:W-1, wrapY?H/2:H-1))` (`CvMap.cpp:1496`). | P1 |
| `Map.IsWrapX()` / `IsWrapY()` (344) | → bool | Also called as `Map:IsWrapX()` (the extra arg is ignored). | P0 / P1 |
| `Map.IsPlot(x,y)` (333) | → bool | No wrapping, raw bounds check. Not used by consumers. | P3 |
| `Map.Rand(max, log)` (363) | → int | §4. | P0 |
| `Map.GetWorldSize()` (327) | → int | `PreGame.worldSize`. | P0 |
| `Map.GetClimate()` (155) / `Map.GetSeaLevel()` (321) | → int | `PreGame` (§2). | P3 / P2 |
| `Map.GetFractalFlags()` (161) | → table | Flags from map wrap: `{FRAC_WRAP_X=true}` if wrapX, `{FRAC_WRAP_Y=true}` if wrapY. A key is absent when its flag is false. | P0 |
| `Map.GetCustomOption(n)` (447) | → int \| *nothing* | §2. | P0 |
| `Map.RecalculateAreas()` (379) | — | `calculateAreas(); recalculateLandmasses(); recalculateContinents(); RecalculateRivers()` (`CvMap.cpp:1757`). See §8. | P0 |
| `Map.CalculateAreas()` (373) | — | **Areas only** (`calculateAreas`). Landmasses, continents and water-flag caches are **not** refreshed. CP `AddLakes` relies on this (§8.5). | P0 |
| `Map.GetArea(id)` (271) | → Area \| *nothing* | `m_areas.Get(id)`. Unknown or -1 → nothing. | P0 |
| `Map.GetNumAreas()` (298) / `GetNumLandAreas()` (305) | → int | Count of areas / of non-water areas. | P3 |
| `Map.Areas()` (84) | → iterator | Stateless closure `(nil, idx)`: idx nil → first area, else next. Yields `idx, area`. | P3 |
| `Map.FindBiggestArea(bWater)` (115) | → Area \| *nothing* | Iterates areas **in container order**; first strictly-greatest `getNumTiles` among areas with `isWater()==bWater`. A missing argument means `false` (land). | P0 |
| `Map.FindBiggestLandmassID(bWater)` (129) | → int \| *nothing* | Same rule over landmasses (`CvMap.cpp:1400`). | P0 |
| `Map.GetNumTilesOfLandmass(id)` (480) | → int | `getLandmassById(id)->getNumTiles()`. **An invalid id dereferences NULL (crash).** The shim should raise an error. | P0 |
| `Map.GetLandPlots()` (291) | → int | Running counter, changed only by `setPlotType` on water↔land transitions (`CvPlot.cpp:7280`). Starts at 0. | P0 |
| `Map.FindWater(plot, range, bFresh)` (144) | → bool | `CvMap.cpp:1444`. Loops `dx=-r..r` (outer), `dy=-r..r` (inner) over `plotXYWithRangeCheck(x,y,dx,dy,r)` (hex offsets, includes the plot itself). If bFresh: true when any `p:isFreshWater(false)` (recompute, §7.4). Else true when any `p:isWater()`. `range` is `luaL_checkint`. Callers pass `RIVER_SOURCE_MIN_RIVER_RANGE/2` (=2.0, a float, which is fine). | P0 |
| `Map.ChangeAIMapHint(n)` (467) / `GetAIMapHint()` | — / int | `m_iAIMapHints += n` (starts at 0). Only stored. | P0 (trivial) |
| `Map.DefaultContinentStamper()` (433) | — | §8.6. | P0 |
| `Map.DoPlaceNaturalWonders()` (440) | — | C++ NW placer (`CvMap.cpp:2051`). Not called by effective consumers (VP ASP places NWs in Lua). | P3 |
| `Map.GetRandomResourceQuantity(r)` (312) | → int | Game RNG; picks among `Resource_QuantityTypes`. | P3 |
| `Map.GetNumResources(r)` / `GetNumResourcesOnLand(r)` (197) | → int | Counters updated by `setResourceType`/`setPlotType`. | P3 |
| `Map.UpdateDeferredFog()`, `Map.GetIndexAfterLastArea()` | | Not used. | P3 |

---

## 6. `Plot` methods (`Lua/CvLuaPlot.cpp`, object = `CvPlot`)

All of these return nothing if `CHECK_PLOT_VALID` fails (§1.2).

### 6.1 Getters

| Method (line) | Returns | Semantics | Pri |
|---|---|---|---|
| `GetX()` (1196), `GetY()` (1202) | int | | P0 |
| `GetIndex()` (1208) | int | `y*W+x`. | P0 |
| `GetPlotType()` (1476) | int | `PlotTypes`, 0..3. Initial value is `PLOT_OCEAN`. | P0 |
| `GetTerrainType()` (415) | int | **`-1` (`NO_TERRAIN`) until something sets terrain.** `SetPlotType(OCEAN)` on an untouched plot is a no-op and leaves -1 (§6.3). | P0 |
| `GetFeatureType()` (405) | int | -1 = none. | P0 |
| `GetResourceType([team])` (1520) | int | With no arg (`lua_gettop<2`) → raw resource. With a team arg, reveal rules apply (never needed). | P0 |
| `GetNumResource()` (1559) | int | Quantity. | P1 |
| `GetImprovementType()` (1597) | int | -1 = none. | P0 |
| `GetRouteType()` (1615) | int | Always -1 during mapgen. Communitu path code only (unreachable). | P3 |
| `GetTeam()` (512) / `IsCity()` (1014) / `IsRevealed(team, [debug])` (1959) | -1 / false / false | Communitu route helpers only (unreachable). Return constants. | P3 |
| `IsWater()` (447) | bool | `plotType == PLOT_OCEAN` (`CvPlot.h:431`). **Terrain is ignored.** | P0 |
| `IsHills()` (1488) | bool | `plotType == PLOT_HILLS`. | P0 |
| `IsMountain()` (1507) | bool | `terrain == TERRAIN_MOUNTAIN` **or** `plotType == PLOT_MOUNTAIN` (`CvPlot.h:447`). | P0 |
| `IsFlatlands()` (1482) | bool | `plotType == PLOT_LAND` (`CvPlot.cpp:7219`). | P2 |
| `IsImpassable([team])` (1185) | bool | No team → cached `m_bIsImpassable` (§6.4). | P0 |
| `IsLake()` (603) | bool | Recomputes the water flags (§7.4), then returns `m_bIsLake` = the plot is water **and its landmass** is water with fewer than `MIN_WATER_SIZE_FOR_OCEAN`(10) tiles (`CvMap.cpp:122`). It uses the **landmass**, not the area. Stale landmass IDs matter (§8.5). | P0 |
| `IsFreshWater()` (609) | bool | Recompute, §7.4. | P0 |
| `IsAdjacentToLand()` (569) | bool | Recompute. **For a land plot this is always false** (it is defined only for water plots, `CvPlot.cpp:1239-1256`). | P0 |
| `IsCoastalLand()` (587) | bool | `isCoastalLand(-1, bUseCachedValue=TRUE, false)` → **cached** `m_bIsAdjacentToWater` (§7.4): a land plot with ≥1 adjacent water plot whose feature is not ICE. **No refresh.** Water plots always give false. The cache is refreshed only by recalc / `IsLake` / `IsFreshWater` / `IsAdjacentToLand` / `FindWater(fresh)` on that plot. | P0 |
| `IsAdjacentToShallowWater()` (575) | bool | Any of the 6 neighbours has `terrain == SHALLOW_WATER_TERRAIN` (coast, 5). The plot type is not checked (`CvPlot.cpp:969`). | P0 |
| `IsAdjacentToArea(area)` (539) | bool | **The argument is an Area object.** True if any neighbour has `getArea()==area:GetID()` (`CvPlot.cpp:834`). | P1 |
| `IsAdjacentToLandmass(id)` (551) | bool | **The argument is a landmass id (int).** True if any neighbour's landmass equals it. | P1 |
| `IsRiver()` (438) | bool | `m_iRiverCrossingCount > 0` (§7). | P0 |
| `IsRiverSide()` (616) | bool | True if any *existing* neighbour has the crossing bit for `directionXY(this, n)` set (`CvPlot.cpp:1369`). The only difference from `IsRiver` is that crossings toward a missing neighbour (map edge) are ignored. | P0 |
| `IsWOfRiver()`, `IsNWOfRiver()`, `IsNEOfRiver()` (1396/1408/1384) | bool | Raw edge flags (§7). | P0 |
| `GetRiverEFlowDirection()`, `GetRiverSEFlowDirection()`, `GetRiverSWFlowDirection()` (1420/1426/1432) | int | `FlowDirectionTypes`. 7 = `NO_FLOWDIRECTION` (initial value). | P0 |
| `GetArea()` (1249) | int | -1 if unassigned. | P0 |
| `Area()` (1232) | Area \| nil | nil if the area is -1 or deleted. | P0 |
| `GetLandmass()` (1261) | int | -1 if unassigned. | P0 |
| `IsStartingPlot()` (1372) | bool | `m_bStartingPlot`. | P0 |
| `IsNaturalWonder()` (`LUAAPIIMPL`, 2467) | bool | `IsNaturalWonder(false)`: the feature has `NaturalWonder=1` (pseudo-NWs excluded, `CvPlot.cpp:7699`). | P1 |
| `GetInlandCorner()` (1305) | Plot \| nil | **Consumes map RNG** (§4). Candidates in shuffled order: 0=self, 1=NE, 2=NW, 3=W neighbour. Returns the first non-nil candidate `c` for which `hasCoastAtSECorner(c)` is false. That function is true when `c` is water, or its E neighbour is water, or its SE neighbour is water (`CvPlot.cpp:6450-6500`). | P0 |
| `CanHaveFeature(f)` (393) | bool | §6.5. | P0 |
| `CanHaveImprovement(imp, [player=-1], [checkAdj=false], [testXAdj=false])` (693) | bool | `CvPlot.cpp:2583`. Needed for goody huts (CP `CanPlaceGoodyAt` passes `player=-1`). Port the no-player path, covering: feature NW/NoImprovement, `isValidMovePlot(NO_PLAYER)` (not impassable and not ice), `Improvement.Water == isWater`, resource rules, `Improvement_ValidTerrains/Features`, `HillsMakesValid`, `NoFreshWater`, `RequiresFlatlands`, adjacency (`NoTwoAdjacent`, `RequiresXAdjacentLand`), etc. Only `IMPROVEMENT_GOODY_HUT` is asked. | P0 |
| `CanHaveResource(r, [ignoreLat], [ignoreCiv])` (671) | bool | `CvPlot.cpp:2434`. Only WB scripts. | P3 |
| `CalculateYield(yield, [display=false])` (1783) | int | §6.6. CP MMU `Plot_GetFertility` → VP ASP (CS and NW site scoring). | P1 |

### 6.2 Setters and their side effects (port these exactly)

**`SetPlotType(t, [bRecalc=false], [bRebuildGfx=false])`** (1514 → `CvPlot::setPlotType`, `CvPlot.cpp:7225-7443`)
1. If `t == current` → **no-op**. If `t` is outside 0..3 → no-op.
2. If the old or new type is `PLOT_OCEAN` → `erase()` (`CvPlot.cpp:294`). This clears **resource (qty 0), improvement, route, feature**, and this plot's own **three river flags** (`setNEOfRiver/NWOfRiver/WOfRiver(false, NO_FLOWDIRECTION)`), with all their side effects (§7.2).
   * Land→land changes (LAND↔HILLS↔MOUNTAIN) keep everything.
3. Set the type. Then `updateImpassable()` (§6.4).
4. **Terrain auto-fix:** if `terrain == NO_TERRAIN` or `Terrains[terrain].Water != isWater()`:
   * Plot is now water: `setTerrainType(isAdjacentToLand(false) ? SHALLOW_WATER_TERRAIN(5) : DEEP_WATER_TERRAIN(6))`. `isAdjacentToLand(false)` recomputes from current neighbours.
   * Plot is now land: `setTerrainType(LAND_TERRAIN)` (`Defines.LAND_TERRAIN` = 0 = GRASS).
   * Consequence: **`PLOT_MOUNTAIN` never sets `TERRAIN_MOUNTAIN`**, and LAND↔HILLS never touch terrain.
5. If water-ness changed:
   * `Map.GetLandPlots() += (land ? 1 : -1)`. Resource-on-land counters are updated.
   * If `bRecalc` and the plot became land: each deep-water neighbour that `isAdjacentToLand(false)` becomes coast.
   * `updatePotentialCityWork()` runs on all 91 plots within radius 5. A plot's flag becomes "any land plot within its radius-5 ring set" (`CvPlot.cpp:6570`).
   * If `bRecalc`: an incremental area/landmass patch (`CvPlot.cpp:7317-7430`, port literally), or a full `recalculateAreas()` if the 6 neighbours touch more than 2 areas. **Mapscripts always pass `false`**, so skipping this is acceptable at P2.
6. `SetPlotType(PLOT_OCEAN)` on land gives terrain COAST if any neighbour is land (always true for CP `AddLakes`), else OCEAN.

**`SetTerrainType(t, [bRecalc=false], [bRebuildGfx=false])`** (475 → `CvPlot.cpp:7446`)
* Ignores `t <= -1` and `t >= NUM_TERRAIN_TYPES` (9).
* If changed: set it, `updateImpassable()`. Then **if `Terrains[t].Water != isWater()` → `setPlotType(t is water ? PLOT_OCEAN : PLOT_LAND, bRecalc, ...)`**, which runs all the side effects above (erase etc.).
  * So `SetTerrainType(TERRAIN_COAST)` on a land plot turns it into ocean.
  * Note DB quirk: `TERRAIN_HILL` has `Water=1`.
  * Setting `TERRAIN_MOUNTAIN` on a flat plot keeps `PLOT_LAND`, but `IsMountain()` becomes true.

**`SetFeatureType(f)`** (466 → `CvPlot.cpp:7544`)
* **No validity check** (it does not call `canHaveFeature`). The `ASSERT` only applies in debug builds.
* If unchanged → no-op.
* **VP rule:** if `f == NO_FEATURE` and terrain is DESERT and `isRiver()` → `f = FEATURE_FLOOD_PLAINS` instead.
* Then `updateImpassable()`. NW counters change (map and area), and an area of -1 would crash here: the shim should error if the area is -1 while setting a NaturalWonder feature. Setting `NO_FEATURE` removes an improvement that `RequiresFeature`.

**`SetResourceType(r, [qty=0])`** (1553 → `CvPlot.cpp:7754`)
* Ignores `r < -1` and unknown ids.
* **If `r` equals the current resource → no-op (the quantity is NOT updated).**
* If `Resources[r].OnlyMinorCivs` → silently refused (`bIgnoreMinorCivRestrictions=false` via `BasicLuaMethod`).
* Otherwise it removes the old counts (area, map, map-on-land) and sets `type, qty`. Area/map counters change by `qty` (but `processArea` uses ±1 per plot, `CvPlot.cpp:13588`, so port literally if `Area:GetNumResources` is ever needed).
* A missing qty means **0**.

**`SetImprovementType(i)`** (1603 → `CvPlot.cpp:8149`)
* Ignores `< -1` and unknown ids. Area improvement counts ±1 (`:8303`, `:8640`).
* Used for goody huts. `eBuilder` becomes player 0 (irrelevant headless).

**`SetArea(id)`** (1255 → `CvPlot.cpp:5735`)
* If changed: the old area loses this plot (`processArea(-1)`: numTiles, river edges ×3 flags, resources ±1, improvements ±1, starting plots), then the new area gains it.
* `SetArea(-1)` is used by CP `AddLakes` before the plot turns into a lake. It leaves `GetArea()==-1` until the next `CalculateAreas`.

**`SetStartingPlot(b)`** (1378) sets the flag only.

**`SetContinentArtType(n)`** (2187) stores a `char`. It is read back nowhere by Lua; dump it.

**`SetWOfRiver/SetNWOfRiver/SetNEOfRiver(b, flow)`** (1402/1414/1390): see §7.2.

### 6.3 Initial-state gotchas

* All plots start `PLOT_OCEAN` with `NO_TERRAIN`. `SetPlotType(PLOT_OCEAN)` on them is a no-op, so **ocean plots keep terrain -1 until `GenerateCoasts`/`SetTerrainType`**.
* A script that forgets to give water plots a terrain leaves `-1`, and `CanHaveFeature` on such a plot asserts in C++. The shim should error loudly if `CanHaveFeature` is called with terrain -1.

### 6.4 Impassability (`CvPlot::updateImpassable`, `CvPlot.cpp:14756`)

It runs on every plot-type, terrain or feature change, and for all plots in `calculateAreas`.
* `m_bIsImpassable = isMountain()`.
* Then, if terrain ≠ -1:
  * no feature → `m_bIsImpassable = Terrains[terrain].Impassable`
  * else → `Features[feature].Impassable`
* **So a `PLOT_MOUNTAIN` whose terrain is GRASS/PLAINS/... and has no feature is NOT impassable** (`Terrains.Impassable` is 0 except for `TERRAIN_MOUNTAIN`). Mapscripts typically leave mountain terrain as grass, plains, etc.
* Impassable features in the VP DB: ICE, FUJI, VOLCANO, GIBRALTAR, POTOSI, SRI_PADA, MT_SINAI, MT_KAILASH, LAKE_VICTORIA, KILIMANJARO.
* `isValidMovePlot(NO_PLAYER)` = `(!m_bIsImpassable && feature != ICE) || route` (`CvPlot.cpp:14904`).

### 6.5 `canHaveFeature(f)` (`CvPlot.cpp:5506`)

Checks in this order:
1. `f == -1` → true.
2. The plot already has a feature → false.
3. `isMountain()` → false.
4. City → false.
5. Unknown f → false.
6. `!Feature_TerrainBooleans(f, terrain)` → false. VP DB: ICE{COAST,OCEAN}, JUNGLE{GRASS,PLAINS}, MARSH{GRASS}, OASIS{DESERT}, FLOOD_PLAINS{DESERT}, FOREST{GRASS,PLAINS,TUNDRA}, ATOLL{COAST,OCEAN}. NWs have no rows, so false.
7. `NoCoast && isCoastalLand()` → false. This uses **the cached** `m_bIsAdjacentToWater`, with `iMinWaterSize=-1`, so any adjacent non-ice water counts.
8. `NoRiver && isRiver()` → false.
9. `RequiresFlatlands && isHills()` → false.
10. `NoAdjacent` and a neighbour already has f → false.
11. `RequiresRiver && !isRiver()` → false.
12. Otherwise true.

### 6.6 `CalculateYield(y)` for an unowned plot (P1, `CvPlot.cpp:11208`, `calculateNatureYield` `:10027`)

This is the no-city, no-owner path.
1. Return 0 if terrain is -1, or if `MOD_CORE_NO_YIELD_ICE` and the plot is ice, or if `!m_bPotentialCityWork` (§6.2.5).
2. `Terrain_Yields`, plus `Plot_Yields(plotType)`, plus `Yields.HillsChange` if hills, `Yields.MountainChange` if mountain, `Yields.LakeChange` if `isLake()` (cached).
3. With a feature: `Feature_YieldChanges` (replaces the sum if `YieldNotAdditive`), plus `Feature_RiverYieldChanges` if river, `Feature_HillsYieldChanges` if hills, `Feature_FreshWaterYields` if fresh, `Feature_CoastalLandYields` if coastal (cached).
   Without a feature: the `Terrain_*` equivalents (`Terrain_RiverYieldChanges`, `Terrain_HillsYieldChanges`, `Terrain_FreshWaterYields`, `Terrain_CoastalLandYields`).
4. **Resources add nothing when there is no owner** (`eTeam == NO_TEAM`).
5. `Plot_AdjacentFeatureYieldChanges` (`MOD_PLOTS_EXTENSIONS`).
6. The improvement, religion and player terms are 0 when there is no owner and no improvement (verify when porting).
7. Clamp at ≥ 0.

---

## 7. Rivers (P0)

### 7.1 Representation

Each plot **owns three of its six edges** (`CvPlot.h:396-403`):

| Flag on plot P | Edge of P | Flow stored in | Legal flows |
|---|---|---|---|
| `WOfRiver` ("P is West of the river") | **E** edge (between P and its E neighbour) | `RiverEFlowDirection` | NORTH / SOUTH |
| `NWOfRiver` | **SE** edge | `RiverSEFlowDirection` | NORTHEAST / SOUTHWEST |
| `NEOfRiver` | **SW** edge | `RiverSWFlowDirection` | SOUTHEAST / NORTHWEST |

P's other three edges are owned by neighbours:
* W edge = `W-neighbour.WOfRiver`
* NW edge = `NW-neighbour.NWOfRiver`
* NE edge = `NE-neighbour.NEOfRiver`

`FlowDirectionTypes` (`CvEnums.h:659`): NORTH=0, NORTHEAST=1, SOUTHEAST=2, SOUTH=3, SOUTHWEST=4, NORTHWEST=5, NUM=6, **NO_FLOWDIRECTION=7**. The masks are `1<<k`: NORTH_MASK=1, SOUTH_MASK=2, SOUTHEAST_MASK=4, NORTHWEST_MASK=8, SOUTHWEST_MASK=16, NORTHEAST_MASK=32. LuaCATS (`enum/FlowDirectionTypes.d.lua`) lists the masks as 8..13, which is wrong; use the `CvEnums.h` values. No consumer uses the masks.

### 7.2 `set{W,NW,NE}OfRiver(b, flow)` (`CvPlot.cpp:6290-6425`)

Taking `SetWOfRiver` as the example:
1. **No-op if `flag == b` and `flow == stored flow`.**
2. If the flag changes:
   * Set it.
   * `updateRiverCrossing(E)` on P and `updateRiverCrossing(W)` on P's E neighbour (if it exists).
   * `area():changeNumRiverEdges(±1)` if P has an area.
3. **The flow is stored even when the flag is unchanged**, including `SetWOfRiver(false, flow)`.

The other two map the same way: NW→(SE on P, NW on its SE neighbour) and NE→(SW on P, NE on its SW neighbour).

### 7.3 Crossings: `updateRiverCrossing(d)` (`CvPlot.cpp:11846`)

```
n = neighbour(P, d)
valid = false
if n == nil or (not n.isWater and not P.isWater):     -- both land, or off-map edge
   valid = ({NE: n and n.NEOfRiver, E: P.WOfRiver, SE: P.NWOfRiver,
             SW: P.NEOfRiver, W: n and n.WOfRiver, NW: n and n.NWOfRiver})[d]
toggle bit d of P.riverCrossing; riverCrossingCount += ±1
```

* **`IsRiver()` = `riverCrossingCount > 0`**, so a river edge between land and water does **not** make a plot a river plot.
* **Crossings are only recomputed when a river flag on P or the plot across changes.** `setPlotType` does not recompute crossings. `updateRiverCrossing()` (all directions) is never called.
* Therefore when a plot later turns into water, its neighbours keep stale crossings toward it. `erase()` does clear P's own three flags, which updates those edges correctly.
* Port this exactly: store the crossing bits plus the count.

### 7.4 Water-flag cache (`CvPlot::updateWaterFlags`, `CvPlot.cpp:1231-1320`)

The cached fields are `m_bIsLake`, `m_bIsAdjacentToLand`, `m_bIsAdjacentToWater` and `m_bIsFreshwater`.

```
if P.isWater:
   isLake = landmass(P.m_iLandmass) and landmass.isWater and landmass.numTiles < MIN_WATER_SIZE_FOR_OCEAN
   adjToWater = false; adjToLand = any neighbour not water
else:
   isLake = false; adjToLand = false
   adjToWater = any neighbour water and neighbour.feature != FEATURE_ICE
fresh = P.isRiver()
if P.isWater or fresh: done
for q in {6 neighbours, P itself}:              -- note: includes P
   if q.isLake(cached)                       -> fresh = true
   if q.feature and Features[q.feature].AddsFreshWater -> fresh   -- OASIS, FOUNTAIN_YOUTH, LAKE_VICTORIA
   if q.improvement and Improvements.AddsFreshWater != 0 -> fresh  -- none in VP DB
   if q.isCity and city adds fresh water          -> fresh
```

When the cache refreshes:
* For **all plots**, inside `Map.RecalculateAreas`. There is one pass before the landmass rebuild (it uses the *old* landmass IDs) and one full pass after it (`updateYield` in `calculateLandmasses`, index order). Toggle passes happen whenever a landmass crosses the 10-tile lake threshold during the flood fill.
  * Because the final pass runs in index order, a land plot's fresh-water bit can depend on a neighbour's not-yet-updated `m_bIsLake`.
  * **This only affects the cached `m_bIsFreshwater`, which Lua never reads.** `IsFreshWater()` recomputes self and reads the neighbours' `m_bIsLake`, and those are all correct after the final pass.
* For **one plot**, on `IsLake()`, `IsFreshWater()`, `IsAdjacentToLand()`, `Map.FindWater(.., true)`, or `setPlotType` (via `isAdjacentToLand(false)`).
* Recommended model: refresh every plot's cache in `RecalculateAreas` after the new landmasses are built (two loops: water plots first, then land plots), and refresh a single plot on the per-plot calls. **`IsCoastalLand()` and `CanHaveFeature`'s NoCoast check must read the cache, not recompute.**

---

## 8. Areas, landmasses, continents, lakes (P0)

### 8.1 IDs and containers

* Areas, landmasses and continents use IDs `0..N-1` in **creation order**. New id = `max(existing id)+1` (`CvMap.cpp:1712`, `:2556`). They are cleared on every recalculation, so IDs are not stable across recalcs. (Vanilla Civ5 used large FFreeList IDs; VP does not.)
* Iteration order (`FindBiggest*`, `Areas()`) is creation order.
* `Area.isWater` is fixed at creation from the seed plot. `numTiles` is maintained by `setArea`.
* `Landmass.isLake()` = `isWater && numTiles < MIN_WATER_SIZE_FOR_OCEAN` (10) (`CvMap.cpp:122`). The define `LAKE_MAX_AREA_SIZE` (=9) is **not used by the VP DLL**.

### 8.2 `calculateAreas()` (`CvMap.cpp:1879-2005`)

```
minAreaSize = 7
clear areas; for each plot: setArea(-1); updateImpassable()
-- pass 1 ("wide"): for each plot i in index order with area == -1:
     R = Reach(i, PT_AREA_CONNECTION, iMaxTurns=1)
     if |R| >= 7: A = newArea(water=P.isWater); A.mountains = P.isMountain; for q in R: q.setArea(A)
-- pass 2 ("thin"): for each plot i with area == -1:
     R = Reach(i, PT_AREA_CONNECTION, iMaxTurns=0)
     if |R| < 7:
        best = -1; bestSize = 0
        for q in R: for n in ring1(q) [NE,E,SE,SW,W,NW]:
            if n and n.isWater == P.isWater and n.area != -1 and size(n.area) > bestSize: best = n.area ...
        if best != -1: for q in R: q.setArea(best); continue
     A = newArea(P.isWater); A.mountains = P.isMountain; for q in R: q.setArea(A)
-- then boundaries (wrap-aware projections; not exposed to Lua)
```

`Reach(start, PT_AREA_CONNECTION, k)` is `CvStepFinder::GetPlotsInReach` with validator `AreaValid` (`CvAStar.cpp:2784`). A step parent→node is valid only if all of these hold:
* `node.area == -1`
* `sameClass(node, parent)`, where `sameClass(a,b) = (a.isImpassable == b.isImpassable) and (a.isWater == b.isWater)`
* for k=1 ("wide") only: the node's two neighbours flanking the rear direction (`rear = directionXY(node, parent)`, neighbours `(rear±1) mod 6`, read from the pathfinder node grid, which is wrap-aware) are each either nil or `sameClass(node, ·)`.

> **⚠ Literal-source result (Ambiguity A1):**
> * `CvAStar::LinkChild` (`CvAStar.cpp:625-630`) refuses every child when `node.m_iMoves == 0 && node.m_iTurns+1 >= data.iMaxTurns`.
> * `CvStepFinder::NodeAddedToPath` sets `m_iMoves=0` always (`:1950-1980`), and the start node has `m_iTurns=0`.
> * `calculateAreas` passes `iMaxTurns` as **0 or 1** (a "small misuse" of the field).
> * **So, read literally, `Reach` returns only the start plot in both passes.** Pass 1 never makes an area. Pass 2 degenerates to: *scan plots in index order; join the largest already-assigned neighbouring area with the same `isWater` (impassability ignored, mountains merge with land, ice with water); otherwise open a new area.* This splits concave shapes (e.g. a "U" open to the south becomes two areas) and never merges two existing areas.
> * The *intended* algorithm is a flood fill with the validators above (closure: a node joins if any already-joined neighbour validly steps to it; the order of evaluation doesn't change the set).
> * Implement the literal behaviour as the default (`area_mode="literal"`) and keep `area_mode="floodfill"` as an option until it can be checked against a real game (e.g. FireTuner: print `plot:GetArea()` on a known map).

### 8.3 Landmasses (`recalculateLandmasses` / `calculateLandmasses`, `CvMap.cpp:2600-2658`)

```
for each plot: updateWaterFlags()  (old landmass ids); setLandmass(-1)
remove all landmasses
for each plot i in index order with landmass == -1:
    L = newLandmass(water = P.isWater); P.setLandmass(L)
    for q in Reach(i, PT_LANDMASS_CONNECTION):   -- iMaxTurns = INT_MAX → a real flood fill
        q.setLandmass(L)                          -- step valid iff parent.isWater == node.isWater (`CvAStar.cpp:2834`)
updateYield() → updateWaterFlags() for all plots (index order)
for each plot with area>=0 and landmass>=0: landmass.addArea(area)
```

Landmasses are **plain 6-connected water/land components** that ignore mountains and ice. They are what VP ASP, Communitu and FeatureGenerator use via `GetLandmass`, `FindBiggestLandmassID` and `GetNumTilesOfLandmass`. They are also what `IsLake` uses.

### 8.4 Continents (`recalculateContinents`, `CvMap.cpp:2681`)

These are the same flood fill but the class is `isDeepWater()` (`water && terrain == DEEP_WATER_TERRAIN`). They are not exposed to Lua.

`RecalculateRivers` (`:2781`) only builds `CvRiver` objects when `MOD_BALANCE_RIVER_CITY_CONNECTIONS` is on. It is not exposed to Lua, so skipping it is fine.

### 8.5 Lake creation path (CP `MapGenerator.AddLakes`)

For plots that are `not IsWater`, `not IsCoastalLand` (cached) and `not IsRiver`, with `Map.Rand(LAKE_PLOT_RAND=160)==0`:
1. `plot:SetArea(-1)`, then `plot:SetPlotType(PLOT_OCEAN)`. This erases the plot and gives terrain COAST.
2. At the end, `Map.CalculateAreas()` runs, which rebuilds **areas only**.

As a result, until the next `RecalculateAreas`, new lake plots keep their old **land** landmass ID. So `IsLake()` returns **false** for them, and neighbours do not get fresh water from them during `AddFeatures`. The neighbours' `IsCoastalLand` cache is also stale. Faithfully reproducing this matters for feature placement.

### 8.6 `Map.DefaultContinentStamper()` (`CvMap.cpp:2438-2536`)

1. `recalculateLandmasses()`.
2. Pick the 4 largest land landmasses with ≥10 tiles, using an insertion-sort quirk; port the loop literally.
3. `shuffleArray({0,1,2,3}, mapRand)` (3 RNG draws), then +1 each, giving art styles 1..4.
4. Centroid per landmass = `sum(x)/n, sum(y)/n`, integer division, **not wrap-aware**.
5. Water landmasses get type 0. A land landmass takes the style of the nearest big continent by `plotDistance` between centroids; the first strictly-smaller distance wins. Small landmasses with no big continents stay 0.
6. Stamp every plot with its landmass's continent type. This is the dump's `continent` field. Communitu overrides `DetermineContinents` and calls `SetContinentArtType` itself.

---

## 9. `Area` methods (`Lua/CvLuaArea.cpp`)

| Method (line) | Returns | Semantics | Pri |
|---|---|---|---|
| `GetID()` (109) | int | | P2 |
| `GetNumTiles()` (119) | int | | P0 |
| `IsWater()` (209) | bool | Fixed at creation. | P0 |
| `GetNumRiverEdges()` (159) | int | Running count of the 3 owned river flags over plots in the area. Maintained by `setArea`/`processArea` and the `set*OfRiver` calls. | P0 |
| `GetNumImprovements(imp)` (329) | int | Per-improvement counter. | P0 |
| `GetNumResources(r)` (308) | int | | P3 |
| `CountNumUniqueResourceTypes()` (99) | int | **Bug-compatible:** it counts resource *infos* with `isOneArea()`, not resources present in the area (`CvArea.cpp:160`). | P3 |
| `IsLake()` | — | **Not registered** (commented out, line 30). Scripts must not call it. | — |

---

## 10. Fractal (API only; algorithm ported separately) (P0)

Source: `Lua/CvLuaFractal.cpp`.
* `Fractal.Create(w, h, grain, flags, xExp, yExp)` → fractal userdata. Its metatable `__index` holds `GetHeight` and `BuildRidges`, and `__gc` destroys it. It calls `fracInit(..., mapRand, flags, nil, xExp, yExp)`.
  * `xExp`/`yExp`: an **explicit `nil`** gives `DEFAULT_FRAC_X_EXP=7` / `DEFAULT_FRAC_Y_EXP=6`.
  * An **absent** argument (`LUA_TNONE`) is *not* `lua_isnil` in stock Lua and becomes 0 (`1<<0`).
  * A **negative** value becomes the default inside `fracInitInternal` (`CvFractal.cpp:88-95`).
  * Every consumer passes 6 arguments (usually `-1,-1` or `nil`), so implement "nil, missing or <0 → default".
* `Fractal.CreateRifts(w, h, grain, flags, riftsFrac, xExp, yExp)` takes the rift fractal as arg 5. Exps use `luaL_optint`, so nil or missing → default.
* `flags` is a table; **the presence of a non-nil key sets the bit** (`HasFlag` uses `!lua_isnil`), so `{FRAC_WRAP_X=false}` still sets WRAP_X. Keys: `FRAC_WRAP_X`=1, `FRAC_WRAP_Y`=2, `FRAC_PERCENT`=4, `FRAC_POLAR`=8, `FRAC_CENTER_RIFT`=16, `FRAC_INVERT_HEIGHTS`=32 (`CvFractal.h:23`). `luaL_checktype` makes a non-table flags argument an error.
* `frac:GetHeight(x, y)` → int (2 args). `frac:GetHeight(pct)` (1 arg) → `getHeightFromPercent`. Any other argument count is a Lua error.
* `frac:BuildRidges(numSeeds, flags, blendRidge, blendFract)` → `ridgeBuilder(mapRand, ...)`.
* All of these draw from **the same map RNG** as `Map.Rand` (§4). `Fractal.CreateHinted` / `CreateRidged` are mentioned in comments only; they are not registered.

---

## 11. Data access: GameInfo, GameInfoTypes, GameDefines, DB

### 11.1 `GameInfo` (provided by the exe; behaviour inferred from consumer usage, LuaCATS `database/GameInfo.d.lua`, and the front-end Lua) (P0)

* `GameInfo.<Table>` is a table-like object for **any** DB table. `GameInfo[name]` is nil for a non-existent table; VPUI checks `GameInfo[strTable]`.
* `T[id]` (number) → the row with `ID == id`, or nil.
* `T["TYPE"]` / `T.TYPE` (string) → the row with `Type == "TYPE"`, or nil. Both are used: `GameInfo.Terrains.TERRAIN_GRASS.ID`, `GameInfo.Civilizations[row.CivilizationType]`.
* `T()` → iterator over all rows **in ID/rowid order**.
  * Plain `SELECT ... FROM T` in SQLite can return index order; for example `Regions` came back sorted by `Type`.
  * The exporter must `ORDER BY rowid`.
* `T("SQL where-clause")` → iterator over `SELECT * FROM T WHERE <clause>`. Example: `GameInfo.CustomModOptions("Name = 'BALANCE_CORE_JFD'")()` takes the first row; it is nil if there are no rows, and the next `.Value` would then error.
* `T{Col = v, ...}` → iterator with an AND of equalities.
* `#T` → row count. VP ASP uses `#GameInfo.Natural_Wonder_Placement` = 17 and `#GameInfo.Resources - 1` = 56.
* **Rows** are Lua tables of column→value:
  * Columns declared **`boolean`** → **Lua booleans**. This is required: `if GameInfo.Eras[era].NoGoodies` and the NW placement flags rely on it, and `0` would be truthy.
  * `integer`/`float` → numbers. `text` → strings. SQL `NULL` → field absent (nil).
  * Columns declared `integer` that hold 0/1, such as `Improvements.AddsFreshWater`, stay numbers.
  * Treat rows as read-only and cache them.
* **Non-primary tables** (no ID), such as `Leader_Traits`, `Civilization_Start_*` and `Feature_TerrainBooleans`, support `()`, `("...")` and `{...}` only.

### 11.2 `GameInfoTypes` (`Lua/CvLuaGameInfo.cpp:97-112`, filled by `CvDllDatabaseUtility.cpp:134-164`)

* For **every table in `sqlite_master` that has both an `ID` and a `Type` column**, map each row's `Type → ID`. Later tables overwrite earlier ones on name collisions.
* It is a plain table: an unknown key gives nil.
* Used: `TERRAIN_*` (TerrainGenerator, P0), `REGION_*`, `RESOURCE_*`, `WORLDSIZE_*`, and dynamic `GameInfoTypes[row.NaturalWonderType]` (VP ASP, P1). VP ASP's own lookup goes through `VP.GameInfoTypes`, which returns the global when it exists.

### 11.3 `GameDefines` (P0)

This is a plain table `Name → Value` from the `Defines` table (2631 rows). Keys used, with their current values:

| Key | Value |
|---|---|
| `SHALLOW_WATER_TERRAIN` | 5 |
| `DEEP_WATER_TERRAIN` | 6 |
| `LAKE_PLOT_RAND` | 160 |
| `PLOTS_PER_RIVER_EDGE` | 12 |
| `RIVER_SOURCE_MIN_RIVER_RANGE` | 4 |
| `RIVER_SOURCE_MIN_SEAWATER_RANGE` | 2 |
| `MAX_CIV_PLAYERS` | 63 |
| `MAX_MAJOR_CIVS` | 22 |
| `MAX_MINOR_CIVS` | 41 |
| `MIN_WATER_SIZE_FOR_OCEAN` | 10 |
| `WEEKS_PER_MONTHS` | — (P3) |

Engine-internal defines also used by the C++ described above: `LAND_TERRAIN`=0, `NUM_RESOURCE_QUANTITY_TYPES`=4, `MAX_PLAYERS`=64, `MAX_TEAMS`=64, `BARBARIAN_PLAYER`=63.

### 11.4 `DB` (P1)

* `DB.Query(sql, ...)` → iterator of row tables. `?` placeholders are bound to the extra arguments (CP MMU: `"select count(*) as count from ... where CivilizationType = ?", civType`).
* `DB.CreateQuery(sql)` → callable `q(...)` that returns an iterator. VP ASP builds four of these at **include time**. They run only if CP is not in `Modding.GetActivatedMods()`.
* VPUI also uses `DB.Query("SELECT tbl_name FROM sqlite_master ...")` and `PRAGMA table_info(...)` only when `GameInfoTypes` is missing, which never happens here.
* Implement over the exported SQLite DB (the Python host can serve these queries) or with a small in-Lua fallback that supports the exact query strings above.

### 11.5 Include-time code that must work before `GetMapInitData` (P0, even though it comes from P1 files)

* **VPUI_core:**
  * `GameInfo.CustomModOptions("Name = 'BALANCE_CORE_JFD'")().Value` → 0
  * `Game.GetNumYieldTypes()` → `GC.getNUM_YIELD_TYPES()` (`Lua/CvLuaGame.cpp:4240`). Return **12** when `BALANCE_CORE_JFD`=0 (`YIELD_CULTURE_LOCAL.ID+1`), or **17** if JFD is enabled (`YIELD_JFD_SOVEREIGNTY.ID+1`).
  * Iterates `GameInfo.GreatPersons[0..]` (reads `.Specialist`)
  * Writes `MapModData.VP`, or global `VP` when `MapModData` is nil
  * `ContextPtr` is checked (leave it nil).
* **VP ASP:**
  * `MapModData.VP` / `VP`, `Locale.Lookup` (aliased as `L`)
  * `#GameInfo.Natural_Wonder_Placement`, `#GameInfo.Resources`
  * `GameDefines.MAX_MAJOR_CIVS`, `GameDefines.MAX_MINOR_CIVS`
  * four `DB.CreateQuery` calls
* **CP MMU:** `local VP = MapModData and MapModData.VP or VP` runs **before** VPUI_core, because ASP includes MMU first. See §11.6.
* **Continental_Drift / Tectonic:** `local L = Locale.ConvertTextKey`.

### 11.6 `MapModData` (P0)

* In game this is a "super-global" shared by all Lua contexts. The front-end and UI contexts have already run `VPUI_core`, so `MapModData.VP` exists when the map script loads.
* **CP MMU captures `VP` at include time, before VP ASP includes `VPUI_core`.** If `MapModData.VP` is not already populated, MMU's upvalue `VP` is nil. VP ASP then crashes in `GetStartRegionPriorityListForCiv_GetIDs` → `VP.GameInfoTypes`, which runs for any civ with a `Civilization_Start_Region_Priority` row.
* **Harness rule:** create `MapModData = {}` and **run `VPUI_core.lua` once before loading the mapscript**, mirroring the game.
* `MapModData.FLuaVector` is read by FLuaVector if present; it may stay nil.

### 11.7 DB tables and columns needed (export these with all columns, `ORDER BY rowid`)

| Table | Used by / columns read | Pri |
|---|---|---|
| `Worlds` | All. `ID, Type, GridWidth, GridHeight, DefaultPlayers, DefaultMinorCivs, FeatureGrainChange` (VP FG), `TerrainGrainChange`, `NumNaturalWonders`. | P0 |
| `Terrains` | `ID, Type, Water, Impassable` (C++), iteration (Communitu). | P0 |
| `Features` | `ID, Type, AppearanceProbability, NaturalWonder, PseudoNaturalWonder, Impassable, NoCoast, NoRiver, NoAdjacent, RequiresFlatlands, RequiresRiver, AddsFreshWater, NoImprovement, YieldNotAdditive`. | P0 |
| `Feature_TerrainBooleans` | `canHaveFeature`. | P0 |
| `Eras` | `NoGoodies` (`GameInfo.Eras[Game.GetStartEra()]`). | P0 |
| `Improvements` + `Improvement_ValidTerrains`, `Improvement_ValidFeatures`, `Improvement_ResourceTypes` | `Goody, TilesPerGoody, GoodyRange, Water`, and the `canHaveImprovement` columns. | P0 |
| `Defines` | `GameDefines`. | P0 |
| `CustomModOptions` | `Name, Value` (VPUI include time). | P0 |
| `GreatPersons` | `ID, Specialist` (VPUI include time). | P0 |
| `Yields` | `ID, Type, HillsChange, MountainChange, LakeChange` (VPUI, CalculateYield). | P0/P1 |
| `GameOptions` | `Type, Default` (`Game.GetCustomOption` fallback). | P1 |
| `MapScriptOptions` | `FileName, OptionID, DefaultValue` (optional fallback for `Map.GetCustomOption`). | P0 |
| `Resources` | `ID, Type, ResourceClassType, ResourceUsage, Happiness, OnlyMinorCivs, Description, ...` (ASP and MMU read many; export all). | P1 |
| `Resource_QuantityTypes`, `Resource_TerrainBooleans`, `Resource_FeatureBooleans`, `Resource_FeatureTerrainBooleans` | Only for `CanHaveResource` / `GetRandomResourceQuantity`. | P3 |
| `Regions` | `ID, Type` (`GameInfoCache("Regions")`, `GameInfo.Regions[id].Type`). | P1 |
| `Natural_Wonder_Placement` | All ~120 columns (§ ASP `kPlacementInfo.*`). It has `ID` but **no `Type`** (`NaturalWonderType` instead). | P1 |
| `Civilizations` | `ID, Type, ShortDescription, Playable` (`GameInfo.Civilizations[civID]`). | P1 |
| `Civilization_Start_Along_Ocean`, `_Along_River`, `_Prefer_Mountain`, `_Prefer_Snow`, `_Place_First_Along_Ocean`, `_Region_Priority`, `_Region_Avoid` | `CivilizationType, RegionType, ...` (CP MMU). | P1 |
| `MinorCivilizations`, `MinorCivTraits` | Headless player setup and `GetMinorCivTrait`. | P1 |
| `Leader_Traits`, `Civilization_Leaders`, `IconTextureAtlases` | VPUI helpers, which are never called at mapgen. | P3 |
| `Terrain_Yields`, `Plot_Yields`, `Plots`, `Feature_YieldChanges`, `Feature_RiverYieldChanges`, `Feature_HillsYieldChanges`, `Feature_FreshWaterYields`, `Feature_CoastalLandYields`, `Terrain_RiverYieldChanges`, `Terrain_HillsYieldChanges`, `Terrain_FreshWaterYields`, `Terrain_CoastalLandYields`, `Plot_AdjacentFeatureYieldChanges` | `CalculateYield`. | P1 |
| `Climates`, `SeaLevels` | `GameInfo.SeaLevels[Map.GetSeaLevel()]` (P2), base FG (P3). | P2 |
| `HandicapInfos`, `GameSpeeds`, `Leaders`, `Months`, `Seasons`, `Maps`, `Map_Sizes`, `MapScripts`, `PolicyBranchTypes`, `ResourceClasses` | Dead files only. | P3 |

---

## 12. Game, PreGame, Players, Teams (headless model)

### 12.1 `Game.*` (`Lua/CvLuaGame.cpp`)

| Symbol (line) | Semantics | Pri |
|---|---|---|
| `Game.GetStartEra()` (1515) | `CvPreGame::era()` → `Eras.ID`. Default 0 (ERA_ANCIENT). | P0 |
| `Game.IsOption(opt)` (1564) | Number → `isOption(id)`; string → `isOption(name)`. Default all false (`GAMEOPTION_NO_GOODY_HUTS` → false). | P0 |
| `Game.GetCustomOption(name)` (2274) | `luaL_checkstring`. `CvPreGame::GetGameOption` (`CvPreGame.cpp:920`): the set value, else `GameOptions."Default" WHERE Type=name`, else *nothing*. `"GAMEOPTION_DISABLE_START_BIAS"` → 0. | P1 |
| `Game.GetResourceUsageType(r)` (2026) | `Resources.ResourceUsage` (0 bonus, 1 strategic, 2 luxury). `r == -1` → -1. **An unknown id crashes in C++.** | P1 |
| `Game.CountCivTeamsEverAlive()` (718) | Number of non-barbarian teams with an ever-alive member = majors + city-states with the default 1:1 teams. | P1 |
| `Game.GetNumYieldTypes()` (4240) | See §11.5. | P0 (include time) |
| `Game.CountCivPlayersAlive()`, `Game.IsNetworkMultiPlayer()` | Dead files only. | P3 |

### 12.2 `Players[i]` / `Teams[i]` (P0/P1)

* **`Players` must contain an object for every `i` in 0..63.** CP MapGenerator `CanPlaceGoodyAt` loops `0..MAX_CIV_PLAYERS-1` and calls `:IsEverAlive()` on each. MMU loops `0..21` and `22..62`. `Teams` should also be 0..63, though no consumer calls it.
* Slot layout:
  * Majors occupy `0..N-1`.
  * City-states occupy `22..22+M-1`. VP ASP addresses them as `cs_number + MAX_MAJOR_CIVS - 1`, with `cs_number` 1-based.
  * The barbarian is 63.
  * Team id = player id.

| Player method (CvLuaPlayer.cpp line) | Headless semantics | Pri |
|---|---|---|
| `IsEverAlive()` (10194) | true for the configured majors and CSs, false otherwise (barbarian false is fine; it's never queried). | P0 |
| `GetStartingPlot()` (3383) | Plot or nil. | P0 |
| `SetStartingPlot(plot)` (3393 → `CvPlayer.cpp setStartingPlot`) | If different: the old start's area loses a starting-plot count (C++ dereferences the old area). Store x/y. `newPlot:setStartingPlot(true)`. The new area gets +1. **The old plot's `IsStartingPlot` flag is NOT cleared.** `nil` clears x/y. | P1 |
| `GetTeam()` (10299) | = player id. | P1 |
| `GetCivilizationType()` (10263) | `Civilizations.ID`. Majors: distinct, from config, else random among `Playable=1`. CSs: `CIVILIZATION_MINOR`. Unused slots: -1. | P1 |
| `GetMinorCivTrait()` (8920) | `MinorCivTraits.ID` of the slot's `MinorCivilizations.MinorCivTrait`. The DLL enum `MinorCivTraitTypes` (CULTURED=0, MILITARISTIC=1, MARITIME=2, MERCANTILE=3, RELIGIOUS=4) matches the DB IDs. Majors return -1 (`NO_MINOR_CIV_TRAIT_TYPE`). | P1 |
| `GetID()`, `IsHuman()`, `GetLeaderType()`, `GetNickName()`, `GetDominantPolicyBranchForTitle()` | Dead-file uses only. `GetID` → i, `IsHuman` → `i==0`. | P3 |

**Recommended headless defaults** (all overridable from the CLI):
* N majors = `Worlds.DefaultPlayers` (DUEL 2, TINY 4, SMALL 6, STANDARD 8, LARGE 10, HUGE 12).
* M city-states = `Worlds.DefaultMinorCivs` (4, 8, 12, 16, 20, 24).
* Civs: a seeded harness RNG that is **independent of the map RNG** picks distinct playable civs (43 available) and distinct minor civs (120).
* Era ANCIENT; handicap `HANDICAP_PRINCE` (unused); game options from `GameOptions.Default`; climate TEMPERATE; sea level MEDIUM.

### 12.3 `PreGame` (P3)

Only dead files read `PreGame` (`GameplayUtilities`: `GetCivilizationShortDescription`, `GetLeaderName`). Expose a small table holding the setup values (worldSize, climate, seaLevel, era, mapRandomSeed, map options) for debugging. The engine-side readers are `Map.GetWorldSize`/`GetClimate`/`GetSeaLevel`, `Game.GetStartEra` and `Map.GetCustomOption`.

---

## 13. Enum tables (plain Lua tables; unknown keys → nil, never an error)

Registered in `Lua/CvLuaEnums.cpp` (`EnumStart` creates or extends the global table; `pRegisterEnum` does `t[name]=value`). Values come from `CvGameCoreDLLUtil/include/CvEnums.h`.

> **Do not error on missing enum keys.** Several scripts use non-existent names and depend on getting `nil`: `PlotTypes.PLOT_PEAK`, `PlotTypes.PLOT_MOUNTAINS`, `TerrainTypes.PLOT_HILLS` (Communitu), and `FeatureTypes.FEATURE_FLOODPLAIN` in base ASP. This overrides the DESIGN.md "unknown call ⇒ error" rule for enum *tables*. Only unknown *functions* should error.

| Enum | Values | Pri |
|---|---|---|
| `PlotTypes` (`CvEnums.h:1247`) | NO_PLOT=-1, PLOT_MOUNTAIN=0, PLOT_HILLS=1, PLOT_LAND=2, PLOT_OCEAN=3, NUM_PLOT_TYPES=4 | P0 |
| `TerrainTypes` (`:1230`) | NO_TERRAIN=-1, GRASS=0, PLAINS=1, DESERT=2, TUNDRA=3, SNOW=4, COAST=5, OCEAN=6, MOUNTAIN=7, HILL=8, NUM=9 (the DB IDs match) | P0 |
| `FeatureTypes` (`:1405`) | NO_FEATURE=-1, ICE=0, JUNGLE, MARSH, OASIS, FLOOD_PLAINS, FOREST, FALLOUT, CRATER, FUJI, MESA, REEF=10, VOLCANO, GIBRALTAR, GEYSER, FOUNTAIN_YOUTH, POTOSI, EL_DORADO, ATOLL=17, SRI_PADA, MT_SINAI, MT_KAILASH, ULURU, LAKE_VICTORIA, KILIMANJARO, SOLOMONS_MINES=24, NUM=25. These are hard-coded in the DLL; the current DB IDs match. | P0 |
| `DirectionTypes` | §3.2 (NO_DIRECTION=7, NUM=6) | P0 |
| `FlowDirectionTypes` | §7.1 | P0 |
| `WorldSizeTypes` | From the `Worlds` table (exe-registered): WORLDSIZE_DUEL=0 … HUGE=5 | P0 |
| `ResourceUsageTypes` | BONUS=0, STRATEGIC=1, LUXURY=2, NUM=3 | P1 |
| `MinorCivTraitTypes` | NO=-1, CULTURED=0, MILITARISTIC=1, MARITIME=2, MERCANTILE=3, RELIGIOUS=4, NUM=5 | P1 |
| `GameOptionTypes` | `CvEnums.h`: NO_GAMEOPTION=-1, NO_CITY_RAZING=0, NO_BARBARIANS=1, RAGING_BARBARIANS=2, ALWAYS_WAR=3, ALWAYS_PEACE=4, ONE_CITY_CHALLENGE=5, NO_CHANGING_WAR_PEACE=6, NEW_RANDOM_SEED=7, LOCK_MODS=8, COMPLETE_KILLS=9, **NO_GOODY_HUTS=10**, RANDOM_PERSONALITIES=11, POLICY_SAVING=12, PROMOTION_SAVING=13, END_TURN_TIMER_ENABLED=14, QUICK_COMBAT=15, DISABLE_START_BIAS=16, NO_SCIENCE=17, NO_POLICIES=18, NO_HAPPINESS=19, NO_TUTORIAL=20, NO_RELIGION=21, NUM=22 (all prefixed `GAMEOPTION_`). These do **not** line up with `GameOptions` table IDs. | P0 |
| `YieldTypes` | `CvGameCoreEnums.h:15`: NO=-1, FOOD=0, PRODUCTION=1, GOLD=2, SCIENCE=3, CULTURE=4, FAITH=5, TOURISM=6, GOLDEN_AGE_POINTS=7, GREAT_GENERAL_POINTS=8, GREAT_ADMIRAL_POINTS=9, POPULATION=10, CULTURE_LOCAL=11 (Lua registration stops at CULTURE_LOCAL; NUM_YIELD_TYPES is registered too). The DB `Yields` IDs match, plus JFD 12..16. | P1 |
| `PlotListTypes`, `ImpactLayers`, `AdjacentTiles*` | Defined in Lua by ASP and scripts, **not** engine-provided. | — |

---

## 14. Other engine globals

| Symbol | Semantics | Pri |
|---|---|---|
| `include(name [, useRegex])` | VFS load (§0) into the **same global environment**, executed every call. Recommend no caching; the libraries are written to tolerate repeat inclusion (VPUI and FLuaVector guard themselves). Returns nothing / a list of names in regex mode. | P0 |
| `print(...)` | Captured to the log. Tab-separated `tostring` like stock Lua. | P0 |
| `Locale.ConvertTextKey(key, ...)` / `Locale.Lookup(key, ...)` | Localized text with `{1_Name}` substitution. Headless: look up `Language_en_US` in `cache\Localization-Merged.db` if available, else return `key`. Only used for prints and option names. | P0 / P1 |
| `Locale.IsNilOrWhitespace` | Dead (`MapUtilities`). | P3 |
| `Modding.GetActivatedModEntryPoints(type)` | **Returns an iterator** used in `for ep in ... do`, yielding `{File="path"}`. Default: an empty iterator. | P0 |
| `Modding.GetActivatedMods()` | **Returns an array** used with `pairs`, of `{ID=guid, Version=n}`. Default: include CP `d1b6328c-ff44-4b0d-aad7-c657f83610cd` (and VP). Then `ASP:IsModActive("EvenMoreResources"/"AloeVera"/...)` returns false without running the DB fallback. Make this configurable to mirror the user's enabled mods. | P1 |
| `Events.SerialEventHexHighlight` | No-op stub (Communitu debug path). | P3 |
| `UI.GetMapPreview`, `Path.GetFileNameWithoutExtension`, `PreGame.*` | Dead files. | P3 |

---

## 15. Lua library: Havok/Firaxis extensions and stdlib caveats

| Function | Semantics | Pri |
|---|---|---|
| `table.fill(value, n)` | **Firaxis extension.** Returns a new table `{[1..n] = value}`. Index 0 is NOT filled: scripts do `plotTypes[i+1]`, and CP MMU sets `[0]` explicitly. Seen as `table.fill(0, iW*iH)`, `table.fill(false, n)`, `table.fill(PlotTypes.PLOT_OCEAN, W*H)`. | P0 |
| `table.fill(t, value, n)` | Three-argument form: overwrite `t[1..n]`, return `t` (`MultilayeredFractal`: `table.fill(self.plotTypes, PLOT_OCEAN, w*h)`). Tell the forms apart by `type(arg1)=='table'` **and** argument count, since `value` itself could be a table. | P0 |
| `table.count(t)` | Firaxis extension: number of non-nil entries, any keys. Not used by consumers; provide anyway. | P3 |
| `math.clamp(v, lo, hi)` | Firaxis extension: `math.min(math.max(v, lo), hi)`. Used by `TerrainGenerator`/`ContinentsWorld`/`PangaeaWorld`, etc. | P0 |
| `math.random`, `math.randomseed` | **Communitu seeds `math.randomseed(Map.Rand(...)*65536 + Map.Rand(...))` and then uses `math.random(lo,hi)`.** **Tectonic and Continental Drift call `math.random()` without ever seeding it**, so in game their result depends on the CRT `rand()` state (non-reproducible). For fidelity, emulate Lua 5.1 on MSVC: `rand()` = `s = s*214013 + 2531011 (mod 2^32); return (s >> 16) & 0x7FFF`, `RAND_MAX = 32767`. `math.random()` = `(rand()%RAND_MAX)/RAND_MAX`; `math.random(m)` = `floor(r*m)+1`; `math.random(m,n)` = `floor(r*(n-m+1))+m`. Seed with `srand(seed)`; the default state is `srand(1)`. Unverified for Havok (A4). | P0 |
| `os.clock` | Used only when Communitu `debugTime` is true. Allow. | P0 (trivial) |
| `io.open` | `FloatMap:Save`. All callers are commented out. Stub with an error or a sandboxed write. | P3 |
| `coroutine.wrap/yield` | CP MMU `Plot_GetPlotsInCircle`. Standard. | P1 |
| `table.sort` | **Unstable.** Output for equal keys depends on the implementation (Lua 5.1 quicksort vs Havok). VP ASP sorts fertility lists, and ties can change start positions vs the real game (A5). | P0 |
| `pairs` / `next` order | Many scripts iterate `pairs()` and draw RNG inside the loop. The iteration order is implementation-defined, so exact in-game parity is impossible unless Havok's hash order is identical (A5). Within the harness, determinism is guaranteed by lupa/Lua 5.1. | P0 |
| Others used | `table.insert/remove/concat/maxn`; `math.abs/ceil/floor/fmod/modf/frexp/ldexp/max/min/pow/sqrt/sin/cos/tan/acos/rad/huge/pi`; `string.format/sub/match` and string methods; `tostring`, `tonumber`, `type`, `pairs`, `ipairs`, `next`, `select`, `setmetatable`, `getmetatable`, `assert`, `error`, `pcall`. All are stock Lua 5.1. | P0 |

---

## 16. Consumer-side findings worth knowing

1. **The user's `My Games\Maps\Communitu_79a.lua` is v3.1.0 and is stale against current VP.**
   * It calls `ASP:IsEvenMoreResourcesActive()`, `ASP:IsAloeVeraResourceActive()`, `ASP:Plot_GetFertility()`, `ASP:GetRandomMultiplier()` and `GetRandomWeighted()`. None of these exist in the current VP ASP or MMU; VP's own copy (v3.2.0, `(2) Vox Populi\Mapscripts\Communitu_79a.lua`) uses `ASP:IsModActive(...)`, `Plot_GetFertility`, `GetRandomMultiplier` and `GetRandomFromWeightedTable`.
   * The My Games copy will raise "attempt to call method ... (a nil value)" when `BuffIslands` or the resource code runs.
   * The `Assets\Maps` copy is identical to the My Games one.
   * The user's `Continental_Drift.lua` (v"1") also differs from VP's (v3.1).
2. `Tectonic`/`Continental_Drift` `GetMapInitData` return non-integer `Width`/`Height` (ratio × size multiplier). The engine rounds them (§1.3).
3. CP `GenerateCoasts` has `bExpandCoasts = args.bExpandCoasts or true`, which is always true.
4. CP `Shuffle(t)` is a Fisher–Yates from the end (`Map.Rand(i)` for `i=#t..2`). This differs from the base-game Shuffle; the effective version is CP's.
5. `PlotTypes.PLOT_PEAK`/`PLOT_MOUNTAINS` are nil. Comparisons with them are always false, and `t[nil]=x` errors. Scripts reach these only on some option paths.

---

## 17. Ambiguities and unverified points

| # | Issue | Recommendation |
|---|---|---|
| **A1** | **VP area algorithm.** Read literally (`CvAStar.cpp:625-630` + `:1950` + `CvMap.cpp:1906,1934`), `GetPlotsInReach(PT_AREA_CONNECTION, iMaxTurns 0/1)` returns only the start plot, so areas become the greedy scan-order merge described in §8.2 and the "wide/compact" logic is dead code. I could not confirm whether the shipped DLL behaves this way: it depends on build and history, and I was told not to run git. | Implement both, default `literal`. Validate against an in-game FireTuner dump of `GetArea()` for one map. |
| A2 | The lua_State used for the map script is created with `CreateLuaThread`, and its relation to UI contexts is exe-side. That determines whether `MapModData.VP` pre-exists (§11.6). | Pre-run VPUI_core (required for VP ASP + CP MMU to work at all). |
| A3 | Float→int conversion in Havok Script (round-half-even like Lua 5.1/x86 `fistp`, or truncation). | Default round-half-even, behind a switch. |
| A4 | `math.random` implementation in Havok Script (CRT `rand()` vs own PRNG). | MSVC `rand` emulation, deterministic seed. |
| A5 | `table.sort` tie order and `pairs` order vs Havok. | Accept: the harness is deterministic, but bit-exact parity with the game is not guaranteed. |
| A6 | `include` caching semantics (re-execute vs once). | Re-execute; the libraries are idempotent. |
| A7 | `GameInfo` is implemented in the exe. Boolean conversion is by declared column type `boolean`, NULL→nil, iteration in rowid order. This is inferred from usage (e.g. `Eras.NoGoodies` must be a Lua boolean) and not readable from source. | As specified. |
| A8 | `Fractal.Create` with absent (not nil) exponent args → 0 under stock Lua 5.1 `lua_isnil`. No consumer hits this. | Treat absent like nil (default). |
| A9 | `CalculateYield`'s improvement/player/religion terms are assumed 0 for unowned, unimproved plots; I did not trace `calculateImprovementYield`/`calculatePlayerYield` fully. | Port `calculateNatureYield` exactly; add the other terms if VP ASP NW/CS scores diverge. |
| A10 | Mapscript option IDs come from the exe front-end, inferred from `AdvancedSetup.lua` and the DB `MapScriptOptions` rows (Tectonic's IDs start at "2" because `CustomOptions[1]` is nil). | As in §2. |

---

## 18. Implementation notes and corrections (added by the fake-client implementation, 2026-11-07)

These were found while building `engine/` and running the acceptance scripts; each is marked with its evidence.

* **`include()` returns a list of the included file names** (not nothing). CP `Kit/CPK.lua` `Import` does `#include(f) == 1` and errors otherwise; the harness returns `{basename}` (or `{}` when not found). The Kit's `CPK.*.lua` files are pulled in lazily through this path, so the VFS must index CP's `Kit/**` (they are `import="1"` in the CP modinfo).
* **Front-end option entry point is `GetMapScriptInfo().CustomOptions`**, not `GetMapScriptOptions()`; no consumer defines `GetMapScriptOptions`. The harness calls `GetMapScriptInfo()` once after loading the script and saves/restores the map RNG around it (in game it runs in a separate front-end Lua state).
* **`CvLandmass::changeNumTiles` triggers `CvMap::updateYield()` (an `updateWaterFlags()` pass over every plot) whenever a water landmass crosses the 10-tile lake threshold** (`CvMap.cpp:88`). Only the water plots' `m_bIsLake` from the last such pass survives into observable state (a land plot's cached fresh-water flag in the final index-order pass reads its higher-index neighbours' `m_bIsLake`); the harness reproduces exactly that.
* **`m_bPotentialCityWork` (gates `CalculateYield`) always equals "some land plot within radius 5"**: `updatePotentialCityWork()` runs on the 91 plots around every water<->land flip and initial state is all-ocean. The harness computes it on demand, cached until the next flip.
* **`erase()` order quirk**: `setFeatureType(NO_FEATURE)` runs *before* the river flags are cleared, so turning a river desert plot into ocean leaves `FEATURE_FLOOD_PLAINS` on the new water plot (the VP flood-plains rule fires). Reproduced literally.
* **No `GetMapInitData` table → latitudes 0/0** (`CvMap::reset` keeps the fresh values), so `plot:GetLatitude()` is 0 everywhere for scripts like vanilla Pangaea/Continents. Wrap defaults stay X=true, Y=false.
* **Literal areas make vanilla `Pangaea.lua` retry its continent fractal ~90 times at standard size** (seed 42: 93 `SetPlotTypes` calls, 16.7 M map-RNG draws, ~16 s under lua51), because its "biggest area >= 84 % of land" test rarely passes when areas are scan-order fragments; with `--areas floodfill` it accepts on attempt 1. This is a cheap in-game check for Ambiguity A1: time a standard Pangaea generation / count Lua.log lines "Setting Plot Types".
* **Vanilla scripts that override VP-incompatible ASP methods fail under VP** (script bugs, not harness): `Assets\Maps\Lakes.lua` / `Highlands.lua` (`CanPlaceCityStateAt` reads `self.cityStateData`), `Assets\Maps\Great_Plains.lua` (`AssignLuxuryRoles` reads `iNumTypesUnassigned`), `DLC\Expansion\Maps\Europe.lua` (`naturalWondersData`), `DLC\Expansion\Maps\Hemispheres.lua` (sets `self.method = 3` in its own `GenerateRegions`; VP reads 3 as a landmass division and indexes `self.landmass_areas[areaID]` = nil). VP ships working copies of Lakes, Highlands, Europe, Terra, Great_Plains_XP in `(2) Vox Populi\Mapscripts`.
* **`pairs()` order matters for RNG parity**: CP `AddRivers` iterates `pairs(adjacentPlotFunctions)` (integer keys 0..5) and draws `Map.Rand` inside the loop. Lua 5.1 and LuaJIT hash numbers differently, so `--runtime luajit21` (~7x faster) diverges from `lua51` from AddRivers onwards. Use lua51 for anything compared against the game.
* `SetPlotType(..., bRecalculate=true)` (incremental area patch, `CvPlot.cpp:7317`) is not used by any consumer with `true`; the harness raises an error if it is.
