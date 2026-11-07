--[[
engine/hexmath.lua -- odd-r hex geometry, ported from CvGameCoreUtils.cpp/.h, CvMap.h, CvGlobals.cpp.

Conventions (CvMap.h): plot index i = y*W + x; y = 0 is the south row; odd rows are shifted half a
hex east.  Hex space: hx = x - floor(y/2).

  local hexmath = require("hexmath")
  local G = hexmath.new(W, H, wrapX, wrapY)
  G.coordRange(c, range, wrap)        -- CvMap.h coordRange (C '%' semantics, -range -> range quirk)
  G.plotXYRaw(x, y)                    -- CvMap::plot(x,y) -> wrapped x', y' or nil (invalid)
  G.plotXY(x, y, dhx, dy)              -- CvGameCoreUtils plotXY -> x', y' or nil  (dhx in hex space)
  G.plotXYWithRangeCheck(x,y,dhx,dy,r) -> x', y' or nil
  G.neighborXY(x, y, dir)              -- the DLL neighbour table (InitPlots): x', y' or nil; dir 6/7 = self
  G.plotDistance(x1,y1,x2,y2)          -- cube distance with the DLL's wrap quirk (dz uses X wrap)
  G.directionXY(x1,y1,x2,y2)           -- DirectionTypes from plot 1 to plot 2 (7 = NO_DIRECTION)
  G.estimateDirection(...)             -- not used by map scripts; see fractal.lua
  G.ringOffset(i)                      -- iterateRingPlots hex offset (dhx, dy) for index i
  hexmath.xToHexspaceX(x, y), hexmath.hexspaceXToX(hx, y), hexmath.hexDistance(dhx, dy)
  hexmath.DIR_DHX / DIR_DY             -- per-direction hex-space deltas (0..7, CvGlobals.cpp)
  hexmath.EVEN_DX/EVEN_DY/ODD_DX/ODD_DY -- the same in offset coordinates, by row parity
]]

local floor = math.floor
local fmod = math.fmod
local abs = math.abs

local M = {}

M.NUM_DIRECTION_TYPES = 6
M.NO_DIRECTION = 7
M.INVALID_PLOT_COORD = -2147483647

-- CvGlobals.cpp aiPlotDirectionX/Y (hex space), slots 6 (DUMMY) and 7 (NONE) are (0,0)
M.DIR_DHX = { [0] = 0, 1, 1, 0, -1, -1, 0, 0 }
M.DIR_DY  = { [0] = 1, 0, -1, -1, 0, 1, 0, 0 }
-- offset-coordinate deltas by row parity (derived; MapmakerUtilities.lua:627)
M.EVEN_DX = { [0] = 0, 1, 0, -1, -1, -1 }
M.EVEN_DY = { [0] = 1, 0, -1, -1, 0, 1 }
M.ODD_DX  = { [0] = 1, 1, 1, 0, -1, 0 }
M.ODD_DY  = { [0] = 1, 0, -1, -1, 0, 1 }

local function xToHexspaceX(x, y) return x - floor(y / 2) end
local function hexspaceXToX(hx, y) return hx + floor(y / 2) end
M.xToHexspaceX = xToHexspaceX
M.hexspaceXToX = hexspaceXToX

function M.hexDistance(dx, dy)
	if (dx >= 0) == (dy >= 0) then
		return abs(dx) + abs(dy)
	end
	local ax, ay = abs(dx), abs(dy)
	return ax >= ay and ax or ay
end

-- C truncating division
local function tdiv(a, b)
	local q = a / b
	if q >= 0 then return floor(q) end
	return -floor(-q)
end
M.tdiv = tdiv

function M.wrapCoordDifference(d, range, wrap)
	if wrap then
		local half = floor(range / 2)
		if d > half then return d - range
		elseif d < -half then return d + range end
	end
	return d
end

-- iterateRingPlots offsets (CvGlobals.cpp aiRingPlotXOffset/YOffset for i < 91, the generic formula beyond)
local function ringOffset(i)
	if i == 0 then return 0, 0 end
	local ring, hi, lo = 0, 0, 0
	while hi < i do
		ring = ring + 1
		lo = hi + 1
		hi = hi + ring * 6
	end
	local diff = i - lo
	local side = floor(diff / ring)
	local off = diff % ring
	if side == 0 then return off, ring - off
	elseif side == 1 then return ring, -off
	elseif side == 2 then return ring - off, -ring
	elseif side == 3 then return -off, -ring + off
	elseif side == 4 then return -ring, off
	else return -ring + off, ring end
end
M.ringOffset = ringOffset
M.MAX_CITY_PLOTS = 91

function M.new(W, H, wrapX, wrapY)
	local G = { W = W, H = H, wrapX = wrapX and true or false, wrapY = wrapY and true or false }
	local INVALID = M.INVALID_PLOT_COORD

	local function coordRange(c, range, wrap)
		if wrap and range ~= 0 then
			if c < 0 then
				return range + fmod(c, range)
			elseif c >= range then
				return fmod(c, range)
			end
		end
		return c
	end
	G.coordRange = coordRange

	-- CvMap::plot(x, y)
	local function plotXYRaw(x, y)
		if x == INVALID or y == INVALID then return nil end
		x = coordRange(x, W, G.wrapX)
		y = coordRange(y, H, G.wrapY)
		if x >= 0 and x < W and y >= 0 and y < H then return x, y end
		return nil
	end
	G.plotXYRaw = plotXYRaw

	-- plotXY / plotXYWithRangeCheck are hot (MapmakerUtilities Plot_GetPlotsInCircle): inlined
	local wrapXf, wrapYf = G.wrapX, G.wrapY
	local function plotXY(x, y, dhx, dy)
		if x == INVALID or y == INVALID then return nil end
		local ny = y + dy
		local nx = x - floor(y / 2) + dhx + floor(ny / 2)
		if nx < 0 or nx >= W then
			if not wrapXf or W == 0 then return nil end
			if nx < 0 then nx = W + fmod(nx, W) else nx = fmod(nx, W) end
			if nx < 0 or nx >= W then return nil end
		end
		if ny < 0 or ny >= H then
			if not wrapYf or H == 0 then return nil end
			if ny < 0 then ny = H + fmod(ny, H) else ny = fmod(ny, H) end
			if ny < 0 or ny >= H then return nil end
		end
		return nx, ny
	end
	G.plotXY = plotXY

	function G.plotXYWithRangeCheck(x, y, dhx, dy, r)
		local hd
		if (dhx >= 0) == (dy >= 0) then
			hd = (dhx >= 0 and dhx or -dhx) + (dy >= 0 and dy or -dy)
		else
			local ax, ay = dhx >= 0 and dhx or -dhx, dy >= 0 and dy or -dy
			hd = ax >= ay and ax or ay
		end
		if hd > r then return nil end
		return plotXY(x, y, dhx, dy)
	end

	-- CvMap::InitPlots neighbour table
	function G.neighborXY(x, y, d)
		if d >= 6 then return x, y end
		local ny = y + M.DIR_DY[d]
		local nx = hexspaceXToX(xToHexspaceX(x, y) + M.DIR_DHX[d], ny)
		nx = coordRange(nx, W, G.wrapX)
		ny = coordRange(ny, H, G.wrapY)
		if nx >= 0 and nx < W and ny >= 0 and ny < H then return nx, ny end
		return nil
	end

	local function dxWrap(d) return M.wrapCoordDifference(d, W, G.wrapX) end
	local function dyWrap(d) return M.wrapCoordDifference(d, H, G.wrapY) end
	G.dxWrap, G.dyWrap = dxWrap, dyWrap

	function G.plotDistance(x1, y1, x2, y2)
		local hx1 = xToHexspaceX(x1, y1)
		local hx2 = xToHexspaceX(x2, y2)
		local z1 = -hx1 - y1
		local z2 = -hx2 - y2
		local dx = dxWrap(hx2 - hx1)
		local dy = dyWrap(y2 - y1)
		local dz = dxWrap(z2 - z1)
		return tdiv(abs(dx) + abs(dy) + abs(dz), 2)
	end

	function G.directionXY(x1, y1, x2, y2)
		local ox = dxWrap(xToHexspaceX(x2, y2) - xToHexspaceX(x1, y1))
		local oy = dyWrap(y2 - y1)
		if oy > 0 then
			return ox >= 0 and 0 or 5
		elseif oy == 0 then
			if ox > 0 then return 1 elseif ox == 0 then return 7 else return 4 end
		else
			return ox > 0 and 2 or 3
		end
	end

	function G.maxPlotDistance()
		local d = G.plotDistance(0, 0, G.wrapX and floor(W / 2) or (W - 1), G.wrapY and floor(H / 2) or (H - 1))
		return d > 1 and d or 1
	end

	return G
end

return M
