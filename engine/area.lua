--[[
engine/area.lua -- Area objects (CvArea / Lua/CvLuaArea.cpp) and Landmass records (CvLandmass, CvMap.cpp).

Area object fields: id, water, mountains, tiles, riverEdges, res[r], imp[i], starts, nw (natural wonders).
Lua methods follow CvLuaArea.cpp's registration list.  `Area:IsLake` is NOT registered in VP (commented
out at CvLuaArea.cpp:30), so calling it raises "c5maps: unimplemented Area:IsLake" -- like the game's
"attempt to call method 'IsLake' (a nil value)".

  local areamod = require("area")
  areamod.install(S)   -- S.newArea(id, water), S.newLandmass(id, water), S.AreaMethods
]]

local M = {}

function M.install(S)
	local toint = S.toint
	local AreaMethods = {}
	S.AreaMethods = AreaMethods
	local AreaMeta = { __index = AreaMethods, __tostring = function(a) return "Area(" .. a.id .. ")" end }
	setmetatable(AreaMethods, {
		__index = function(_, k)
			if type(k) == "string" and k:match("^%u") then
				error("c5maps: unimplemented Area:" .. k .. (k == "IsLake" and " (not registered in VP: CvLuaArea.cpp:30 is commented out; use plot:IsLake())" or ""), 2)
			end
			return nil
		end,
	})

	function S.newArea(id, water)
		return setmetatable({
			_isArea = true, id = id, water = water and true or false, mountains = false,
			tiles = 0, riverEdges = 0, res = {}, imp = {}, starts = 0, nw = 0,
		}, AreaMeta)
	end

	function S.newLandmass(id, water)
		return { id = id, water = water and true or false, tiles = 0, cx = 0, cy = 0, continentType = 0, areas = {} }
	end

	local A = AreaMethods
	function A:GetID() return self.id end
	function A:IsNone() return false end
	function A:GetNumTiles() return self.tiles end
	function A:IsWater() return self.water end
	function A:GetNumRiverEdges() return self.riverEdges end
	function A:GetNumOwnedTiles() return 0 end
	function A:GetNumUnownedTiles() return self.tiles end
	function A:GetNumCities() return 0 end
	function A:GetNumUnits() return 0 end
	function A:GetTotalPopulation() return 0 end
	function A:GetNumStartingPlots() return self.starts end
	function A:GetUnitsPerPlayer() return 0 end
	function A:GetCitiesPerPlayer() return 0 end
	function A:GetPopulationPerPlayer() return 0 end
	function A:GetNumRevealedTiles() return 0 end
	function A:GetNumUnrevealedTiles() return self.tiles end
	function A:GetNumResources(r) return self.res[toint(r)] or 0 end
	function A:GetNumTotalResources()
		local t = 0
		for _, v in pairs(self.res) do t = t + v end
		return t
	end
	function A:GetNumImprovements(i) return self.imp[toint(i)] or 0 end
	function A:CountNumUniqueResourceTypes()
		-- bug-compatible (CvArea.cpp:160): counts resource infos with OneArea, not resources present here
		local c = 0
		for _, row in ipairs(S.gi.rows("Resources")) do
			if row.OneArea then c = c + 1 end
		end
		return c
	end
	function A:CountCoastalLand()
		if self.water then return 0 end
		local c = 0
		for i = 0, S.numPlots - 1 do
			local p = S.plots[i]
			if p._area == self.id and S.fn.isCoastalLandCached(p, -1) then c = c + 1 end
		end
		return c
	end
	return AreaMethods
end

return M
