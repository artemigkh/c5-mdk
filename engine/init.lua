--[[
engine/init.lua -- bootstrap of the c5maps fake client and the map generation driver.

  local init = require("init")
  local ok, result = init.run(opts)
     ok == true  -> result = { json = <dump JSON string>, dump = <dump table>, timing = {...}, options = ..., log = ... }
     ok == false -> result = { error = <message with traceback>, log = ..., timing = ... }

opts (all optional unless noted):
  data_dir        engine/data folder (gameinfo.lua + tables/)               (required)
  script_path     map script file (required unless list_options)
  script_name     file name used for PreGame/MapScriptOptions (default: basename of script_path)
  files           VFS: array of {path=, source=} in priority order (later wins)
  seed            map seed (CvPreGame::mapRandomSeed)
  world_size      Worlds.Type or ID (default WORLDSIZE_STANDARD)
  climate, sea_level, era, handicap     DB Type strings or IDs
  civs            array of Civilizations.Type (majors, slots 0..)
  minors          array of MinorCivilizations.Type (slots 22..)
  map_options     { ["<option index>"] = value } overrides (1-based option index, 1-based value)
  game_options    { GAMEOPTION_X = value }
  areas_mode      "literal" (default) | "floodfill"
  float_to_int    "round" (default, Lua 5.1/MSVC x86) | "trunc"
  echo            echo print() to stdout
  list_options    only load the script and return its GetMapScriptInfo() options
  pre_vpui        run VPUI_core before the script (default true; engine-api.md §11.6)
  texts           { TXT_KEY = "text" } for Locale lookups

Driver flow (CvMapGenerator.cpp / CvGame.cpp:576-605): load script (top-level code + includes) ->
GetMapInitData(worldSize) -> CvMap::init -> GenerateMap() -> GetGameInitialItemsOverrides() ->
ValidateCoast().
]]

local M = {}

local function clock() return os.clock() end

-------------------------------------------------------------------------------------------------
-- minimal JSON encoder (arrays are 1-based Lua arrays; set mt.__jsonobject to force an object)
-------------------------------------------------------------------------------------------------
local function jsonString(s)
	s = s:gsub('[%c"\\]', function(c)
		if c == '"' then return '\\"' elseif c == "\\" then return "\\\\"
		elseif c == "\n" then return "\\n" elseif c == "\r" then return "\\r" elseif c == "\t" then return "\\t" end
		return string.format("\\u%04x", c:byte())
	end)
	return '"' .. s .. '"'
end

local encode
local function isArray(t)
	local mt = getmetatable(t)
	if mt and mt.__jsonobject then return false end
	if mt and mt.__jsonarray then return true end
	local n = #t
	if n == 0 then return next(t) == nil end
	for k in pairs(t) do
		if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then return false end
	end
	return true
end
function encode(v, out)
	local tv = type(v)
	if tv == "nil" then out[#out + 1] = "null"
	elseif tv == "boolean" then out[#out + 1] = v and "true" or "false"
	elseif tv == "number" then
		if v ~= v or v == math.huge or v == -math.huge then out[#out + 1] = "null"
		elseif v == math.floor(v) and math.abs(v) < 1e15 then out[#out + 1] = string.format("%d", v)
		else out[#out + 1] = string.format("%.17g", v) end
	elseif tv == "string" then out[#out + 1] = jsonString(v)
	elseif tv == "table" then
		if isArray(v) then
			out[#out + 1] = "["
			for i = 1, #v do
				if i > 1 then out[#out + 1] = "," end
				encode(v[i], out)
			end
			out[#out + 1] = "]"
		else
			out[#out + 1] = "{"
			local keys = {}
			for k in pairs(v) do keys[#keys + 1] = k end
			table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
			for i, k in ipairs(keys) do
				if i > 1 then out[#out + 1] = "," end
				out[#out + 1] = jsonString(tostring(k))
				out[#out + 1] = ":"
				encode(v[k], out)
			end
			out[#out + 1] = "}"
		end
	else
		out[#out + 1] = jsonString(tostring(v))
	end
end
function M.toJSON(v)
	local out = {}
	encode(v, out)
	return table.concat(out)
end

-------------------------------------------------------------------------------------------------
local function buildDump(S, opts, logLines)
	local GI = S.gi
	local n = S.numPlots
	local pt, ter, feat, res, resq, rw, rnw, rne, area, lake, cont = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
	local fn = S.fn
	for i = 0, n - 1 do
		local p = S.plots[i]
		fn.updateWaterFlags(p)   -- IsLake() semantics for the dump
		local k = i + 1
		pt[k] = p._pt; ter[k] = p._ter; feat[k] = p._feat; res[k] = p._res; resq[k] = p._resq
		rw[k] = p._w and p._fE or -1
		rnw[k] = p._nw and p._fSE or -1
		rne[k] = p._ne and p._fSW or -1
		area[k] = p._area
		lake[k] = p._lake and 1 or 0
		cont[k] = p._art
	end
	local function typesOf(tbl)
		local out, rows = {}, GI.rows(tbl)
		local maxId = -1
		for _, r in ipairs(rows) do if r.ID > maxId then maxId = r.ID end end
		for i = 0, maxId do out[i + 1] = "" end
		for _, r in ipairs(rows) do out[r.ID + 1] = r.Type end
		return setmetatable(out, { __jsonarray = true })
	end
	local resourceClass, featNW = {}, {}
	for _, r in ipairs(GI.rows("Resources")) do resourceClass[r.ID + 1] = r.ResourceClassType or "" end
	for _, r in ipairs(GI.rows("Features")) do featNW[r.ID + 1] = r.NaturalWonder and 1 or 0 end
	local areas = setmetatable({}, { __jsonobject = true })
	local areaAllLake = {}
	for i = 0, n - 1 do
		local p = S.plots[i]
		if p._area >= 0 then
			if areaAllLake[p._area] == nil then areaAllLake[p._area] = true end
			if not p._lake then areaAllLake[p._area] = false end
		end
	end
	for _, a in ipairs(S.areas) do
		areas[tostring(a.id)] = { water = a.water and 1 or 0, size = a.tiles,
			lake = (a.water and areaAllLake[a.id]) and 1 or 0 }
	end
	local starts = {}
	for pid = 0, 63 do
		local plot = S.playerStarts[pid]
		local slot = S.playerSlots[pid]
		if plot then
			starts[#starts + 1] = { player = pid, team = pid, x = plot._x, y = plot._y,
				civ = slot.civType or "", name = slot.name or "", minor = slot.minor and true or false }
		end
	end
	local worldRow = GI.byID("Worlds")[S.pregame.worldSize]
	return {
		script = opts.script_name, seed = opts.seed or 0,
		world_size = worldRow and worldRow.Type or tostring(S.pregame.worldSize),
		width = S.W, height = S.H, wrap_x = S.wrapX, wrap_y = S.wrapY,
		top_latitude = S.topLatitude, bottom_latitude = S.bottomLatitude,
		areas_mode = S.areasMode,
		terrain_types = typesOf("Terrains"), feature_types = typesOf("Features"), resource_types = typesOf("Resources"),
		plot_type = pt, terrain = ter, feature = feat, resource = res, resource_qty = resq,
		river_w = rw, river_nw = rnw, river_ne = rne, area = area, lake = lake, continent = cont,
		resource_class = setmetatable(resourceClass, { __jsonarray = true }),
		feature_natural_wonder = setmetatable(featNW, { __jsonarray = true }),
		areas = areas,
		start_plots = setmetatable(starts, { __jsonarray = true }),
		map_options = setmetatable(S.pregame.mapOptions, { __jsonobject = true }),
		map_rand_calls = S.mapRand:getCallCount(),
		log = table.concat(logLines, "\n"),
	}
end

-------------------------------------------------------------------------------------------------
local function collectOptions(env, S)
	-- GetMapScriptInfo() runs in a separate front-end Lua state in the game, so it must not disturb
	-- the map RNG here: save and restore it around the call.
	local info, opts = nil, {}
	local f = rawget(env, "GetMapScriptInfo")
	if type(f) == "function" then
		local hi, lo = S.mapRand:getSeedParts()
		local calls = S.mapRand:getCallCount()
		local ok, res = pcall(f)
		S.mapRand:setSeedParts(hi, lo)
		S.mapRand.callCount = calls
		if ok and type(res) == "table" then
			info = res
			local co = res.CustomOptions
			if type(co) == "table" then
				for i = 1, table.maxn(co) do
					local o = co[i]
					if type(o) == "table" then
						local vals = {}
						if type(o.Values) == "table" then
							for j = 1, table.maxn(o.Values) do
								local v = o.Values[j]
								if type(v) == "table" then v = v[1] or v.Name end
								vals[#vals + 1] = env.Locale.Lookup(tostring(v))
							end
						end
						opts[#opts + 1] = { index = i, name = env.Locale.Lookup(tostring(o.Name)),
							default = o.DefaultValue, values = vals, sort = o.SortPriority }
					end
				end
			end
		elseif not ok then
			env.print("[c5maps] GetMapScriptInfo() failed: " .. tostring(res))
		end
	end
	return info, opts
end

-------------------------------------------------------------------------------------------------
function M.run(opts)
	local timing = {}
	local logLines = {}
	local t0 = clock()
	local tPhase = t0
	local function phase(name)
		local t = clock()
		timing[#timing + 1] = { name = name, seconds = t - tPhase }
		tPhase = t
	end
	local S
	local function log(line)
		if opts.rng_trace and S then line = "[rng " .. S.mapRand.callCount .. "] " .. line end
		logLines[#logLines + 1] = line
	end

	local result = { log = logLines, timing = timing }
	local env = _G
	local prof
	if opts.profile then
		-- sampling profiler: every N VM instructions record the running function and line
		prof = { lines = {}, funcs = {}, n = 0 }
		local getinfo = debug.getinfo
		debug.sethook(function()
			local info = getinfo(2, "Sl")
			if info then
				local src = info.short_src or "?"
				local lk = src .. ":" .. tostring(info.currentline)
				local fk = src .. ":" .. tostring(info.linedefined)
				prof.lines[lk] = (prof.lines[lk] or 0) + 1
				prof.funcs[fk] = (prof.funcs[fk] or 0) + 1
				prof.n = prof.n + 1
			end
		end, "", opts.profile_interval or 1000)
	end
	local ok, err = xpcall(function()
		local gameinfo = require("gameinfo")
		local mapmod = require("map")
		local gamemod = require("game")
		local fractal = require("fractal")
		local inc = require("include")

		local GI = gameinfo.new(opts.data_dir)
		if opts.texts then for k, v in pairs(opts.texts) do GI.texts[k] = v end end
		local scriptName = opts.script_name or (opts.script_path and inc.basename(opts.script_path)) or ""
		opts.script_name = scriptName
		local cfg = {
			seed = opts.seed or 0, areas_mode = opts.areas_mode, float_to_int = opts.float_to_int,
			world_size = opts.world_size or "WORLDSIZE_STANDARD", climate = opts.climate, sea_level = opts.sea_level,
			era = opts.era, handicap = opts.handicap, civs = opts.civs, minors = opts.minors,
			game_options = opts.game_options, script_name = scriptName,
			activated_mods = opts.activated_mods, mod_entry_points = opts.mod_entry_points,
		}
		S = mapmod.newState(GI, cfg)
		result.state = S
		gamemod.install(S, env)
		env.Map = S.Map
		env.Fractal = fractal.newLuaAPI({
			getMapRand = function() return S.mapRand end,
			getMapInfo = function() return S.W, S.H, S.wrapX, S.wrapY end,
		})
		env.ContextPtr = nil
		env.UI = nil
		local I = inc.install(env, { files = opts.files, log = log, echo = opts.echo, rawprint = print })
		result.includes = I.resolved
		phase("bootstrap")

		-- VPUI_core is loaded by the front-end/UI contexts before the map script in game (§11.6)
		env.MapModData = {}
		if opts.pre_vpui ~= false then
			if I.resolve("VPUI_core") then env.include("VPUI_core") end
		end
		phase("vpui_core")

		-- 1. load the script: top-level code and every include run now
		if not opts.script_path then error("c5maps: no script_path given", 0) end
		log("[c5maps] loading " .. opts.script_path)
		local chunk = inc.loadLuaFile(opts.script_path)
		chunk()
		phase("load_script")

		-- map options: defaults from GetMapScriptInfo().CustomOptions, then overrides
		local info, optList = collectOptions(env, S)
		result.options = optList
		result.script_info = info and { Name = info.Name, Description = info.Description } or nil
		for _, o in ipairs(optList) do
			if o.default ~= nil then S.pregame.mapOptions[tostring(o.index)] = o.default end
		end
		for k, v in pairs(opts.map_options or {}) do S.pregame.mapOptions[tostring(k)] = v end
		if opts.list_options then return end

		-- 2. GetMapInitData(worldSize)
		local worldRow = GI.byID("Worlds")[S.pregame.worldSize]
		if not worldRow then error("c5maps: unknown world size id " .. tostring(S.pregame.worldSize), 0) end
		local W, H = worldRow.GridWidth, worldRow.GridHeight
		local wrapX, wrapY, top, bottom = true, false, 90, -90
		local gotData = false
		local gmid = rawget(env, "GetMapInitData")
		if type(gmid) == "function" then
			local t = gmid(S.pregame.worldSize)
			if type(t) == "table" then
				gotData = true
				local ti = S.toint
				if t.Width ~= nil then W = ti(t.Width) end
				if t.Height ~= nil then H = ti(t.Height) end
				if t.WrapX ~= nil then wrapX = S.tobool(t.WrapX) end
				if t.WrapY ~= nil then wrapY = S.tobool(t.WrapY) end
				if t.TopLatitude ~= nil then top = ti(t.TopLatitude) end
				if t.BottomLatitude ~= nil then bottom = ti(t.BottomLatitude) end
				log(("[c5maps] GetMapInitData -> %dx%d wrapX=%s wrapY=%s lat %d..%d"):format(W, H, tostring(wrapX), tostring(wrapY), bottom, top))
			end
		end
		if not gotData then
			-- kMap.init() without init data: world grid, wrap defaults, latitudes keep their (fresh) 0/0
			top, bottom = 0, 0
			log(("[c5maps] no GetMapInitData table -> world grid %dx%d, latitudes 0/0"):format(W, H))
		end
		phase("get_map_init_data")

		-- 3. CvMap::init
		mapmod.initMap(S, W, H, wrapX, wrapY, top, bottom)
		phase("map_init")

		-- 4. GenerateMap()
		local gen = rawget(env, "GenerateMap")
		if type(gen) ~= "function" then error("Cannot find map script entry point GenerateMap()", 0) end
		gen()
		collectgarbage("collect")
		phase("generate_map")

		-- 5. GetGameInitialItemsOverrides()
		local gio = rawget(env, "GetGameInitialItemsOverrides")
		if type(gio) == "function" then
			local t = gio()
			if type(t) == "table" then
				for _, k in ipairs({ "GrantInitialFreeTechsPerTeam", "GrantInitialGoldPerPlayer",
					"GrantInitialCulturePerPlayer", "ClearResearchQueuePerPlayer", "GrantInitialUnitsPerPlayer" }) do
					if type(t[k]) == "table" then
						local parts = {}
						for id, b in pairs(t[k]) do parts[#parts + 1] = tostring(id) .. "=" .. tostring(b) end
						table.sort(parts)
						log("[c5maps] GetGameInitialItemsOverrides." .. k .. ": " .. table.concat(parts, " "))
					end
				end
			end
		end
		phase("initial_items")

		-- 6. engine post-processing
		S.validateCoast()
		phase("validate_coast")
	end, debug.traceback)
	if prof then
		debug.sethook()
		local function top(t, k)
			local arr = {}
			for key, c in pairs(t) do arr[#arr + 1] = { key, c } end
			table.sort(arr, function(a, b) return a[2] > b[2] end)
			local out = {}
			for i = 1, math.min(k, #arr) do
				out[#out + 1] = ("%6.2f%%  %s"):format(100 * arr[i][2] / prof.n, arr[i][1])
			end
			return table.concat(out, string.char(10))
		end
		local NL = string.char(10)
		result.profile = "== hottest functions (by definition line) ==" .. NL .. top(prof.funcs, 40)
			.. NL .. "== hottest lines ==" .. NL .. top(prof.lines, 40)
	end

	if not ok then
		result.error = tostring(err)
		result.ok = false
		result.log_text = table.concat(logLines, "\n")
		return false, result
	end
	if opts.list_options then
		result.ok = true
		result.log_text = table.concat(logLines, "\n")
		return true, result
	end
	local dump = buildDump(S, opts, logLines)
	result.dump = dump
	result.json = M.toJSON(dump)
	phase("dump")
	result.ok = true
	result.log_text = dump.log
	result.total_seconds = clock() - t0
	return true, result
end

return M
