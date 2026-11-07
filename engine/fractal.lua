--[[
engine/fractal.lua -- exact pure-Lua 5.1 port of CvFractal (VP DLL, CvGameCoreDLL_Expansion2/CvFractal.cpp)
plus the Lua binding from Lua/CvLuaFractal.cpp.

Two layers:

1. M.CvFractal -- the C++ class, method-for-method:
     local f = M.CvFractal.new([mapInfo])
     f:fracInit(iNewXs, iNewYs, iGrain, random, iFlags, pRifts, iFracXExp, iFracYExp)
     f:fracInitHinted(iNewXs, iNewYs, iGrain, random, hints, iHintsLength, iFlags, pRifts, iFracXExp, iFracYExp)
         -- hints: 1-based Lua array of bytes; C++ pbyHints[i] == hints[i+1]
     f:fracInitInternal(...), f:tectonicAction(pRifts), f:yieldX(x)
     f:getHeight(x, y), f:getHeightFromPercent(pct)
     f:ridgeBuilder(random, iNumVoronoiSeeds, iRidgeFlags, iBlendRidge, iBlendFract [, mapInfo])
     f:reset(), f:uninit()
   iFlags / iRidgeFlags are integer bitmasks (M.FRAC_*). `random` is an engine/random.lua object.
   mapInfo = { width=, height=, wrapX=, wrapY= } or a function returning (width, height, wrapX, wrapY).
   It stands in for GC.getMap(): ridgeBuilder -> estimateDirection -> dxWrap/dyWrap use the *game map's*
   grid size and wrap flags (not the fractal's).  Without mapInfo the fractal's own
   (iXs, iYs, FRAC_WRAP_X, FRAC_WRAP_Y) are used.

2. M.newLuaAPI(ctx) -> the global `Fractal` table exactly as CvLuaFractal.cpp registers it:
     Fractal.Create(iNewXs, iNewYs, iGrain, flagsTable, iFracXExp, iFracYExp)
     Fractal.CreateRifts(iNewXs, iNewYs, iGrain, flagsTable, riftsFractal, iFracXExp, iFracYExp)
     frac:GetHeight(x, y)          -> getHeight
     frac:GetHeight(percent)       -> getHeightFromPercent  (dispatch on argument count, else error)
     frac:BuildRidges(iNumSeeds, flagsTable, iBlendRidge, iBlendFract)
   ctx.getMapRand()  -> the shared map Random (CvGame::getMapRand, also used by Map.Rand)
   ctx.getMapInfo()  -> width, height, wrapX, wrapY   (GC.getMap(), used by BuildRidges)
   Flags are *tables*: a flag is set when t.FRAC_xxx ~= nil (even `false` counts, like lua_isnil).
   M.fractalFlagsTable(wrapX, wrapY) builds what Map.GetFractalFlags() returns.

Binding quirks reproduced on purpose (they are observable by scripts):
  * Number arguments go through lua_tointeger: non-numbers -> 0, non-integers are rounded to nearest
    (ties to even) as Lua 5.1's MSVC x86 lua_number2integer (fld/fistp) does -- e.g.
    BuildRidges((numPlates*2)/3, ...) with numPlates=10 uses 7 seeds, not 6.
  * Fractal.Create reads iFracXExp/iFracYExp with `lua_isnil(L,5) ? default : lua_tointeger(L,5)`
    *after* the new userdata was pushed on the stack.  So when fewer than 6 arguments are passed,
    the slot right after the last argument is the userdata (-> exp 0), and slots beyond it are
    "none" (lua_isnil false -> exp 0).  Only an explicit nil (or -1) gives the default exponent.
  * Fractal.CreateRifts uses luaL_optint for the exponents (same stack effect: with only 5 args,
    slot 6 is the userdata -> "number expected" error) and lua_touserdata for the rifts arg
    (anything that is not a fractal -> no rifts).
]]

local floor = math.floor

local M = {}

M.FRACTAL_MAX_DIMS     = 255
M.FRAC_WRAP_X          = 0x0001
M.FRAC_WRAP_Y          = 0x0002
M.FRAC_PERCENT         = 0x0004  -- Returns raw data as a percent.
M.FRAC_POLAR           = 0x0008  -- Sets polar regions to zero.
M.FRAC_CENTER_RIFT     = 0x0010  -- Draws rift in center of world, too.
M.FRAC_INVERT_HEIGHTS  = 0x0020  -- Inverts the heights
M.DEFAULT_FRAC_X_EXP   = 7
M.DEFAULT_FRAC_Y_EXP   = 6
M.FLOAT_PRECISION      = 1000
M.NUM_DIRECTION_TYPES  = 6
M.NO_DIRECTION         = -1

local FRACTAL_MAX_DIMS = M.FRACTAL_MAX_DIMS
local FRAC_WRAP_X, FRAC_WRAP_Y = 1, 2
local FRAC_PERCENT, FRAC_POLAR, FRAC_CENTER_RIFT, FRAC_INVERT_HEIGHTS = 4, 8, 16, 32
local FLOAT_PRECISION = 1000
local INT_MAX = 2147483647

-- int m_aaiFrac[FRACTAL_MAX_DIMS+1][FRACTAL_MAX_DIMS+1] is stored flat with the same row stride
-- (256) as the C++ array, so [x][256] aliases [x+1][0] exactly like the C++ would.
-- Flat index (1-based) = x*STRIDE + y + 1.
local STRIDE = FRACTAL_MAX_DIMS + 1

---------------------------------------------------------------------------------------------
-- small integer helpers (C semantics)
---------------------------------------------------------------------------------------------
local function hasBit(flags, bit)          -- (flags & bit) != 0 for a single power-of-two bit
	return flags % (bit + bit) >= bit
end

local function tdiv(a, b)                  -- C/C++ int division (truncates toward zero)
	local q = a / b
	if q >= 0 then return floor(q) end
	return -floor(-q)
end

local function shl1(k)                     -- 1 << k on x86 (count masked to 5 bits), as int
	k = k % 32
	if k == 31 then return -2147483648 end
	return 2 ^ k
end

local function range(n, lo, hi)
	if n < lo then return lo elseif n > hi then return hi end
	return n
end

-- CvGameCoreUtils.h
local function xToHexspaceX(iX, iY)
	if iY >= 0 then return iX - floor(iY / 2) end
	return iX - tdiv(iY - 1, 2)
end

local function hexDistance(iDX, iDY)
	local ax = iDX >= 0 and iDX or -iDX
	local ay = iDY >= 0 and iDY or -iDY
	if (iDX >= 0) == (iDY >= 0) then return ax + ay end
	return ax >= ay and ax or ay
end

local function wrapCoordDifference(iDiff, uiRange, bWrap)
	if bWrap then
		local half = floor(uiRange / 2)
		if iDiff > half then return iDiff - uiRange
		elseif iDiff < -half then return iDiff + uiRange end
	end
	return iDiff
end

-- hexspaceDirections[6][3] = {{0,1,-1},{1,0,-1},{1,-1,0},{0,-1,1},{-1,0,1},{-1,1,0}}  (NE,E,SE,SW,W,NW)
local function estimateDirection(iStartX, iStartY, iDestX, iDestY, gw, gh, wrapX, wrapY)
	local iStartXHex = xToHexspaceX(iStartX, iStartY)
	local iDestXHex = xToHexspaceX(iDestX, iDestY)
	local iDX = wrapCoordDifference(iDestXHex - iStartXHex, gw, wrapX)
	local iDY = wrapCoordDifference(iDestY - iStartY, gh, wrapY)
	if iDX == 0 and iDY == 0 then return -1 end
	local iStartZ = -iStartXHex - iStartY
	local iDestZ = -iDestXHex - iDestY
	local iDZ = iDestZ - iStartZ
	local maximum, idx = 0, -1
	local d
	d = iDY - iDZ;  if d > maximum then maximum = d; idx = 0 end
	d = iDX - iDZ;  if d > maximum then maximum = d; idx = 1 end
	d = iDX - iDY;  if d > maximum then maximum = d; idx = 2 end
	d = iDZ - iDY;  if d > maximum then maximum = d; idx = 3 end
	d = iDZ - iDX;  if d > maximum then maximum = d; idx = 4 end
	d = iDY - iDX;  if d > maximum then maximum = d; idx = 5 end
	return idx
end

M.xToHexspaceX = xToHexspaceX
M.hexDistance = hexDistance
M.wrapCoordDifference = wrapCoordDifference
M.estimateDirection = estimateDirection

---------------------------------------------------------------------------------------------
-- CvFractal
---------------------------------------------------------------------------------------------
local CvFractal = {}
CvFractal.__index = CvFractal
M.CvFractal = CvFractal

function CvFractal.new(mapInfo)
	local self = setmetatable({ frac = {}, mapInfo = mapInfo }, CvFractal)
	self:reset()
	return self
end

function CvFractal:uninit()
end

function CvFractal:reset()
	self:uninit()
	self.fracXExp = -1
	self.fracYExp = -1
	self.xs = -1
	self.ys = -1
	self.flags = 0
	self.fracX = -1
	self.fracY = -1
end

function CvFractal:fracInit(iNewXs, iNewYs, iGrain, random, iFlags, pRifts, iFracXExp, iFracYExp)
	self:fracInitInternal(iNewXs, iNewYs, iGrain, random, nil, -1, iFlags, pRifts,
		iFracXExp or M.DEFAULT_FRAC_X_EXP, iFracYExp or M.DEFAULT_FRAC_Y_EXP)
end

-- hints: 1-based Lua array, length = iHintsWidth*iHintsHeight where
--   iHintsWidth  = 2^(iFracXExp - iSmooth) + (wrapX and 0 or 1)
--   iHintsHeight = 2^(iFracYExp - iSmooth) + (wrapY and 0 or 1), iSmooth = clamp(minExp - grain, 0, minExp)
function CvFractal:fracInitHinted(iNewXs, iNewYs, iGrain, random, hints, iHintsLength, iFlags, pRifts, iFracXExp, iFracYExp)
	local iFlagsNonPolar = iFlags
	if hasBit(iFlags, FRAC_POLAR) then iFlagsNonPolar = iFlags - FRAC_POLAR end
	self:fracInitInternal(iNewXs, iNewYs, iGrain, random, hints, iHintsLength, iFlagsNonPolar, pRifts,
		iFracXExp or M.DEFAULT_FRAC_X_EXP, iFracYExp or M.DEFAULT_FRAC_Y_EXP)
end

function CvFractal:fracInitInternal(iNewXs, iNewYs, iGrain, random, hints, iHintsLength, iFlags, pRifts, iFracXExp, iFracYExp)
	self:reset()

	if iFracXExp < 0 then iFracXExp = M.DEFAULT_FRAC_X_EXP end
	if iFracYExp < 0 then iFracYExp = M.DEFAULT_FRAC_Y_EXP end
	if iFracXExp > 8 or iFracYExp > 8 then
		error(("CvFractal: fractal exponent %d/%d exceeds the C++ array (max 8)"):format(iFracXExp, iFracYExp), 3)
	end

	self.fracXExp = iFracXExp
	self.fracYExp = iFracYExp
	local fracX = 2 ^ iFracXExp
	local fracY = 2 ^ iFracYExp
	self.fracX, self.fracY = fracX, fracY

	-- Init m_aaiFrac to all zeroes (we zero the whole prefix [0..fracX][0..255] so the table
	-- stays a dense Lua array; C++ zeroes [0..fracX][0..fracY], the rest is never read).
	local frac = {}
	for i = 1, (fracX + 1) * STRIDE + 1 do frac[i] = 0 end
	self.frac = frac

	if iNewXs == 0 or iNewYs == 0 then
		error("CvFractal: integer division by zero (width/height 0)", 3)
	end
	self.xs = iNewXs
	self.ys = iNewYs
	self.flags = iFlags
	self.xInc = tdiv(fracX * FLOAT_PRECISION, iNewXs)
	self.yInc = tdiv(fracY * FLOAT_PRECISION, iNewYs)

	local wrapX = hasBit(iFlags, FRAC_WRAP_X)
	local wrapY = hasBit(iFlags, FRAC_WRAP_Y)
	local polar = hasBit(iFlags, FRAC_POLAR)
	local centerRift = hasBit(iFlags, FRAC_CENTER_RIFT)

	local iMinExp = iFracXExp < iFracYExp and iFracXExp or iFracYExp
	local iSmooth = range(iMinExp - iGrain, 0, iMinExp)

	local iHintsWidth = 2 ^ (iFracXExp - iSmooth) + (wrapX and 0 or 1)
	local iHintsHeight = 2 ^ (iFracYExp - iSmooth) + (wrapY and 0 or 1)
	if hints ~= nil and iHintsLength ~= iHintsWidth * iHintsHeight then
		error(("pbyHints is the wrong size! got %s, expected %d"):format(tostring(iHintsLength), iHintsWidth * iHintsHeight), 3)
	end

	local get = random.get
	local xEnd0 = wrapX and 0 or 1
	local yEnd0 = wrapY and 0 or 1

	for iPass = iSmooth, 0, -1 do
		local p = 2 ^ iPass                     -- 1 << iPass

		if wrapY then
			for iX = 0, fracX do
				frac[iX * STRIDE + fracY + 1] = frac[iX * STRIDE + 1]
			end
		elseif polar then
			for iX = 0, fracX do
				frac[iX * STRIDE + 1] = 0
				frac[iX * STRIDE + fracY + 1] = 0
			end
		end

		if wrapX then
			for iY = 0, fracY do
				frac[fracX * STRIDE + iY + 1] = frac[iY + 1]
			end
		elseif polar then
			for iY = 0, fracY do
				frac[iY + 1] = 0
				frac[fracX * STRIDE + iY + 1] = 0
			end
		end

		if centerRift then
			if wrapY then
				local y12 = floor(fracY / 12)
				for iX = 0, fracX do
					for iY = 0, floor(fracY / 6) - 1 do
						local dv = (y12 - iY >= 0 and y12 - iY or iY - y12) + 1
						local i1 = iX * STRIDE + iY + 1
						local i2 = iX * STRIDE + floor(fracY / 2) + iY + 1
						frac[i1] = tdiv(frac[i1], dv)
						frac[i2] = tdiv(frac[i2], dv)
					end
				end
			end
			if wrapX then
				local x12 = floor(fracX / 12)
				for iY = 0, fracY do
					for iX = 0, floor(fracX / 6) - 1 do
						local dv = (x12 - iX >= 0 and x12 - iX or iX - x12) + 1
						local i1 = iX * STRIDE + iY + 1
						local i2 = (floor(fracX / 2) + iX) * STRIDE + iY + 1
						frac[i1] = tdiv(frac[i1], dv)
						frac[i2] = tdiv(frac[i2], dv)
					end
				end
			end
		end

		local xCount = floor(fracX / p) + xEnd0      -- (m_iFracX >> iPass) + (wrapX ? 0 : 1)
		local yCount = floor(fracY / p) + yEnd0
		if iPass == iSmooth then
			-- first pass: set the initial random spots (x outer, y inner -- RNG order matters)
			for iX = 0, xCount - 1 do
				local base = iX * p * STRIDE + 1
				for iY = 0, yCount - 1 do
					if hints == nil then
						frac[base + iY * p] = get(random, 256, "Fractal Gen")
					else
						local iXX = iX % iHintsWidth
						local iYY = iY % iHintsHeight
						local v = hints[iYY * iHintsWidth + iXX + 1]
						if v == nil then error("iHintsI out of range", 3) end
						frac[base + iY * p] = floor(v) % 256   -- byte
					end
				end
			end
		else
			-- interpolate
			local rnum = shl1(8 - iSmooth + iPass)
			local rsub = shl1(7 - iSmooth + iPass)
			local pS = p * STRIDE
			for iX = 0, xCount - 1 do
				local xOdd = iX % 2 == 1                   -- ((iX << iPass) & iScreen) != 0
				local col = iX * pS + 1
				for iY = 0, yCount - 1 do
					local yOdd = iY % 2 == 1               -- ((iY << iPass) & iScreen) != 0
					local i = col + iY * p
					local iSum
					if xOdd then
						if yOdd then  -- (center)
							iSum = frac[i - pS - p] + frac[i + pS - p] + frac[i - pS + p] + frac[i + pS + p]
							iSum = floor(iSum / 4)
						else          -- (horizontal)
							iSum = floor((frac[i - pS] + frac[i + pS]) / 2)
						end
					elseif yOdd then  -- (vertical)
						iSum = floor((frac[i - p] + frac[i + p]) / 2)
					end
					-- (corner): already set in an earlier pass
					if iSum then
						iSum = iSum + get(random, rnum, "Fractal Gen")
						iSum = iSum - rsub
						if iSum < 0 then iSum = 0 elseif iSum > 255 then iSum = 255 end
						frac[i] = iSum
					end
				end
			end
		end
	end

	if pRifts then
		self:tectonicAction(pRifts)  -- Assumes FRAC_WRAP_X is on.
	end

	if hasBit(iFlags, FRAC_INVERT_HEIGHTS) then
		for iX = 0, fracX - 1 do
			for iY = 0, fracY - 1 do
				local i = iX * STRIDE + iY + 1
				frac[i] = 255 - frac[i]
			end
		end
	end
end

function CvFractal:getHeight(iX, iY)
	if 0 > iX or iX >= self.xs then return 0 end
	if 0 > iY or iY >= self.ys then return 0 end

	local fracX, fracY = self.fracX, self.fracY
	local xInc, yInc = self.xInc, self.yInc

	local iLowX = tdiv(xInc * iX, FLOAT_PRECISION)
	if iLowX > fracX - 1 then iLowX = fracX - 1 end
	local iLowY = tdiv(yInc * iY, FLOAT_PRECISION)
	if iLowY > fracY - 1 then iLowY = fracY - 1 end
	local iErrX = xInc * iX - iLowX * FLOAT_PRECISION
	local iErrY = yInc * iY - iLowY * FLOAT_PRECISION

	if iLowX < 0 or iLowX >= FRACTAL_MAX_DIMS then return 0 end
	if iLowY < 0 or iLowY >= FRACTAL_MAX_DIMS then return 0 end

	local frac = self.frac
	local i = iLowX * STRIDE + iLowY + 1
	local iSum = (FLOAT_PRECISION - iErrX) * (FLOAT_PRECISION - iErrY) * frac[i]
		+ iErrX * (FLOAT_PRECISION - iErrY) * frac[i + STRIDE]
		+ (FLOAT_PRECISION - iErrX) * iErrY * frac[i + 1]
		+ iErrX * iErrY * frac[i + STRIDE + 1]
	iSum = tdiv(iSum, FLOAT_PRECISION * FLOAT_PRECISION)

	local iHeight = range(iSum, 0, 255)
	if hasBit(self.flags, FRAC_PERCENT) then
		return floor(iHeight * 100 / 256)
	end
	return iHeight
end

function CvFractal:getHeightFromPercent(iPercent)
	local iLowerBound, iUpperBound = 0, 255
	iPercent = range(iPercent, 0, 100)
	local iEstimate = floor(255 * iPercent / 100)
	local frac = self.frac
	local fracX, fracY = self.fracX, self.fracY
	local total = fracX * fracY

	while iEstimate ~= iLowerBound do
		local iSum = 0
		for iX = 0, fracX - 1 do
			local base = iX * STRIDE + 1
			for i = base, base + fracY - 1 do
				if frac[i] < iEstimate then iSum = iSum + 1 end
			end
		end
		if tdiv(100 * iSum, total) > iPercent then
			iUpperBound = iEstimate
		else
			iLowerBound = iEstimate
		end
		iEstimate = tdiv(iUpperBound + iLowerBound, 2)
	end
	return iEstimate
end

function CvFractal:yieldX(iBadX)  -- Assumes FRAC_WRAP_X is on.
	if iBadX < 0 then return iBadX + self.fracX end
	if iBadX >= self.fracX then return iBadX - self.fracX end
	return iBadX
end

function CvFractal:tectonicAction(pRifts)  -- Assumes FRAC_WRAP_X is on.
	local fracX, fracY = self.fracX, self.fracY
	local frac, rfrac = self.frac, pRifts.frac
	local iRift2x = floor(fracX / 4) * 3
	local iWidth = 16
	for iY = 0, fracY do
		-- pRifts->m_aaiFrac[iRift2x][iY]; if the rifts fractal is smaller, C++ reads stale memory: we use 0
		local rv = rfrac[iRift2x * STRIDE + iY + 1] or 0
		local off = tdiv(tdiv((rv - 128) * fracX, 128), 8)
		for iX = 0, iWidth - 1 do
			local iDeep = 0
			local iRx = self:yieldX(off + iX)
			local iLx = self:yieldX(off - iX)
			local ir = iRx * STRIDE + iY + 1
			frac[ir] = tdiv(frac[ir] * iX + iDeep * (iWidth - iX), iWidth)
			local il = iLx * STRIDE + iY + 1
			frac[il] = tdiv(frac[il] * iX + iDeep * (iWidth - iX), iWidth)
		end
	end
	for iY = 0, fracY do
		frac[fracX * STRIDE + iY + 1] = frac[iY + 1]
	end
end

local function resolveMapInfo(self, mapInfo)
	mapInfo = mapInfo or self.mapInfo
	if type(mapInfo) == "function" then
		return mapInfo()
	elseif type(mapInfo) == "table" then
		return mapInfo.width, mapInfo.height, mapInfo.wrapX and true or false, mapInfo.wrapY and true or false
	end
	return self.xs, self.ys, hasBit(self.flags, FRAC_WRAP_X), hasBit(self.flags, FRAC_WRAP_Y)
end

function CvFractal:ridgeBuilder(random, iNumVoronoiSeeds, iRidgeFlags, iBlendRidge, iBlendFract, mapInfo)
	local gw, gh, gwrapX, gwrapY = resolveMapInfo(self, mapInfo)
	local get = random.get
	local fracX, fracY = self.fracX, self.fracY

	if iNumVoronoiSeeds < 3 then iNumVoronoiSeeds = 3 end

	local sX, sY, sWeak, sBias, sStr = {}, {}, {}, {}, {}
	for s = 1, iNumVoronoiSeeds do
		local hy = get(random, fracY, "Ridge Gen 1")
		local hx = xToHexspaceX(get(random, fracX, "Ridge Gen 2"), hy)
		local weak = get(random, 7, "Ridge Gen 3") - 3
		if weak < 0 then weak = 0 end
		local bias = get(random, M.NUM_DIRECTION_TYPES, "Ridge Gen 4")
		local str = get(random, 8, "Ridge Gen 5") - 4
		if str < 0 then str = 0 end

		local recheck = true
		while recheck do
			recheck = false
			for t = 1, s - 1 do
				if hexDistance(hx - sX[t], hy - sY[t]) < 7 then
					hx = get(random, fracX, "Ridge Gen 6")
					hy = get(random, fracY, "Ridge Gen 7")
					recheck = true
					break
				end
			end
		end
		sX[s], sY[s], sWeak[s], sBias[s], sStr[s] = hx, hy, weak, bias, str
	end

	local sOpp = {}
	for s = 1, iNumVoronoiSeeds do sOpp[s] = (sBias[s] + 3) % 6 end

	local frac = self.frac
	local blendDiv = iBlendRidge + iBlendFract
	if blendDiv < 1 then blendDiv = 1 end
	local useFlags = iRidgeFlags ~= 0
	local halfW, halfH = floor(gw / 2), floor(gh / 2)

	for iX = 0, fracX - 1 do
		for iY = 0, fracY - 1 do
			local iThisHexX = xToHexspaceX(iX, iY)
			local iClosest, iNext = INT_MAX, INT_MAX
			-- estimateDirection(iThisHexX, iY, ...) converts the *already hexspace* X again (sic)
			local startXHex = iThisHexX - floor(iY / 2)
			local startZ = -startXHex - iY
			for s = 1, iNumVoronoiSeeds do
				local shx, shy = sX[s], sY[s]
				local dx, dy = iThisHexX - shx, iY - shy
				local d
				-- hexDistance(dx, dy)
				local ax = dx >= 0 and dx or -dx
				local ay = dy >= 0 and dy or -dy
				if (dx >= 0) == (dy >= 0) then d = ax + ay else d = ax >= ay and ax or ay end
				if useFlags then
					d = d + sWeak[s]
					d = d + get(random, 3, "Ridge Gen 8")
					-- estimateDirection(iThisHexX, iY, shx, shy) inlined
					local destXHex = xToHexspaceX(shx, shy)
					local iDX = destXHex - startXHex
					if gwrapX then
						if iDX > halfW then iDX = iDX - gw elseif iDX < -halfW then iDX = iDX + gw end
					end
					local iDY = shy - iY
					if gwrapY then
						if iDY > halfH then iDY = iDY - gh elseif iDY < -halfH then iDY = iDY + gh end
					end
					local dir = -1
					if iDX ~= 0 or iDY ~= 0 then
						local iDZ = (-destXHex - shy) - startZ
						local maximum, v = 0
						v = iDY - iDZ; if v > maximum then maximum = v; dir = 0 end
						v = iDX - iDZ; if v > maximum then maximum = v; dir = 1 end
						v = iDX - iDY; if v > maximum then maximum = v; dir = 2 end
						v = iDZ - iDY; if v > maximum then maximum = v; dir = 3 end
						v = iDZ - iDX; if v > maximum then maximum = v; dir = 4 end
						v = iDY - iDX; if v > maximum then maximum = v; dir = 5 end
					end
					if dir == sBias[s] then
						d = d - sStr[s]
					elseif dir == sOpp[s] then
						d = d + sStr[s]
					end
					if d < 1 then d = 1 end
				end
				if d < iClosest then
					iNext = iClosest
					iClosest = d
				elseif d < iNext then
					iNext = d
				end
			end

			local iRidgeHeight = 0
			if iNext ~= 0 then
				-- static_cast<int>((255.0 * iClosestSeed) / iNextClosestSeed): IEEE double, same as Lua
				local r = (255.0 * iClosest) / iNext
				if r >= 0 then iRidgeHeight = floor(r) else iRidgeHeight = -floor(-r) end
			end
			local i = iX * STRIDE + iY + 1
			frac[i] = tdiv(iRidgeHeight * iBlendRidge + frac[i] * iBlendFract, blendDiv)
		end
	end
end

-- Raw access for tests/tools: m_aaiFrac[x][y]
function CvFractal:getRaw(x, y)
	return self.frac[x * STRIDE + y + 1]
end

---------------------------------------------------------------------------------------------
-- Lua binding (CvLuaFractal.cpp)
---------------------------------------------------------------------------------------------

-- lua_tointeger emulation (Lua 5.1, MSVC x86: fistp => round to nearest, ties to even).
local function toInteger(v)
	if type(v) == "string" then v = tonumber(v) end
	if type(v) ~= "number" then return 0 end
	if v ~= v then return 0 end
	local f = floor(v)
	local fr = v - f
	if fr > 0.5 or (fr == 0.5 and f % 2 == 1) then f = f + 1 end
	return f
end
M.toInteger = toInteger

-- GetFractalFlags(L, idx): luaL_checktype(table) + HasFlag = field ~= nil
local FLAG_NAMES = { "FRAC_WRAP_X", "FRAC_WRAP_Y", "FRAC_PERCENT", "FRAC_POLAR", "FRAC_CENTER_RIFT", "FRAC_INVERT_HEIGHTS" }
local FLAG_BITS = { 1, 2, 4, 8, 16, 32 }
function M.getFractalFlags(t, argn, fname)
	if type(t) ~= "table" then
		error(("bad argument #%d to '%s' (table expected, got %s)"):format(argn or 4, fname or "?", type(t)), 3)
	end
	local flags = 0
	for k = 1, #FLAG_NAMES do
		if t[FLAG_NAMES[k]] ~= nil then flags = flags + FLAG_BITS[k] end
	end
	return flags
end

-- Map.GetFractalFlags(): table with FRAC_WRAP_X / FRAC_WRAP_Y = true per map wrap (CvLuaMap.cpp)
function M.fractalFlagsTable(wrapX, wrapY)
	local t = {}
	if wrapX then t.FRAC_WRAP_X = true end
	if wrapY then t.FRAC_WRAP_Y = true end
	return t
end

-- Map.GetFractalFlags-style int (CvMap::getMapFractalFlags)
function M.mapFractalFlags(wrapX, wrapY)
	return (wrapX and FRAC_WRAP_X or 0) + (wrapY and FRAC_WRAP_Y or 0)
end

function M.newLuaAPI(ctx)
	ctx = ctx or {}
	local function mapRand()
		local r = ctx.getMapRand and ctx.getMapRand() or ctx.mapRand
		if not r then error("Fractal: no map random generator configured (ctx.getMapRand)", 3) end
		return r
	end

	local Methods = {}
	local Meta = { __index = Methods }   -- objects are tables standing in for the userdata
	local isFractal = setmetatable({}, { __mode = "k" })

	local function checkSelf(self, fname)
		if not isFractal[self] then
			error(("bad argument #1 to '%s' (userdata expected, got %s)"):format(fname, type(self)), 3)
		end
		return self.cv
	end

	-- emulate the Lua stack slot `idx` after CreateFractal pushed the userdata at n+1
	local function stackSlot(n, args, idx, ud)
		if idx <= n then return args[idx], false end
		if idx == n + 1 then return ud, false end
		return nil, true   -- "none"
	end

	local function newObject()
		local obj = setmetatable({}, Meta)
		isFractal[obj] = true
		obj.cv = CvFractal.new(ctx.getMapInfo)   -- nil -> fractal's own size/wrap
		return obj
	end

	local Fractal = {}

	-- Fractal.Create(iNewXs, iNewYs, iGrain, flags, iFracXExp, iFracYExp)
	function Fractal.Create(...)
		local n = select("#", ...)
		local args = { ... }
		local obj = newObject()
		local iNewXs = toInteger(args[1])
		local iNewYs = toInteger(args[2])
		local iGrain = toInteger(args[3])
		local rand = mapRand()
		local flags = M.getFractalFlags((stackSlot(n, args, 4, obj)), 4, "Create")
		local v5, none5 = stackSlot(n, args, 5, obj)
		local v6, none6 = stackSlot(n, args, 6, obj)
		-- lua_isnil(L, i) ? default : lua_tointeger(L, i)   (lua_isnil is false for "none")
		local iFracXExp = (v5 == nil and not none5) and M.DEFAULT_FRAC_X_EXP or toInteger(v5)
		local iFracYExp = (v6 == nil and not none6) and M.DEFAULT_FRAC_Y_EXP or toInteger(v6)
		obj.cv:fracInit(iNewXs, iNewYs, iGrain, rand, flags, nil, iFracXExp, iFracYExp)
		return obj
	end

	-- Fractal.CreateRifts(iNewXs, iNewYs, iGrain, flags, riftsFractal, iFracXExp, iFracYExp)
	function Fractal.CreateRifts(...)
		local n = select("#", ...)
		local args = { ... }
		local obj = newObject()
		local iNewXs = toInteger(args[1])
		local iNewYs = toInteger(args[2])
		local iGrain = toInteger(args[3])
		local rand = mapRand()
		local flags = M.getFractalFlags((stackSlot(n, args, 4, obj)), 4, "CreateRifts")
		local r5 = stackSlot(n, args, 5, obj)
		local pRifts = (isFractal[r5] and r5.cv) or nil     -- lua_touserdata: non-userdata -> NULL
		local function optint(idx, def)
			local v, none = stackSlot(n, args, idx, obj)
			if v == nil then return def end                 -- luaL_opt: none or nil -> default
			local num = (type(v) == "number" and v) or (type(v) == "string" and tonumber(v))
			if not num then
				error(("bad argument #%d to 'CreateRifts' (number expected, got %s)"):format(idx,
					isFractal[v] and "userdata" or type(v)), 3)
			end
			return toInteger(num)
		end
		local iFracXExp = optint(6, M.DEFAULT_FRAC_X_EXP)
		local iFracYExp = optint(7, M.DEFAULT_FRAC_Y_EXP)
		-- note: when rifts arg is the fractal itself (n==4), pRifts is the fresh, uninitialised object;
		-- that only happens with too few arguments and is not reproducible bit-for-bit.
		obj.cv:fracInit(iNewXs, iNewYs, iGrain, rand, flags, pRifts, iFracXExp, iFracYExp)
		return obj
	end

	-- frac:GetHeight(x, y) / frac:GetHeight(percent)
	function Methods.GetHeight(self, ...)
		local cv = checkSelf(self, "GetHeight")
		local nargs = select("#", ...)
		if nargs == 1 then
			return cv:getHeightFromPercent(toInteger((...)))
		elseif nargs == 2 then
			local x, y = ...
			return cv:getHeight(toInteger(x), toInteger(y))
		end
		error("Invalid number of arguments.", 2)
	end

	-- frac:BuildRidges(iNumSeeds, flags, iBlendRidge, iBlendFract)
	function Methods.BuildRidges(self, iNumSeeds, flags, iBlendRidge, iBlendFract)
		local cv = checkSelf(self, "BuildRidges")
		local rand = mapRand()
		local n = toInteger(iNumSeeds)
		local f = M.getFractalFlags(flags, 3, "BuildRidges")
		cv:ridgeBuilder(rand, n, f, toInteger(iBlendRidge), toInteger(iBlendFract))
		return
	end

	return Fractal
end

return M
