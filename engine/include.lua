--[[
engine/include.lua -- the game's include() over a virtual file system, plus print capture.

  local inc = require("include")
  local I = inc.install(env, {
      files = { {path=..., source=...}, ... },   -- VFS candidates in priority order (later wins)
      log = function(line) ... end,             -- receives every captured line
      echo = true|false,                        -- also print to stdout
  })
  I.resolve(name) -> path | nil ;  I.resolved -> list of {name=, path=} in include order

include(name) resolves the bare file name case-insensitively (".lua" optional), re-executes the file
every call in the shared global environment, and returns a list of the included paths (CPK.lua's
Import relies on `#include(f) == 1`).  include(pattern, true) includes every VFS file whose name
matches the Lua pattern (regex form) and returns their names.  A missing file returns {} and logs.
]]

local M = {}

local function readFile(path)
	local f, err = io.open(path, "rb")
	if not f then return nil, err end
	local s = f:read("*a")
	f:close()
	if s:sub(1, 3) == "\239\187\191" then s = s:sub(4) end   -- UTF-8 BOM (the game tolerates it)
	return s
end
M.readFile = readFile

local function basename(p)
	return (p:gsub("\\", "/"):match("([^/]+)$"))
end
M.basename = basename

function M.loadLuaFile(path, chunkname)
	local src, err = readFile(path)
	if not src then error("c5maps: cannot read " .. tostring(path) .. ": " .. tostring(err), 0) end
	if src:sub(1, 1) == "#" then src = "--" .. src end
	local chunk, perr = loadstring(src, chunkname or ("@" .. path))
	if not chunk then error(perr, 0) end
	return chunk
end

function M.install(env, opts)
	opts = opts or {}
	local index = {}
	local files = opts.files or {}
	for i = 1, #files do
		local e = files[i]
		local name = basename(e.path):lower()
		index[name] = e
	end
	local I = { index = index, resolved = {} }
	local logf = opts.log or function() end
	local origPrint = opts.rawprint or print

	local function capture(...)
		local n = select("#", ...)
		local parts = {}
		for i = 1, n do parts[i] = tostring((select(i, ...))) end
		local line = table.concat(parts, "\t")
		logf(line)
		if opts.echo then origPrint(line) end
	end
	env.print = capture
	I.print = capture

	function I.resolve(name)
		local key = basename(tostring(name)):lower()
		if not key:match("%.lua$") then key = key .. ".lua" end
		local e = index[key]
		return e and e.path, e
	end

	local depth = 0
	local function include(name, regex)
		if type(name) ~= "string" then error("bad argument #1 to 'include' (string expected)", 2) end
		if regex then
			local out = {}
			local names = {}
			for k, e in pairs(index) do
				if basename(e.path):match(name) then names[#names + 1] = k end
			end
			table.sort(names)
			for _, k in ipairs(names) do
				local sub = include(basename(index[k].path))
				for _, p in ipairs(sub) do out[#out + 1] = p end
			end
			return out
		end
		local path, e = I.resolve(name)
		if not path then
			logf("[include] " .. name .. " -> NOT FOUND")
			return {}
		end
		I.resolved[#I.resolved + 1] = { name = name, path = path, source = e.source }
		logf(("[include] %s%s -> %s"):format(string.rep("  ", depth), name, path))
		local chunk = M.loadLuaFile(path)
		depth = depth + 1
		chunk()   -- errors propagate untouched so the top-level xpcall traceback stays complete
		depth = depth - 1
		return { basename(path) }
	end
	env.include = include
	I.include = include
	return I
end

return M
