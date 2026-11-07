--[[
engine/gameinfo.lua -- GameInfo / GameInfoTypes / DB / Locale over the data exported by host/gamedb.py.

  local gameinfo = require("gameinfo")
  local GI = gameinfo.new(dataDir)      -- dataDir holds gameinfo.lua + tables/*.lua
  GI.GameInfo, GI.GameInfoTypes, GI.DB, GI.Locale
  GI.rows(name) -> array of row tables (rowid order), GI.byType(name), GI.byID(name)

GameInfo.<Table> is a userdata proxy (newproxy) so that #GameInfo.X works under Lua 5.1:
  T[id] -> row with ID == id;  T["TYPE"] / T.TYPE -> row with Type == "TYPE";
  T() -> iterator over all rows (rowid order);  T("sql where clause") / T{Col=v,...} -> filtered iterator;
  #T -> row count.
GameInfo[name] is nil for tables that do not exist.
Rows: column -> value; `boolean` columns are Lua booleans; NULL columns are absent.

DB.Query(sql, ...) / DB.CreateQuery(sql) support the subset used by consumers:
  SELECT <*, cols, count(*) [AS x], literals> FROM <table> [WHERE <expr>] [ORDER BY col [ASC|DESC], ...] [LIMIT n]
  plus `SELECT tbl_name FROM sqlite_master WHERE type = 'table'` and `PRAGMA table_info(T)`.
  Anything else raises "c5maps: unsupported SQL".
]]

local M = {}

local floor = math.floor
local newproxy = newproxy

-------------------------------------------------------------------------------------------------
-- tiny SQL expression compiler (WHERE clauses)
-------------------------------------------------------------------------------------------------
local function tokenize(s)
	local toks = {}
	local i, n = 1, #s
	while i <= n do
		local c = s:sub(i, i)
		if c:match("%s") then
			i = i + 1
		elseif c == "'" or c == '"' then
			local j = i + 1
			local buf = {}
			while true do
				if j > n then error("c5maps: unterminated string in SQL: " .. s, 0) end
				local d = s:sub(j, j)
				if d == c then
					if s:sub(j + 1, j + 1) == c then buf[#buf + 1] = c; j = j + 2
					else break end
				else buf[#buf + 1] = d; j = j + 1 end
			end
			if c == "'" then toks[#toks + 1] = { t = "str", v = table.concat(buf) }
			else toks[#toks + 1] = { t = "id", v = table.concat(buf) } end
			i = j + 1
		elseif c == "[" then
			local j = s:find("]", i + 1, true)
			toks[#toks + 1] = { t = "id", v = s:sub(i + 1, j - 1) }
			i = j + 1
		elseif c:match("%d") or (c == "-" and s:sub(i + 1, i + 1):match("%d") and (#toks == 0 or toks[#toks].t == "op")) then
			local num = s:match("^%-?%d+%.?%d*", i)
			toks[#toks + 1] = { t = "num", v = tonumber(num) }
			i = i + #num
		elseif c:match("[%a_]") then
			local w = s:match("^[%w_%.]+", i)
			local u = w:upper()
			if u == "AND" or u == "OR" or u == "NOT" or u == "IS" or u == "NULL" or u == "IN" or u == "LIKE"
				or u == "SELECT" or u == "FROM" or u == "WHERE" or u == "ORDER" or u == "BY" or u == "ASC"
				or u == "DESC" or u == "LIMIT" or u == "AS" or u == "PRAGMA" or u == "TRUE" or u == "FALSE" then
				toks[#toks + 1] = { t = "kw", v = u }
			else
				toks[#toks + 1] = { t = "id", v = w }
			end
			i = i + #w
		elseif c == "?" then
			toks[#toks + 1] = { t = "param" }
			i = i + 1
		else
			local two = s:sub(i, i + 1)
			if two == "<>" or two == "!=" or two == "<=" or two == ">=" or two == "==" then
				toks[#toks + 1] = { t = "op", v = two }
				i = i + 2
			elseif c == "=" or c == "<" or c == ">" or c == "(" or c == ")" or c == "," or c == "*" or c == ";" then
				toks[#toks + 1] = { t = "op", v = c }
				i = i + 1
			else
				error("c5maps: unsupported SQL character '" .. c .. "' in: " .. s, 0)
			end
		end
	end
	return toks
end

-- normalise a row value for SQL comparison (booleans compare as 0/1 like SQLite)
local function sqlval(v)
	if v == true then return 1 elseif v == false then return 0 end
	return v
end

local function compare(a, op, b)
	a, b = sqlval(a), sqlval(b)
	if a == nil or b == nil then return false end
	if type(a) ~= type(b) then
		-- SQLite affinity: numeric text vs number
		local na, nb = tonumber(a), tonumber(b)
		if na and nb then a, b = na, nb else
			if op == "=" or op == "==" then return false end
			if op == "<>" or op == "!=" then return true end
			a, b = tostring(a), tostring(b)
		end
	end
	if op == "=" or op == "==" then return a == b
	elseif op == "<>" or op == "!=" then return a ~= b
	elseif op == "<" then return a < b
	elseif op == ">" then return a > b
	elseif op == "<=" then return a <= b
	elseif op == ">=" then return a >= b end
	error("c5maps: unsupported SQL operator " .. tostring(op), 0)
end

local function likeToPattern(p)
	local out = { "^" }
	for ch in p:gmatch(".") do
		if ch == "%" then out[#out + 1] = ".*"
		elseif ch == "_" then out[#out + 1] = "."
		elseif ch:match("%p") then out[#out + 1] = "%" .. ch
		else out[#out + 1] = ch end
	end
	out[#out + 1] = "$"
	return table.concat(out)
end

-- Parser state: toks, pos, params (array), pidx
local Parser = {}
Parser.__index = Parser

local function newParser(toks, params, src)
	return setmetatable({ toks = toks, pos = 1, params = params or {}, pidx = 0, src = src }, Parser)
end
function Parser:peek(k) return self.toks[self.pos + (k or 0)] end
function Parser:next() local t = self.toks[self.pos]; self.pos = self.pos + 1; return t end
function Parser:fail(msg) error("c5maps: unsupported SQL (" .. msg .. "): " .. tostring(self.src), 0) end
function Parser:isKw(v, k) local t = self:peek(k); return t and t.t == "kw" and t.v == v end
function Parser:isOp(v, k) local t = self:peek(k); return t and t.t == "op" and t.v == v end
function Parser:expectOp(v) if not self:isOp(v) then self:fail("expected '" .. v .. "'") end; self:next() end

-- value term -> function(row) -> value
function Parser:term()
	local t = self:next()
	if not t then self:fail("unexpected end") end
	if t.t == "num" or t.t == "str" then local v = t.v; return function() return v end end
	if t.t == "kw" and (t.v == "TRUE" or t.v == "FALSE") then local v = (t.v == "TRUE") and 1 or 0; return function() return v end end
	if t.t == "kw" and t.v == "NULL" then return function() return nil end end
	if t.t == "param" then
		self.pidx = self.pidx + 1
		local v = self.params[self.pidx]
		if type(v) == "boolean" then v = v and 1 or 0 end
		return function() return v end
	end
	if t.t == "id" then
		local col = t.v:match("([^%.]+)$")
		return function(row) return row[col] end
	end
	if t.t == "op" and t.v == "(" then
		local e = self:expr()
		self:expectOp(")")
		return e
	end
	self:fail("unexpected token " .. tostring(t.v))
end

function Parser:predicate()
	if self:isKw("NOT") then
		self:next()
		local p = self:predicate()
		return function(row) return not p(row) end
	end
	if self:isOp("(") then
		-- could be a parenthesised boolean expression
		local save = self.pos
		self:next()
		local ok, e = pcall(self.expr, self)
		if ok and self:isOp(")") then
			self:next()
			if not (self:peek() and (self:peek().t == "op" and self:peek().v ~= ")" and self:peek().v ~= ",")) then
				return e
			end
		end
		self.pos = save
	end
	local lhs = self:term()
	local t = self:peek()
	if t and t.t == "op" and (t.v == "=" or t.v == "==" or t.v == "<>" or t.v == "!=" or t.v == "<" or t.v == ">" or t.v == "<=" or t.v == ">=") then
		self:next()
		local rhs = self:term()
		local op = t.v
		return function(row) return compare(lhs(row), op, rhs(row)) end
	end
	if self:isKw("IS") then
		self:next()
		local neg = false
		if self:isKw("NOT") then self:next(); neg = true end
		if not self:isKw("NULL") then self:fail("IS without NULL") end
		self:next()
		if neg then return function(row) return lhs(row) ~= nil end end
		return function(row) return lhs(row) == nil end
	end
	local neg = false
	if self:isKw("NOT") then self:next(); neg = true end
	if self:isKw("IN") then
		self:next()
		self:expectOp("(")
		local vals = {}
		repeat
			vals[#vals + 1] = self:term()
			local more = self:isOp(",")
			if more then self:next() end
		until not more
		self:expectOp(")")
		return function(row)
			local v = lhs(row)
			local hit = false
			for i = 1, #vals do if compare(v, "=", vals[i](row)) then hit = true; break end end
			if neg then return not hit end
			return hit
		end
	end
	if self:isKw("LIKE") then
		self:next()
		local rhs = self:term()
		return function(row)
			local v, p = lhs(row), rhs(row)
			if v == nil or p == nil then return false end
			local hit = tostring(v):lower():match(likeToPattern(tostring(p):lower())) ~= nil
			if neg then return not hit end
			return hit
		end
	end
	-- bare value: truthy if non-zero
	return function(row) local v = sqlval(lhs(row)); return v ~= nil and v ~= 0 and v ~= "" end
end

function Parser:conj()
	local p = self:predicate()
	while self:isKw("AND") do
		self:next()
		local a, b = p, self:predicate()
		p = function(row) return a(row) and b(row) end
	end
	return p
end

function Parser:expr()
	local p = self:conj()
	while self:isKw("OR") do
		self:next()
		local a, b = p, self:conj()
		p = function(row) return a(row) or b(row) end
	end
	return p
end

local whereCache = {}
local function compileWhere(src, params)
	if not params or #params == 0 then
		local c = whereCache[src]
		if c then return c end
	end
	local p = newParser(tokenize(src), params, src)
	local f = p:expr()
	if p:peek() and not p:isOp(";") then p:fail("trailing tokens") end
	if not params or #params == 0 then whereCache[src] = f end
	return f
end
M.compileWhere = compileWhere

-------------------------------------------------------------------------------------------------
function M.new(dataDir)
	dataDir = dataDir or "data"
	local idxChunk, err = loadfile(dataDir .. "/gameinfo.lua")
	if not idxChunk then error("c5maps: cannot load game data index (" .. tostring(err) .. "); run python host/gamedb.py", 0) end
	local index = idxChunk()
	local tables = index.tables

	local GI = { index = index }
	local rowsCache, byIDCache, byTypeCache = {}, {}, {}

	local function rows(name)
		local r = rowsCache[name]
		if r then return r end
		local info = tables[name]
		if not info then return nil end
		local chunk, e = loadfile(dataDir .. "/tables/" .. info.file .. ".lua")
		if not chunk then error("c5maps: cannot load table " .. name .. ": " .. tostring(e), 0) end
		local raw = chunk()
		local cols = info.cols
		local ncol = #cols
		r = {}
		for i = 1, #raw do
			local src = raw[i]
			local row = {}
			for c = 1, ncol do
				local v = src[c]
				if v ~= nil then row[cols[c]] = v end
			end
			r[i] = row
		end
		rowsCache[name] = r
		return r
	end
	GI.rows = rows

	local function byID(name)
		local m = byIDCache[name]
		if m then return m end
		m = {}
		local rs = rows(name)
		if rs and tables[name].id then
			for i = 1, #rs do
				local id = rs[i].ID
				if id ~= nil and m[id] == nil then m[id] = rs[i] end
			end
		end
		byIDCache[name] = m
		return m
	end
	local function byType(name)
		local m = byTypeCache[name]
		if m then return m end
		m = {}
		local rs = rows(name)
		if rs and tables[name].type then
			for i = 1, #rs do
				local ty = rs[i].Type
				if ty ~= nil and m[ty] == nil then m[ty] = rs[i] end
			end
		end
		byTypeCache[name] = m
		return m
	end
	GI.byID, GI.byType = byID, byType

	local function iterRows(rs, pred)
		local i = 0
		local n = #rs
		return function()
			while true do
				i = i + 1
				if i > n then return nil end
				local row = rs[i]
				if not pred or pred(row) then return row end
			end
		end
	end

	local function makeFilter(name, arg)
		if arg == nil then return nil end
		if type(arg) == "string" then
			return compileWhere(arg)
		elseif type(arg) == "table" then
			local conds = {}
			for k, v in pairs(arg) do conds[#conds + 1] = { k, sqlval(v) } end
			return function(row)
				for i = 1, #conds do
					local c = conds[i]
					if sqlval(row[c[1]]) ~= c[2] then
						-- numeric text equality
						local a, b = tonumber(sqlval(row[c[1]])), tonumber(c[2])
						if not (a and b and a == b) then return false end
					end
				end
				return true
			end
		end
		error("c5maps: GameInfo." .. name .. "(...) expects nil, a where-clause string or a table", 3)
	end

	-- table proxies
	local proxies = {}
	local function makeProxy(name)
		local mt = {}
		mt.__index = function(_, k)
			if type(k) == "number" then
				return byID(name)[k]
			elseif type(k) == "string" then
				return byType(name)[k]
			end
			return nil
		end
		mt.__call = function(_, arg)
			return iterRows(rows(name), makeFilter(name, arg))
		end
		mt.__len = function() return tables[name].n end
		mt.__tostring = function() return "GameInfo." .. name end
		mt.__newindex = function() error("c5maps: GameInfo." .. name .. " is read-only", 2) end
		local p
		if newproxy then
			p = newproxy(true)
			local pm = getmetatable(p)
			for k, v in pairs(mt) do pm[k] = v end
		else
			p = setmetatable({}, mt)
		end
		return p
	end

	local GameInfo = setmetatable({}, {
		__index = function(t, name)
			if type(name) ~= "string" or not tables[name] then return nil end
			local p = proxies[name]
			if not p then
				p = makeProxy(name)
				proxies[name] = p
			end
			return p
		end,
		__newindex = function() error("c5maps: GameInfo is read-only", 2) end,
	})
	GI.GameInfo = GameInfo

	-- GameInfoTypes: plain table, unknown key -> nil
	local GameInfoTypes = {}
	for k, v in pairs(index.types) do GameInfoTypes[k] = v end
	GI.GameInfoTypes = GameInfoTypes

	-- GameDefines
	local GameDefines = {}
	local drows = rows("Defines")
	if drows then
		for i = 1, #drows do
			local r = drows[i]
			if r.Name ~= nil then GameDefines[r.Name] = r.Value end
		end
	end
	GI.GameDefines = GameDefines

	---------------------------------------------------------------------------------------------
	-- DB.Query / DB.CreateQuery
	---------------------------------------------------------------------------------------------
	local function runSelect(sql, params)
		local toks = tokenize(sql)
		local p = newParser(toks, params, sql)
		if p:isKw("PRAGMA") then
			p:next()
			local fn = p:next()
			if not (fn and fn.t == "id" and fn.v:lower() == "table_info") then p:fail("pragma") end
			p:expectOp("(")
			local tn = p:next().v
			p:expectOp(")")
			local info = tables[tn]
			local out = {}
			if info then
				for i, c in ipairs(info.cols) do out[#out + 1] = { cid = i - 1, name = c, type = info.decl[i] } end
			end
			return out
		end
		if not p:isKw("SELECT") then p:fail("only SELECT") end
		p:next()
		-- select list
		local items = {}
		repeat
			local item = {}
			if p:isOp("*") then
				p:next(); item.star = true
			else
				local t = p:peek()
				if t.t == "id" and t.v:lower() == "count" and p:isOp("(", 1) then
					p:next(); p:expectOp("("); p:next(); p:expectOp(")")
					item.count = true; item.name = "count(*)"
				elseif t.t == "id" then
					p:next(); item.col = t.v:match("([^%.]+)$"); item.name = item.col
				elseif t.t == "num" or t.t == "str" then
					p:next(); item.const = t.v; item.name = tostring(t.v)
				else
					p:fail("select item")
				end
			end
			if p:isKw("AS") then p:next(); item.name = p:next().v end
			items[#items + 1] = item
			local more = p:isOp(",")
			if more then p:next() end
		until not more
		if not p:isKw("FROM") then p:fail("FROM expected") end
		p:next()
		local tname = p:next().v
		local pred
		if p:isKw("WHERE") then
			p:next()
			pred = p:expr()
		end
		local order = nil
		if p:isKw("ORDER") then
			p:next()
			if not p:isKw("BY") then p:fail("ORDER BY") end
			p:next()
			order = {}
			repeat
				local c = p:next().v
				local desc = false
				if p:isKw("DESC") then p:next(); desc = true elseif p:isKw("ASC") then p:next() end
				order[#order + 1] = { c, desc }
				local more = p:isOp(",")
				if more then p:next() end
			until not more
		end
		local limit
		if p:isKw("LIMIT") then p:next(); limit = p:next().v end
		if p:peek() and not p:isOp(";") then p:fail("trailing tokens") end

		local src
		if tname == "sqlite_master" then
			src = {}
			for _, n in ipairs(index.order) do src[#src + 1] = { type = "table", name = n, tbl_name = n } end
		else
			src = rows(tname)
			if not src then error("c5maps: DB.Query: no such table: " .. tostring(tname), 0) end
		end
		local matched = {}
		for i = 1, #src do
			if not pred or pred(src[i]) then matched[#matched + 1] = src[i] end
		end
		if order then
			table.sort(matched, function(a, b)
				for _, o in ipairs(order) do
					local x, y = sqlval(a[o[1]]), sqlval(b[o[1]])
					if x ~= y then
						if x == nil then return not o[2] end
						if y == nil then return o[2] end
						if o[2] then return x > y else return x < y end
					end
				end
				return false
			end)
		end
		local hasCount = false
		for _, it in ipairs(items) do if it.count then hasCount = true end end
		local out = {}
		if hasCount then
			local row = {}
			for _, it in ipairs(items) do
				if it.count then row[it.name] = #matched
				elseif it.const ~= nil then row[it.name] = it.const
				elseif it.col and matched[1] then row[it.name] = matched[1][it.col] end
			end
			out[1] = row
		else
			for i = 1, #matched do
				local r = matched[i]
				local row = {}
				for _, it in ipairs(items) do
					if it.star then for k, v in pairs(r) do row[k] = v end
					elseif it.const ~= nil then row[it.name] = it.const
					else row[it.name] = r[it.col] end
				end
				out[#out + 1] = row
				if limit and #out >= limit then break end
			end
		end
		return out
	end

	local DB = {}
	function DB.Query(sql, ...)
		if type(sql) ~= "string" then error("bad argument #1 to 'Query' (string expected)", 2) end
		local res = runSelect(sql, { ... })
		local i = 0
		return function()
			i = i + 1
			return res[i]
		end
	end
	function DB.CreateQuery(sql)
		if type(sql) ~= "string" then error("bad argument #1 to 'CreateQuery' (string expected)", 2) end
		return function(...)
			return DB.Query(sql, ...)
		end
	end
	setmetatable(DB, { __index = function(_, k) error("c5maps: unimplemented DB." .. tostring(k), 2) end })
	GI.DB = DB

	---------------------------------------------------------------------------------------------
	-- Locale
	---------------------------------------------------------------------------------------------
	local texts = {}
	GI.texts = texts
	local function lookup(key, ...)
		if key == nil then return "" end
		local s = texts[key] or tostring(key)
		local args = { ... }
		if #args > 0 then
			s = s:gsub("{(%d+)_[^}]*}", function(n)
				local v = args[tonumber(n)]
				if v == nil then return nil end
				return tostring(v)
			end)
		end
		return s
	end
	local Locale = {
		ConvertTextKey = lookup,
		Lookup = lookup,
		IsNilOrWhitespace = function(s) return s == nil or tostring(s):match("^%s*$") ~= nil end,
		ToUpper = function(s) return tostring(s):upper() end,
		ToLower = function(s) return tostring(s):lower() end,
		Length = function(s) return #tostring(s) end,
		Compare = function(a, b) a, b = tostring(a), tostring(b); if a < b then return -1 elseif a > b then return 1 end return 0 end,
		HasTextKey = function(k) return texts[k] ~= nil end,
	}
	setmetatable(Locale, { __index = function(_, k) error("c5maps: unimplemented Locale." .. tostring(k), 2) end })
	GI.Locale = Locale

	return GI
end

return M
