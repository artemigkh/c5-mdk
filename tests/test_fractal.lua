-- tests/test_fractal.lua -- tests for engine/random.lua and engine/fractal.lua.
-- Run with: python tests/run_lua_tests.py   (lupa.lua51; package.path must include engine/?.lua)
-- Pure Lua 5.1; returns a table { passed = n, failed = n, failures = {...}, log = {...} }.

local Random = require("random")
local F = require("fractal")

local results = { passed = 0, failed = 0, failures = {}, log = {} }
local function log(fmt, ...) results.log[#results.log + 1] = string.format(fmt, ...) end

local function test(name, fn)
	local ok, err = pcall(fn)
	if ok then
		results.passed = results.passed + 1
	else
		results.failed = results.failed + 1
		results.failures[#results.failures + 1] = name .. ": " .. tostring(err)
	end
end

local function eq(a, b, msg)
	if a ~= b then error((msg or "") .. " expected " .. tostring(b) .. ", got " .. tostring(a), 2) end
end

local function eqList(got, want, msg)
	for i = 1, #want do
		if got[i] ~= want[i] then
			error(string.format("%s: index %d expected %s, got %s", msg or "", i, tostring(want[i]), tostring(got[i])), 2)
		end
	end
end

---------------------------------------------------------------------------------------------
-- Random (CvRandom) known answers, derived by executing the C++ arithmetic by hand:
--   newSeed = 1103515245*seed + 12345 (mod 2^64);  r = (newSeed >> 16) & 0xFFFFFFFF;
--   result  = (r * num) / 2^32
---------------------------------------------------------------------------------------------
test("random: seed 0 sequence", function()
	local r = Random.new(0)
	-- step 1: 1103515245*0 + 12345 = 12345;  r = 12345>>16 = 0;  0*100/2^32 = 0
	eq(r:get(100, "t"), 0, "draw1")
	eq(r:getSeed(), 12345, "seed1")
	-- step 2: 1103515245*12345 + 12345 = 13622895699525 + 12345 = 13622895711870
	--         r = floor(13622895711870 / 65536) = 207868892   (fits in 32 bits, no mask effect)
	--         207868892*100 = 20786889200;  / 4294967296 = 4.84 -> 4
	eq(r:get(100, "t"), 4, "draw2")
	eq(r:getSeed(), 13622895711870, "seed2")
	-- step 3: 1103515245*13622895711870 + 12345 = 15033033637484186047807... (> 2^64)
	--         mod 2^64 = 17423423094097455071 = 0xF1CC...;  hi32 = 4056687708, lo32 = 1838571743 (64-bit wrap!)
	--         r = bits 16..47 = 1862117124;  1862117124*100/2^32 = 43.36 -> 43
	eq(r:get(100, "t"), 43, "draw3 (64-bit wrap)")
	-- step 4: r = 3325679205 (>= 2^31: unsigned) -> *100/2^32 = 77.43 -> 77
	eq(r:get(100, "t"), 77, "draw4")
	eq(r:get(100, "t"), 51, "draw5")
	eq(r:getCallCount(), 5, "callCount")
end)

test("random: seed 42 sequence, num=256 and 7", function()
	local r = Random.new(42)
	-- step 1: 42*1103515245 + 12345 = 46347640290 + 12345 = 46347652635
	--         r = floor(46347652635/65536) = 707209;  707209*256/2^32 = 0.042 -> 0
	eq(r:get(256, "t"), 0)
	eq(r:get(256, "t"), 192)
	eq(r:get(256, "t"), 224)
	eq(r:get(7, "t"), 6)
	local hi, lo = r:getSeedParts()
	-- final state 5026830740666840310 = 1170400236 * 2^32 + 3816158454
	eq(hi, 1170400236, "hi"); eq(lo, 3816158454, "lo")
end)

test("random: seeds above 2^32 and large nums", function()
	local r = Random.new(2 ^ 40 + 3)
	eq(r:get(1000), 425); eq(r:get(1000), 366)
	local hi, lo = r:getSeedParts()
	eq(hi, 3578617270); eq(lo, 465823161)
	local r2 = Random.new(73637380)
	-- num = 0xFFFFFFFF: r*num needs 64 bits (2978182055 * 4294967295 ~ 1.28e19 > 2^53)
	eq(r2:get(4294967295), 2978182054, "num=2^32-1")
	eq(r2:get(3), 1)
end)

test("random: trivial cases do not advance the state", function()
	local r = Random.new(99)
	local hi, lo = r:getSeedParts()
	eq(r:get(1), 0); eq(r:get(0), 0)
	local hi2, lo2 = r:getSeedParts()
	eq(hi2, hi); eq(lo2, lo); eq(r:getCallCount(), 0)
	-- negative num -> (unsigned long) wrap: get(-5) == get(4294967291), state advances
	local a, b = Random.new(7), Random.new(7)
	eq(a:get(-5), b:get(4294967291), "unsigned conversion of negative num")
end)

test("random: getFloat matches C++ float math", function()
	local r = Random.new(1)
	-- seed 1: newSeed = 1103515245 + 12345 = 1103527590; r = floor(1103527590/65536) = 16838
	-- get(0xFFFFFFFF) = floor(16838*(2^32-1)/2^32) = 16837; (float)16837 / (float)(2^32-1 -> 2^32)
	eq(r:getFloat(), 16837 / 4294967296)
	eq(string.format("%.9g", r:getFloat()), "0.350900084", "2nd float (C++ harness value)")
	eq(Random.toFloat32(16777217), 16777216, "float32 ties-to-even")
	eq(Random.toFloat32(16777219), 16777220, "float32 ties-to-even up")
end)

test("random: reset/reseed/init semantics", function()
	local r = Random.new(5)
	eq(r:getResetCount(), 1)
	r:init(5)                         -- same seed: no reseed
	eq(r:getResetCount(), 1)
	r:get(10); r:reseed(5)
	eq(r:getResetCount(), 2); eq(r:getCallCount(), 1, "reseed keeps call count")
	local c = r:clone()
	eq(c:get(1000), r:get(1000), "clone continues identically")
end)

test("random: 1e5 draws in range, integral, state stays 64-bit", function()
	local r = Random.new(123456789)
	local nums = { 2, 3, 6, 7, 100, 256, 1000, 65535, 65536, 2 ^ 31, 4294967295 }
	local counts = {}
	for i = 1, 100000 do
		local n = nums[i % #nums + 1]
		local v = r:get(n)
		if v < 0 or v >= n or v % 1 ~= 0 then error("out of range: get(" .. n .. ") = " .. v) end
		if n == 6 then counts[v] = (counts[v] or 0) + 1 end
		local hi, lo = r:getSeedParts()
		if hi < 0 or hi >= 4294967296 or lo < 0 or lo >= 4294967296 or hi % 1 ~= 0 or lo % 1 ~= 0 then
			error("seed halves out of 32-bit range")
		end
	end
	for v = 0, 5 do
		if (counts[v] or 0) < 1200 then error("get(6) badly distributed at " .. v) end
	end
end)

---------------------------------------------------------------------------------------------
-- Fractal
---------------------------------------------------------------------------------------------
local mapRand = Random.new(0)
local mapW, mapH, mapWX, mapWY = 80, 52, true, false
local Fractal = F.newLuaAPI({
	getMapRand = function() return mapRand end,
	getMapInfo = function() return mapW, mapH, mapWX, mapWY end,
})

local function heights(frac, W, H)
	local t = {}
	for y = 0, H - 1 do for x = 0, W - 1 do t[#t + 1] = frac:GetHeight(x, y) end end
	return t
end

test("fractal: golden values from the real DLL code (C++ harness)", function()
	-- tests/cpp harness case: FRAC 1 80 52 2 8(POLAR) -1 -1 -1 ridges(20,flags,1,2) map 80x52 wrapX
	mapRand = Random.new(1)
	local f = Fractal.Create(80, 52, 2, { FRAC_POLAR = true }, -1, -1)
	f:BuildRidges(20, { FRAC_WRAP_X = true }, 1, 2)
	local h = heights(f, 80, 52)
	eqList(h, { 70, 69, 74, 73, 81, 79, 69, 65, 60, 50, 45, 33, 51, 36, 61, 60, 42, 7, 11, 23 }, "heights")
	local p = {}
	for pct = 0, 100, 5 do p[#p + 1] = f:GetHeight(pct) end
	eqList(p, { 0, 50, 61, 68, 74, 79, 85, 91, 98, 104, 111, 116, 122, 129, 136, 143, 152, 162, 176, 196, 255 }, "percent")
	local hi, lo = mapRand:getSeedParts()
	eq(hi, 1486191596); eq(lo, 1110272438)
end)

test("fractal: determinism (same seed -> same heights)", function()
	local function build(seed)
		mapRand = Random.new(seed)
		local f = Fractal.Create(80, 52, 3, { FRAC_WRAP_X = true }, -1, -1)
		f:BuildRidges(16, { FRAC_WRAP_X = true }, 1, 2)
		return heights(f, 80, 52)
	end
	local a, b, c = build(777), build(777), build(778)
	eqList(a, b, "same seed")
	local diff = 0
	for i = 1, #a do if a[i] ~= c[i] then diff = diff + 1 end end
	if diff < #a / 4 then error("different seeds gave nearly identical fractals") end
end)

test("fractal: heights in [0,255] for many flag/grain combos", function()
	mapRand = Random.new(31337)
	local flagSets = {
		{}, { FRAC_WRAP_X = true }, { FRAC_WRAP_Y = true }, { FRAC_WRAP_X = true, FRAC_WRAP_Y = true },
		{ FRAC_POLAR = true }, { FRAC_INVERT_HEIGHTS = true }, { FRAC_CENTER_RIFT = true, FRAC_WRAP_X = true, FRAC_WRAP_Y = true },
	}
	for _, flags in ipairs(flagSets) do
		for grain = 0, 8 do
			local f = Fractal.Create(66, 42, grain, flags, 6, 5)
			for _, v in ipairs(heights(f, 66, 42)) do
				if v < 0 or v > 255 or v % 1 ~= 0 then error("height out of range: " .. v) end
			end
		end
	end
	local fp = Fractal.Create(66, 42, 3, { FRAC_PERCENT = true }, -1, -1)
	for _, v in ipairs(heights(fp, 66, 42)) do
		if v < 0 or v > 99 then error("percent height out of range: " .. v) end
	end
	-- out-of-range coordinates return 0 like the C++
	eq(fp:GetHeight(-1, 0), 0); eq(fp:GetHeight(66, 0), 0); eq(fp:GetHeight(0, 42), 0)
end)

test("fractal: GetHeight(percent) is monotonic and splits the data", function()
	mapRand = Random.new(4242)
	local f = Fractal.Create(80, 52, 2, { FRAC_WRAP_X = true }, -1, -1)
	local prev = -1
	for pct = 0, 100 do
		local h = f:GetHeight(pct)
		if h < prev then error(("not monotonic at %d%%: %d < %d"):format(pct, h, prev)) end
		prev = h
	end
	eq(f:GetHeight(0), 0, "0%"); eq(f:GetHeight(100), 255, "100%")
	eq(f:GetHeight(-50), 0, "clamped low"); eq(f:GetHeight(150), 255, "clamped high")
	-- about half of the raw fractal cells are below the 50% threshold
	local cv = (function() for k, v in pairs(f) do if k == "cv" then return v end end end)()
	local t50, below, total = f:GetHeight(50), 0, cv.fracX * cv.fracY
	for x = 0, cv.fracX - 1 do for y = 0, cv.fracY - 1 do
		if cv:getRaw(x, y) < t50 then below = below + 1 end
	end end
	if below / total > 0.55 or below / total < 0.40 then error("50% threshold splits " .. below / total) end
end)

test("fractal: FRAC_WRAP_X gives edge continuity", function()
	-- With wrapX the fractal column fracX is a copy of column 0, so the east edge of the map blends
	-- into the west edge: compare the |difference| across the seam with that across interior columns.
	local function seamStats(flags, seed)
		mapRand = Random.new(seed)
		local W, H = 128, 80
		local f = Fractal.Create(W, H, 3, flags, 7, 6)
		local seam, inner = 0, 0
		for y = 0, H - 1 do
			seam = seam + math.abs(f:GetHeight(W - 1, y) - f:GetHeight(0, y))
			inner = inner + math.abs(f:GetHeight(W / 2, y) - f:GetHeight(W / 2 - 1, y))
		end
		return seam / H, inner / H
	end
	local sw, iw, sn, inn = 0, 0, 0, 0
	for seed = 1, 10 do
		local a, b = seamStats({ FRAC_WRAP_X = true }, seed); sw, iw = sw + a, iw + b
		local c, d = seamStats({}, seed); sn, inn = sn + c, inn + d
	end
	log("seam |dh| wrapX=%.2f (interior %.2f); no wrap=%.2f (interior %.2f)", sw / 10, iw / 10, sn / 10, inn / 10)
	if sw / 10 > 3 * (iw / 10) + 2 then error("wrapX seam discontinuous: " .. sw / 10 .. " vs " .. iw / 10) end
	if sn / 10 < sw / 10 then error("no-wrap seam should not be smoother than wrapped seam") end
	-- raw check: column fracX == column 0 before the last pass (and exactly after tectonics)
	mapRand = Random.new(9)
	local cv = F.CvFractal.new()
	local rifts = F.CvFractal.new()
	rifts:fracInit(80, 52, 2, mapRand, 0, nil, -1, -1)
	cv:fracInit(80, 52, 2, mapRand, F.FRAC_WRAP_X, rifts, -1, -1)
	for y = 0, cv.fracY do eq(cv:getRaw(cv.fracX, y), cv:getRaw(0, y), "tectonic wrap copy y=" .. y) end
end)

test("fractal: rifts / polar / center rift / invert / hinted execute", function()
	mapRand = Random.new(2024)
	local rifts = Fractal.Create(80, 52, 2, {}, -1, -1)
	local cont = Fractal.CreateRifts(80, 52, 2, { FRAC_POLAR = true, FRAC_WRAP_X = true }, rifts, -1, -1)
	cont:BuildRidges(20, { FRAC_WRAP_X = true }, 1, 2)
	local polar = Fractal.Create(80, 52, 2, { FRAC_POLAR = true }, -1, -1)
	-- POLAR without wrap zeroes the fractal border -> map corners are 0
	eq(polar:GetHeight(0, 0), 0, "polar corner")
	Fractal.Create(80, 52, 2, { FRAC_CENTER_RIFT = true, FRAC_WRAP_X = true }, -1, -1)
	local inv = Fractal.Create(80, 52, 2, { FRAC_INVERT_HEIGHTS = true, FRAC_POLAR = true }, -1, -1)
	if inv:GetHeight(1, 1) <= 0 then error("inverted polar fractal should be high near the border") end
	-- CreateRifts with a non-fractal 5th arg -> no rifts (lua_touserdata == NULL)
	Fractal.CreateRifts(80, 52, 2, {}, -1, 7, 6)
	-- hinted init (not exposed to Lua by the DLL, available on the class)
	local cv = F.CvFractal.new()
	local iSmooth = 6 - 2
	local w, h = 2 ^ (7 - iSmooth), 2 ^ (6 - iSmooth) + 1
	local hints = {}
	for i = 1, w * h do hints[i] = (i * 37) % 256 end
	cv:fracInitHinted(80, 52, 2, mapRand, hints, w * h, F.FRAC_WRAP_X + F.FRAC_POLAR, nil, -1, -1)
	eq(cv:getRaw(0, 0), hints[1], "hint copied")
	eq(cv:getRaw(2 ^ iSmooth, 0), hints[2], "hint copied x=1")
end)

test("fractal: Lua binding quirks", function()
	mapRand = Random.new(5)
	local ok, err = pcall(Fractal.Create, 80, 52, 2, 0, -1, -1)
	if ok or not tostring(err):find("table expected") then error("flags must be a table: " .. tostring(err)) end
	local f = Fractal.Create(80, 52, 2, {}, -1, -1)
	ok, err = pcall(f.GetHeight, f)
	if ok or not tostring(err):find("Invalid number of arguments") then error("GetHeight() arity: " .. tostring(err)) end
	-- explicit nil exponents -> defaults
	local g = Fractal.Create(80, 52, 2, {}, nil, nil)
	local cvg; for k, v in pairs(g) do if k == "cv" then cvg = v end end
	eq(cvg.fracX, 128); eq(cvg.fracY, 64)
	-- omitted exponents: slot 5 is the new userdata -> lua_tointeger = 0 -> exp 0 (1x1 fractal)
	local o = Fractal.Create(80, 52, 2, {})
	local cvo; for k, v in pairs(o) do if k == "cv" then cvo = v end end
	eq(cvo.fracX, 1); eq(cvo.fracY, 1)
	-- false counts as a set flag (HasFlag tests != nil)
	eq(F.getFractalFlags({ FRAC_WRAP_X = false, FRAC_POLAR = true }), 1 + 8)
	-- lua_tointeger rounding (MSVC fistp: nearest, ties to even)
	eq(F.toInteger(6.667), 7); eq(F.toInteger(2.5), 2); eq(F.toInteger(3.5), 4); eq(F.toInteger(-1.5), -2)
	eq(F.toInteger(nil), 0); eq(F.toInteger("12"), 12)
	-- Map.GetFractalFlags helper
	local mf = F.fractalFlagsTable(true, false)
	eq(mf.FRAC_WRAP_X, true); eq(mf.FRAC_WRAP_Y, nil)
end)

test("fractal: timing 128x80 grain 2", function()
	mapW, mapH = 128, 80
	mapRand = Random.new(1)
	local clock = os.clock
	local t0 = clock()
	local N = 10
	for i = 1, N do Fractal.Create(128, 80, 2, { FRAC_WRAP_X = true, FRAC_POLAR = true }, -1, -1) end
	local tCreate = (clock() - t0) / N

	t0 = clock()
	local f = Fractal.Create(128, 80, 2, { FRAC_POLAR = true }, -1, -1)
	f:BuildRidges(24, { FRAC_WRAP_X = true }, 1, 2)
	local tRidge = clock() - t0

	t0 = clock()
	local s = 0
	for y = 0, 79 do for x = 0, 127 do s = s + f:GetHeight(x, y) end end
	local tSweep = clock() - t0

	t0 = clock()
	for pct = 0, 100, 5 do f:GetHeight(pct) end
	local tPct = (clock() - t0) / 21

	log("timing: Create 128x80 g2 = %.2f ms; Create+BuildRidges(24) = %.2f ms; 10240x GetHeight = %.2f ms; GetHeight(pct) = %.2f ms",
		tCreate * 1000, tRidge * 1000, tSweep * 1000, tPct * 1000)
	if tCreate > 0.25 then error("Create too slow: " .. tCreate) end
	if tRidge > 1.0 then error("Create+BuildRidges too slow: " .. tRidge) end
	mapW, mapH = 80, 52
end)

return results
