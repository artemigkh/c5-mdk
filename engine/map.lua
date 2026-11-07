--[[
engine/map.lua -- engine state + the `Map` global (Lua/CvLuaMap.cpp over CvMap.cpp).

  local mapmod = require("map")
  local S = mapmod.newState(GI, cfg)   -- GI from gameinfo.new; cfg: seed, areas_mode, float_to_int, ...
  mapmod.initMap(S, W, H, wrapX, wrapY, topLat, bottomLat)   -- CvMap::init: every plot reset
  S.Map                                -- the global Map table
  S.recalculateAreas(), S.calculateAreas(), S.recalculateLandmasses(), S.validateCoast(), ...

Areas (CvMap::calculateAreas, CvMap.cpp:1879) come in two flavours selected by cfg.areas_mode:
  "literal"   (default) -- the VP DLL read literally: CvStepFinder::GetPlotsInReach with iMaxTurns 1/0
                returns only the start plot (CvAStar::LinkChild forbids every child when
                m_iMoves == 0 && m_iTurns+1 >= iMaxTurns), so the wide pass creates nothing and the
                narrow pass is a scan-order greedy merge into the largest adjacent same-domain area.
  "floodfill" -- the intended algorithm: reach = closure of AreaValid steps (same isImpassable and
                isWater; the wide pass also requires the rear-left/rear-right neighbours to match).
]]

local floor = math.floor
local fmod = math.fmod
local abs = math.abs

local hexmath = require("hexmath")
local Random = require("random")
local fractal = require("fractal")
local plotmod = require("plot")
local areamod = require("area")

local M = {}

local PLOT_OCEAN = 3

-- lua_tointeger: nil/non-number -> 0; numeric strings convert; non-integers round half to even
-- (Lua 5.1 on MSVC x86, fistp) -- or truncate with cfg.float_to_int = "trunc".
local function makeToInt(mode)
	local trunc = (mode == "trunc")
	return function(v)
		local tv = type(v)
		if tv ~= "number" then
			if tv == "string" then v = tonumber(v); if not v then return 0 end else return 0 end
		end
		local f = floor(v)
		if f == v then return v end
		if v ~= v then return 0 end
		if trunc then
			if v < 0 then return -floor(-v) end
			return f
		end
		local fr = v - f
		if fr > 0.5 or (fr == 0.5 and f % 2 == 1) then return f + 1 end
		return f
	end
end
M.makeToInt = makeToInt

local function tobool(v) return v ~= nil and v ~= false end

local function tdiv(a, b)
	local q = a / b
	if q >= 0 then return floor(q) end
	return -floor(-q)
end

-------------------------------------------------------------------------------------------------
-- static info built from GameInfo
-------------------------------------------------------------------------------------------------
local function buildInfo(GI)
	local info = {}
	local function idOf(tbl, ty)
		local r = GI.byType(tbl)[ty]
		return r and r.ID
	end
	local terrains = GI.rows("Terrains")
	info.numTerrains = 0
	info.terrainWater, info.terrainImpassable = {}, {}
	for _, r in ipairs(terrains) do
		info.terrainWater[r.ID] = r.Water and true or false
		info.terrainImpassable[r.ID] = r.Impassable and true or false
		if r.ID + 1 > info.numTerrains then info.numTerrains = r.ID + 1 end
	end
	info.TERRAIN_MOUNTAIN = idOf("Terrains", "TERRAIN_MOUNTAIN") or 7
	info.TERRAIN_DESERT = idOf("Terrains", "TERRAIN_DESERT") or 2
	info.TERRAIN_SNOW = idOf("Terrains", "TERRAIN_SNOW") or 4
	info.FEATURE_ICE = 0          -- hard-coded enums in the DLL
	info.FEATURE_FLOOD_PLAINS = 4

	info.features, info.featureExists = {}, {}
	info.featureImpassable, info.featureAddsFresh, info.featureNW, info.featureNWorPseudo = {}, {}, {}, {}
	info.featureIdByType = {}
	for _, r in ipairs(GI.rows("Features")) do
		local id = r.ID
		info.features[id] = r
		info.featureExists[id] = true
		info.featureIdByType[r.Type] = id
		info.featureImpassable[id] = r.Impassable and true or false
		info.featureAddsFresh[id] = r.AddsFreshWater and true or false
		info.featureNW[id] = r.NaturalWonder and true or false
		info.featureNWorPseudo[id] = (r.NaturalWonder or r.PseudoNaturalWonder) and true or false
	end
	info.featureTerrain = {}
	for _, r in ipairs(GI.rows("Feature_TerrainBooleans") or {}) do
		local f, t = info.featureIdByType[r.FeatureType], idOf("Terrains", r.TerrainType)
		if f and t then
			info.featureTerrain[f] = info.featureTerrain[f] or {}
			info.featureTerrain[f][t] = true
		end
	end

	info.improvements, info.improvementExists, info.improvementAddsFresh, info.improvementRequiresFeature = {}, {}, {}, {}
	for _, r in ipairs(GI.rows("Improvements")) do
		info.improvements[r.ID] = r
		info.improvementExists[r.ID] = true
		local af = r.AddsFreshWater
		info.improvementAddsFresh[r.ID] = (af ~= nil and af ~= false and af ~= 0) and true or false
		info.improvementRequiresFeature[r.ID] = r.RequiresFeature and true or false
	end
	local function linkTable(tbl, col, otherTbl, otherCol)
		local out = {}
		for _, r in ipairs(GI.rows(tbl) or {}) do
			local im = idOf("Improvements", r.ImprovementType)
			local o = idOf(otherTbl, r[otherCol])
			if im and o then
				out[im] = out[im] or {}
				out[im][o] = true
			end
		end
		return out
	end
	info.improvementTerrainValid = linkTable("Improvement_ValidTerrains", "ImprovementType", "Terrains", "TerrainType")
	info.improvementFeatureValid = linkTable("Improvement_ValidFeatures", "ImprovementType", "Features", "FeatureType")
	info.improvementResourceValid = linkTable("Improvement_ResourceTypes", "ImprovementType", "Resources", "ResourceType")
	info.improvementImprovementValid = linkTable("Improvement_ValidImprovements", "ImprovementType", "Improvements", "PrereqImprovement")
	info.improvementPrereqNatureYield = {}
	for _, r in ipairs(GI.rows("Improvement_PrereqNatureYields") or {}) do
		local im = idOf("Improvements", r.ImprovementType)
		if im and (r.Yield or 0) > 0 then info.improvementPrereqNatureYield[im] = true end
	end

	info.resourceExists, info.resourceOnlyMinor, info.resourceUsage, info.resourceTechReveal, info.resourceClass = {}, {}, {}, {}, {}
	for _, r in ipairs(GI.rows("Resources")) do
		info.resourceExists[r.ID] = true
		info.resourceOnlyMinor[r.ID] = r.OnlyMinorCivs and true or false
		info.resourceUsage[r.ID] = r.ResourceUsage or 0
		info.resourceTechReveal[r.ID] = r.TechReveal ~= nil
		info.resourceClass[r.ID] = r.ResourceClassType
	end

	-- yields
	info.yields = {}
	local yieldId = {}
	for _, r in ipairs(GI.rows("Yields")) do info.yields[r.ID] = r; yieldId[r.Type] = r.ID end
	local function yieldTable(tbl, keyCol, keyTbl)
		local out = {}
		for _, r in ipairs(GI.rows(tbl) or {}) do
			local k = idOf(keyTbl, r[keyCol])
			local y = yieldId[r.YieldType]
			if k and y then
				out[k] = out[k] or {}
				out[k][y] = (out[k][y] or 0) + (r.Yield or 0)
			end
		end
		return out
	end
	info.terrainYield = yieldTable("Terrain_Yields", "TerrainType", "Terrains")
	info.plotYield = yieldTable("Plot_Yields", "PlotType", "Plots")
	info.featureYield = yieldTable("Feature_YieldChanges", "FeatureType", "Features")
	info.featureRiverYield = yieldTable("Feature_RiverYieldChanges", "FeatureType", "Features")
	info.featureHillsYield = yieldTable("Feature_HillsYieldChanges", "FeatureType", "Features")
	info.featureFreshYield = yieldTable("Feature_FreshWaterYields", "FeatureType", "Features")
	info.featureCoastalYield = yieldTable("Feature_CoastalLandYields", "FeatureType", "Features")
	info.terrainRiverYield = yieldTable("Terrain_RiverYieldChanges", "TerrainType", "Terrains")
	info.terrainHillsYield = yieldTable("Terrain_HillsYieldChanges", "TerrainType", "Terrains")
	info.terrainFreshYield = yieldTable("Terrain_FreshWaterYields", "TerrainType", "Terrains")
	info.terrainCoastalYield = yieldTable("Terrain_CoastalLandYields", "TerrainType", "Terrains")
	info.plotAdjFeatureYield = {}
	for _, r in ipairs(GI.rows("Plot_AdjacentFeatureYieldChanges") or {}) do
		local pt, f, y = idOf("Plots", r.PlotType), info.featureIdByType[r.FeatureType], yieldId[r.YieldType]
		if pt and f and y then
			info.plotAdjFeatureYield[pt] = info.plotAdjFeatureYield[pt] or {}
			info.plotAdjFeatureYield[pt][f] = info.plotAdjFeatureYield[pt][f] or {}
			info.plotAdjFeatureYield[pt][f][y] = { v = r.Yield or 0, ignoreNW = r.IgnoreNaturalWonderPlots and true or false }
		end
	end

	-- custom mod options
	local cmo = {}
	for _, r in ipairs(GI.rows("CustomModOptions") or {}) do cmo[r.Name] = r.Value end
	info.customModOptions = cmo
	info.MOD_CORE_NO_YIELD_ICE = (cmo.CORE_NO_YIELD_ICE == 1)
	info.MOD_PLOTS_EXTENSIONS = (cmo.PLOTS_EXTENSIONS == 1)
	info.MOD_BALANCE_CORE_JFD = (cmo.BALANCE_CORE_JFD == 1)
	return info
end

-------------------------------------------------------------------------------------------------
function M.newState(GI, cfg)
	cfg = cfg or {}
	local S = {
		gi = GI, cfg = cfg,
		toint = makeToInt(cfg.float_to_int), tobool = tobool, tdiv = tdiv,
		fn = {},
		W = 0, H = 0, numPlots = 0, plots = {}, wrapX = true, wrapY = false,
		topLatitude = 0, bottomLatitude = 0,
		areas = {}, areaById = {}, landmasses = {}, landmassById = {}, continents = {},
		landPlots = 0, landVersion = 0, numResources = {}, numResourcesOnLand = {}, numNaturalWonders = 0,
		aiMapHints = 0, mapReady = false,
		areasMode = cfg.areas_mode or "literal",
	}
	local D = GI.GameDefines
	S.defines = {
		SHALLOW_WATER_TERRAIN = D.SHALLOW_WATER_TERRAIN or 5,
		DEEP_WATER_TERRAIN = D.DEEP_WATER_TERRAIN or 6,
		LAND_TERRAIN = D.LAND_TERRAIN or 0,
		MIN_WATER_SIZE_FOR_OCEAN = D.MIN_WATER_SIZE_FOR_OCEAN or 10,
		BALANCE_PRODUCTION_DESERT_IMPROVEMENT = D.BALANCE_PRODUCTION_DESERT_IMPROVEMENT or 0,
		BARBARIAN_CAMP_IMPROVEMENT = GI.GameInfoTypes[D.BARBARIAN_CAMP_IMPROVEMENT or "IMPROVEMENT_BARBARIAN_CAMP"] or GI.GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP,
	}
	S.info = buildInfo(GI)

	-- map RNG (CvGame::init: m_mapRand.init(mapRandomSeed % 73637381))
	local seed = cfg.seed or 0
	S.mapRand = Random.new(fmod(seed, 73637381), "Map Rand")
	S.mapRandCalls = 0

	function S.shuffleArray(arr, n)   -- CvGameCoreUtils.h shuffleArray, 0-based arr
		for i = 0, n - 1 do
			local j = S.mapRand:get(n - i, "shuffleArray") + i
			arr[i], arr[j] = arr[j], arr[i]
		end
	end

	-- ring offsets for radius 5 (iterateRingPlots)
	S.ringDHX, S.ringDY = {}, {}
	for i = 0, 90 do
		S.ringDHX[i], S.ringDY[i] = hexmath.ringOffset(i)
	end

	plotmod.install(S)
	areamod.install(S)
	M.installAreas(S)
	M.installMapAPI(S)
	return S
end

-------------------------------------------------------------------------------------------------
function M.initMap(S, W, H, wrapX, wrapY, top, bottom)
	S.W, S.H = W, H
	S.wrapX, S.wrapY = wrapX and true or false, wrapY and true or false
	S.topLatitude = math.max(-90, math.min(90, top or 0))
	S.bottomLatitude = math.max(-90, math.min(90, bottom or 0))
	S.numPlots = W * H
	S.G = hexmath.new(W, H, S.wrapX, S.wrapY)
	local plots = {}
	S.plots = plots
	for y = 0, H - 1 do
		for x = 0, W - 1 do
			local i = y * W + x
			plots[i] = S.newPlot(i, x, y)
		end
	end
	local G = S.G
	for i = 0, S.numPlots - 1 do
		local p = plots[i]
		local n = {}
		for d = 0, 7 do
			local nx, ny = G.neighborXY(p._x, p._y, d)
			if nx then n[d] = plots[ny * W + nx] end
		end
		p._n = n
	end
	S.areas, S.areaById, S.landmasses, S.landmassById, S.continents = {}, {}, {}, {}, {}
	S.landPlots = 0
	S.numResources, S.numResourcesOnLand = {}, {}
	S.numNaturalWonders = 0
	S.aiMapHints = 0
	S.mapReady = true
end

-------------------------------------------------------------------------------------------------
-- areas / landmasses / continents
-------------------------------------------------------------------------------------------------
function M.installAreas(S)
	local fn = S.fn

	local function addArea(water)
		local id = 0
		for _, a in ipairs(S.areas) do if a.id + 1 > id then id = a.id + 1 end end
		local a = S.newArea(id, water)
		S.areas[#S.areas + 1] = a
		S.areaById[id] = a
		return a
	end
	S.addArea = addArea

	local function sameClass(a, b)
		return a._imps == b._imps and (a._pt == PLOT_OCEAN) == (b._pt == PLOT_OCEAN)
	end

	-- floodfill reach (the intended GetPlotsInReach with AreaValid)
	local function reachFlood(start, wide)
		local G = S.G
		local out = { start }
		local inSet = { [start] = true }
		local head = 1
		while head <= #out do
			local parent = out[head]
			head = head + 1
			local pn = parent._n
			for d = 0, 5 do
				local node = pn[d]
				if node and not inSet[node] and node._area == -1 and sameClass(node, parent) then
					local ok = true
					if wide then
						local rear = G.directionXY(node._x, node._y, parent._x, parent._y)
						if rear < 6 then
							local rl = node._n[(rear + 5) % 6]
							local rr = node._n[(rear + 1) % 6]
							if rl and not sameClass(node, rl) then ok = false end
							if ok and rr and not sameClass(node, rr) then ok = false end
						end
					end
					if ok then
						inSet[node] = true
						out[#out + 1] = node
					end
				end
			end
		end
		return out
	end

	local function reach(start, maxTurns)
		if S.areasMode == "floodfill" then
			return reachFlood(start, maxTurns == 1)
		end
		return { start }   -- literal: LinkChild forbids every child (iMaxTurns 0/1)
	end
	S.areaReach = reach

	function S.calculateAreas()
		local minAreaSize = 7
		local plots, n = S.plots, S.numPlots
		S.areas, S.areaById = {}, {}
		for i = 0, n - 1 do
			local p = plots[i]
			p._area = -1     -- setArea(-1): the old areas are already gone (RemoveAll)
			fn.updateImpassable(p)
		end
		-- wide pass
		for i = 0, n - 1 do
			local p = plots[i]
			if p._area == -1 then
				local R = reach(p, 1)
				if #R >= minAreaSize then
					local a = addArea(p._pt == PLOT_OCEAN)
					a.mountains = fn.isMountain(p)
					for k = 1, #R do fn.setArea(R[k], a.id) end
				end
			end
		end
		-- small and thin
		for i = 0, n - 1 do
			local p = plots[i]
			if p._area == -1 then
				local R = reach(p, 0)
				local merged = false
				if #R < minAreaSize then
					local best, bestSize = -1, 0
					local pw = p._pt == PLOT_OCEAN
					for k = 1, #R do
						local q = R[k]
						local qn = q._n
						for d = 0, 5 do
							local nb = qn[d]
							if nb and (nb._pt == PLOT_OCEAN) == pw and nb._area ~= -1 then
								local sz = S.areaById[nb._area].tiles
								if sz > bestSize then bestSize = sz; best = nb._area end
							end
						end
					end
					if best ~= -1 then
						for k = 1, #R do fn.setArea(R[k], best) end
						merged = true
					end
				end
				if not merged then
					local a = addArea(p._pt == PLOT_OCEAN)
					a.mountains = fn.isMountain(p)
					for k = 1, #R do fn.setArea(R[k], a.id) end
				end
			end
		end
		-- boundaries (CvArea::FindBoundaries) are not exposed to Lua; UpdateBadPlotsCount is a no-op
		-- (it returns early for plots of its own area)
	end

	-- landmasses -----------------------------------------------------------------------------
	local MINW = S.defines.MIN_WATER_SIZE_FOR_OCEAN
	local function isLakeLM(lm) return lm.water and lm.tiles < MINW end

	-- CvMap::updateYield() as triggered by CvLandmass::changeNumTiles when the lake state flips.
	-- It runs updateWaterFlags() on every plot; only the water plots' m_bIsLake can survive into
	-- observable state (everything else is recomputed by the final pass), so only that is refreshed.
	local function lakeTogglePass()
		local plots = S.plots
		local byId = S.landmassById
		for i = 0, S.numPlots - 1 do
			local p = plots[i]
			if p._pt == PLOT_OCEAN then
				local lm = byId[p._lm]
				p._lake = lm and isLakeLM(lm) or false
			end
		end
	end

	local function changeLMTiles(lm, chg)
		local old = isLakeLM(lm)
		lm.tiles = lm.tiles + chg
		if old ~= isLakeLM(lm) then lakeTogglePass() end
	end

	local function setLandmass(p, id)
		if p._lm ~= id then
			local lm = S.landmassById[p._lm]
			if lm then
				changeLMTiles(lm, -1)
				lm.cx = lm.cx - p._x
				lm.cy = lm.cy - p._y
			end
			p._lm = id
			lm = S.landmassById[id]
			if lm then
				changeLMTiles(lm, 1)
				lm.cx = lm.cx + p._x
				lm.cy = lm.cy + p._y
			end
		end
	end
	fn.setLandmass = setLandmass

	function S.calculateLandmasses()
		local plots, n = S.plots, S.numPlots
		for i = 0, n - 1 do
			local p = plots[i]
			if p._lm == -1 then
				local id = 0
				for _, l in ipairs(S.landmasses) do if l.id + 1 > id then id = l.id + 1 end end
				local lm = S.newLandmass(id, p._pt == PLOT_OCEAN)
				S.landmasses[#S.landmasses + 1] = lm
				S.landmassById[id] = lm
				setLandmass(p, id)
				-- GetPlotsInReach(PT_LANDMASS_CONNECTION): flood fill, LandmassValid = same isWater
				local w = p._pt == PLOT_OCEAN
				local queue, head = { p }, 1
				local seen = { [p] = true }
				while head <= #queue do
					local q = queue[head]
					head = head + 1
					local qn = q._n
					for d = 0, 5 do
						local nb = qn[d]
						if nb and not seen[nb] and (nb._pt == PLOT_OCEAN) == w then
							seen[nb] = true
							queue[#queue + 1] = nb
						end
					end
				end
				for k = 1, #queue do setLandmass(queue[k], id) end
			end
		end
		-- updateYield(): updateWaterFlags for all plots, index order
		local uwf = fn.updateWaterFlags
		for i = 0, n - 1 do uwf(plots[i]) end
	end

	function S.recalculateLandmasses()
		local plots, n = S.plots, S.numPlots
		local uwf = fn.updateWaterFlags
		for i = 0, n - 1 do
			local p = plots[i]
			uwf(p)
			setLandmass(p, -1)
		end
		S.landmasses, S.landmassById = {}, {}
		S.calculateLandmasses()
		for i = 0, n - 1 do
			local p = plots[i]
			if p._area >= 0 and p._lm >= 0 then
				S.landmassById[p._lm].areas[p._area] = true
			end
		end
	end

	function S.recalculateContinents()
		local plots, n = S.plots, S.numPlots
		local DEEP = S.defines.DEEP_WATER_TERRAIN
		local function isDeep(p) return p._pt == PLOT_OCEAN and p._ter == DEEP end
		for i = 0, n - 1 do plots[i]._cont = -1 end
		S.continents = {}
		local nextId = 0
		for i = 0, n - 1 do
			local p = plots[i]
			if p._cont == -1 then
				local id = nextId
				nextId = nextId + 1
				S.continents[#S.continents + 1] = { id = id, land = not isDeep(p) }
				local d0 = isDeep(p)
				p._cont = id
				local queue, head = { p }, 1
				while head <= #queue do
					local q = queue[head]
					head = head + 1
					local qn = q._n
					for d = 0, 5 do
						local nb = qn[d]
						if nb and nb._cont == -1 and isDeep(nb) == d0 then
							nb._cont = id
							queue[#queue + 1] = nb
						end
					end
				end
			end
		end
	end

	function S.recalculateAreas()
		S.calculateAreas()
		S.recalculateLandmasses()
		S.recalculateContinents()
		-- RecalculateRivers: CvRiver objects are not exposed to Lua
	end

	function S.defaultContinentStamper()
		local N = 4
		local minSize = 10
		local ids, sizes = { [0] = -1, -1, -1, -1 }, { [0] = 0, 0, 0, 0 }
		S.recalculateLandmasses()
		for _, lm in ipairs(S.landmasses) do
			if not lm.water then
				local nt = lm.tiles
				for b = 0, N - 1 do
					if nt >= minSize and nt > sizes[b] then
						for k = N - 1, b + 1, -1 do
							ids[k] = ids[k - 1]
							sizes[k] = sizes[k - 1]
						end
						ids[b] = lm.id
						sizes[b] = nt
						break
					end
				end
			end
		end
		local style = { [0] = 0, 1, 2, 3 }
		S.shuffleArray(style, 4)
		for i = 0, N - 1 do style[i] = style[i] + 1 end
		local numLarge = 0
		for i = 0, N - 1 do if ids[i] ~= -1 then numLarge = numLarge + 1 end end
		local function centroid(lm)
			if lm.tiles > 0 then return tdiv(lm.cx, lm.tiles), tdiv(lm.cy, lm.tiles) end
			return 0, 0
		end
		local lx, ly = { [0] = 0, 0, 0, 0 }, { [0] = 0, 0, 0, 0 }
		for i = 0, numLarge - 1 do
			lx[i], ly[i] = centroid(S.landmassById[ids[i]])
		end
		for _, lm in ipairs(S.landmasses) do
			local x, y = centroid(lm)
			if lm.water then
				lm.continentType = 0
			else
				local best = 999999
				for i = 0, numLarge - 1 do
					local d = S.G.plotDistance(x, y, lx[i], ly[i])
					if d < best then
						best = d
						lm.continentType = style[i]
					end
				end
			end
		end
		for i = 0, S.numPlots - 1 do
			local p = S.plots[i]
			local lm = S.landmassById[p._lm]
			if lm then p._art = lm.continentType end
		end
	end

	-- CvWorldBuilderMapLoader::ValidateCoast (runs after every generated map)
	function S.validateCoast()
		local coast = S.defines.SHALLOW_WATER_TERRAIN
		local TW = S.info.terrainWater
		for y = 0, S.H - 1 do
			for x = 0, S.W - 1 do
				local p = S.plots[y * S.W + x]
				local t = p._ter
				if t >= 0 and t < S.info.numTerrains and t ~= coast and TW[t] then
					fn.updateWaterFlags(p)
					if p._adjL then fn.setTerrainType(p, coast, false) end
				end
			end
		end
	end
end

-------------------------------------------------------------------------------------------------
-- Map.* (Lua/CvLuaMap.cpp)
-------------------------------------------------------------------------------------------------
function M.installMapAPI(S)
	local toint, tobool = S.toint, S.tobool
	local fn = S.fn
	local Map = {}
	S.Map = Map

	local function needMap(name)
		if not S.mapReady then
			error("c5maps: Map." .. name .. " called before the map exists (only Map.Rand/GetCustomOption/GetWorldSize... work in GetMapInitData and at file top level)", 3)
		end
	end

	local function checkInteger(v, argn, fname)
		if type(v) == "number" then return toint(v) end
		if type(v) == "string" and tonumber(v) then return toint(tonumber(v)) end
		error(("bad argument #%d to '%s' (number expected, got %s)"):format(argn, fname, v == nil and "no value" or type(v)), 3)
	end
	local function checkString(v, argn, fname)
		if type(v) == "string" then return v end
		if type(v) == "number" then return tostring(v) end
		error(("bad argument #%d to '%s' (string expected, got %s)"):format(argn, fname, v == nil and "no value" or type(v)), 3)
	end

	function Map.Rand(max, log)
		local n = checkInteger(max, 1, "Rand")
		checkString(log, 2, "Rand")
		S.mapRandCalls = S.mapRandCalls + 1
		return Random.getMapRandNum(S.mapRand, n, log)
	end

	function Map.GetGridSize() needMap("GetGridSize"); return S.W, S.H end
	function Map.GetNumPlots() needMap("GetNumPlots"); return S.numPlots end
	function Map.IsWrapX() return S.wrapX end
	function Map.IsWrapY() return S.wrapY end
	function Map.GetFractalFlags() return fractal.fractalFlagsTable(S.wrapX, S.wrapY) end
	function Map.GetWorldSize() return S.pregame.worldSize end
	function Map.GetClimate() return S.pregame.climate end
	function Map.GetSeaLevel() return S.pregame.seaLevel end
	function Map.GetCustomOption(n)
		local key = checkString(n, 1, "GetCustomOption")
		local v = S.pregame.mapOptions[key]
		if v == nil then return end
		return v
	end
	function Map.ChangeAIMapHint(n) S.aiMapHints = S.aiMapHints + toint(n) end
	function Map.GetAIMapHint() return S.aiMapHints end

	function Map.GetPlot(x, y)
		needMap("GetPlot")
		local nx, ny = S.G.plotXYRaw(toint(x), toint(y))
		if nx then return S.plots[ny * S.W + nx] end
	end
	function Map.GetPlotByIndex(i)
		needMap("GetPlotByIndex")
		i = toint(i)
		if i >= 0 and i < S.numPlots then return S.plots[i] end
	end
	function Map.IsPlot(x, y)
		x, y = toint(x), toint(y)
		return x >= 0 and x < S.W and y >= 0 and y < S.H
	end
	function Map.GetPlotXY(...)
		needMap("GetPlotXY")
		local a = { ... }
		local x, y, dx, dy
		if select("#", ...) == 2 then x, y, dx, dy = 0, 0, toint(a[1]), toint(a[2])
		else x, y, dx, dy = toint(a[1]), toint(a[2]), toint(a[3]), toint(a[4]) end
		local nx, ny = S.G.plotXY(x, y, dx, dy)
		if nx then return S.plots[ny * S.W + nx] end
		return nil
	end
	function Map.PlotXYWithRangeCheck(x, y, dx, dy, r)
		needMap("PlotXYWithRangeCheck")
		local nx, ny = S.G.plotXYWithRangeCheck(toint(x), toint(y), toint(dx), toint(dy), toint(r))
		if nx then return S.plots[ny * S.W + nx] end
		return nil
	end
	function Map.PlotDirection(x, y, dir)
		needMap("PlotDirection")
		x, y = toint(x), toint(y)
		local d = abs(fmod(toint(dir), 6))
		if x == hexmath.INVALID_PLOT_COORD or y == hexmath.INVALID_PLOT_COORD then return nil end
		local G = S.G
		local mx = G.coordRange(x, S.W, S.wrapX)
		local my = G.coordRange(y, S.H, S.wrapY)
		if mx < 0 or mx >= S.W or my < 0 or my >= S.H then
			error(("c5maps: Map.PlotDirection(%d, %d, %d): coordinates outside the map -- the DLL reads its neighbour table out of bounds here (undefined behaviour / crash)"):format(x, y, toint(dir)), 2)
		end
		return S.plots[my * S.W + mx]._n[d]
	end
	function Map.PlotDistance(x1, y1, x2, y2)
		needMap("PlotDistance")
		return S.G.plotDistance(toint(x1), toint(y1), toint(x2), toint(y2))
	end
	function Map.MaxPlotDistance() needMap("MaxPlotDistance"); return S.G.maxPlotDistance() end

	function Map.RecalculateAreas() needMap("RecalculateAreas"); S.recalculateAreas() end
	function Map.CalculateAreas() needMap("CalculateAreas"); S.calculateAreas() end
	function Map.GetArea(id)
		local a = S.areaById[toint(id)]
		if a then return a end
	end
	function Map.GetNumAreas() return #S.areas end
	function Map.GetNumLandAreas()
		local c = 0
		for _, a in ipairs(S.areas) do if not a.water then c = c + 1 end end
		return c
	end
	function Map.GetIndexAfterLastArea()
		local id = 0
		for _, a in ipairs(S.areas) do if a.id + 1 > id then id = a.id + 1 end end
		return id
	end
	function Map.Areas()
		return function(_, idx)
			local it
			if idx == nil then it = 0 else it = toint(idx) + 1 end
			local a = S.areas[it + 1]
			if a then return it, a end
		end
	end
	function Map.FindBiggestArea(bWater)
		local w = tobool(bWater)
		local best, bestV = nil, 0
		for _, a in ipairs(S.areas) do
			if a.water == w and a.tiles > bestV then bestV = a.tiles; best = a end
		end
		if best then return best end
	end
	function Map.FindBiggestLandmassID(bWater)
		local w = tobool(bWater)
		local best, bestV = nil, 0
		for _, l in ipairs(S.landmasses) do
			if l.water == w and l.tiles > bestV then bestV = l.tiles; best = l end
		end
		if best then return best.id end
	end
	function Map.GetNumTilesOfLandmass(id)
		local l = S.landmassById[toint(id)]
		if not l then
			error("c5maps: Map.GetNumTilesOfLandmass(" .. tostring(id) .. "): no such landmass (the DLL dereferences NULL here)", 2)
		end
		return l.tiles
	end
	function Map.GetLandPlots() return S.landPlots end
	function Map.GetNumResources(r) return S.numResources[toint(r)] or 0 end
	function Map.GetNumResourcesOnLand(r) return S.numResourcesOnLand[toint(r)] or 0 end
	function Map.FindWater(plot, range, bFresh)
		needMap("FindWater")
		if type(plot) ~= "table" or not plot._n then error("bad argument #1 to 'FindWater' (Plot expected)", 2) end
		local r = checkInteger(range, 2, "FindWater")
		local fresh = tobool(bFresh)
		local G = S.G
		local x, y = plot._x, plot._y
		for dx = -r, r do
			for dy = -r, r do
				local nx, ny = G.plotXYWithRangeCheck(x, y, dx, dy, r)
				if nx then
					local q = S.plots[ny * S.W + nx]
					if fresh then
						fn.updateWaterFlags(q)
						if q._fresh then return true end
					else
						if q._pt == PLOT_OCEAN then return true end
					end
				end
			end
		end
		return false
	end
	function Map.DefaultContinentStamper() needMap("DefaultContinentStamper"); S.defaultContinentStamper() end
	function Map.GetRandomResourceQuantity(r)
		-- uses the GAME rng (getJonRandNum), not the map rng: emulate with a separate CvRandom
		local id = toint(r)
		local rows = {}
		local ty
		for _, row in ipairs(S.gi.rows("Resources")) do if row.ID == id then ty = row.Type end end
		for _, row in ipairs(S.gi.rows("Resource_QuantityTypes") or {}) do
			if row.ResourceType == ty then rows[#rows + 1] = row.Quantity end
		end
		if #rows == 0 then return 1 end
		S.gameRand = S.gameRand or Random.new(fmod(S.cfg.seed or 0, 73637381), "Game Rand")
		return rows[S.gameRand:get(#rows, "Resource Quantity") + 1]
	end
	function Map.UpdateDeferredFog() end

	setmetatable(Map, { __index = function(_, k) error("c5maps: unimplemented Map." .. tostring(k), 2) end })
	return Map
end

return M
