-- tests/test_engine.lua -- engine tests: hex math, plot setters, rivers, areas, landmasses, GameInfo, Map.Rand.
-- Run with: python tests/run_lua_tests.py   (lupa.lua51; package.path includes engine/?.lua)
-- Needs engine/data (python host/gamedb.py).

local results = { passed = 0, failed = 0, failures = {}, log = {} }
local function log(fmt, ...) results.log[#results.log + 1] = string.format(fmt, ...) end
local function test(name, fn)
	local ok, err = pcall(fn)
	if ok then results.passed = results.passed + 1
	else
		results.failed = results.failed + 1
		results.failures[#results.failures + 1] = name .. ": " .. tostring(err)
	end
end
local function eq(a, b, msg)
	if a ~= b then error((msg or "") .. " expected " .. tostring(b) .. ", got " .. tostring(a), 2) end
end
local function truthy(v, msg) if not v then error((msg or "") .. " expected true", 2) end end
local function falsy(v, msg) if v then error((msg or "") .. " expected false", 2) end end
local function errors(fn, pattern, msg)
	local ok, err = pcall(fn)
	if ok then error((msg or "") .. " expected an error", 2) end
	if pattern and not tostring(err):find(pattern, 1, true) then
		error((msg or "") .. " error '" .. tostring(err) .. "' does not contain '" .. pattern .. "'", 2)
	end
end

-- locate engine/data from package.path
local dataDir
for entry in package.path:gmatch("[^;]+") do
	local dir = entry:match("^(.*)[/\\]%?%.lua$")
	if dir and dir:match("engine$") then
		local f = io.open(dir .. "/data/gameinfo.lua", "r")
		if f then f:close(); dataDir = dir .. "/data"; break end
	end
end
if not dataDir then
	results.failed = 1
	results.failures[1] = "engine/data/gameinfo.lua not found (run python host/gamedb.py)"
	return results
end

local hexmath = require("hexmath")
local Random = require("random")
local gameinfo = require("gameinfo")
local mapmod = require("map")
local gamemod = require("game")

local GI = gameinfo.new(dataDir)

-- fresh engine state + map; installs Players/Game/enums into _G (like the real bootstrap)
local function newMap(W, H, opts)
	opts = opts or {}
	local S = mapmod.newState(GI, { seed = opts.seed or 1, areas_mode = opts.areas_mode })
	gamemod.install(S, _G)
	if W then mapmod.initMap(S, W, H, opts.wrapX ~= false, opts.wrapY or false, 90, -90) end
	return S, S.Map
end

local PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN = 0, 1, 2, 3
local GRASS, PLAINS, DESERT, COAST, OCEAN, T_MOUNTAIN, T_HILL = 0, 1, 2, 5, 6, 7, 8

-- set every plot from a picture: rows given north (top) to south; '#' land, 'M' mountain, '.' water
local function paint(S, rows)
	local H = #rows
	for r = 1, H do
		local y = H - r
		local row = rows[r]
		for x = 0, #row - 1 do
			local ch = row:sub(x + 1, x + 1)
			local p = S.Map.GetPlot(x, y)
			if ch == "#" then p:SetPlotType(PLOT_LAND); p:SetTerrainType(GRASS)
			elseif ch == "M" then p:SetPlotType(PLOT_MOUNTAIN); p:SetTerrainType(GRASS)
			else p:SetPlotType(PLOT_OCEAN); p:SetTerrainType(OCEAN) end
		end
	end
end

---------------------------------------------------------------------------------------------
-- hex math
---------------------------------------------------------------------------------------------
test("hexmath: neighbours even row (y=2)", function()
	local S, Map = newMap(10, 6, { wrapX = false })
	local want = { [0] = { 2, 3 }, { 3, 2 }, { 2, 1 }, { 1, 1 }, { 1, 2 }, { 1, 3 } }
	for d = 0, 5 do
		local p = Map.PlotDirection(2, 2, d)
		eq(p:GetX(), want[d][1], "dir " .. d .. " x"); eq(p:GetY(), want[d][2], "dir " .. d .. " y")
	end
end)

test("hexmath: neighbours odd row (y=3)", function()
	local S, Map = newMap(10, 6, { wrapX = false })
	local want = { [0] = { 3, 4 }, { 3, 3 }, { 3, 2 }, { 2, 2 }, { 1, 3 }, { 2, 4 } }
	for d = 0, 5 do
		local p = Map.PlotDirection(2, 3, d)
		eq(p:GetX(), want[d][1], "dir " .. d .. " x"); eq(p:GetY(), want[d][2], "dir " .. d .. " y")
	end
end)

test("hexmath: wrap and edges", function()
	local S, Map = newMap(10, 6)
	eq(Map.PlotDirection(0, 2, 4):GetX(), 9, "W of x=0 wraps")
	eq(Map.PlotDirection(9, 3, 1):GetX(), 0, "E of x=9 wraps")
	eq(Map.PlotDirection(0, 0, 3), nil, "SW off the south edge")
	eq(Map.GetPlot(-1, 2):GetX(), 9, "GetPlot wraps x")
	eq(Map.GetPlot(-10, 2), nil, "coordRange quirk: -W maps to W (invalid)")
	eq(Map.GetPlot(3, 6), nil, "y out of range")
	eq(Map.PlotDirection(2, 2, 7):GetX(), 3, "NO_DIRECTION(7) -> 7%6 = EAST")
	eq(Map.PlotDistance(0, 0, 9, 0), 1, "wrapped distance")
	eq(Map.PlotDistance(0, 0, 3, 4), 5, "plain distance")
	local S2, Map2 = newMap(10, 6, { wrapX = false })
	eq(Map2.PlotDirection(0, 2, 4), nil, "no wrap: W of x=0")
	eq(Map2.PlotDistance(0, 0, 9, 0), 9, "unwrapped distance")
	errors(function() Map2.PlotDirection(0, 9, 0) end, "PlotDirection", "PlotDirection off-map y")
end)

test("hexmath: PlotXYWithRangeCheck uses hex-space offsets", function()
	local S, Map = newMap(20, 10, { wrapX = false })
	local count = 0
	for dx = -2, 2 do for dy = -2, 2 do
		if Map.PlotXYWithRangeCheck(10, 5, dx, dy, 2) then count = count + 1 end
	end end
	eq(count, 19, "radius-2 hex disc")
	local p = Map.PlotXYWithRangeCheck(10, 5, 0, 1, 1)
	eq(p:GetX(), 11, "odd row: hex (0,+1) is NE"); eq(p:GetY(), 6)
end)

test("hexmath: directionXY / ring order / distances", function()
	local G = hexmath.new(10, 6, true, false)
	for d = 0, 5 do
		local nx, ny = G.neighborXY(4, 3, d)
		eq(G.directionXY(4, 3, nx, ny), d, "directionXY dir " .. d)
		local rdx, rdy = hexmath.ringOffset(d + 1)
		eq(rdx, hexmath.DIR_DHX[d], "ring1 dhx " .. d); eq(rdy, hexmath.DIR_DY[d], "ring1 dy " .. d)
	end
	eq(G.directionXY(4, 3, 4, 3), 7, "same plot -> NO_DIRECTION")
	local x, y = hexmath.ringOffset(18); eq(x, -1); eq(y, 2)
	x, y = hexmath.ringOffset(90); eq(x, -1); eq(y, 5)
	eq(hexmath.hexDistance(2, -1), 2); eq(hexmath.hexDistance(2, 1), 3)
end)

---------------------------------------------------------------------------------------------
-- plot setters
---------------------------------------------------------------------------------------------
test("plot: initial state and identity", function()
	local S, Map = newMap(8, 6)
	local p = Map.GetPlot(3, 3)
	eq(p:GetPlotType(), PLOT_OCEAN); eq(p:GetTerrainType(), -1); eq(p:GetFeatureType(), -1)
	eq(p:GetArea(), -1); eq(p:GetLandmass(), -1); eq(p:GetRiverEFlowDirection(), 7)
	truthy(Map.GetPlot(3, 3) == Map.GetPlotByIndex(3 * 8 + 3), "canonical plot objects")
	eq(p:GetIndex(), 27)
	p:SetPlotType(PLOT_OCEAN)
	eq(p:GetTerrainType(), -1, "SetPlotType(OCEAN) on untouched ocean is a no-op")
	errors(function() return p:NoSuchMethod() end, "unimplemented Plot:NoSuchMethod")
	eq(p.someScriptField, nil, "non-method keys read nil")
	errors(function() return Map.NoSuchThing() end, "unimplemented Map.NoSuchThing")
end)

test("plot: SetPlotType terrain auto-fix and land counter", function()
	local S, Map = newMap(8, 6)
	local a, b = Map.GetPlot(3, 3), Map.GetPlot(4, 3)
	a:SetPlotType(PLOT_LAND)
	eq(a:GetTerrainType(), GRASS, "new land gets LAND_TERRAIN")
	eq(Map.GetLandPlots(), 1)
	b:SetPlotType(PLOT_LAND); b:SetTerrainType(PLAINS)
	b:SetPlotType(PLOT_OCEAN)
	eq(b:GetTerrainType(), COAST, "water next to land -> coast")
	eq(Map.GetLandPlots(), 1)
	a:SetPlotType(PLOT_MOUNTAIN)
	eq(a:GetTerrainType(), GRASS, "PLOT_MOUNTAIN never sets TERRAIN_MOUNTAIN")
	falsy(a:IsImpassable(), "PLOT_MOUNTAIN with grass terrain and no feature is passable")
	truthy(a:IsMountain())
	local c = Map.GetPlot(0, 0)
	c:SetPlotType(PLOT_LAND); c:SetPlotType(PLOT_OCEAN)
	eq(c:GetTerrainType(), OCEAN, "isolated water -> ocean")
	eq(PlotTypes.PLOT_PEAK, nil, "unknown enum keys read nil")
	a:SetPlotType(nil)
	eq(a:GetPlotType(), PLOT_MOUNTAIN, "nil coerces to 0")
end)

test("plot: SetTerrainType flips plot type (incl. TERRAIN_HILL Water=1)", function()
	local S, Map = newMap(8, 6)
	local p = Map.GetPlot(3, 3)
	p:SetPlotType(PLOT_LAND)
	p:SetResourceType(GameInfoTypes.RESOURCE_IRON, 3)
	p:SetTerrainType(COAST)
	eq(p:GetPlotType(), PLOT_OCEAN, "water terrain makes the plot ocean")
	eq(p:GetResourceType(), -1, "and erases the resource")
	p:SetTerrainType(GRASS)
	eq(p:GetPlotType(), PLOT_LAND)
	p:SetTerrainType(T_HILL)
	eq(p:GetPlotType(), PLOT_OCEAN, "TERRAIN_HILL has Water=1 in the DB")
	p:SetTerrainType(GRASS)
	p:SetTerrainType(T_MOUNTAIN)
	eq(p:GetPlotType(), PLOT_LAND); truthy(p:IsMountain(), "TERRAIN_MOUNTAIN -> IsMountain")
	truthy(p:IsImpassable(), "TERRAIN_MOUNTAIN is impassable")
	p:SetTerrainType(-1); eq(p:GetTerrainType(), T_MOUNTAIN, "-1 ignored")
end)

test("plot: resources / features", function()
	local S, Map = newMap(8, 6)
	local p = Map.GetPlot(3, 3)
	p:SetPlotType(PLOT_LAND)
	p:SetResourceType(GameInfoTypes.RESOURCE_WHEAT)
	eq(p:GetNumResource(), 0, "missing qty -> 0")
	p:SetResourceType(GameInfoTypes.RESOURCE_WHEAT, 5)
	eq(p:GetNumResource(), 0, "same resource: no-op, qty unchanged")
	p:SetResourceType(-1); p:SetResourceType(GameInfoTypes.RESOURCE_IRON, 4)
	eq(p:GetNumResource(), 4)
	p:SetFeatureType(FeatureTypes.FEATURE_FOREST)
	eq(p:GetFeatureType(), FeatureTypes.FEATURE_FOREST)
	falsy(p:CanHaveFeature(FeatureTypes.FEATURE_JUNGLE), "already has a feature")
	p:SetFeatureType(-1)
	truthy(p:CanHaveFeature(FeatureTypes.FEATURE_FOREST), "forest on grass")
	falsy(p:CanHaveFeature(FeatureTypes.FEATURE_OASIS), "oasis needs desert")
	p:SetPlotType(PLOT_MOUNTAIN)
	falsy(p:CanHaveFeature(FeatureTypes.FEATURE_FOREST), "no features on mountains")
	local q = Map.GetPlot(0, 0)
	errors(function() q:CanHaveFeature(FeatureTypes.FEATURE_ICE) end, "NO_TERRAIN")
end)

---------------------------------------------------------------------------------------------
-- rivers
---------------------------------------------------------------------------------------------
test("rivers: crossings only for land-land edges, desert flood plains rule", function()
	local S, Map = newMap(8, 6, { wrapX = false })
	local a, b = Map.GetPlot(3, 2), Map.GetPlot(4, 2)
	a:SetPlotType(PLOT_LAND); b:SetPlotType(PLOT_LAND)
	a:SetWOfRiver(true, FlowDirectionTypes.FLOWDIRECTION_NORTH)
	truthy(a:IsWOfRiver()); eq(a:GetRiverEFlowDirection(), FlowDirectionTypes.FLOWDIRECTION_NORTH)
	truthy(a:IsRiver(), "a is river"); truthy(b:IsRiver(), "b (across the edge) is river")
	truthy(a:IsRiverSide()); truthy(b:IsRiverSide())
	a:SetWOfRiver(false, 7)
	falsy(a:IsRiver()); falsy(b:IsRiver())
	-- land-water edge: flag set, but no crossing
	local c = Map.GetPlot(3, 4)
	c:SetPlotType(PLOT_LAND)
	c:SetWOfRiver(true, 0)
	truthy(c:IsWOfRiver()); falsy(c:IsRiver(), "edge towards water is not a crossing")
	-- crossings are NOT recomputed when the neighbour later becomes land
	Map.GetPlot(4, 4):SetPlotType(PLOT_LAND)
	falsy(c:IsRiver(), "stale crossing (only flag changes update crossings)")
	-- flow stored even without a flag change
	c:SetWOfRiver(true, 3); eq(c:GetRiverEFlowDirection(), 3)
	-- desert river: removing the feature puts flood plains back
	a:SetNEOfRiver(true, FlowDirectionTypes.FLOWDIRECTION_SOUTHEAST)
	local sw = Map.PlotDirection(3, 2, DirectionTypes.DIRECTION_SOUTHWEST)
	sw:SetPlotType(PLOT_LAND)
	a:SetNEOfRiver(false, 7); a:SetNEOfRiver(true, 2)   -- recompute with land on both sides
	truthy(a:IsRiver())
	a:SetTerrainType(DESERT)
	a:SetFeatureType(FeatureTypes.FEATURE_FLOOD_PLAINS)
	a:SetFeatureType(-1)
	eq(a:GetFeatureType(), FeatureTypes.FEATURE_FLOOD_PLAINS, "NO_FEATURE on river desert -> flood plains")
	-- erase (land -> ocean) clears own river flags
	a:SetPlotType(PLOT_OCEAN)
	falsy(a:IsNEOfRiver()); eq(a:GetRiverSWFlowDirection(), 7)
end)

---------------------------------------------------------------------------------------------
-- areas
---------------------------------------------------------------------------------------------
local N_SHAPE = {
	"..............",
	".##########...",
	".##########...",
	".##########...",
	".###....###...",
	".###....###...",
	".###....###...",
	".###....###...",
	"..............",
}

local function landAreas(S)
	local ids = {}
	for _, a in ipairs(S.areas) do if not a.water then ids[#ids + 1] = a end end
	return ids
end

test("areas: literal vs floodfill on an n-shaped island", function()
	local S, Map = newMap(14, 9, { wrapX = false, areas_mode = "literal" })
	paint(S, N_SHAPE)
	Map.RecalculateAreas()
	local la = landAreas(S)
	eq(#la, 2, "literal: the two legs become separate areas")
	local total = 0
	for _, a in ipairs(la) do total = total + a:GetNumTiles() end
	eq(total, 54, "all land assigned")
	local S2, Map2 = newMap(14, 9, { wrapX = false, areas_mode = "floodfill" })
	paint(S2, N_SHAPE)
	Map2.RecalculateAreas()
	eq(#landAreas(S2), 1, "floodfill: one land area")
	eq(Map2.FindBiggestArea(false):GetNumTiles(), 54)
	eq(Map.FindBiggestLandmassID(false) ~= nil, true)
	local lm = Map.GetPlot(2, 2):GetLandmass()
	eq(Map.GetNumTilesOfLandmass(lm), 54, "landmass = connected component")
	eq(Map.GetPlot(2, 2):Area():IsWater(), false)
	errors(function() return Map.GetPlot(2, 2):Area():IsLake() end, "IsLake")
	local n = 0
	for i, a in Map.Areas() do n = n + 1; eq(a:GetID(), S.areas[i + 1].id) end
	eq(n, #S.areas)
end)

test("areas: literal merges single mountains/ice into neighbours, impassability ignored", function()
	local S, Map = newMap(10, 5, { wrapX = false })
	paint(S, { "..........", ".########.", ".###M####.", ".########.", ".........." })
	Map.RecalculateAreas()
	local m = Map.GetPlot(4, 2)
	truthy(m:IsImpassable() == false, "PLOT_MOUNTAIN on grass is passable")
	local id = Map.GetPlot(3, 2):GetArea()
	eq(m:GetArea(), id, "mountain plot joins the land area")
end)

test("areas: CalculateAreas does not touch landmasses", function()
	local S, Map = newMap(10, 5, { wrapX = false })
	paint(S, { "..........", ".########.", ".########.", ".########.", ".........." })
	Map.RecalculateAreas()
	local p = Map.GetPlot(4, 2)
	local lmBefore = p:GetLandmass()
	p:SetArea(-1)
	p:SetPlotType(PLOT_OCEAN)
	Map.CalculateAreas()
	eq(p:GetLandmass(), lmBefore, "landmass id kept (stale)")
	falsy(p:IsLake(), "stale land landmass -> not a lake until RecalculateAreas")
	Map.RecalculateAreas()
	truthy(p:IsLake(), "after RecalculateAreas the 1-plot lake is a lake")
	truthy(Map.GetPlot(3, 2):IsFreshWater(), "land next to a lake is fresh water")
	falsy(Map.GetPlot(0, 0):IsLake(), "the surrounding sea is not a lake")
end)

test("landmasses: lake threshold MIN_WATER_SIZE_FOR_OCEAN", function()
	local S, Map = newMap(16, 7, { wrapX = false })
	paint(S, {
		"################",
		"#.........######",   -- 9-plot water body: lake
		"################",
		"#..........#####",   -- 10-plot water body: not a lake
		"################",
		"################",
		"################",
	})
	Map.RecalculateAreas()
	truthy(Map.GetPlot(1, 5):IsLake(), "9 tiles -> lake")
	falsy(Map.GetPlot(1, 3):IsLake(), "10 tiles -> ocean")
	eq(Map.GetNumTilesOfLandmass(Map.GetPlot(1, 3):GetLandmass()), 10)
	truthy(Map.GetPlot(1, 4):IsCoastalLand(), "coastal land (cached after recalc)")
	falsy(Map.GetPlot(13, 0):IsCoastalLand())
	errors(function() Map.GetNumTilesOfLandmass(999) end, "no such landmass")
end)

test("continent stamper consumes 3 map RNG draws", function()
	local S, Map = newMap(20, 8, { wrapX = false, seed = 7 })
	paint(S, {
		"....................",
		".#####......#####...",
		".#####......#####...",
		"....................",
		".#####.....######...",
		".#####.....######...",
		"....................",
		"....................",
	})
	Map.RecalculateAreas()
	local before = S.mapRand:getCallCount()
	Map.DefaultContinentStamper()
	eq(S.mapRand:getCallCount() - before, 3)
	local seen = {}
	for _, xy in ipairs({ { 2, 6 }, { 13, 6 }, { 2, 3 }, { 13, 3 } }) do
		local art = Map.GetPlot(xy[1], xy[2]):GetContinentArtType()
		truthy(art >= 1 and art <= 4, "art style 1..4")
		truthy(not seen[art], "distinct styles"); seen[art] = true
	end
	eq(Map.GetPlot(0, 0):GetContinentArtType(), 0, "water -> 0")
end)

---------------------------------------------------------------------------------------------
-- GameInfo
---------------------------------------------------------------------------------------------
test("GameInfo access forms", function()
	local G = GI.GameInfo
	eq(G.Terrains.TERRAIN_GRASS.ID, 0)
	eq(G.Terrains["TERRAIN_COAST"].ID, 5)
	eq(G.Terrains[3].Type, "TERRAIN_TUNDRA")
	eq(G.Terrains[5].Water, true, "boolean column -> Lua boolean")
	eq(G.Terrains[0].Water, false)
	eq(G.Terrains.NOPE, nil)
	eq(G.NoSuchTable, nil, "GameInfo[name] nil for missing tables")
	local n = 0
	for row in G.Terrains() do eq(row.ID, n, "rowid order"); n = n + 1 end
	eq(n, 9)
	eq(#G.Resources, GI.index.tables.Resources.n, "#GameInfo.X = row count")
	local lux = 0
	for row in G.Resources("ResourceClassType = 'RESOURCECLASS_LUXURY'") do lux = lux + 1 end
	local lux2 = 0
	for row in G.Resources{ ResourceClassType = "RESOURCECLASS_LUXURY" } do lux2 = lux2 + 1 end
	truthy(lux > 10, "luxuries found"); eq(lux, lux2, "string and table filters agree")
	eq(G.CustomModOptions("Name = 'BALANCE_CORE_JFD'")().Value, 0)
	eq(GI.GameInfoTypes.TERRAIN_SNOW, 4)
	eq(GI.GameInfoTypes.WORLDSIZE_STANDARD, 3)
	eq(GI.GameInfoTypes.NOT_A_TYPE, nil)
	eq(GI.GameDefines.MIN_WATER_SIZE_FOR_OCEAN, 10)
	local c = 0
	for row in GI.DB.Query("select count(*) as count from Terrains where Water = ?", true) do c = row.count end
	eq(c, 3, "COAST, OCEAN and TERRAIN_HILL have Water=1")
	local q = GI.DB.CreateQuery("SELECT 1 FROM Resources WHERE Type = 'RESOURCE_IRON'")
	local hit = false
	for _ in q() do hit = true end
	truthy(hit, "CreateQuery")
end)

---------------------------------------------------------------------------------------------
-- Map.Rand
---------------------------------------------------------------------------------------------
test("Map.Rand parity with Random.getMapRandNum", function()
	local S, Map = newMap(4, 4, { seed = 12345 })
	local ref = Random.new(12345 % 73637381)
	for i = 1, 200 do
		local n = (i * 37) % 97 - 5
		eq(Map.Rand(n, "test"), Random.getMapRandNum(ref, n, "test"), "draw " .. i .. " n=" .. n)
	end
	local c = S.mapRand:getCallCount()
	eq(Map.Rand(1, "x"), 0); eq(Map.Rand(0, "x"), 0)
	eq(S.mapRand:getCallCount(), c, "n < 2 does not advance")
	errors(function() Map.Rand(10) end, "bad argument #2 to 'Rand'")
	eq(type(Map.Rand(10, 5)), "number", "a number is accepted for the log string")
end)

test("math.random MSVC emulation and table.fill", function()
	newMap()
	math.randomseed(1)
	local a = math.random(1, 100)
	math.randomseed(1)
	eq(math.random(1, 100), a, "deterministic")
	-- srand(1): first rand() = 41
	math.randomseed(1)
	eq(math.random(32767), math.floor((41 % 32767) / 32767 * 32767) + 1)
	local t = table.fill(0, 5)
	eq(#t, 5); eq(t[0], nil)
	local u = table.fill(t, 7, 3)
	eq(u, t); eq(t[3], 7); eq(t[4], 0)
	eq(math.clamp(5, 0, 3), 3)
end)

return results
