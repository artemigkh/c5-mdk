# Engine API usage matrix

This is generated from a static scan of all 123 consumer Lua files, with comments stripped. It shows which engine symbols each effective script and library uses, so the implementer can prioritise. Semantics for every symbol are in `engine-api.md`.

**Columns** are the files that actually run (VFS-resolved, see engine-api.md §0):

| Col | File | Source |
|---|---|---|
| MG | `MapGenerator.lua` | CP override |
| FG | `FeatureGenerator.lua` | VP override |
| TG | `TerrainGenerator.lua` | base |
| FW | `FractalWorld.lua` | base |
| IM | `IslandMaker.lua` | base (Communitu) |
| FLV | `FLuaVector.lua` | CP override |
| COM | `Communitu_79a.lua` | My Games copy, v3.1.0 |
| CD | `Continental_Drift.lua` | My Games |
| TEC | `Tectonic v6 - VI.lua` | My Games |
| ASP | `AssignStartingPlots.lua` | VP override |
| MMU | `MapmakerUtilities.lua` | CP override |
| NWC | `NaturalWondersCustomMethods.lua` | VP override |
| VPUI | `VPUI_core.lua` | CP; included by ASP |
| MLF | `MultilayeredFractal.lua` | base |

* **"Other effective scripts/libs"**: every other mapscript in `Assets\Maps`, `DLC\Expansion\Maps`, `DLC\DLC_SP_Maps*\Maps`, `(1) Community Patch\Mapscripts` and `(2) Vox Populi\Mapscripts` (+EMP), plus the base `ContinentsWorld`, `FourContinentsWorld`, `PangaeaWorld` and `HintedWorld`. Names may repeat because several copies of a script exist; for example, Communitu also appears in `Assets\Maps` and VP `Mapscripts`.
* **"Only in dead/overridden files"**: listed only when nothing effective uses the symbol. These are base/Expansion copies of overridden libraries, `WorldBuilderRandomItems`, `GameplayUtilities`, `GameCalendarUtilities` and `MapUtilities`.

**Priority**

| Tag | Meaning |
|---|---|
| P0 | Used by MG/FG/TG/FW/IM/FLV/COM/CD/TEC. |
| P1 | Used by ASP/MMU/NWC/VPUI. |
| P2 | Used only by other effective scripts or libs. |
| P3 | Only in dead files. |
| P3* | Referenced by an effective file, but only on code paths that are unreachable during map generation: Communitu's `IsPlotConnected(nil, ...)` route helpers, the debug highlight, and the commented-out `FloatMap:Save`. Stubs are enough. |
| P1* | `GetTeam` is a **Player** method in MMU (P1); in COM it is the unreachable Plot form. |

**Method attribution** comes from the C++ registration lists (`CvLuaPlot/Area/Player/Team/Game/Fractal.cpp`). Methods defined in Lua (ASP/FeatureGenerator/etc.) are excluded. Ambiguous names list both classes, e.g. `Plot/Area:IsWater`.

**Not engine symbols** (defined in Lua, so excluded): `PlotListTypes`, `ImpactLayers`, `AdjacentTilesCareAbout*Types`, `Plots()`, `Shuffle()`, every `ASP:*`, `FeatureGenerator:*`, `FractalWorld:*`, `MultilayeredFractal:*`.

**Include-time requirements** (they run during script load, so they are effectively P0 even when tagged P1): `GameInfo.CustomModOptions(...)`, `Game.GetNumYieldTypes`, `GameInfo.GreatPersons[i]` (VPUI), `#GameInfo.Natural_Wonder_Placement`, `#GameInfo.Resources`, `GameDefines.MAX_MAJOR_CIVS`, `GameDefines.MAX_MINOR_CIVS`, `DB.CreateQuery`, `Locale.Lookup` (ASP), and `Locale.ConvertTextKey` (CD, TEC). See engine-api.md §11.5.

**Counts by priority** (rows below): P0 178 · P1 52 · P1* 1 · P2 7 · P3 33 · P3* 8. `GameInfoTypes` keys are grouped by prefix.

## Map

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Map.CalculateAreas` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Map.ChangeAIMapHint` | P0 |  |  |  |  |  |  | x | x | x |  |  |  |  |  | 16: Arborea, Archipelago, Communitu_79a, Continental_Drift, Ice_Age, Large_Islands, Rainforest, Script_Oceania ... |  |
| `Map.DefaultContinentStamper` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Map.FindBiggestArea` | P0 |  |  |  |  |  |  |  | x | x |  |  |  |  |  | 15: Arborea, Continental_Drift, Continents, ContinentsPlus, Europe, Frontier, Great_Plains_XP, North_vs_South ... |  |
| `Map.FindBiggestLandmassID` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 6: Arborea, Communitu_79a, Europe, Frontier, North_vs_South, Rainforest |  |
| `Map.FindWater` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `Map.GetArea` | P0 | x |  |  |  |  |  |  | x |  | x |  |  |  |  | 3: Continental_Drift, Europe, Script_Oceania |  |
| `Map.GetCustomOption` | P0 |  |  |  |  |  |  | x | x | x |  | x |  |  |  | 32: Arborea, Archipelago, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus, Donut ... |  |
| `Map.GetFractalFlags` | P0 |  | x | x | x |  |  |  |  |  |  |  |  |  | x | 32: Arborea, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier, Ice_Age, Pangaea ... |  |
| `Map.GetGridSize` | P0 |  | x | x | x |  |  | x | x |  | x | x |  |  | x | 56: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `Map.GetLandPlots` | P0 |  |  |  |  |  |  | x | x | x |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, Tectonic v6 - VI |  |
| `Map.GetNumPlots` | P0 | x |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `Map.GetNumTilesOfLandmass` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 5: Arborea, Communitu_79a, Europe, Frontier, Rainforest |  |
| `Map.GetPlot` | P0 |  | x | x |  |  |  | x | x |  | x | x | x |  |  | 49: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `Map.GetPlotByIndex` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 1: Communitu_79a |  |
| `Map.GetWorldSize` | P0 |  | x | x | x |  |  | x | x | x | x |  |  |  | x | 41: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `Map.IsWrapX` | P0 |  | x |  |  |  |  |  | x | x | x | x |  |  |  | 3: Continental_Drift, Skirmish, Tectonic v6 - VI |  |
| `Map.PlotDirection` | P0 | x | x |  | x |  |  | x | x |  | x |  | x |  |  | 27: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `Map.PlotDistance` | P0 |  |  |  |  |  |  | x |  |  | x |  |  |  |  | 1: Communitu_79a |  |
| `Map.PlotXYWithRangeCheck` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Map.Rand` | P0 | x | x |  | x | x |  | x | x | x | x | x |  |  | x | 50: Amazon, Amazon_XP, Arborea, Archipelago, Boreal, Communitu_79a, Continental_Drift, Continents ... |  |
| `Map.RecalculateAreas` | P0 | x |  |  |  |  |  | x | x |  | x |  |  |  |  | 14: Arborea, Communitu_79a, Continental_Drift, Continents, ContinentsPlus, Europe, Frontier, Pangaea ... |  |
| `Map.IsWrapY` | P1 |  |  |  |  |  |  |  |  |  | x | x |  |  |  |  |  |
| `Map.MaxPlotDistance` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Map.GetSeaLevel` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 3: ContinentsWorld, FourContinentsWorld, PangaeaWorld |  |
| `Map.Areas` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `Map.GetClimate` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | FeatureGenerator@base, FeatureGenerator@exp1, FeatureGenerator@exp2 |
| `Map.GetNumResources` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `Map.GetNumResourcesOnLand` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `Map.GetPlotXY` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `Map.GetRandomResourceQuantity` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |

## Fractal

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Fractal.Create` | P0 |  | x | x | x |  |  | x |  |  |  |  |  |  | x | 48: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continents, ContinentsPlus, ContinentsWorld ... |  |
| `Fractal.CreateRifts` | P0 |  |  |  | x |  |  |  |  |  |  |  |  |  | x |  |  |
| `Fractal:BuildRidges` | P0 |  |  |  | x |  |  |  |  |  |  |  |  |  | x | 27: Arborea, Boreal, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier, Highlands ... |  |
| `Fractal:GetHeight` | P0 |  | x | x | x |  |  | x |  |  |  |  |  |  | x | 51: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continents, ContinentsPlus, ContinentsWorld ... |  |

## Plot

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Plot/Area:IsWater` | P0 | x |  | x |  |  |  | x | x | x | x | x | x |  |  | 37: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Donut, Europe, Four_Corners ... |  |
| `Plot:Area` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `Plot:CanHaveFeature` | P0 | x | x |  |  |  |  | x | x | x |  |  |  |  |  | 17: Amazon, Amazon_XP, Communitu_79a, Continental_Drift, Great_Plains, Great_Plains_XP, Ice_Age, Lakes ... |  |
| `Plot:CanHaveImprovement` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Plot:GetArea` | P0 | x |  |  |  |  |  |  | x |  | x |  |  |  |  | 28: Amazon, Amazon_XP, Arborea, Boreal, Continental_Drift, ContinentsPlus, Europe, Four_Corners ... |  |
| `Plot:GetFeatureType` | P0 |  | x |  |  |  |  | x | x |  | x | x | x |  |  | 17: Amazon, Amazon_XP, Communitu_79a, Continental_Drift, Europe, Great_Plains, Great_Plains_XP, Ring ... |  |
| `Plot:GetImprovementType` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Plot:GetIndex` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 1: Communitu_79a |  |
| `Plot:GetInlandCorner` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `Plot:GetLandmass` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 7: Arborea, Communitu_79a, Continental_Drift, Europe, Frontier, Rainforest, Ring |  |
| `Plot:GetPlotType` | P0 | x | x |  |  |  |  | x | x |  | x | x | x |  |  | 46: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `Plot:GetResourceType` | P0 | x |  |  |  |  |  | x |  |  | x | x |  |  |  | 5: Amazon, Amazon_XP, Communitu_79a, Great_Plains, Great_Plains_XP |  |
| `Plot:GetRiverEFlowDirection` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:GetRiverSEFlowDirection` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:GetRiverSWFlowDirection` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:GetTerrainType` | P0 | x | x | x |  |  |  | x | x | x | x | x | x |  |  | 40: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, ContinentsPlus, Donut, Europe ... |  |
| `Plot:GetX` | P0 | x |  |  | x |  |  | x | x |  | x | x | x |  |  | 25: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `Plot:GetY` | P0 | x |  |  |  |  |  | x | x |  | x | x | x |  |  | 25: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `Plot:IsAdjacentToLand` | P0 | x | x |  |  |  |  |  | x | x | x |  |  |  |  | 3: Continental_Drift, Script_Oceania, Tectonic v6 - VI |  |
| `Plot:IsAdjacentToShallowWater` | P0 | x |  |  |  |  |  |  | x | x |  |  |  |  |  | 2: Continental_Drift, Tectonic v6 - VI |  |
| `Plot:IsCoastalLand` | P0 | x | x |  |  |  |  |  | x |  | x |  |  |  |  | 10: Amazon, Amazon_XP, Boreal, Continental_Drift, Great_Plains, Great_Plains_XP, InlandSea, Skirmish ... |  |
| `Plot:IsFreshWater` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 1: Communitu_79a |  |
| `Plot:IsHills` | P0 | x |  |  |  |  |  | x | x |  |  |  |  |  |  | 11: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Great_Plains, Great_Plains_XP, InlandSea ... |  |
| `Plot:IsImpassable` | P0 | x |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `Plot:IsLake` | P0 |  | x |  |  |  |  | x | x |  | x | x | x |  |  | 6: Communitu_79a, Continental_Drift, Europe, Great_Plains_XP, Script_Oceania, Terra |  |
| `Plot:IsMountain` | P0 | x |  |  |  |  |  | x | x |  | x |  |  |  |  | 12: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Great_Plains, Great_Plains_XP ... |  |
| `Plot:IsNEOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:IsNWOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:IsRiver` | P0 | x | x |  |  |  |  |  | x |  | x |  |  |  |  | 9: Amazon, Amazon_XP, Continental_Drift, Europe, Great_Plains_XP, Tilted_Axis, WB_Script_Random_Canada, WB_Script_Random_North_America ... |  |
| `Plot:IsRiverSide` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:IsStartingPlot` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Plot:IsWOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:SetArea` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Plot:SetContinentArtType` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 6: Amazon, Amazon_XP, Communitu_79a, Great_Plains, Great_Plains_XP, Script_Random_China |  |
| `Plot:SetFeatureType` | P0 | x | x |  |  |  |  | x | x | x | x |  | x |  |  | 23: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Great_Plains, Great_Plains_XP ... |  |
| `Plot:SetImprovementType` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 2: WB_Script_Random_Earth, WB_Script_Randomize_Everything |  |
| `Plot:SetNEOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:SetNWOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:SetPlotType` | P0 | x | x | x |  |  |  | x | x |  | x |  | x |  |  | 30: Amazon, Amazon_XP, Arborea, Communitu_79a, Continental_Drift, Continents, ContinentsPlus, Donut ... |  |
| `Plot:SetResourceType` | P0 |  |  |  |  |  |  | x |  |  | x |  |  |  |  | 5: Amazon, Amazon_XP, Communitu_79a, Great_Plains, Great_Plains_XP |  |
| `Plot:SetTerrainType` | P0 | x | x |  |  |  |  | x | x | x | x |  | x |  |  | 14: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Great_Plains_XP, Ring ... |  |
| `Plot:SetWOfRiver` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `Plot:CalculateYield` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `Plot:GetNumResource` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `Plot:IsAdjacentToArea` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Plot:IsAdjacentToLandmass` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Plot:IsNaturalWonder` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Plot/Player:GetTeam` | P1* |  |  |  |  |  |  | x |  |  |  | x |  |  |  | 5: Communitu_79a, Hemispheres, North_vs_South, Skirmish, West_vs_East |  |
| `Plot:IsFlatlands` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 6: Amazon, Amazon_XP, Great_Plains, Great_Plains_XP, Ring, Skirmish |  |
| `Plot:CanHaveResource` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `Plot:GetRouteType` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:IsCity` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Plot:IsRevealed` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |

## Area

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Area:GetNumImprovements` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Area:GetNumRiverEdges` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `Area:GetNumTiles` | P0 | x |  |  |  |  |  |  | x | x |  |  |  |  |  | 22: Amazon, Amazon_XP, Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, Europe ... |  |
| `Area/Player:GetID` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 13: Arborea, Continents, ContinentsPlus, Europe, Frontier, Great_Plains_XP, North_vs_South, Pangaea ... |  |
| `Area:CountNumUniqueResourceTypes` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |

## Player / Team

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Player:GetStartingPlot` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Player:IsEverAlive` | P0 | x |  |  |  |  |  |  |  |  |  | x |  |  |  | 2: Large_Islands, Ring |  |
| `Players[]` | P0 | x |  |  |  |  |  |  |  |  | x | x |  |  |  | 7: Frontier, Hemispheres, Large_Islands, North_vs_South, Ring, Skirmish, West_vs_East |  |
| `Player/Plot:SetStartingPlot` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  | 5: Frontier, Hemispheres, North_vs_South, Skirmish, West_vs_East |  |
| `Player:GetCivilizationType` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  | 1: Frontier |  |
| `Player:GetMinorCivTrait` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Player:GetDominantPolicyBranchForTitle` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `Player:GetLeaderType` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `Player:GetNickName` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `Player:IsHuman` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |

## Game

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Game.GetStartEra` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Game.IsOption` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `Game.CountCivTeamsEverAlive` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `Game.GetCustomOption` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  | 1: Frontier |  |
| `Game.GetNumYieldTypes` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `Game.GetResourceUsageType` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Game.CountCivPlayersAlive` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |

## PreGame

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `PreGame.GetCivilizationShortDescription` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `PreGame.GetLeaderName` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |

## GameInfo

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `GameInfo.Eras[]` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `GameInfo.Features()` | P0 | x |  |  |  |  |  | x | x |  |  |  |  |  |  | 6: Communitu_79a, Continental_Drift, Europe, Great_Plains_XP, Script_Oceania, WB_Script_Random_Russia |  |
| `GameInfo.Features[]` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `GameInfo.Improvements()` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `GameInfo.Terrains()` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `GameInfo.Terrains.TYPE` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `GameInfo.Worlds()` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `GameInfo.Worlds.TYPE` | P0 |  | x |  |  |  |  | x | x | x |  |  |  |  |  | 32: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, ContinentsPlus, Donut, Europe ... |  |
| `GameInfo.Worlds[]` | P0 |  | x | x |  |  |  | x | x | x |  |  |  |  |  | 28: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, ContinentsPlus, Donut, Europe ... |  |
| `GameInfo.Civilization_Leaders{filter}` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo.Civilization_Start_Along_Ocean{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Along_River{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Place_First_Along_Ocean{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Prefer_Mountain{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Prefer_Snow{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Region_Avoid{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilization_Start_Region_Priority{filter}` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameInfo.Civilizations[]` | P1 |  |  |  |  |  |  |  |  |  | x |  |  | x |  | 1: Frontier |  |
| `GameInfo.CustomModOptions()` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo.IconTextureAtlases{filter}` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo.Leader_Traits{filter}` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo.Natural_Wonder_Placement[]` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `GameInfo.Regions[]` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `GameInfo.Resources[]` | P1 |  |  |  |  |  |  |  |  |  | x | x |  |  |  |  |  |
| `GameInfo.Yields.TYPE` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo[name]` | P1 |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| `GameInfo.SeaLevels[]` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 3: ContinentsWorld, FourContinentsWorld, PangaeaWorld |  |
| `GameInfo.Climates[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | FeatureGenerator@base, FeatureGenerator@exp1, FeatureGenerator@exp2 |
| `GameInfo.Leaders[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `GameInfo.MapScripts{filter}` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `GameInfo.Map_Sizes()` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `GameInfo.Maps[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `GameInfo.Months[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameCalendarUtilities@base |
| `GameInfo.Natural_Wonder_Placement()` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | AssignStartingPlots@cp, AssignStartingPlots@exp1, AssignStartingPlots@exp2 |
| `GameInfo.PolicyBranchTypes[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `GameInfo.ResourceClasses[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | WorldBuilderRandomItems@base, WorldBuilderRandomItems@exp1, WorldBuilderRandomItems@exp2 |
| `GameInfo.Resources()` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | AssignStartingPlots@base, AssignStartingPlots@cp, AssignStartingPlots@exp1, AssignStartingPlots@exp2 ... |
| `GameInfo.Seasons[]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameCalendarUtilities@base |

## GameInfoTypes

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `GameInfoTypes.TERRAIN_*` | P0 |  |  | x |  |  |  |  |  |  |  |  |  |  |  | 17: Amazon, Amazon_XP, Europe, Great_Plains, Great_Plains_XP, Sandstorm, Script_Random_China, WB_Script_Random_Africa ... |  |
| `enum:GameInfoTypes[...]` | P0 |  |  | x |  |  |  |  |  |  | x | x |  | x |  | 17: Amazon, Amazon_XP, Europe, Great_Plains, Great_Plains_XP, Sandstorm, Script_Random_China, WB_Script_Random_Africa ... |  |
| `GameInfoTypes.REGION_*` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  | 1: Great_Plains_XP |  |
| `GameInfoTypes.RESOURCE_*` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `GameInfoTypes.WORLDSIZE_*` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  | 1: Great_Plains_XP |  |

## GameDefines

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `GameDefines.DEEP_WATER_TERRAIN` | P0 | x |  |  |  |  |  |  | x | x |  |  |  |  |  | 2: Continental_Drift, Tectonic v6 - VI |  |
| `GameDefines.LAKE_PLOT_RAND` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `GameDefines.MAX_CIV_PLAYERS` | P0 | x |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `GameDefines.MIN_WATER_SIZE_FOR_OCEAN` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `GameDefines.PLOTS_PER_RIVER_EDGE` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `GameDefines.RIVER_SOURCE_MIN_RIVER_RANGE` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `GameDefines.RIVER_SOURCE_MIN_SEAWATER_RANGE` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 8: Amazon, Amazon_XP, Boreal, Great_Plains, Great_Plains_XP, InlandSea, Skirmish, West_vs_East |  |
| `GameDefines.SHALLOW_WATER_TERRAIN` | P0 | x |  |  |  |  |  |  | x | x |  |  |  |  |  | 2: Continental_Drift, Tectonic v6 - VI |  |
| `GameDefines.MAX_MAJOR_CIVS` | P1 |  |  |  |  |  |  |  |  |  | x | x |  |  |  | 3: Frontier, Large_Islands, Ring |  |
| `GameDefines.MAX_MINOR_CIVS` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `GameDefines.WEEKS_PER_MONTHS` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameCalendarUtilities@base |

## Enums

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DirectionTypes.DIRECTION_EAST` | P0 | x | x |  | x |  |  | x | x |  |  |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.DIRECTION_NORTHEAST` | P0 | x | x |  | x |  |  | x | x |  |  |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.DIRECTION_NORTHWEST` | P0 | x | x |  | x |  |  | x | x |  |  |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.DIRECTION_SOUTHEAST` | P0 | x | x |  |  |  |  | x | x |  | x |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.DIRECTION_SOUTHWEST` | P0 | x | x |  |  |  |  | x | x |  |  |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.DIRECTION_WEST` | P0 | x | x |  | x |  |  | x | x |  |  |  | x |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `DirectionTypes.NO_DIRECTION` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `DirectionTypes.NUM_DIRECTION_TYPES` | P0 | x |  |  |  |  |  | x | x |  |  |  |  |  |  | 25: Amazon, Amazon_XP, Boreal, Communitu_79a, Continental_Drift, Europe, Four_Corners, Great_Plains ... |  |
| `FeatureTypes.FEATURE_ATOLL` | P0 |  | x |  |  |  |  | x | x |  | x |  |  |  |  | 2: Communitu_79a, Continental_Drift |  |
| `FeatureTypes.FEATURE_FLOOD_PLAINS` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 3: Communitu_79a, Great_Plains, Great_Plains_XP |  |
| `FeatureTypes.FEATURE_FOREST` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 5: Amazon, Amazon_XP, Communitu_79a, Great_Plains, Great_Plains_XP |  |
| `FeatureTypes.FEATURE_ICE` | P0 |  | x |  |  |  |  | x | x |  | x |  | x |  |  | 5: Communitu_79a, Continental_Drift, Europe, Great_Plains_XP, Script_Oceania |  |
| `FeatureTypes.FEATURE_JUNGLE` | P0 |  | x |  |  |  |  | x |  |  | x | x |  |  |  | 3: Amazon, Amazon_XP, Communitu_79a |  |
| `FeatureTypes.FEATURE_MARSH` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 6: Amazon, Amazon_XP, Communitu_79a, Great_Plains, Great_Plains_XP, Terra |  |
| `FeatureTypes.FEATURE_OASIS` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 3: Communitu_79a, Great_Plains, Great_Plains_XP |  |
| `FeatureTypes.NO_FEATURE` | P0 |  | x |  |  |  |  | x |  |  | x |  | x |  |  | 13: Amazon, Amazon_XP, Communitu_79a, Europe, Great_Plains, Great_Plains_XP, Terra, WB_Script_Random_Africa ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_NORTH` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 23: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_NORTHEAST` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_NORTHWEST` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_SOUTH` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 23: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_SOUTHEAST` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.FLOWDIRECTION_SOUTHWEST` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 24: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.NO_FLOWDIRECTION` | P0 | x |  |  |  |  |  | x |  |  |  |  |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `FlowDirectionTypes.NUM_FLOWDIRECTION_TYPES` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `GameOptionTypes.GAMEOPTION_NO_GOODY_HUTS` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `PlotTypes.NUM_PLOT_TYPES` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  | 23: Amazon, Amazon_XP, Boreal, Europe, Four_Corners, Great_Plains, Great_Plains_XP, Highlands ... |  |
| `PlotTypes.PLOT_HILLS` | P0 |  | x |  | x |  |  | x | x | x | x | x |  |  | x | 43: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `PlotTypes.PLOT_LAND` | P0 | x | x | x | x |  |  | x | x | x | x |  |  |  | x | 54: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `PlotTypes.PLOT_MOUNTAIN` | P0 |  | x |  | x |  |  | x | x | x | x |  | x |  | x | 47: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `PlotTypes.PLOT_OCEAN` | P0 | x | x |  | x |  |  | x | x | x | x | x | x |  | x | 45: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, Continents, ContinentsPlus ... |  |
| `TerrainTypes.NO_TERRAIN` | P0 |  |  | x |  |  |  |  |  |  |  |  |  |  |  | 18: Donut, North_vs_South, Ring, Sandstorm, Skirmish, Tilted_Axis, WB_Script_Antarctica_Thawed, WB_Script_Random_Africa ... |  |
| `TerrainTypes.PLOT_HILLS` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `TerrainTypes.TERRAIN_COAST` | P0 |  | x |  |  |  |  | x | x |  | x | x | x |  |  | 6: Communitu_79a, Continental_Drift, Europe, Script_Oceania, Terra, WB_Script_Random_Scandinavia |  |
| `TerrainTypes.TERRAIN_DESERT` | P0 |  |  |  |  |  |  | x |  |  | x |  |  |  |  | 7: Amazon, Amazon_XP, Communitu_79a, Europe, Great_Plains_XP, Script_Random_China, Terra |  |
| `TerrainTypes.TERRAIN_GRASS` | P0 |  |  |  |  |  |  | x |  |  | x |  |  |  |  | 9: Amazon, Amazon_XP, Communitu_79a, Europe, Great_Plains_XP, Rainforest, Script_Random_China, Terra ... |  |
| `TerrainTypes.TERRAIN_OCEAN` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 2: Boreal, Communitu_79a |  |
| `TerrainTypes.TERRAIN_PLAINS` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 7: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Great_Plains_XP, Script_Random_China |  |
| `TerrainTypes.TERRAIN_SNOW` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 20: Amazon, Amazon_XP, Boreal, Communitu_79a, ContinentsPlus, Europe, Four_Corners, Great_Plains ... |  |
| `TerrainTypes.TERRAIN_TUNDRA` | P0 |  | x |  |  |  |  | x |  |  | x |  |  |  |  | 7: Boreal, Communitu_79a, Europe, Great_Plains_XP, Ice_Age, Script_Oceania, Terra |  |
| `WorldSizeTypes.WORLDSIZE_DUEL` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `WorldSizeTypes.WORLDSIZE_HUGE` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `WorldSizeTypes.WORLDSIZE_LARGE` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `WorldSizeTypes.WORLDSIZE_SMALL` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `WorldSizeTypes.WORLDSIZE_STANDARD` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `WorldSizeTypes.WORLDSIZE_TINY` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `enum:WorldSizeTypes[...]` | P0 |  |  |  | x |  |  |  | x | x |  |  |  |  | x | 25: Arborea, Boreal, Continental_Drift, Continents, ContinentsPlus, ContinentsWorld, FourContinentsWorld, Frontier ... |  |
| `FeatureTypes.FEATURE_REEF` | P1 |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |
| `MinorCivTraitTypes.MINOR_CIV_TRAIT_MILITARISTIC` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `ResourceUsageTypes.RESOURCEUSAGE_LUXURY` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `ResourceUsageTypes.RESOURCEUSAGE_STRATEGIC` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `YieldTypes.YIELD_CULTURE` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `YieldTypes.YIELD_FAITH` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `YieldTypes.YIELD_FOOD` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `YieldTypes.YIELD_GOLD` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `YieldTypes.YIELD_PRODUCTION` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `YieldTypes.YIELD_SCIENCE` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `PlotTypes.PLOT_MOUNTAINS` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 3: Boreal, Highlands, Terra |  |
| `PlotTypes.PLOT_PEAK` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  | x | 6: Amazon, Amazon_XP, Great_Plains, Great_Plains_XP, Highlands, Script_Random_China |  |
| `FeatureTypes.FEATURE_FLOODPLAIN` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | AssignStartingPlots@base, AssignStartingPlots@exp1, AssignStartingPlots@exp2 |
| `enum:PolicyBranchTypes[...]` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |

## Globals

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `global:include()` | P0 | x | x |  |  |  |  | x | x | x | x | x | x |  |  | 61: Amazon, Amazon_XP, Arborea, Archipelago, Boreal, Communitu_79a, Continental_Drift, Continents ... |  |
| `global:print()` | P0 | x |  |  |  | x |  | x | x | x | x | x |  | x | x | 58: Amazon, Amazon_XP, Arborea, Archipelago, Boreal, Communitu_79a, Continental_Drift, Continents ... |  |

## Lua libs

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `math.abs` | P0 |  | x | x |  | x |  | x | x |  |  | x |  |  |  | 16: Boreal, Communitu_79a, Continental_Drift, Four_Corners, Great_Plains, Great_Plains_XP, Highlands, Ice_Age ... |  |
| `math.acos` | P0 |  |  |  |  |  |  |  | x |  |  |  |  |  |  | 1: Continental_Drift |  |
| `math.ceil` | P0 |  | x |  |  | x |  | x | x | x | x | x |  |  |  | 20: Amazon, Amazon_XP, Arborea, Communitu_79a, Continental_Drift, Europe, Frontier, Great_Plains ... |  |
| `math.clamp` | P0 |  |  | x |  |  |  |  |  |  |  |  |  |  |  | 13: ContinentsWorld, FourContinentsWorld, Four_Corners, Highlands, InlandSea, PangaeaWorld, Tilted_Axis, WB_Script_Eastern_Asia ... |  |
| `math.cos` | P0 |  |  |  |  |  |  | x | x | x |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, Tectonic v6 - VI |  |
| `math.floor` | P0 |  |  | x | x | x |  | x | x | x | x |  |  | x | x | 35: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continental_Drift, ContinentsPlus, Donut ... |  |
| `math.fmod` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 6: Communitu_79a, ContinentsPlus, Hemispheres, Large_Islands, PangaeaPlus, Script_Small_Continents_Plus |  |
| `math.frexp` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `math.huge` | P0 | x |  |  |  |  |  | x |  |  |  | x |  |  |  | 22: Amazon, Amazon_XP, Boreal, Communitu_79a, Europe, Four_Corners, Great_Plains, Great_Plains_XP ... |  |
| `math.ldexp` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `math.max` | P0 |  |  | x | x |  |  | x | x |  | x | x |  |  | x | 13: Arborea, Communitu_79a, Continental_Drift, Frontier, Ice_Age, Pangaea, PangaeaPlus, Rainforest ... |  |
| `math.min` | P0 |  |  |  |  |  |  | x | x |  | x | x |  |  |  | 21: Amazon, Amazon_XP, Arborea, Communitu_79a, Continental_Drift, Europe, Frontier, Great_Plains ... |  |
| `math.modf` | P0 |  |  |  |  | x |  | x |  |  |  |  |  |  |  | 6: Communitu_79a, ContinentsPlus, Hemispheres, Large_Islands, PangaeaPlus, Script_Small_Continents_Plus |  |
| `math.pi` | P0 |  |  |  |  |  |  | x | x |  |  |  |  |  |  | 2: Communitu_79a, Continental_Drift |  |
| `math.pow` | P0 |  |  |  |  |  |  | x | x | x |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, Tectonic v6 - VI |  |
| `math.rad` | P0 |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |
| `math.random` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `math.randomseed` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `math.sin` | P0 |  |  |  |  |  |  | x | x | x |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, Tectonic v6 - VI |  |
| `math.sqrt` | P0 |  |  |  |  |  |  | x | x | x |  | x |  |  |  | 4: Communitu_79a, Continental_Drift, Donut, Tectonic v6 - VI |  |
| `math.tan` | P0 |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |
| `os.clock` | P0 |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `string.format` | P0 |  |  |  |  |  |  | x | x |  | x |  |  |  |  | 2: Communitu_79a, Continental_Drift |  |
| `string.match` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `string.sub` | P0 |  |  |  |  |  |  |  | x |  |  |  |  |  |  | 1: Continental_Drift |  |
| `table.fill` | P0 |  |  |  | x | x |  | x |  |  | x | x |  |  | x | 33: Amazon, Amazon_XP, Arborea, Boreal, Communitu_79a, Continents, ContinentsPlus, ContinentsWorld ... |  |
| `table.insert` | P0 | x | x |  | x |  |  | x | x | x | x | x |  | x | x | 22: Amazon, Amazon_XP, Communitu_79a, Continental_Drift, ContinentsPlus, Europe, Frontier, Great_Plains ... |  |
| `table.maxn` | P0 |  | x |  |  |  |  |  | x |  | x |  |  |  |  | 12: Amazon, Amazon_XP, Continental_Drift, Europe, Frontier, Great_Plains_XP, Hemispheres, North_vs_South ... |  |
| `table.remove` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 13: Amazon, Amazon_XP, Communitu_79a, ContinentsPlus, Europe, Frontier, Great_Plains, Great_Plains_XP ... |  |
| `table.sort` | P0 |  |  |  |  |  |  | x |  |  | x | x |  |  |  | 10: Communitu_79a, ContinentsPlus, Europe, Frontier, Great_Plains_XP, Hemispheres, PangaeaPlus, Skirmish ... |  |
| `coroutine.wrap` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `coroutine.yield` | P1 |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |
| `table.concat` | P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 4: ContinentsPlus, Hemispheres, PangaeaPlus, Script_Small_Continents_Plus |  |
| `io-file:close` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `io-file:write` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `io.open` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |

## Other engine

| Symbol | Pri | MG | FG | TG | FW | IM | FLV | COM | CD | TEC | ASP | MMU | NWC | VPUI | MLF | Other effective scripts/libs | Only in dead/overridden files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Locale.ConvertTextKey` | P0 |  |  |  |  |  |  |  | x | x |  |  |  |  |  | 2: Continental_Drift, Tectonic v6 - VI |  |
| `Map:IsWrapX` | P0 |  |  |  |  |  |  | x | x |  |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, WB_Script_Random_Scandinavia |  |
| `Map:IsWrapY` | P0 |  |  |  |  |  |  | x | x |  |  |  |  |  |  | 3: Communitu_79a, Continental_Drift, WB_Script_Random_Scandinavia |  |
| `MapModData` | P0 |  |  |  |  |  | x |  |  |  | x | x |  | x |  | 2: Europe, Great_Plains_XP |  |
| `Modding.GetActivatedModEntryPoints` | P0 | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `DB.CreateQuery` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `DB.Query` | P1 |  |  |  |  |  |  |  |  |  |  | x |  | x |  |  |  |
| `Locale.Lookup` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Modding.GetActivatedMods` | P1 |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |
| `Game:IsNetworkMultiPlayer` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | GameplayUtilities@base |
| `Locale.IsNilOrWhitespace` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `Path.GetFileNameWithoutExtension` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `UI.GetMapPreview` | P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | MapUtilities@base |
| `(City):Plot` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |
| `Events.SerialEventHexHighlight` | P3* |  |  |  |  |  |  | x |  |  |  |  |  |  |  | 1: Communitu_79a |  |