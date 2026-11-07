------------------------------------------------------------------------------
-- Template_Map.lua  --  minimal, VP-compatible map script skeleton
-- Copy to "<My Games>\Sid Meier's Civilization 5\Maps\<YourName>.lua" and edit.
-- Pipeline order below is mandatory (MapGenerator.lua: "do not change this order").
------------------------------------------------------------------------------
include("MapGenerator");
include("FractalWorld");
include("FeatureGenerator");
include("TerrainGenerator");

------------------------------------------------------------------------------
function GetMapScriptInfo()
	local world_age, temperature, rainfall, sea_level, resources = GetCoreMapOptions();
	return {
		Name = "Template Map",
		Description = "Fractal continents skeleton with the five standard options.",
		IsAdvancedMap = false,
		SupportsMultiplayer = true,
		IconIndex = 1,
		SortIndex = 2,
		-- Option IDs are the 1-based positions in this list: 1=age 2=temp 3=rain 4=sea 5=resources
		CustomOptions = {world_age, temperature, rainfall, sea_level, resources},
	};
end

------------------------------------------------------------------------------
function GetMapInitData(worldSize)
	-- Return nothing to use the Worlds table defaults (80x52 standard, WrapX, no WrapY).
	-- Example override: shrink width by 10% and keep height.
	-- local w = GameInfo.Worlds[worldSize];
	-- return { Width = math.floor(w.GridWidth * 0.9), Height = w.GridHeight, WrapX = true };
end

------------------------------------------------------------------------------
-- Resolve an option whose last value is "Random" to a concrete 1-based value.
local function Opt(id, numReal)
	local v = Map.GetCustomOption(id) or 2;
	if v > numReal then v = 1 + Map.Rand(numReal, "Random option " .. id); end
	return v;
end

------------------------------------------------------------------------------
function GeneratePlotTypes()
	print("Generating Plot Types (Template_Map) ...");
	local fractal_world = FractalWorld.Create();
	fractal_world:InitFractal{continent_grain = 2, rift_grain = -1};
	local plotTypes = fractal_world:GeneratePlotTypes{
		sea_level = Opt(4, 3),
		world_age = Opt(1, 3),
	};
	SetPlotTypes(plotTypes);   -- 1-based table, index = y*W + x + 1
	GenerateCoasts();          -- water next to land becomes COAST, rest OCEAN
end

------------------------------------------------------------------------------
function GenerateTerrain()
	print("Generating Terrain (Template_Map) ...");
	local terraingen = TerrainGenerator.Create{temperature = Opt(2, 3)};
	SetTerrainTypes(terraingen:GenerateTerrain());   -- 0-based table, index = y*W + x
end

------------------------------------------------------------------------------
function AddFeatures()
	print("Adding Features (Template_Map) ...");
	local featuregen = FeatureGenerator.Create{rainfall = Opt(3, 3)};
	featuregen:AddFeatures();
end

------------------------------------------------------------------------------
function StartPlotSystem()
	print("Creating start plot database (Template_Map) ...");
	local res = Map.GetCustomOption(5) or 2;   -- 1..3 density, 4 legendary, 5 strategic balance
	if res == 6 then res = 1 + Map.Rand(3, "Random resources"); end

	local start_plot_database = AssignStartingPlots.Create();
	-- method: RegionDivision.CONTINENTAL splits by landmass; RECTANGULAR for pangaea-like maps
	start_plot_database:GenerateRegions{method = RegionDivision.CONTINENTAL, resources = res};
	start_plot_database:ChooseLocations();
	start_plot_database:BalanceAndAssign();
	start_plot_database:PlaceNaturalWonders();
	start_plot_database:PlaceResourcesAndCityStates();
end
