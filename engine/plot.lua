--[[
engine/plot.lua -- canonical Plot objects and their C++ side effects (CvPlot.cpp, Lua/CvLuaPlot.cpp).

One Lua table per plot index (identity comparable).  State lives in underscore fields on the plot
table itself (fast access):
  _i,_x,_y           index / coordinates
  _pt,_ter,_feat     plot type, terrain (-1 = NO_TERRAIN), feature (-1)
  _res,_resq,_imp    resource / quantity / improvement (-1)
  _area,_lm,_cont    area id, landmass id, continent id (-1 = unassigned)
  _art               continent art type
  _start             m_bStartingPlot
  _w,_nw,_ne         river edge flags (W of river = E edge, NW = SE edge, NE = SW edge)
  _fE,_fSE,_fSW      flow directions (7 = NO_FLOWDIRECTION)
  _rc[0..5], _rcn    river crossing bits + count  (IsRiver = _rcn > 0)
  _lake,_adjL,_adjW,_fresh   updateWaterFlags cache
  _imps              m_bIsImpassable
  _n[0..7]           DLL neighbour table (nil when off-map; 6 and 7 = self)

  local plotmod = require("plot")
  plotmod.install(S)   -- S = engine state built by map.lua; fills S.PlotMethods, S.newPlot, S.fn.*
]]

local floor = math.floor

local M = {}

local PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN = 0, 1, 2, 3
local NO_FLOW = 7

function M.install(S)
	local toint, tobool = S.toint, S.tobool
	local fn = S.fn
	local TWater, TImpassable = S.info.terrainWater, S.info.terrainImpassable
	local FImpassable, FAddsFresh = S.info.featureImpassable, S.info.featureAddsFresh
	local FNW, FNWorPseudo = S.info.featureNW, S.info.featureNWorPseudo
	local IAddsFresh = S.info.improvementAddsFresh
	local NUM_TERRAIN = S.info.numTerrains
	local TERRAIN_MOUNTAIN = S.info.TERRAIN_MOUNTAIN
	local TERRAIN_DESERT = S.info.TERRAIN_DESERT
	local FEATURE_ICE = S.info.FEATURE_ICE
	local FEATURE_FLOOD_PLAINS = S.info.FEATURE_FLOOD_PLAINS
	local SHALLOW = S.defines.SHALLOW_WATER_TERRAIN
	local DEEP = S.defines.DEEP_WATER_TERRAIN
	local LAND_TERRAIN = S.defines.LAND_TERRAIN
	local MIN_WATER_OCEAN = S.defines.MIN_WATER_SIZE_FOR_OCEAN

	local PlotMethods = {}
	S.PlotMethods = PlotMethods
	local PlotMeta = { __index = PlotMethods, __tostring = function(p) return ("Plot(%d,%d)"):format(p._x, p._y) end }
	S.PlotMeta = PlotMeta
	setmetatable(PlotMethods, {
		__index = function(_, k)
			-- method-looking names error loudly; other keys (scripts storing private fields) read nil
			if type(k) == "string" and k:match("^%u") then
				error("c5maps: unimplemented Plot:" .. k, 2)
			end
			return nil
		end,
	})

	function S.newPlot(i, x, y)
		local p = {
			_i = i, _x = x, _y = y,
			_pt = PLOT_OCEAN, _ter = -1, _feat = -1, _res = -1, _resq = 0, _imp = -1, _route = -1,
			_area = -1, _lm = -1, _cont = -1, _art = 0, _start = false,
			_w = false, _nw = false, _ne = false, _fE = NO_FLOW, _fSE = NO_FLOW, _fSW = NO_FLOW,
			_rc = { [0] = false, false, false, false, false, false }, _rcn = 0,
			_lake = false, _adjL = false, _adjW = false, _fresh = false, _imps = false,
			_n = nil,
		}
		return setmetatable(p, PlotMeta)
	end

	local function isWater(p) return p._pt == PLOT_OCEAN end
	local function isMountain(p) return p._ter == TERRAIN_MOUNTAIN or p._pt == PLOT_MOUNTAIN end
	local function isRiver(p) return p._rcn > 0 end
	fn.isWater, fn.isMountain, fn.isRiver = isWater, isMountain, isRiver

	---------------------------------------------------------------------------------------------
	-- caches
	---------------------------------------------------------------------------------------------
	local function updateImpassable(p)
		local imp = isMountain(p)
		local t = p._ter
		if t ~= -1 then
			local f = p._feat
			if f == -1 then
				local v = TImpassable[t]
				if v ~= nil then imp = v end
			else
				local v = FImpassable[f]
				if v ~= nil then imp = v end
			end
		end
		p._imps = imp
	end
	fn.updateImpassable = updateImpassable

	local function updateWaterFlags(p)
		local n = p._n
		if p._pt == PLOT_OCEAN then
			local lm = S.landmassById[p._lm]
			p._lake = lm and (lm.water and lm.tiles < MIN_WATER_OCEAN) or false
			p._adjW = false
			local adj = false
			for d = 0, 5 do
				local q = n[d]
				if q and q._pt ~= PLOT_OCEAN then adj = true; break end
			end
			p._adjL = adj
		else
			p._lake = false
			p._adjL = false
			local adj = false
			for d = 0, 5 do
				local q = n[d]
				if q and q._pt == PLOT_OCEAN and q._feat ~= FEATURE_ICE then adj = true; break end
			end
			p._adjW = adj
		end
		local fresh = p._rcn > 0
		p._fresh = fresh
		if p._pt == PLOT_OCEAN or fresh then return end
		for d = 0, 6 do   -- +1: includes the plot itself
			local q = n[d]
			if q then
				if q._lake then p._fresh = true; return end
				local f = q._feat
				if f ~= -1 and FAddsFresh[f] then p._fresh = true; return end
				local im = q._imp
				if im ~= -1 and IAddsFresh[im] then p._fresh = true; return end
			end
		end
	end
	fn.updateWaterFlags = updateWaterFlags

	---------------------------------------------------------------------------------------------
	-- rivers
	---------------------------------------------------------------------------------------------
	local function updateRiverCrossing(p, d)
		local q = p._n[d]
		local valid = false
		if not q or (q._pt ~= PLOT_OCEAN and p._pt ~= PLOT_OCEAN) then
			if d == 0 then valid = q and q._ne or false
			elseif d == 1 then valid = p._w
			elseif d == 2 then valid = p._nw
			elseif d == 3 then valid = p._ne
			elseif d == 4 then valid = q and q._w or false
			elseif d == 5 then valid = q and q._nw or false end
		end
		local rc = p._rc
		if rc[d] ~= valid then
			rc[d] = valid
			p._rcn = p._rcn + (valid and 1 or -1)
		end
	end
	fn.updateRiverCrossing = updateRiverCrossing

	-- flag field, flow field, own crossing direction, opposite direction on the neighbour
	local function setRiverEdge(p, flagKey, flowKey, dirOwn, dirOpp, b, flow)
		if p[flagKey] == b and flow == p[flowKey] then return end
		if p[flagKey] ~= b then
			p[flagKey] = b
			updateRiverCrossing(p, dirOwn)
			local q = p._n[dirOwn]
			if q then updateRiverCrossing(q, dirOpp) end
			local a = S.areaById[p._area]
			if a then a.riverEdges = a.riverEdges + (b and 1 or -1) end
		end
		p[flowKey] = flow
	end
	local function setWOfRiver(p, b, flow) setRiverEdge(p, "_w", "_fE", 1, 4, b, flow) end
	local function setNWOfRiver(p, b, flow) setRiverEdge(p, "_nw", "_fSE", 2, 5, b, flow) end
	local function setNEOfRiver(p, b, flow) setRiverEdge(p, "_ne", "_fSW", 3, 0, b, flow) end
	fn.setWOfRiver, fn.setNWOfRiver, fn.setNEOfRiver = setWOfRiver, setNWOfRiver, setNEOfRiver

	---------------------------------------------------------------------------------------------
	-- area bookkeeping (processArea)
	---------------------------------------------------------------------------------------------
	local function startingPlotCount(p)
		local c = 0
		local players = S.playerStarts
		if players then
			for pid = 0, 63 do
				local st = players[pid]
				if st == p then c = c + 1 end
			end
		end
		return c
	end

	local function processArea(p, a, chg)
		a.tiles = a.tiles + chg
		if p._ne then a.riverEdges = a.riverEdges + chg end
		if p._nw then a.riverEdges = a.riverEdges + chg end
		if p._w then a.riverEdges = a.riverEdges + chg end
		if p._res ~= -1 then a.res[p._res] = (a.res[p._res] or 0) + chg end
		if p._imp ~= -1 then a.imp[p._imp] = (a.imp[p._imp] or 0) + chg end
		local sp = startingPlotCount(p)
		if sp > 0 then a.starts = a.starts + sp * chg end
		if p._feat ~= -1 and FNWorPseudo[p._feat] then a.nw = a.nw + chg end
	end

	local function setArea(p, id)
		if p._area ~= id then
			local a = S.areaById[p._area]
			if a then processArea(p, a, -1) end
			p._area = id
			a = S.areaById[id]
			if a then processArea(p, a, 1) end
		end
	end
	fn.setArea = setArea

	---------------------------------------------------------------------------------------------
	-- setters
	---------------------------------------------------------------------------------------------
	local setTerrainType, setPlotType, setFeatureType, setResourceType, setImprovementType

	function setResourceType(p, r, qty)
		if r < -1 then return end
		local info = S.info
		if r > -1 and not info.resourceExists[r] then return end
		local old = p._res
		if old ~= r then
			if r ~= -1 and info.resourceOnlyMinor[r] then return end   -- bIgnoreMinorCivRestrictions = false
			local a = S.areaById[p._area]
			if old ~= -1 then
				local oq = p._resq
				if a then a.res[old] = (a.res[old] or 0) - oq end
				S.numResources[old] = (S.numResources[old] or 0) - oq
				if p._pt ~= PLOT_OCEAN then S.numResourcesOnLand[old] = (S.numResourcesOnLand[old] or 0) - oq end
			end
			p._res = r
			p._resq = qty
			if r ~= -1 then
				if a then a.res[r] = (a.res[r] or 0) + qty end
				S.numResources[r] = (S.numResources[r] or 0) + qty
				if p._pt ~= PLOT_OCEAN then S.numResourcesOnLand[r] = (S.numResourcesOnLand[r] or 0) + qty end
			end
		end
	end
	fn.setResourceType = setResourceType

	function setImprovementType(p, im)
		if im < -1 then return end
		if im > -1 and not S.info.improvementExists[im] then return end
		local old = p._imp
		if old ~= im then
			local a = S.areaById[p._area]
			if a then
				if old ~= -1 then a.imp[old] = (a.imp[old] or 0) - 1 end
				if im ~= -1 then a.imp[im] = (a.imp[im] or 0) + 1 end
			end
			p._imp = im
		end
	end
	fn.setImprovementType = setImprovementType

	function setFeatureType(p, f)
		local old = p._feat
		if old == f then return end
		if f == -1 and p._ter == TERRAIN_DESERT and p._rcn > 0 then
			f = FEATURE_FLOOD_PLAINS
		end
		p._feat = f
		updateImpassable(p)
		if f ~= -1 and (old == -1 or not FNWorPseudo[old]) and FNWorPseudo[f] then
			S.numNaturalWonders = S.numNaturalWonders + 1
			local a = S.areaById[p._area]
			if not a then
				error(("c5maps: SetFeatureType(%d) natural wonder on plot (%d,%d) with no area: the C++ dereferences a NULL area here (crash in game)"):format(f, p._x, p._y), 3)
			end
			a.nw = a.nw + 1
		end
		if old ~= -1 and FNWorPseudo[old] and (f == -1 or not FNWorPseudo[f]) then
			S.numNaturalWonders = S.numNaturalWonders - 1
			local a = S.areaById[p._area]
			if not a then
				error(("c5maps: SetFeatureType on plot (%d,%d) removing a natural wonder with no area (C++ crash)"):format(p._x, p._y), 3)
			end
			a.nw = a.nw - 1
		end
		if f == -1 and p._imp ~= -1 and S.info.improvementRequiresFeature[p._imp] then
			setImprovementType(p, -1)
		end
	end
	fn.setFeatureType = setFeatureType

	local function erase(p)
		setResourceType(p, -1, 0)
		setImprovementType(p, -1)
		p._route = -1
		setFeatureType(p, -1)
		setNEOfRiver(p, false, NO_FLOW)
		setNWOfRiver(p, false, NO_FLOW)
		setWOfRiver(p, false, NO_FLOW)
	end
	fn.erase = erase

	function setPlotType(p, t, bRecalc)
		if p._pt == t then return end
		if t <= -1 or t >= 4 then return end
		if p._pt == PLOT_OCEAN or t == PLOT_OCEAN then erase(p) end
		local wasWater = p._pt == PLOT_OCEAN
		p._pt = t
		updateImpassable(p)
		local nowWater = t == PLOT_OCEAN
		local ter = p._ter
		if ter == -1 or TWater[ter] ~= nowWater then
			if nowWater then
				updateWaterFlags(p)   -- isAdjacentToLand(false)
				if p._adjL then setTerrainType(p, SHALLOW, bRecalc) else setTerrainType(p, DEEP, bRecalc) end
			else
				setTerrainType(p, LAND_TERRAIN, bRecalc)
			end
		end
		if wasWater ~= nowWater then
			S.landVersion = S.landVersion + 1
			S.landPlots = S.landPlots + (nowWater and -1 or 1)
			local r = p._res
			if r ~= -1 then
				S.numResourcesOnLand[r] = (S.numResourcesOnLand[r] or 0) + (nowWater and -1 or 1)
			end
			if bRecalc then
				error("c5maps: unimplemented SetPlotType(..., bRecalculate=true) (CvPlot.cpp:7317 incremental area patch)", 3)
			end
		end
	end
	fn.setPlotType = setPlotType

	function setTerrainType(p, t, bRecalc)
		if t <= -1 or t >= NUM_TERRAIN then return end
		if p._ter ~= t then
			p._ter = t
			updateImpassable(p)
			local tw = TWater[t]
			if tw ~= (p._pt == PLOT_OCEAN) then
				setPlotType(p, tw and PLOT_OCEAN or PLOT_LAND, bRecalc)
			end
		end
	end
	fn.setTerrainType = setTerrainType

	---------------------------------------------------------------------------------------------
	-- derived queries
	---------------------------------------------------------------------------------------------
	local function isAdjacentToShallowWater(p)
		local n = p._n
		for d = 0, 5 do
			local q = n[d]
			if q and q._ter == SHALLOW then return true end
		end
		return false
	end

	-- m_bPotentialCityWork: updatePotentialCityWork() runs for every plot within radius 5 of each
	-- water<->land flip, so the flag always equals "some land plot within radius 5" of the current map.
	-- Computed on demand and cached per plot until the next water<->land flip (S.landVersion).
	local function ring5(p)
		local r = p._ring5
		if r then return r end
		r = {}
		local G = S.G
		local x, y = p._x, p._y
		local plots, W = S.plots, S.W
		for i = 0, 90 do
			local nx, ny = G.plotXY(x, y, S.ringDHX[i], S.ringDY[i])
			if nx then r[#r + 1] = plots[ny * W + nx] end
		end
		p._ring5 = r
		return r
	end
	fn.ring5 = ring5
	local function isPotentialCityWork(p)
		if p._pcwV == S.landVersion then return p._pcw end
		local r = ring5(p)
		local v = false
		for k = 1, #r do
			if r[k]._pt ~= PLOT_OCEAN then v = true; break end
		end
		p._pcw = v
		p._pcwV = S.landVersion
		return v
	end
	fn.isPotentialCityWork = isPotentialCityWork

	local function isNaturalWonder(p, orPseudo)
		local f = p._feat
		if f == -1 then return false end
		if orPseudo then return FNWorPseudo[f] and true or false end
		return FNW[f] and true or false
	end

	local function isValidMovePlotNoPlayer(p)
		return (not p._imps and p._feat ~= FEATURE_ICE) or p._route ~= -1
	end

	local function canHaveFeature(p, f)
		if f == -1 then return true end
		if p._feat ~= -1 then return false end
		if isMountain(p) then return false end
		local info = S.info
		if not info.featureExists[f] then return false end
		if p._ter == -1 then
			error(("c5maps: CanHaveFeature on plot (%d,%d) with NO_TERRAIN (-1): the C++ asserts/reads out of range here; give the plot a terrain first"):format(p._x, p._y), 3)
		end
		local tb = info.featureTerrain[f]
		if not (tb and tb[p._ter]) then return false end
		local fi = info.features[f]
		if fi.NoCoast and p._adjW then return false end   -- cached isCoastalLand() (m_bIsAdjacentToWater)
		if fi.NoRiver and p._rcn > 0 then return false end
		if fi.RequiresFlatlands and p._pt == PLOT_HILLS then return false end
		if fi.NoAdjacent then
			local n = p._n
			for d = 0, 5 do
				local q = n[d]
				if q and q._feat == f then return false end
			end
		end
		if fi.RequiresRiver and not (p._rcn > 0) then return false end
		return true
	end
	fn.canHaveFeature = canHaveFeature

	local function isRiverSide(p)
		local n = p._n
		local G = S.G
		for d = 0, 5 do
			local q = n[d]
			if q then
				local dir = G.directionXY(p._x, p._y, q._x, q._y)
				if dir < 6 and p._rc[dir] then return true end
			end
		end
		return false
	end

	local function isCoastalLandCached(p, minWaterSize)
		if not p._adjW then return false end
		if minWaterSize < 2 then return true end
		local n = p._n
		for d = 0, 5 do
			local q = n[d]
			if q and q._pt == PLOT_OCEAN and q._feat ~= FEATURE_ICE then
				local lm = S.landmassById[q._lm]
				if lm and lm.tiles >= minWaterSize then return true end
			end
		end
		return false
	end
	fn.isCoastalLandCached = isCoastalLandCached

	local function canHaveImprovement(p, im, player, checkAdj, testXAdj)
		local info = S.info
		local ii = info.improvements[im]
		if not ii then return false end
		if player ~= -1 then
			error("c5maps: CanHaveImprovement with a player argument is not implemented (only the NO_PLAYER path)", 3)
		end
		local f = p._feat
		local valid = false
		if f ~= -1 then
			if ii.CreatesFeature and info.featureIdByType[ii.CreatesFeature] == f then return false end
			if FNW[f] then return false end
		end
		if ii.MountainsMakesValid and isMountain(p) then valid = true end
		if not isValidMovePlotNoPlayer(p) then return false end
		if (ii.Water and true or false) ~= (p._pt == PLOT_OCEAN) then return false end
		if f ~= -1 and info.features[f].NoImprovement then return false end
		local res = p._res   -- getResourceType(NO_TEAM)
		if res ~= -1 then
			if info.improvementResourceValid[im] and info.improvementResourceValid[im][res] then
				valid = true
			elseif not ii.BuildableOnResources then
				return false
			end
		else
			if ii.RequiresResource then return false end
		end
		-- (NoAdjacentCity / AdjacentCity: no cities exist during map generation)
		if ii.NoFreshWater and p._fresh then return false end   -- isFreshWater() uses the cache
		if ii.RequiresFlatlands and p._pt ~= PLOT_LAND then return false end
		if ii.RequiresFlatlandsOrFreshWater and p._pt ~= PLOT_LAND and not p._fresh then return false end
		local n = p._n
		if ii.RequiresFeature and f == -1 then
			local lake = false
			if ii.Lakeside then
				for d = 0, 5 do local q = n[d]; if q and q._lake then lake = true; break end end
			end
			if not lake then return false end
		end
		if ii.Lakeside then
			for d = 0, 5 do local q = n[d]; if q and q._lake then valid = true; break end end
		end
		if ii.RequiresImprovement then
			if p._imp == -1 then return false else valid = false end
		end
		if ii.Coastal and not isCoastalLandCached(p, MIN_WATER_OCEAN) then return false end
		if ii.CoastMakesValid and (p._pt == PLOT_OCEAN and not p._lake) then valid = true end
		if ii.HillsMakesValid and p._pt == PLOT_HILLS then valid = true end
		if ii.WaterAdjacencyMakesValid and (isCoastalLandCached(p, -1) or p._fresh or p._rcn > 0) then valid = true end
		if ii.FreshWaterMakesValid and p._fresh then valid = true end
		if ii.RiverSideMakesValid and p._rcn > 0 then valid = true end
		if p._ter ~= -1 and info.improvementTerrainValid[im] and info.improvementTerrainValid[im][p._ter] then valid = true end
		if p._imp ~= -1 and info.improvementImprovementValid[im] and info.improvementImprovementValid[im][p._imp] then valid = true end
		if f ~= -1 and info.improvementFeatureValid[im] and info.improvementFeatureValid[im][f] then valid = true end
		local xsame = ii.XSameAdjacentMakesValid or 0
		if xsame > 0 then
			if testXAdj then valid = true else
				local c = 0
				for d = 0, 5 do
					local q = n[d]
					if q and q._imp == im then c = c + 1; if c >= xsame then valid = true; break end end
				end
			end
		end
		if not valid then return false end
		if ii.RiverSideMakesValid then
			valid = false
			local G = S.G
			for d = 0, 5 do
				local q = n[d]
				if q then
					local dir = G.directionXY(p._x, p._y, q._x, q._y)
					if dir < 6 and p._rc[dir] and q._imp ~= im then valid = true; break end
				end
			end
			if not valid then return false end
		end
		local reqLand = ii.RequiresXAdjacentLand
		if reqLand and reqLand > -1 then
			local c = 0
			for d = 0, 5 do local q = n[d]; if q and q._pt ~= PLOT_OCEAN then c = c + 1 end end
			if c < reqLand then return false end
		end
		local reqWater = ii.RequiresXAdjacentWater
		if reqWater and reqWater > -1 then
			local c = 0
			for d = 0, 5 do local q = n[d]; if q and q._pt == PLOT_OCEAN then c = c + 1 end end
			if c < reqWater then return false end
		end
		if info.improvementPrereqNatureYield[im] then
			error("c5maps: CanHaveImprovement: Improvement_PrereqNatureYields not implemented for " .. tostring(ii.Type), 3)
		end
		if not checkAdj then return true end
		if ii.AdjacentLuxury or ii.NoTwoAdjacent then
			local luxMet = not ii.AdjacentLuxury
			for d = 0, 5 do
				local q = n[d]
				if q then
					if ii.AdjacentLuxury and q._res ~= -1 and info.resourceUsage[q._res] == 2 then luxMet = true end
					if ii.NoTwoAdjacent and q._imp == im then return false end
				end
			end
			if not luxMet then return false end
		end
		return true
	end

	-- calculateNatureYield + calculateYieldFast for an unowned, city-less plot
	local function calculateYield(p, y)
		local info = S.info
		local ter = p._ter
		if ter == -1 then return 0 end
		if info.MOD_CORE_NO_YIELD_ICE and p._feat == FEATURE_ICE then return 0 end
		if not isPotentialCityWork(p) then return 0 end
		local f = p._feat
		local yv = info.terrainYield[ter] and info.terrainYield[ter][y] or 0
		-- desert production bonus needs resource AND improvement (never during mapgen unless both set)
		if y == 1 and ter == TERRAIN_DESERT and p._pt ~= PLOT_HILLS and f == -1 and p._res ~= -1 and p._imp ~= -1 then
			yv = yv + (S.defines.BALANCE_PRODUCTION_DESERT_IMPROVEMENT or 0)
		end
		yv = yv + (info.plotYield[p._pt] and info.plotYield[p._pt][y] or 0)
		local yi = info.yields[y]
		local hills = p._pt == PLOT_HILLS
		if hills then yv = yv + (yi and yi.HillsChange or 0) end
		if isMountain(p) then yv = yv + (yi and yi.MountainChange or 0) end
		if p._lake then yv = yv + (yi and yi.LakeChange or 0) end
		local river = p._rcn > 0
		local fresh = p._fresh
		local coastal = p._adjW   -- isCoastalLand() cached
		local function get(t, k) local r = t[k]; return r and r[y] or 0 end
		if f ~= -1 then
			local fi = info.features[f]
			local ch = get(info.featureYield, f)
			if fi.YieldNotAdditive then yv = ch else yv = yv + ch end
			if river then yv = yv + get(info.featureRiverYield, f) end
			if hills then yv = yv + get(info.featureHillsYield, f) end
			if fresh then yv = yv + get(info.featureFreshYield, f) end
			if coastal then yv = yv + get(info.featureCoastalYield, f) end
		else
			if river then yv = yv + get(info.terrainRiverYield, ter) end
			if hills then yv = yv + get(info.terrainHillsYield, ter) end
			if fresh then yv = yv + get(info.terrainFreshYield, ter) end
			if coastal then yv = yv + get(info.terrainCoastalYield, ter) end
		end
		-- resources add nothing without an owner (eTeam == NO_TEAM)
		local adj = info.MOD_PLOTS_EXTENSIONS and info.plotAdjFeatureYield[p._pt]
		if adj then
			local nwPlot = isNaturalWonder(p, false)
			local n = p._n
			for d = 0, 5 do
				local q = n[d]
				if q and q._feat ~= -1 then
					local e = adj[q._feat]
					if e then
						local v = e[y]
						if v then
							if not v.ignoreNW or not nwPlot then yv = yv + v.v end
						end
					end
				end
			end
		end
		-- improvement / religion / player terms: taken as 0 for unowned plots (engine-api.md A9)
		if yv < 0 then yv = 0 end
		return yv
	end
	fn.calculateYield = calculateYield

	local function getLatitude(p)
		local lat
		if S.wrapX or not S.wrapY then
			lat = S.tdiv(p._y * 100, S.H)
		else
			lat = S.tdiv(p._x * 100, S.W)
		end
		lat = S.tdiv(lat * (S.topLatitude - S.bottomLatitude), 100)
		return math.abs(lat + S.bottomLatitude)
	end

	---------------------------------------------------------------------------------------------
	-- Lua-visible methods
	---------------------------------------------------------------------------------------------
	local P = PlotMethods
	function P:GetX() return self._x end
	function P:GetY() return self._y end
	function P:GetIndex() return self._i end
	function P:GetPlotIndex() return self._i end
	function P:GetPlotType() return self._pt end
	function P:GetTerrainType() return self._ter end
	function P:GetFeatureType() return self._feat end
	function P:GetResourceType(...)
		local r = self._res
		if select("#", ...) >= 1 then
			local team = toint((...))
			if team ~= -1 and r ~= -1 then
				if self._imp ~= -1 and self._imp == S.defines.BARBARIAN_CAMP_IMPROVEMENT then return -1 end
				if S.info.resourceTechReveal[r] then return -1 end   -- no team has techs during map generation
			end
		end
		return r
	end
	function P:GetNonObsoleteResourceType(...) return P.GetResourceType(self, ...) end
	function P:GetNumResource() return self._resq end
	function P:SetNumResource(n) self._resq = toint(n) end
	function P:ChangeNumResource(n) self._resq = self._resq + toint(n) end
	function P:GetImprovementType() return self._imp end
	function P:GetRouteType() return self._route end
	function P:GetTeam() return -1 end
	function P:GetOwner() return -1 end
	function P:IsOwned() return false end
	function P:IsCity() return false end
	function P:GetPlotCity() return nil end
	function P:GetWorkingCity() return nil end
	function P:IsRevealed() return false end
	function P:IsVisible() return false end
	function P:IsUnit() return false end
	function P:GetNumUnits() return 0 end
	function P:IsRoute() return self._route ~= -1 end
	function P:IsBarbarian() return false end
	function P:IsWater() return self._pt == PLOT_OCEAN end
	function P:IsHills() return self._pt == PLOT_HILLS end
	function P:IsMountain() return isMountain(self) end
	function P:IsFlatlands() return self._pt == PLOT_LAND end
	function P:IsOpenGround()
		if self._pt == PLOT_HILLS or isMountain(self) then return false end
		local f = self._feat
		if f ~= -1 and S.info.features[f].Rough then return false end
		return true
	end
	function P:IsRoughGround() return not P.IsOpenGround(self) end
	function P:IsImpassable(...)
		return self._imps
	end
	function P:IsLake() updateWaterFlags(self); return self._lake end
	function P:IsFreshWater() updateWaterFlags(self); return self._fresh end
	function P:IsAdjacentToLand() updateWaterFlags(self); return self._adjL end
	function P:IsCoastalLand() return isCoastalLandCached(self, -1) end
	function P:IsAdjacentToShallowWater() return isAdjacentToShallowWater(self) end
	function P:IsAdjacentToIce()
		local n = self._n
		for d = 0, 5 do local q = n[d]; if q and q._feat == FEATURE_ICE then return true end end
		return false
	end
	function P:IsAdjacentToArea(area)
		if type(area) ~= "table" or not area._isArea then error("bad argument #2 to 'IsAdjacentToArea' (Area expected)", 2) end
		local id = area.id
		local n = self._n
		for d = 0, 5 do local q = n[d]; if q and q._area == id then return true end end
		return false
	end
	function P:IsAdjacentToLandmass(id)
		id = toint(id)
		local n = self._n
		for d = 0, 5 do local q = n[d]; if q and q._lm == id then return true end end
		return false
	end
	function P:ShareAdjacentArea(other)
		local n = self._n
		for d = 0, 5 do
			local q = n[d]
			if q and q._area ~= -1 and P.IsAdjacentToArea(other, S.areaById[q._area]) then return true end
		end
		return false
	end
	function P:IsRiver() return self._rcn > 0 end
	function P:GetRiverCrossingCount() return self._rcn end
	function P:IsRiverCrossing(d) d = toint(d); return self._rc[d] or false end
	function P:IsRiverSide() return isRiverSide(self) end
	function P:IsWOfRiver() return self._w end
	function P:IsNWOfRiver() return self._nw end
	function P:IsNEOfRiver() return self._ne end
	function P:GetRiverEFlowDirection() return self._fE end
	function P:GetRiverSEFlowDirection() return self._fSE end
	function P:GetRiverSWFlowDirection() return self._fSW end
	function P:SetWOfRiver(b, flow) setWOfRiver(self, tobool(b), toint(flow)) end
	function P:SetNWOfRiver(b, flow) setNWOfRiver(self, tobool(b), toint(flow)) end
	function P:SetNEOfRiver(b, flow) setNEOfRiver(self, tobool(b), toint(flow)) end
	function P:GetArea() return self._area end
	function P:Area() return S.areaById[self._area] end
	function P:SetArea(id) setArea(self, toint(id)) end
	function P:GetLandmass() return self._lm end
	function P:GetContinent() return self._cont end
	function P:IsStartingPlot() return self._start end
	function P:SetStartingPlot(b) self._start = tobool(b) end
	function P:GetContinentArtType() return self._art end
	function P:SetContinentArtType(n)
		n = toint(n)
		-- stored as a signed char
		n = n % 256
		if n >= 128 then n = n - 256 end
		self._art = n
	end
	function P:IsNaturalWonder(orPseudo) return isNaturalWonder(self, tobool(orPseudo)) end
	function P:HasAnyNaturalWonder() return isNaturalWonder(self, true) end
	function P:IsGoody() return self._imp ~= -1 and S.info.improvements[self._imp].Goody and true or false end
	function P:IsPotentialCityWork() return isPotentialCityWork(self) end
	function P:GetLatitude() return getLatitude(self) end
	function P:CanHaveFeature(f) return canHaveFeature(self, toint(f)) end
	function P:CanHaveImprovement(im, player, checkAdj, testXAdj)
		local pl = -1
		if player ~= nil then pl = toint(player) end
		return canHaveImprovement(self, toint(im), pl, tobool(checkAdj), tobool(testXAdj))
	end
	function P:CalculateYield(y, display) return calculateYield(self, toint(y)) end
	function P:GetYield(y) return calculateYield(self, toint(y)) end
	function P:CalculateNatureYield(y) return calculateYield(self, toint(y)) end
	function P:GetInlandCorner()
		local order = { [0] = 0, 1, 2, 3 }
		S.shuffleArray(order, 4)
		local n = self._n
		local function hasCoastAtSECorner(c)
			if c._pt == PLOT_OCEAN then return true end
			local e = c._n[1]
			if e and e._pt == PLOT_OCEAN then return true end
			local se = c._n[2]
			if se and se._pt == PLOT_OCEAN then return true end
			return false
		end
		for i = 0, 3 do
			local k = order[i]
			local c
			if k == 0 then c = self elseif k == 1 then c = n[0] elseif k == 2 then c = n[5] else c = n[4] end
			if c and not hasCoastAtSECorner(c) then return c end
		end
		return nil
	end
	function P:SetPlotType(t, bRecalc, bGfx) setPlotType(self, toint(t), tobool(bRecalc)) end
	function P:SetTerrainType(t, bRecalc, bGfx) setTerrainType(self, toint(t), tobool(bRecalc)) end
	function P:SetFeatureType(f, ...) setFeatureType(self, toint(f)) end
	function P:SetResourceType(r, q) setResourceType(self, toint(r), toint(q)) end
	function P:SetImprovementType(im) setImprovementType(self, toint(im)) end
	function P:SetRouteType(r) self._route = toint(r) end
	function P:Erase() erase(self) end
	function P:IsNone() return false end
	function P:GetNumAdjacentMountains()
		local c = 0
		local n = self._n
		for d = 0, 5 do local q = n[d]; if q and isMountain(q) then c = c + 1 end end
		return c
	end
	function P:GetNearestLandArea() error("c5maps: unimplemented Plot:GetNearestLandArea", 2) end
	function P:SeeFromLevel() error("c5maps: unimplemented Plot:SeeFromLevel", 2) end
	-- feature / terrain / plot-type predicate helpers registered by VP
	function P:HasFeature(f) return self._feat == toint(f) end
	function P:HasPlotType(t) return self._pt == toint(t) end
	function P:HasTerrain(t) return self._ter == toint(t) end
	function P:HasResource(r) return self._res == toint(r) end
	function P:HasImprovement(i) return self._imp == toint(i) end
	function P:IsFeatureIce() return self._feat == FEATURE_ICE end
	function P:IsPlotMountain() return self._pt == PLOT_MOUNTAIN end
	P.IsPlotMountains = P.IsPlotMountain
	function P:IsPlotHill() return self._pt == PLOT_HILLS end
	P.IsPlotHills = P.IsPlotHill
	function P:IsPlotLand() return self._pt == PLOT_LAND end
	function P:IsPlotOcean() return self._pt == PLOT_OCEAN end

	return PlotMethods
end

return M
