--[[
engine/random.lua -- exact pure-Lua 5.1 port of CvRandom (Vox Populi / Community Patch DLL,
CvGameCoreDLL_Expansion2/CvRandom.cpp).

ALGORITHM (as in the VP DLL; note VP widened the original Firaxis 32-bit state to 64 bits):

    #define RANDOM_A      (1103515245)
    #define RANDOM_C      (12345)
    #define RANDOM_SHIFT  (16)
    unsigned long long m_ullRandomSeed;            // 64-bit state

    unsigned long get(unsigned long ulNum) {
        if (ulNum < 2) return 0;                   // trivial cases: state NOT advanced
        m_ulCallCount++;
        ull newSeed = RANDOM_A * seed + RANDOM_C;  // mod 2^64
        ul  r = (newSeed >> 16) & 0xFFFFFFFF;      // bits 16..47 of the new state
        ul  result = (r * ulNum) / 2^32;           // 64-bit product, then divide
        seed = newSeed;
        return result;                             // in [0, ulNum)
    }
    float getFloat() { return (float)get(0xFFFFFFFF) / (float)0xFFFFFFFF; }

Lua 5.1 numbers are IEEE doubles (53-bit mantissa) and there is no bit library, so:
  * the 64-bit state is held as two unsigned 32-bit halves (hi, lo);
  * every product is split into 16-bit limbs so no intermediate exceeds 2^53;
  * all divisions/modulos are by powers of two, which are exact in doubles.

  newSeed = A*(hi*2^32 + lo) + C   (mod 2^64), with A = Ah*2^16 + Al (Ah = 16838, Al = 20077)
                                                     lo = lh*2^16 + ll
    t1 = A*ll + C            (< 2^47)
    t2 = A*lh                (< 2^47)  -> contributes t2*2^16 = floor(t2/2^16)*2^32 + (t2%2^16)*2^16
    s  = t1%2^32 + (t2%2^16)*2^16      (< 2^33)
    newLo = s % 2^32
    carry = floor(t1/2^32) + floor(t2/2^16) + floor(s/2^32)
    newHi = ((Ah*hi % 2^16)*2^16 + Al*hi + carry) % 2^32       (A*hi only needed mod 2^32)
  r = (newHi % 2^16)*2^16 + floor(newLo/2^16)
  result = floor(r*num / 2^32), with r = rh*2^16 + rl:
    a = rh*num, b = rl*num (each < 2^48);  r*num = a*2^16 + b
    result = floor(a/2^16) + floor(((a%2^16)*2^16 + b) / 2^32)

`num` is an `unsigned long` in C++: a negative Lua number is converted the way C converts a
negative int to unsigned (num + 2^32) -- so get(-5) behaves like get(4294967291), as the DLL would.
(Map.Rand goes through CvGame::getMapRandNum which negates negative inputs itself; see getMapRandNum
below.)

API:
  local Random = require("random")
  local r = Random.new(seed [, name])   -- CvRandom(name) + init(seed); seed defaults to 0
  r:init(seed)          -- reset(seed): reseed if different, callCount = 0
  r:reset(seed)         -- same as C++ reset (seed defaults to 0)
  r:uninit()            -- no-op (as in C++)
  r:get(num, desc)      -- integer in [0, num); 0 (state untouched) when num < 2
  r:getFloat()          -- float32-exact port of CvRandom::getFloat
  r:reseed(seed)        -- set seed, resetCount++ (callCount kept)
  r:getSeed()           -- seed as a Lua number (exact only while < 2^53; see getSeedParts)
  r:getSeedParts()      -- hi32, lo32 (always exact)
  r:setSeedParts(hi,lo) -- reseed with an exact 64-bit value
  r:getCallCount(), r:getResetCount()
  r:clone()             -- CvRandom::Clone
  r:copyFrom(other)     -- CvRandom::CopyFrom
  r:equals(other)       -- operator== (seed equality)
  Random.getMapRandNum(r, num, desc)  -- CvGame::getMapRandNum semantics (negative num -> -get(-num))
]]

local floor = math.floor
local frexp = math.frexp

local TWO16 = 65536
local TWO32 = 4294967296
local A_HI = 16838          -- floor(1103515245 / 2^16)
local A_LO = 20077          -- 1103515245 % 2^16
local RANDOM_A = 1103515245
local RANDOM_C = 12345
local MAX_UNSIGNED_INT = 4294967295

local Random = {}
Random.__index = Random
Random.RANDOM_A = RANDOM_A
Random.RANDOM_C = RANDOM_C
Random.RANDOM_SHIFT = 16
Random.MAX_UNSIGNED_INT = MAX_UNSIGNED_INT

-- Split a Lua number into the (hi, lo) 32-bit halves of the C++ `unsigned long long` it would
-- convert to. Non-integers are truncated toward zero (C conversion); negatives wrap mod 2^64.
local function splitSeed(v)
	v = tonumber(v) or 0
	if v >= 0 then v = floor(v) else v = -floor(-v) end
	local lo = v % TWO32
	local hi = floor(v / TWO32) % TWO32
	return hi, lo
end

function Random.new(seed, name)
	local self = setmetatable({
		hi = 0, lo = 0,                 -- m_ullRandomSeed
		name = name or "CvRandom",
		callCount = 0, resetCount = 0,
		synchronous = true,
	}, Random)
	self:reset()                        -- constructor calls reset() (seed 0 -> no reseed)
	if seed ~= nil then self:init(seed) end
	return self
end

function Random:init(seed)
	self:reset(seed)
end

function Random:uninit()
end

function Random:reset(seed)
	local hi, lo = splitSeed(seed or 0)
	if hi ~= self.hi or lo ~= self.lo then
		self:setSeedParts(hi, lo)
	end
	self.callCount = 0
end

function Random:reseed(seed)
	local hi, lo = splitSeed(seed)
	self:setSeedParts(hi, lo)
end

function Random:setSeedParts(hi, lo)
	self.resetCount = self.resetCount + 1
	self.hi = floor(hi) % TWO32
	self.lo = floor(lo) % TWO32
end

function Random:getSeed()
	return self.hi * TWO32 + self.lo
end

function Random:getSeedParts()
	return self.hi, self.lo
end

function Random:getCallCount() return self.callCount end
function Random:getResetCount() return self.resetCount end

-- Returns value from 0 to num-1 inclusive (exact port of CvRandom::get).
function Random:get(num, desc)
	if num < 2 or num % 1 ~= 0 or num >= TWO32 then
		-- (unsigned long) conversion: truncate toward zero, then wrap mod 2^32
		if num >= 0 then num = floor(num) else num = -floor(-num) end
		num = num % TWO32
		if num < 2 then return 0 end
	end
	self.callCount = self.callCount + 1

	local hi, lo = self.hi, self.lo
	-- newSeed = A*seed + C (mod 2^64)
	local ll = lo % TWO16
	local lh = (lo - ll) / TWO16
	local t1 = RANDOM_A * ll + RANDOM_C
	local t2 = RANDOM_A * lh
	local t2lo = t2 % TWO16
	local t1lo = t1 % TWO32
	local s = t1lo + t2lo * TWO16
	local newLo = s % TWO32
	local carry = (t1 - t1lo) / TWO32 + (t2 - t2lo) / TWO16 + (s - newLo) / TWO32
	local newHi = (((A_HI * hi) % TWO16) * TWO16 + A_LO * hi + carry) % TWO32

	-- r = (newSeed >> 16) & 0xFFFFFFFF
	local rl = (newLo - newLo % TWO16) / TWO16
	local rh = newHi % TWO16
	-- result = (r * num) / 2^32 with r = rh*2^16 + rl
	local a = rh * num
	local b = rl * num
	local al = a % TWO16
	local result = (a - al) / TWO16 + floor((al * TWO16 + b) / TWO32)

	self.hi, self.lo = newHi, newLo
	return result
end

-- Round a non-negative integer-valued double to the nearest IEEE single (ties to even),
-- emulating the C++ (float) cast.
local function toFloat32(x)
	if x == 0 then return 0 end
	local _, e = frexp(x)          -- x = m * 2^e, 0.5 <= m < 1
	if e <= 24 then return x end   -- fits in the 24-bit significand
	local ulp = 2 ^ (e - 24)
	local q = x / ulp              -- exact (power-of-two division)
	local fq = floor(q)
	local frac = q - fq
	if frac > 0.5 or (frac == 0.5 and fq % 2 == 1) then fq = fq + 1 end
	return fq * ulp
end
Random.toFloat32 = toFloat32

function Random:getFloat()
	-- (float)get(MAX_UNSIGNED_INT) / (float)MAX_UNSIGNED_INT; (float)0xFFFFFFFF == 2^32 exactly,
	-- so the division is a power-of-two scale and introduces no further rounding.
	return toFloat32(self:get(MAX_UNSIGNED_INT, "getFloat")) / toFloat32(MAX_UNSIGNED_INT)
end

function Random:clone()
	local r = Random.new(nil, self.name)
	r.hi, r.lo = self.hi, self.lo
	r.callCount, r.resetCount = self.callCount, self.resetCount
	r.synchronous = self.synchronous
	return r
end

function Random:copyFrom(other)
	self.hi, self.lo = other.hi, other.lo
	self.callCount, self.resetCount = other.callCount, other.resetCount
	self.synchronous = other.synchronous
	self.name = other.name .. "(Copy)"
end

function Random:equals(other)
	return self.hi == other.hi and self.lo == other.lo
end

-- CvGame::getMapRandNum: if (iNum > 0) return get(iNum); return (int)get(-iNum) * -1;
function Random.getMapRandNum(r, num, desc)
	if num > 0 then return r:get(num, desc) end
	local v = r:get(-num, desc)
	return v == 0 and 0 or -v
end

return Random
