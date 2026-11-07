--[[
engine/game.lua -- Game, PreGame, Players[0..63], Teams[0..63], enums, Modding, Firaxis Lua extensions,
and the deterministic MSVC-style math.random.

  local gamemod = require("game")
  gamemod.install(S, env)   -- env = the global table the map script runs in

Headless player model (engine-api.md §12.2): majors in slots 0..N-1, city-states in
22..22+M-1 (MAX_MAJOR_CIVS = 22), barbarian 63.  Team id = player id.
]]

local floor = math.floor
local fmod = math.fmod

local M = {}

local function errIndex(prefix)
	return function(_, k)
		error("c5maps: unimplemented " .. prefix .. tostring(k), 2)
	end
end
local function methodErrIndex(prefix)
	return function(_, k)
		if type(k) == "string" and k:match("^%u") then
			error("c5maps: unimplemented " .. prefix .. k, 2)
		end
		return nil
	end
end

-- MSVC CRT rand(): s = s*214013 + 2531011 (mod 2^32); return (s >> 16) & 0x7FFF
function M.newCRand(seed)
	local s = (seed or 1) % 4294967296
	local R = {}
	function R.srand(v) s = floor(v) % 4294967296 end
	function R.rand()
		s = (s * 214013 + 2531011) % 4294967296
		return floor(s / 65536) % 32768
	end
	return R
end

-- enum tables from CvLuaEnums.cpp / CvEnums.h; unknown keys must read nil
local function staticEnums(env, GI)
	env.PlotTypes = { NO_PLOT = -1, PLOT_MOUNTAIN = 0, PLOT_HILLS = 1, PLOT_LAND = 2, PLOT_OCEAN = 3, NUM_PLOT_TYPES = 4 }
	env.TerrainTypes = { NO_TERRAIN = -1, TERRAIN_GRASS = 0, TERRAIN_PLAINS = 1, TERRAIN_DESERT = 2, TERRAIN_TUNDRA = 3,
		TERRAIN_SNOW = 4, TERRAIN_COAST = 5, TERRAIN_OCEAN = 6, TERRAIN_MOUNTAIN = 7, TERRAIN_HILL = 8, NUM_TERRAIN_TYPES = 9 }
	local feats = { "FEATURE_ICE", "FEATURE_JUNGLE", "FEATURE_MARSH", "FEATURE_OASIS", "FEATURE_FLOOD_PLAINS",
		"FEATURE_FOREST", "FEATURE_FALLOUT", "FEATURE_CRATER", "FEATURE_FUJI", "FEATURE_MESA", "FEATURE_REEF",
		"FEATURE_VOLCANO", "FEATURE_GIBRALTAR", "FEATURE_GEYSER", "FEATURE_FOUNTAIN_YOUTH", "FEATURE_POTOSI",
		"FEATURE_EL_DORADO", "FEATURE_ATOLL", "FEATURE_SRI_PADA", "FEATURE_MT_SINAI", "FEATURE_MT_KAILASH",
		"FEATURE_ULURU", "FEATURE_LAKE_VICTORIA", "FEATURE_KILIMANJARO", "FEATURE_SOLOMONS_MINES" }
	env.FeatureTypes = { NO_FEATURE = -1, NUM_FEATURE_TYPES = #feats }
	for i, n in ipairs(feats) do env.FeatureTypes[n] = i - 1 end
	env.DirectionTypes = { NO_DIRECTION = 7, DIRECTION_NORTHEAST = 0, DIRECTION_EAST = 1, DIRECTION_SOUTHEAST = 2,
		DIRECTION_SOUTHWEST = 3, DIRECTION_WEST = 4, DIRECTION_NORTHWEST = 5, NUM_DIRECTION_TYPES = 6 }
	env.FlowDirectionTypes = { NO_FLOWDIRECTION = 7, FLOWDIRECTION_NORTH = 0, FLOWDIRECTION_NORTHEAST = 1,
		FLOWDIRECTION_SOUTHEAST = 2, FLOWDIRECTION_SOUTH = 3, FLOWDIRECTION_SOUTHWEST = 4, FLOWDIRECTION_NORTHWEST = 5,
		NUM_FLOWDIRECTION_TYPES = 6, FLOWDIRECTION_NORTH_MASK = 1, FLOWDIRECTION_SOUTH_MASK = 2,
		FLOWDIRECTION_SOUTHEAST_MASK = 4, FLOWDIRECTION_NORTHWEST_MASK = 8, FLOWDIRECTION_SOUTHWEST_MASK = 16,
		FLOWDIRECTION_NORTHEAST_MASK = 32 }
	env.ResourceUsageTypes = { RESOURCEUSAGE_BONUS = 0, RESOURCEUSAGE_STRATEGIC = 1, RESOURCEUSAGE_LUXURY = 2, NUM_RESOURCEUSAGE_TYPES = 3 }
	env.MinorCivTraitTypes = { NO_MINOR_CIV_TRAIT_TYPE = -1, MINOR_CIV_TRAIT_CULTURED = 0, MINOR_CIV_TRAIT_MILITARISTIC = 1,
		MINOR_CIV_TRAIT_MARITIME = 2, MINOR_CIV_TRAIT_MERCANTILE = 3, MINOR_CIV_TRAIT_RELIGIOUS = 4, NUM_MINOR_CIV_TRAIT_TYPES = 5 }
	local gopts = { "GAMEOPTION_NO_CITY_RAZING", "GAMEOPTION_NO_BARBARIANS", "GAMEOPTION_RAGING_BARBARIANS",
		"GAMEOPTION_ALWAYS_WAR", "GAMEOPTION_ALWAYS_PEACE", "GAMEOPTION_ONE_CITY_CHALLENGE",
		"GAMEOPTION_NO_CHANGING_WAR_PEACE", "GAMEOPTION_NEW_RANDOM_SEED", "GAMEOPTION_LOCK_MODS",
		"GAMEOPTION_COMPLETE_KILLS", "GAMEOPTION_NO_GOODY_HUTS", "GAMEOPTION_RANDOM_PERSONALITIES",
		"GAMEOPTION_POLICY_SAVING", "GAMEOPTION_PROMOTION_SAVING", "GAMEOPTION_END_TURN_TIMER_ENABLED",
		"GAMEOPTION_QUICK_COMBAT", "GAMEOPTION_DISABLE_START_BIAS", "GAMEOPTION_NO_SCIENCE", "GAMEOPTION_NO_POLICIES",
		"GAMEOPTION_NO_HAPPINESS", "GAMEOPTION_NO_TUTORIAL", "GAMEOPTION_NO_RELIGION" }
	env.GameOptionTypes = { NO_GAMEOPTION = -1, NUM_GAMEOPTION_TYPES = #gopts }
	for i, n in ipairs(gopts) do env.GameOptionTypes[n] = i - 1 end
	local ylds = { "YIELD_FOOD", "YIELD_PRODUCTION", "YIELD_GOLD", "YIELD_SCIENCE", "YIELD_CULTURE", "YIELD_FAITH",
		"YIELD_TOURISM", "YIELD_GOLDEN_AGE_POINTS", "YIELD_GREAT_GENERAL_POINTS", "YIELD_GREAT_ADMIRAL_POINTS",
		"YIELD_POPULATION", "YIELD_CULTURE_LOCAL" }
	env.YieldTypes = { NO_YIELD = -1, NUM_YIELD_TYPES = 17 }
	for i, n in ipairs(ylds) do env.YieldTypes[n] = i - 1 end
	env.DomainTypes = { NO_DOMAIN = -1, DOMAIN_SEA = 0, DOMAIN_AIR = 1, DOMAIN_LAND = 2, DOMAIN_IMMOBILE = 3, DOMAIN_HOVER = 4, NUM_DOMAIN_TYPES = 5 }
	env.PolicyBranchTypes = { NO_POLICY_BRANCH_TYPE = -1 }
	-- exe-registered, DB-derived
	env.WorldSizeTypes = {}
	for _, r in ipairs(GI.rows("Worlds")) do env.WorldSizeTypes[r.Type] = r.ID end
	env.WorldSizeTypes.NO_WORLDSIZE = -1
	env.ClimateTypes = {}
	for _, r in ipairs(GI.rows("Climates") or {}) do env.ClimateTypes[r.Type] = r.ID end
	env.SeaLevelTypes = {}
	for _, r in ipairs(GI.rows("SeaLevels") or {}) do env.SeaLevelTypes[r.Type] = r.ID end
	env.ResourceClassTypes = {}
	for _, r in ipairs(GI.rows("ResourceClasses") or {}) do env.ResourceClassTypes[r.Type] = r.ID end
	env.HandicapTypes = {}
	for _, r in ipairs(GI.rows("HandicapInfos") or {}) do env.HandicapTypes[r.Type] = r.ID end
	env.EraTypes = {}
	for _, r in ipairs(GI.rows("Eras") or {}) do env.EraTypes[r.Type] = r.ID end
	env.ResourceTypes = {}
	for _, r in ipairs(GI.rows("Resources") or {}) do env.ResourceTypes[r.Type] = r.ID end
	env.ImprovementTypes = {}
	for _, r in ipairs(GI.rows("Improvements") or {}) do env.ImprovementTypes[r.Type] = r.ID end
	env.SlotStatus = { SS_TAKEN = 0, SS_COMPUTER = 1, SS_CLOSED = 2, SS_OPEN = 3, SS_OBSERVER = 4 }   -- order unverified (exe enum)
	env.SlotClaim = { SLOTCLAIM_UNASSIGNED = 0, SLOTCLAIM_RESERVED = 1, SLOTCLAIM_ASSIGNED = 2 }        -- unverified (exe enum)
end

function M.install(S, env)
	local GI = S.gi
	local cfg = S.cfg
	local toint, tobool = S.toint, S.tobool
	staticEnums(env, GI)

	local D = GI.GameDefines
	local MAX_MAJOR = D.MAX_MAJOR_CIVS or 22
	local MAX_PLAYERS = D.MAX_PLAYERS or 64
	local BARB = D.BARBARIAN_PLAYER or 63

	---------------------------------------------------------------------------------------------
	-- PreGame state
	---------------------------------------------------------------------------------------------
	local function idOf(tbl, ty, fallback)
		if ty == nil then return fallback end
		if type(ty) == "number" then return ty end
		local r = GI.byType(tbl)[ty]
		if not r then error("c5maps: unknown " .. tbl .. " type " .. tostring(ty), 0) end
		return r.ID
	end
	local pregame = {
		worldSize = idOf("Worlds", cfg.world_size, 3),
		climate = idOf("Climates", cfg.climate, 1),
		seaLevel = idOf("SeaLevels", cfg.sea_level, 1),
		era = idOf("Eras", cfg.era, 0),
		handicap = idOf("HandicapInfos", cfg.handicap, nil),
		mapRandomSeed = cfg.seed or 0,
		mapOptions = {},
		gameOptions = {},
		mapScriptName = cfg.script_name or "",
	}
	if pregame.handicap == nil then
		local r = GI.byType("HandicapInfos").HANDICAP_PRINCE
		pregame.handicap = r and r.ID or 0
	end
	for k, v in pairs(cfg.game_options or {}) do pregame.gameOptions[k] = v end
	S.pregame = pregame

	---------------------------------------------------------------------------------------------
	-- Players / Teams
	---------------------------------------------------------------------------------------------
	local civs, minors = cfg.civs or {}, cfg.minors or {}
	local minorCivId = (GI.byType("Civilizations").CIVILIZATION_MINOR or {}).ID or -1
	local barbCivId = (GI.byType("Civilizations").CIVILIZATION_BARBARIAN or {}).ID or -1
	local playerSlots = {}
	for i = 0, MAX_PLAYERS - 1 do playerSlots[i] = { id = i, team = i, alive = false, civ = -1, minor = false, minorType = -1 } end
	-- cfg.teams = N groups the majors round-robin into teams 0..N-1 (player i -> team i % N); the team id is
	-- then the lowest member's player id, as in an un-modified staging room.  Default: team id = player id.
	local nTeams = cfg.teams and toint(cfg.teams) or 0
	for i, civ in ipairs(civs) do
		local slot = playerSlots[i - 1]
		slot.alive, slot.civ, slot.civType = true, idOf("Civilizations", civ), civ
		if nTeams > 0 then slot.team = (i - 1) % nTeams end
		local row = GI.byID("Civilizations")[slot.civ]
		slot.name = row and row.ShortDescription or civ
	end
	for i, mc in ipairs(minors) do
		local slot = playerSlots[MAX_MAJOR + i - 1]
		if not slot or MAX_MAJOR + i - 1 >= BARB then error("c5maps: too many city-states", 0) end
		slot.alive, slot.civ, slot.minor = true, minorCivId, true
		slot.minorType = idOf("MinorCivilizations", mc)
		slot.civType = mc
		local row = GI.byID("MinorCivilizations")[slot.minorType]
		slot.name = row and row.ShortDescription or mc
		slot.trait = row and row.MinorCivTrait and (GI.byType("MinorCivTraits")[row.MinorCivTrait] or {}).ID or -1
	end
	playerSlots[BARB].alive = true
	playerSlots[BARB].civ = barbCivId
	playerSlots[BARB].civType = "CIVILIZATION_BARBARIAN"
	playerSlots[BARB].barbarian = true
	S.playerSlots = playerSlots
	S.playerStarts = {}   -- pid -> plot

	local PlayerMethods = setmetatable({}, { __index = methodErrIndex("Player:") })
	local PlayerMeta = { __index = PlayerMethods }
	local Players = {}
	for i = 0, MAX_PLAYERS - 1 do Players[i] = setmetatable({ _pid = i }, PlayerMeta) end
	local PL = PlayerMethods
	local function slot(p) return playerSlots[p._pid] end
	function PL:GetID() return self._pid end
	function PL:IsAlive() return slot(self).alive end
	function PL:IsEverAlive() return slot(self).alive end
	function PL:IsHuman() return self._pid == 0 and slot(self).alive end
	function PL:IsMinorCiv() return slot(self).minor end
	function PL:IsBarbarian() return slot(self).barbarian or false end
	function PL:GetTeam() return slot(self).team end
	function PL:GetCivilizationType() return slot(self).civ end
	function PL:GetMinorCivType() return slot(self).minorType end
	function PL:GetMinorCivTrait() return slot(self).minor and (slot(self).trait or -1) or -1 end
	function PL:GetHandicapType() return pregame.handicap end
	function PL:GetName() return slot(self).name or "" end
	function PL:GetCivilizationShortDescription() return slot(self).name or "" end
	function PL:GetLeaderType() return -1 end
	function PL:GetNumCities() return 0 end
	function PL:GetCapitalCity() return nil end
	function PL:GetStartingPlot() return S.playerStarts[self._pid] end
	function PL:SetStartingPlot(plot)
		local old = S.playerStarts[self._pid]
		if plot ~= nil and (type(plot) ~= "table" or not plot._n) then
			error("bad argument #2 to 'SetStartingPlot' (Plot expected)", 2)
		end
		if old ~= plot then
			if old then
				local a = S.areaById[old._area]
				if not a then error("c5maps: SetStartingPlot: old starting plot has no area (C++ NULL dereference)", 2) end
				a.starts = a.starts - 1
			end
			S.playerStarts[self._pid] = plot
			if plot then
				plot._start = true
				local a = S.areaById[plot._area]
				if a then a.starts = a.starts + 1 end
			end
		end
	end
	env.Players = Players

	local TeamMethods = setmetatable({}, { __index = methodErrIndex("Team:") })
	local TeamMeta = { __index = TeamMethods }
	local Teams = {}
	for i = 0, MAX_PLAYERS - 1 do Teams[i] = setmetatable({ _tid = i }, TeamMeta) end
	local function teamMembers(t)
		local out = {}
		for i = 0, MAX_PLAYERS - 1 do
			local sl = playerSlots[i]
			if sl.alive and sl.team == t then out[#out + 1] = sl end
		end
		return out
	end
	S.teamMembers = teamMembers
	function TeamMethods:GetID() return self._tid end
	function TeamMethods:IsAlive() return #teamMembers(self._tid) > 0 end
	function TeamMethods:IsEverAlive() return #teamMembers(self._tid) > 0 end
	function TeamMethods:IsMinorCiv() local m = teamMembers(self._tid)[1]; return m and m.minor or false end
	function TeamMethods:IsBarbarian() local m = teamMembers(self._tid)[1]; return m and m.barbarian or false end
	function TeamMethods:GetNumMembers() return #teamMembers(self._tid) end
	function TeamMethods:IsHasTech() return false end
	env.Teams = Teams

	---------------------------------------------------------------------------------------------
	-- Game
	---------------------------------------------------------------------------------------------
	local Random = require("random")
	local Game = {}
	local gameRand
	local function getGameRand()
		gameRand = gameRand or Random.new(fmod(cfg.seed or 0, 73637381), "Game Rand")
		return gameRand
	end
	local gopt = env.GameOptionTypes
	local goptName = {}
	for k, v in pairs(gopt) do if v >= 0 and k ~= "NUM_GAMEOPTION_TYPES" then goptName[v] = k end end
	local function gameOptionValue(name)
		local v = pregame.gameOptions[name]
		if v ~= nil then return v end
		local r = GI.byType("GameOptions")[name]
		if r then return r.Default end
		return nil
	end
	function Game.GetStartEra() return pregame.era end
	function Game.GetHandicapType() return pregame.handicap end
	function Game.IsOption(opt)
		local name
		if type(opt) == "number" then name = goptName[toint(opt)] else name = tostring(opt) end
		if not name then return false end
		local v = pregame.gameOptions[name]
		return v ~= nil and v ~= 0 and v ~= false
	end
	function Game.GetCustomOption(name)
		if type(name) ~= "string" and type(name) ~= "number" then error("bad argument #1 to 'GetCustomOption' (string expected)", 2) end
		local v = gameOptionValue(tostring(name))
		if v == nil then return end
		if v == true then return 1 elseif v == false then return 0 end
		return v
	end
	function Game.IsCustomModOption(name) return S.info.customModOptions[name] == 1 end
	function Game.GetResourceUsageType(r)
		r = toint(r)
		if r == -1 then return -1 end
		local u = S.info.resourceUsage[r]
		if u == nil then error("c5maps: Game.GetResourceUsageType(" .. r .. "): unknown resource (C++ NULL dereference)", 2) end
		return u
	end
	function Game.CountCivTeamsEverAlive()
		local c = 0
		-- CvGame::countCivTeamsEverAlive: teams 0..MAX_CIV_TEAMS-1 (majors and city-states) that are ever alive
		for i = 0, (D.MAX_CIV_TEAMS or 63) - 1 do if #teamMembers(i) > 0 then c = c + 1 end end
		return c
	end
	function Game.CountCivPlayersAlive()
		local c = 0
		for i = 0, (D.MAX_CIV_PLAYERS or 63) - 1 do if playerSlots[i].alive then c = c + 1 end end
		return c
	end
	function Game.CountCivPlayersEverAlive() return Game.CountCivPlayersAlive() end
	function Game.GetNumYieldTypes()
		if S.info.MOD_BALANCE_CORE_JFD then
			local r = GI.byType("Yields").YIELD_JFD_SOVEREIGNTY
			return r and r.ID + 1 or 17
		end
		local r = GI.byType("Yields").YIELD_CULTURE_LOCAL
		return r and r.ID + 1 or 12
	end
	function Game.GetGameTurn() return 0 end
	function Game.GetElapsedGameTurns() return 0 end
	function Game.GetMaxTurns() return 0 end
	function Game.GetStartTurn() return 0 end
	function Game.GetActivePlayer() return 0 end
	function Game.GetActiveTeam() return 0 end
	function Game.IsNetworkMultiPlayer() return false end
	function Game.IsGameMultiPlayer() return false end
	function Game.IsDebugMode() return false end
	function Game.GetGameSpeedType() return (GI.byType("GameSpeeds").GAMESPEED_STANDARD or { ID = 0 }).ID end
	function Game.Rand(n, log)
		if type(n) ~= "number" then error("bad argument #1 to 'Rand' (number expected)", 2) end
		if type(log) ~= "string" and type(log) ~= "number" then error("bad argument #2 to 'Rand' (string expected)", 2) end
		-- getJonRandNum(max): get(max) for max > 0 (the game RNG, independent of the map RNG)
		local v = toint(n)
		if v <= 0 then return 0 end
		return getGameRand():get(v, log)
	end
	setmetatable(Game, { __index = errIndex("Game.") })
	env.Game = Game

	---------------------------------------------------------------------------------------------
	-- PreGame
	---------------------------------------------------------------------------------------------
	local PreGame = {}
	function PreGame.GetWorldSize() return pregame.worldSize end
	function PreGame.GetClimate() return pregame.climate end
	function PreGame.GetSeaLevel() return pregame.seaLevel end
	function PreGame.GetEra() return pregame.era end
	function PreGame.GetHandicap(p) return pregame.handicap end
	function PreGame.GetMapRandomSeed() return pregame.mapRandomSeed end
	function PreGame.GetMapScript() return pregame.mapScriptName end
	function PreGame.GetMapOption(id) return pregame.mapOptions[tostring(id)] end
	function PreGame.GetGameOption(name)
		if type(name) == "number" then name = goptName[name] end
		local v = gameOptionValue(name)
		if v == nil then return -1 end
		return v
	end
	function PreGame.GetNumMinorCivs() return #minors end
	function PreGame.GetNumCivs() return #civs end
	function PreGame.GetCivilization(p) return playerSlots[toint(p)] and playerSlots[toint(p)].civ or -1 end
	function PreGame.GetMinorCivType(p) return playerSlots[toint(p)] and playerSlots[toint(p)].minorType or -1 end
	function PreGame.GetSlotStatus(p)
		local s = playerSlots[toint(p)]
		if s and s.alive then return toint(p) == 0 and env.SlotStatus.SS_TAKEN or env.SlotStatus.SS_COMPUTER end
		return env.SlotStatus.SS_CLOSED
	end
	function PreGame.GetSlotClaim(p)
		local s = playerSlots[toint(p)]
		return (s and s.alive) and env.SlotClaim.SLOTCLAIM_ASSIGNED or env.SlotClaim.SLOTCLAIM_UNASSIGNED
	end
	function PreGame.IsMinorCiv(p) return playerSlots[toint(p)] and playerSlots[toint(p)].minor or false end
	function PreGame.GetCivilizationShortDescription(p) return playerSlots[toint(p)] and playerSlots[toint(p)].name or "" end
	function PreGame.GetLeaderName(p) return "" end
	function PreGame.IsMultiplayerGame() return false end
	setmetatable(PreGame, { __index = errIndex("PreGame.") })
	env.PreGame = PreGame

	---------------------------------------------------------------------------------------------
	-- Modding, Events, misc globals
	---------------------------------------------------------------------------------------------
	local mods = cfg.activated_mods or {
		{ ID = "d1b6328c-ff44-4b0d-aad7-c657f83610cd", Version = 1 },  -- (1) Community Patch
		{ ID = "8411a7a8-dad3-4622-a18e-fcc18324c799", Version = 1 },  -- (2) Vox Populi
	}
	local entryPoints = cfg.mod_entry_points or {}
	local Modding = {}
	function Modding.GetActivatedMods()
		local out = {}
		for i, m in ipairs(mods) do out[i] = { ID = m.ID, Version = m.Version } end
		return out
	end
	function Modding.GetActivatedModEntryPoints(kind)
		local list = entryPoints[kind] or {}
		local i = 0
		return function()
			i = i + 1
			local e = list[i]
			if e then return { File = e.File or e, ModID = e.ModID, Name = e.Name } end
		end
	end
	function Modding.IsModActive(id)
		for _, m in ipairs(mods) do if m.ID == id then return true end end
		return false
	end
	setmetatable(Modding, { __index = errIndex("Modding.") })
	env.Modding = Modding

	local noop = function() end
	local Events = setmetatable({}, { __index = function(t, k)
		-- LuaEvents-style objects: callable no-ops with Add/Remove
		local ev = setmetatable({ Add = noop, Remove = noop, RemoveAll = noop }, { __call = noop })
		rawset(t, k, ev)
		return ev
	end })
	env.Events = Events
	env.LuaEvents = Events

	env.MapModData = env.MapModData or {}
	env.GameDefines = GI.GameDefines
	env.GameInfo = GI.GameInfo
	env.GameInfoTypes = GI.GameInfoTypes
	env.DB = GI.DB
	env.Locale = GI.Locale

	---------------------------------------------------------------------------------------------
	-- Firaxis Lua extensions
	---------------------------------------------------------------------------------------------
	local tbl = env.table
	tbl.fill = function(a, b, c)
		local n = select("#", a, b, c)
		if type(a) == "table" and c ~= nil then
			for i = 1, toint(c) do a[i] = b end
			return a
		end
		local t = {}
		for i = 1, toint(b) do t[i] = a end
		return t
	end
	tbl.count = function(t)
		local c = 0
		for _ in pairs(t) do c = c + 1 end
		return c
	end
	local mth = env.math
	mth.clamp = function(v, lo, hi) return math.min(math.max(v, lo), hi) end

	-- math.random / math.randomseed: Lua 5.1 lmathlib over the MSVC CRT rand(), default srand(1)
	local crand = M.newCRand(1)
	S.crand = crand
	local RAND_MAX = 32767
	mth.random = function(...)
		local r = (crand.rand() % RAND_MAX) / RAND_MAX
		local n = select("#", ...)
		if n == 0 then return r end
		local m, u = ...
		if n == 1 then
			m = toint(m)
			if not (1 <= m) then error("bad argument #1 to 'random' (interval is empty)", 2) end
			return floor(r * m) + 1
		elseif n == 2 then
			m, u = toint(m), toint(u)
			if not (m <= u) then error("bad argument #2 to 'random' (interval is empty)", 2) end
			return floor(r * (u - m + 1)) + m
		end
		error("wrong number of arguments", 2)
	end
	mth.randomseed = function(s) crand.srand(toint(s)) end
end

return M
