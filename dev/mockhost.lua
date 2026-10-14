-- Mock Noctalia 5.2.1 plugin host for exercising dadmin/assistant with stock Lua (no Luau, no shell).
--
--   lua dev/mockhost.lua            (run from the project root)
--
-- Every entry runs in its own environment like the real host. Backend calls run the real Python backend
-- against a throwaway config/state directory. The ui.* constructors validate prop names, enum values,
-- palette colors, glyph names and child rules against the Noctalia 5.2.1 type definitions, and every
-- noctalia.tr() key is checked against translations/en.json.

local ROOT = arg and arg[0] and arg[0]:match("^(.*)/dev/mockhost%.lua$") or "."
local PLUGIN = ROOT .. "/plugin"
local BACKEND = ROOT .. "/backend/bin/noctalia-assistant"
local TMP = os.getenv("MOCK_TMP") or "/tmp/noctalia-assistant-mock"

local failures, checks = {}, 0
local function fail(msg) failures[#failures + 1] = msg; io.stderr:write("  FAIL " .. msg .. "\n") end
local function check(cond, msg) checks = checks + 1; if not cond then fail(msg) end; return cond end

-- ------------------------------------------------------------------------------------------- json
local json = {}
do
  local function isArray(t)
    local n = 0
    for k in pairs(t) do
      if type(k) ~= "number" or k < 1 or k % 1 ~= 0 then return false end
      n = n + 1
    end
    for i = 1, n do if t[i] == nil then return false end end
    return true, n
  end
  local esc = { ['"'] = '\\"', ["\\"] = "\\\\", ["\b"] = "\\b", ["\f"] = "\\f", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }
  local function enc(v)
    local t = type(v)
    if v == nil then return "null"
    elseif t == "boolean" then return tostring(v)
    elseif t == "number" then
      if v % 1 == 0 and math.abs(v) < 2^53 then return string.format("%d", v) end
      return string.format("%.17g", v)
    elseif t == "string" then
      return '"' .. v:gsub('[%c"\\]', function(c) return esc[c] or string.format("\\u%04x", c:byte()) end) .. '"'
    elseif t == "table" then
      local arr, n = isArray(v)
      if arr then
        local parts = {}
        for i = 1, n do parts[i] = enc(v[i]) end
        return "[" .. table.concat(parts, ",") .. "]"
      end
      local parts = {}
      for k, val in pairs(v) do
        if type(val) == "function" then error("function in state/json value at key " .. tostring(k)) end
        parts[#parts + 1] = enc(tostring(k)) .. ":" .. enc(val)
      end
      table.sort(parts)
      return "{" .. table.concat(parts, ",") .. "}"
    end
    error("cannot encode " .. t)
  end
  json.encode = enc

  function json.decode(s)
    local pos = 1
    local function ws() pos = s:find("[^ \t\r\n]", pos) or #s + 1 end
    local val
    local function str()
      pos = pos + 1
      local out = {}
      while true do
        local c = s:sub(pos, pos)
        if c == "" then error("unterminated string") end
        if c == '"' then pos = pos + 1; break end
        if c == "\\" then
          local n = s:sub(pos + 1, pos + 1)
          local map = { b = "\b", f = "\f", n = "\n", r = "\r", t = "\t", ['"'] = '"', ["\\"] = "\\", ["/"] = "/" }
          if n == "u" then
            local cp = tonumber(s:sub(pos + 2, pos + 5), 16)
            pos = pos + 6
            if cp >= 0xD800 and cp <= 0xDBFF and s:sub(pos, pos + 1) == "\\u" then
              local lo = tonumber(s:sub(pos + 2, pos + 5), 16)
              cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo - 0xDC00)
              pos = pos + 6
            end
            out[#out + 1] = utf8.char(cp)
          else
            out[#out + 1] = map[n]; pos = pos + 2
          end
        else
          out[#out + 1] = c; pos = pos + 1
        end
      end
      return table.concat(out)
    end
    function val()
      ws()
      local c = s:sub(pos, pos)
      if c == "{" then
        pos = pos + 1; local t = {}; ws()
        if s:sub(pos, pos) == "}" then pos = pos + 1; return t end
        while true do
          ws(); local k = str(); ws(); pos = pos + 1
          t[k] = val(); ws()
          local d = s:sub(pos, pos); pos = pos + 1
          if d == "}" then return t end
        end
      elseif c == "[" then
        pos = pos + 1; local t = {}; ws()
        if s:sub(pos, pos) == "]" then pos = pos + 1; return t end
        while true do
          t[#t + 1] = val(); ws()
          local d = s:sub(pos, pos); pos = pos + 1
          if d == "]" then return t end
        end
      elseif c == '"' then return str()
      elseif s:sub(pos, pos + 3) == "true" then pos = pos + 4; return true
      elseif s:sub(pos, pos + 4) == "false" then pos = pos + 5; return false
      elseif s:sub(pos, pos + 3) == "null" then pos = pos + 4; return nil
      else
        local num = s:match("^-?%d+%.?%d*[eE]?[-+]?%d*", pos)
        pos = pos + #num
        return math.tointeger(tonumber(num)) or tonumber(num)
      end
    end
    local ok, res = pcall(val)
    if not ok then return nil, res end
    return res
  end
end

-- --------------------------------------------------------------------------------------- shell
local function shq(s) return "'" .. tostring(s):gsub("'", "'\\''") .. "'" end
local ENV = {
  NOCTALIA_ASSISTANT_CONFIG_DIR = TMP .. "/config",
  NOCTALIA_ASSISTANT_STATE_DIR = TMP .. "/state",
  XDG_RUNTIME_DIR = TMP .. "/run",
}
local function envPrefix()
  local parts = {}
  for k, v in pairs(ENV) do parts[#parts + 1] = k .. "=" .. shq(v) end
  table.sort(parts)
  return "env " .. table.concat(parts, " ") .. " "
end
local function sh(cmd)
  local p = io.popen(cmd .. " 2>/tmp/noctalia-assistant-mock.stderr")
  local out = p:read("a")
  local ok, _, code = p:close()
  local ef = io.open("/tmp/noctalia-assistant-mock.stderr"); local err = ef and ef:read("a") or ""; if ef then ef:close() end
  return out, err, ok and 0 or code
end

-- ------------------------------------------------------------------------------- validation data
local function readFile(p) local f = io.open(p); if not f then return nil end; local s = f:read("a"); f:close(); return s end
local GLYPHS = json.decode(readFile("/usr/share/noctalia/assets/fonts/tabler.json"))
local EN = json.decode(readFile(PLUGIN .. "/translations/en.json"))
local function trLookup(key)
  local cur = EN
  for part in key:gmatch("[^.]+") do
    if type(cur) ~= "table" then return nil end
    cur = cur[part]
  end
  return type(cur) == "string" and cur or nil
end
local ROLES = {}
for _, r in ipairs({ "primary", "on_primary", "secondary", "on_secondary", "tertiary", "on_tertiary", "error", "on_error",
  "surface", "on_surface", "surface_variant", "on_surface_variant", "outline", "shadow", "hover", "on_hover" }) do ROLES[r] = true end
local function validColor(c)
  if type(c) ~= "string" then return false end
  if c:match("^#%x%x%x%x%x%x$") or c:match("^#%x%x%x%x%x%x%x%x$") then return true end
  local role, alpha = c:match("^([%l_]+)/([%d.]+)$")
  if role then return ROLES[role] and tonumber(alpha) and tonumber(alpha) <= 1 end
  return ROLES[c] == true
end

local COMMON = { "key", "width", "height", "flexGrow", "opacity", "visible" }
local FLEX = { "gap", "padding", "paddingH", "paddingV", "align", "justify", "fill", "radius", "border", "borderWidth", "minWidth", "minHeight", "onClick", "onHover", "tooltip" }
local PROPS = {
  column = FLEX, row = FLEX,
  scroll = { "gap", "padding", "paddingH", "paddingV", "align", "justify", "fill", "radius", "border", "borderWidth", "stickToBottom", "scrollToBottomRev", "onScroll" },
  box = { "fill", "radius", "border", "borderWidth", "softness", "onClick", "onHover", "tooltip" },
  label = { "text", "fontSize", "color", "fontWeight", "fontFamily", "baseline", "maxWidth", "maxLines", "textAlign" },
  markdown = { "text" },
  glyph = { "name", "size", "color" },
  separator = { "thickness", "color", "spacing", "orientation" },
  spacer = {},
  button = { "text", "glyph", "fontSize", "glyphSize", "variant", "contentAlign", "controlSize", "tooltip", "enabled", "selected", "onClick", "onRightClick", "onHover" },
  input = { "value", "placeholder", "fontSize", "controlSize", "password", "multiline", "submitOnEnter", "frameVisible", "focus", "enabled", "onChange", "onSubmit" },
}
local ALLOWED = {}
for t, list in pairs(PROPS) do
  ALLOWED[t] = {}
  for _, p in ipairs(COMMON) do ALLOWED[t][p] = true end
  for _, p in ipairs(list) do ALLOWED[t][p] = true end
end
local ENUMS = {
  align = { start = 1, center = 1, ["end"] = 1, stretch = 1 },
  justify = { start = 1, center = 1, ["end"] = 1, space_between = 1 },
  fontWeight = { thin = 1, light = 1, normal = 1, medium = 1, semibold = 1, bold = 1, heavy = 1 },
  textAlign = { start = 1, center = 1, ["end"] = 1 },
  variant = { default = 1, primary = 1, secondary = 1, destructive = 1, outline = 1, ghost = 1 },
  contentAlign = { start = 1, center = 1, ["end"] = 1 },
  controlSize = { sm = 1, md = 1, lg = 1 },
}
local CONTAINERS = { column = true, row = true, scroll = true }

local ui = {}
for t in pairs(PROPS) do
  ui[t] = function(props, children)
    props = props or {}
    for k, v in pairs(props) do
      if not check(ALLOWED[t][k], "ui." .. t .. " unknown prop '" .. tostring(k) .. "'") then goto continue end
      if ENUMS[k] then check(ENUMS[k][v], "ui." .. t .. "." .. k .. " bad value '" .. tostring(v) .. "'") end
      if k == "fill" or k == "border" or k == "color" then check(validColor(v), "ui." .. t .. "." .. k .. " invalid color '" .. tostring(v) .. "'") end
      if (t == "glyph" and k == "name") or (t == "button" and k == "glyph") then check(GLYPHS[v] ~= nil, "unknown glyph '" .. tostring(v) .. "'") end
      if k:match("^on%u") then check(type(v) == "function" or type(v) == "string", "ui." .. t .. "." .. k .. " must be a function") end
      if k == "text" or k == "tooltip" or k == "placeholder" then check(type(v) == "string", "ui." .. t .. "." .. k .. " must be a string, got " .. type(v)) end
      ::continue::
    end
    if children ~= nil then
      check(CONTAINERS[t], "ui." .. t .. " cannot take children")
      local seen = {}
      for _, c in ipairs(children) do
        check(type(c) == "table" and c.type, "ui." .. t .. " child is not a node")
        local key = c.props and c.props.key
        if key then
          check(not seen[key], "duplicate sibling key '" .. tostring(key) .. "'")
          seen[key] = true
        end
      end
    end
    return { type = t, props = props, children = children or {} }
  end
end

local function findAll(node, pred, out)
  out = out or {}
  if pred(node) then out[#out + 1] = node end
  for _, c in ipairs(node.children or {}) do findAll(c, pred, out) end
  return out
end
local function findKey(tree, key) return findAll(tree, function(n) return n.props.key == key end)[1] end
local function texts(tree)
  local out = {}
  for _, n in ipairs(findAll(tree, function(n) return n.props.text ~= nil end)) do out[#out + 1] = n.props.text end
  return table.concat(out, "\n")
end
local function buttonByGlyph(tree, glyph) return findAll(tree, function(n) return n.type == "button" and n.props.glyph == glyph end) end
local function buttonByText(tree, text) return findAll(tree, function(n) return n.type == "button" and n.props.text == text end)[1] end

-- --------------------------------------------------------------------------------------- host
local host = {
  state = {}, watchers = {}, pendingWatch = {}, panelsOpen = {}, toggles = {}, ipc = {}, notifications = {},
  terminal = {}, clipboard = nil, killed = {}, streams = {}, runtimes = {}, cpuMax = {}, logs = {},
}

local function timed(name, fn, ...)
  local t0 = os.clock()
  local ok, err = pcall(fn, ...)
  local dt = (os.clock() - t0) * 1000
  if dt > (host.cpuMax[name] or 0) then host.cpuMax[name] = dt end
  if not ok then fail(name .. ": " .. tostring(err)) end
  return dt
end

local function flushWatchers()
  local guard = 0
  while #host.pendingWatch > 0 and guard < 1000 do
    guard = guard + 1
    local job = table.remove(host.pendingWatch, 1)
    timed(job.owner .. ":watch(" .. job.key .. ")", job.fn, job.value)
  end
end

local dispatchIpc -- forward

local function makeNoctalia(owner, settings)
  local N = { json = { encode = json.encode, decode = json.decode }, string = {}, state = {} }
  function N.string.trim(s) return (tostring(s):gsub("^%s*(.-)%s*$", "%1")) end
  function N.tr(key, subst)
    local s = trLookup(key)
    check(s ~= nil, "missing translation key '" .. tostring(key) .. "'")
    s = s or key
    if subst then
      for k, v in pairs(subst) do
        check(type(v) == "string", "tr substitution {" .. k .. "} must be a string")
        s = s:gsub("{" .. k .. "}", function() return tostring(v) end)
      end
    end
    check(not s:find("{%a+}"), "unfilled placeholder in '" .. key .. "': " .. s)
    return s
  end
  function N.log(m) host.logs[#host.logs + 1] = owner .. ": " .. tostring(m) end
  function N.getConfig(k)
    check(settings[k] ~= nil, owner .. " read undeclared setting '" .. k .. "'")
    return settings[k]
  end
  function N.getenv(k) return ENV[k] or os.getenv(k) end
  function N.expandPath(p) return (p:gsub("^~", os.getenv("HOME"))) end
  function N.mkdirAll(p) os.execute("mkdir -p " .. shq(p)); return true end
  function N.writeFile(p, c) local f = io.open(p, "w"); if not f then return false, "cannot write" end; f:write(c); f:close(); return true end
  function N.readFile(p) return readFile(p) end
  function N.pluginDataDir() local d = TMP .. "/plugindata"; os.execute("mkdir -p " .. shq(d)); return d end
  local ms = 0
  function N.nowMs() ms = ms + 1; return os.time() * 1000 + ms end
  function N.setUpdateInterval(i) host.runtimes[owner].interval = i end
  function N.notify(t, b) host.notifications[#host.notifications + 1] = { title = t, body = b } end
  function N.notifyError(t, b) host.notifications[#host.notifications + 1] = { title = t, body = b, error = true } end
  function N.copyToClipboard(t, mime) check(mime == "text/plain", "clipboard mime"); host.clipboard = t; return true end
  function N.runInTerminal(cmd) host.terminal[#host.terminal + 1] = cmd; return true end
  function N.togglePanel(id) host.toggles[#host.toggles + 1] = id end
  function N.openSettings() host.openedSettings = true end
  function N.state.set(k, v)
    local copy = json.decode(json.encode(v))     -- values cross entries as JSON
    host.state[k] = copy
    for _, w in ipairs(host.watchers[k] or {}) do
      host.pendingWatch[#host.pendingWatch + 1] = { owner = w.owner, key = k, fn = w.fn, value = copy }
    end
  end
  function N.state.get(k) local v = host.state[k]; if type(v) == "table" then return json.decode(json.encode(v)) end; return v end
  function N.state.watch(k, fn)
    host.watchers[k] = host.watchers[k] or {}
    table.insert(host.watchers[k], { owner = owner, fn = fn })
  end
  function N.runAsync(argv, cb, timeoutMs)
    check(type(argv) == "table", owner .. " runAsync should use the argv form")
    if argv[1] == "noctalia" and argv[2] == "msg" and argv[3] == "plugin" then
      check(argv[4] == "dadmin/assistant:brain" and argv[5] == "all", "ipc target " .. tostring(argv[4]) .. " " .. tostring(argv[5]))
      host.ipc[#host.ipc + 1] = { event = argv[6], payload = argv[7] }
      dispatchIpc(argv[6], argv[7])
      return true
    end
    if argv[1] == "kill" then host.killed[#host.killed + 1] = argv[3]; if cb then cb({ exitCode = 0, stdout = "", stderr = "" }) end; return true end
    local parts = {}
    for i, a in ipairs(argv) do parts[i] = shq(a) end
    local out, err, code = sh(envPrefix() .. table.concat(parts, " "))
    if cb then timed(owner .. ":runAsync(" .. tostring(argv[2]) .. ")", cb, { exitCode = code, stdout = out, stderr = err, timedOut = false }) end
    return true
  end
  function N.runStream(cmd, onLine)
    host.streams[#host.streams + 1] = { owner = owner, cmd = cmd, onLine = onLine }
    return true
  end
  return N
end

local BASE = { pairs = pairs, ipairs = ipairs, type = type, tostring = tostring, tonumber = tonumber, string = string,
  table = table, math = math, os = { time = os.time, date = os.date, clock = os.clock }, pcall = pcall, error = error,
  select = select, next = next, setmetatable = setmetatable, getmetatable = getmetatable, rawget = rawget, unpack = table.unpack }

local function loadEntry(owner, file, extra, settings)
  local rt = { owner = owner, env = nil, interval = 1000, cache = {} }
  host.runtimes[owner] = rt
  local noct = makeNoctalia(owner, settings)
  local sandbox = setmetatable({ noctalia = noct, ui = ui }, { __index = BASE })
  for k, v in pairs(extra or {}) do sandbox[k] = v end
  local function makeRequire(dir)
    return function(rel)
      check(type(rel) == "string" and rel:match("^%.%.?/") and rel:match("%.luau$"), "require path must be relative .luau: " .. tostring(rel))
      local path = dir .. "/" .. rel:gsub("^%./", "")
      path = path:gsub("/[^/]+/%.%./", "/")
      if rt.cache[path] then return rt.cache[path] end
      local modEnv = setmetatable({}, { __index = sandbox })
      modEnv.require = makeRequire(path:match("^(.*)/[^/]+$"))
      local chunk, err = loadfile(path, "t", modEnv)
      if not chunk then error(err) end
      local val = chunk()
      check(val ~= nil, "module returned nil: " .. path)
      rt.cache[path] = val
      return val
    end
  end
  local env = setmetatable({}, { __index = sandbox })
  env.require = makeRequire(PLUGIN)
  rt.env = env
  local chunk, err = loadfile(PLUGIN .. "/" .. file, "t", env)
  if not check(chunk ~= nil, "load " .. file .. ": " .. tostring(err)) then return rt end
  timed(owner .. ":load", chunk)
  return rt
end

local function call(rt, fname, ...)
  local fn = rawget(rt.env, fname)
  if fn then return timed(rt.owner .. ":" .. fname, fn, ...) end
  return 0
end

-- ---------------------------------------------------------------------------------- scenario
os.execute("rm -rf " .. shq(TMP) .. " && mkdir -p " .. shq(TMP .. "/config") .. " " .. shq(TMP .. "/state") .. " " .. shq(TMP .. "/run"))
local cfgf = io.open(TMP .. "/config/config.toml", "w")
cfgf:write('[llm]\nbase_url = "http://127.0.0.1:9"\nmodel = "qwen3.6"\nfallback_models = ["qwen3.6", "qwen3.8"]\n')
cfgf:close()

local SETTINGS = { show_thinking = true, notify_when_closed = true, backend = BACKEND }

local panelState = { chat = {}, pinned = {} }
local function makePanelApi(name)
  local api = {}
  function api.render(tree)
    check(type(tree) == "table" and tree.type, name .. " render without a tree")
    panelState[name].tree = tree
    panelState[name].renders = (panelState[name].renders or 0) + 1
  end
  function api.close() panelState[name].closeRequested = true end
  function api.setWantsSecondTicks(b) panelState[name].ticks = b end
  function api.setNeedsFrameTick() end
  return api
end

local barState = {}
local barWidget = {
  setGlyph = function(g) check(GLYPHS[g] ~= nil, "bar glyph " .. g); barState.glyph = g end,
  setGlyphColor = function(c) check(validColor(c), "bar color " .. c); barState.color = c end,
  setTooltip = function(t) barState.tooltip = t end,
  setText = function(t) barState.text = t end,
}
local launcherState = {}
local launcher = { setResults = function(q, r) launcherState.query = q; launcherState.results = r end, setQuery = function() end }

print("== loading entries")
local service = loadEntry("service", "service.luau", {}, SETTINGS)
local chat = loadEntry("chat", "chat.luau", { panel = makePanelApi("chat") }, SETTINGS)
local pinnedRt = loadEntry("pinned", "pinned.luau", { panel = makePanelApi("pinned") }, SETTINGS)
local widget = loadEntry("widget", "widget.luau", { barWidget = barWidget }, SETTINGS)
local launch = loadEntry("launcher", "launcher.luau", { launcher = launcher }, SETTINGS)

dispatchIpc = function(event, payload)
  call(service, "onIpc", event, payload)
end
flushWatchers()

local function tick(n)
  for _ = 1, (n or 1) do
    call(service, "update")
    flushWatchers()
    call(chat, "update")
    call(pinnedRt, "update")
    flushWatchers()
  end
end

local function pumpStream(opts)
  opts = opts or {}
  local s = table.remove(host.streams, 1)
  if not check(s ~= nil, "expected a runStream") then return end
  check(s.cmd:find("turn %-%-request") and s.cmd:find("printf"), "stream command shape: " .. s.cmd)
  local p = io.popen(envPrefix() .. "sh -c " .. shq(s.cmd))
  local n = 0
  for line in p:lines() do
    n = n + 1
    timed("service:onLine", s.onLine, line)
    if opts.onLine then opts.onLine(n, line) end
    if n % 5 == 0 then tick() end
  end
  p:close()
  tick()
  return n
end

local info = host.state["assistant.info"]
check(info and info.ready and info.apiKey == false, "service published info with no key")
check(info and info.models and #info.models == 2, "fallback models published")
check(host.runtimes.service.interval == 2000, "idle update interval")

print("== open chat panel (welcome + connection card)")
call(chat, "onOpen", "")
flushWatchers()
local tree = panelState.chat.tree
check(tree ~= nil, "chat rendered on open")
check(host.state["assistant.open.chat"] == true, "open flag set")
check(findKey(tree, "welcome") ~= nil, "welcome shown for empty chat")
check(findKey(tree, "connectcard") ~= nil, "connection card shown when the server can't be reached")
check(texts(tree):find("What are my keyboard shortcuts", 1, true), "suggestions shown")
local dotTip = findAll(tree, function(n) return n.type == "row" and n.props.tooltip == trLookup("header.no_connection") end)[1]
check(dotTip ~= nil, "header shows the not-connected state")

print("== set server address + API key from the panel")
local serverInput = findAll(tree, function(n) return n.type == "input" and n.props.key and n.props.key:find("^server") end)[1]
check(serverInput and serverInput.props.value == "http://127.0.0.1:9", "server field prefilled with the current address")
timed("chat:onChange(server)", serverInput.props.onChange, "http://127.0.0.1:9/alt")
local keyInput = findAll(tree, function(n) return n.type == "input" and n.props.password end)[1]
check(keyInput ~= nil, "password input exists")
timed("chat:onChange(key)", keyInput.props.onChange, "sk-test-123")
local saveBtn = buttonByText(tree, trLookup("connect.save"))
timed("chat:click(save connection)", saveBtn.props.onClick)
flushWatchers(); tick()
local cfgText = readFile(TMP .. "/config/config.toml") or ""
check(cfgText:find('base_url = "http://127.0.0.1:9/alt"', 1, true), "server address written to config.toml")
check(cfgText:find('fallback_models', 1, true), "other config lines kept")
check(host.state["assistant.info"].baseUrl == "http://127.0.0.1:9/alt", "info shows the new address")
local secrets = readFile(TMP .. "/config/secrets.toml") or ""
check(secrets:find('api_key = "sk-test-123"', 1, true), "secrets.toml written")
local mode = io.popen("stat -c %a " .. shq(TMP .. "/config/secrets.toml")):read("l")
check(mode == "600", "secrets.toml mode 600, got " .. tostring(mode))
local leftovers = io.popen("ls " .. shq(TMP .. "/run")):read("a")
check(not leftovers:find("key%-"), "key temp file removed")
check(host.state["assistant.info"].apiKey == true, "info.apiKey true after save")
check(findKey(panelState.chat.tree, "connectcard") ~= nil, "card stays while the server is still unreachable")
check(texts(panelState.chat.tree):find("cannot reach", 1, true), "card explains why it is not connected")

print("== send a message via the composer (no server reachable -> clean error)")
tree = panelState.chat.tree
local composer = findAll(tree, function(n) return n.type == "input" and n.props.multiline end)[1]
check(composer and composer.props.submitOnEnter and composer.props.focus, "composer is a focused chat input")
timed("chat:onSubmit", composer.props.onSubmit, "  hello there  ")
check(host.ipc[#host.ipc].event == "send" and host.ipc[#host.ipc].payload == "hello there", "send dispatched trimmed")
flushWatchers()
check(findKey(panelState.chat.tree, "live") ~= nil, "live bubble while waiting")
pumpStream()
local conv = host.state["assistant.conv"]
check(conv and #conv.messages == 2, "user + assistant error message stored, got " .. tostring(conv and #conv.messages))
check(conv.messages[2] and conv.messages[2].error ~= nil, "unreachable server surfaces an error")
check(host.state["assistant.live"].busy == false, "not busy after turn")
check(texts(panelState.chat.tree):find("cannot reach", 1, true), "error text rendered")
check(buttonByText(panelState.chat.tree, trLookup("connect.fix")) == nil, "an unreachable server is not mistaken for a key problem")

print("== demo turn: streaming render, tools, thinking, code blocks")
local rendersBefore = panelState.chat.renders
dispatchIpc("demo", "")
flushWatchers()
local sawStreaming = false
pumpStream({ onLine = function(n)
  local live = host.state["assistant.live"]
  if live and live.busy and live.content ~= "" and findKey(panelState.chat.tree, "live") then sawStreaming = true end
end })
check(sawStreaming, "panel rendered partial answers while streaming")
check(panelState.chat.renders - rendersBefore > 5, "several renders during the stream")
conv = host.state["assistant.conv"]
local last = conv.messages[#conv.messages]
check(last.role == "assistant" and last.content:find("pacman", 1, true), "demo answer stored")
check(last.tools and #last.tools == 1 and last.tools[1].summary == "pacman -Q paru flatpak", "tool chip data kept")
check(last.reasoning and #last.reasoning > 10, "reasoning kept for display")
tree = panelState.chat.tree
local runButtons = buttonByGlyph(tree, "terminal-2")
check(#runButtons == 2, "two runnable bash blocks, got " .. #runButtons)
check(texts(tree):find("Thought", 1, true), "collapsed thinking row")
check(#host.notifications == 0, "no notification while the panel is open")

print("== copy + run a code block")
local copyBtn = findAll(tree, function(n) return n.type == "button" and n.props.glyph == "copy" and n.props.tooltip == trLookup("code.copy") end)[1]
timed("chat:click(copy)", copyBtn.props.onClick)
check(host.clipboard == "sudo pacman -S paru\nparu -S spotify", "copied code: " .. tostring(host.clipboard))
check(#buttonByGlyph(panelState.chat.tree, "check") >= 1, "copy shows a check")
timed("chat:click(run)", runButtons[1].props.onClick)
local termCmd = host.terminal[#host.terminal]
check(termCmd and termCmd:find(" run ", 1, true), "terminal command uses the confirm runner")
local runFile = termCmd and termCmd:match("run '([^']+)'$")
check(runFile and readFile(runFile) == "sudo pacman -S paru\nparu -S spotify\n", "command file content")
check(panelState.chat.closeRequested == true, "transient panel closes for the terminal")
panelState.chat.closeRequested = nil
os.remove(runFile or "")

print("== expand thinking")
local thinkRow = findAll(panelState.chat.tree, function(n) return n.type == "row" and type(n.props.onClick) == "function" and n.children[2] and n.children[2].props.text and n.children[2].props.text:find("Thought") end)[1]
timed("chat:click(thinking)", thinkRow.props.onClick)
check(texts(panelState.chat.tree):find("Check which helpers exist first", 1, true), "reasoning expanded")

print("== notification when closed")
call(chat, "onClose")
check(host.state["assistant.open.chat"] == false, "open flag cleared")
dispatchIpc("send", "second question")
pumpStream()
check(#host.notifications == 1 and host.notifications[1].error == true, "error notification while closed")

print("== history view: open + delete")
call(chat, "onOpen", "")
flushWatchers()
local histBtn = buttonByGlyph(panelState.chat.tree, "history")[1]
timed("chat:click(history)", histBtn.props.onClick)
tree = panelState.chat.tree
check(findKey(tree, "history") ~= nil, "history list shown")
local items = host.state["assistant.history"].items
check(#items >= 1, "history has items")
local firstId = string.format("%d", items[1].id)
local row = findKey(tree, "h" .. firstId)
timed("chat:click(history item)", row.props.onClick)
flushWatchers(); tick()
check(host.state["assistant.conv"].id == items[1].id, "conversation loaded from history")
timed("chat:click(history)", buttonByGlyph(panelState.chat.tree, "history")[1].props.onClick)
local trash = findAll(findKey(panelState.chat.tree, "h" .. firstId), function(n) return n.type == "button" and n.props.glyph == "trash" end)[1]
timed("chat:click(trash)", trash.props.onClick)
local confirm = buttonByText(panelState.chat.tree, trLookup("common.delete"))
check(confirm ~= nil, "delete asks for confirmation")
timed("chat:click(confirm delete)", confirm.props.onClick)
flushWatchers(); tick()
local still = false
for _, h in ipairs(host.state["assistant.history"].items) do if h.id == items[1].id then still = true end end
check(not still, "conversation deleted")

print("== models view: pick a model")
local modelRow = findAll(panelState.chat.tree, function(n) return n.type == "row" and n.props.tooltip ~= nil and type(n.props.onClick) == "function" end)[1]
timed("chat:click(model)", modelRow.props.onClick)
local pick = buttonByText(panelState.chat.tree, "qwen3.8")
check(pick ~= nil, "model list rendered")
timed("chat:click(qwen3.8)", pick.props.onClick)
flushWatchers()
check(host.state["assistant.info"].model == "qwen3.8", "model switched")
local state = json.decode(readFile(TMP .. "/state/state.json") or "{}")
check(state and state.model == "qwen3.8", "model persisted by backend")

print("== new chat, pin, unpin")
timed("chat:click(new)", buttonByGlyph(panelState.chat.tree, "message-plus")[1].props.onClick)
flushWatchers()
check(#host.state["assistant.conv"].messages == 0 and findKey(panelState.chat.tree, "welcome"), "new chat is empty")
local draftInput = findAll(panelState.chat.tree, function(n) return n.type == "input" and n.props.multiline end)[1]
timed("chat:onChange(draft)", draftInput.props.onChange, "half-typed question")
timed("chat:click(pin)", buttonByGlyph(panelState.chat.tree, "pin")[1].props.onClick)
check(host.toggles[#host.toggles] == "dadmin/assistant:pinned" and panelState.chat.closeRequested, "pin opens the persistent panel and closes the sheet")
call(chat, "onClose")
call(pinnedRt, "onOpen", "")
flushWatchers()
local pinnedComposer = findAll(panelState.pinned.tree, function(n) return n.type == "input" and n.props.multiline end)[1]
check(pinnedComposer.props.value == "half-typed question", "draft carried over to the pinned panel")
check(#buttonByGlyph(panelState.pinned.tree, "pinned-off") == 1, "pinned panel offers unpin")

print("== widget and toggle routing")
call(widget, "update")
check(barState.glyph == "sparkles" and barState.color == "on_surface", "idle bar glyph")
call(widget, "onClick")
check(host.toggles[#host.toggles] == "dadmin/assistant:pinned", "bar click toggles the pinned panel when it is open")
dispatchIpc("toggle")
check(host.toggles[#host.toggles] == "dadmin/assistant:pinned", "hotkey toggle closes the pinned panel")
call(pinnedRt, "onClose")
dispatchIpc("toggle")
check(host.toggles[#host.toggles] == "dadmin/assistant:chat", "hotkey toggle opens the chat sheet")

print("== cancel a running turn")
dispatchIpc("demo", "")
local s = table.remove(host.streams, 1)
s.onLine('{"type":"turn_start","conversation_id":99,"model":"qwen3.8","pid":4242,"title":"x"}')
s.onLine('{"type":"delta","text":"partial "}')
tick()
call(widget, "update")
check(barState.color == "primary", "bar glyph lights up while busy")
dispatchIpc("cancel")
check(host.killed[#host.killed] == "4242", "cancel sends SIGTERM to the backend pid")
s.onLine('{"type":"turn_end","conversation_id":99,"cancelled":true,"error":null,"need_key":false}')
tick()
last = host.state["assistant.conv"].messages[#host.state["assistant.conv"].messages]
check(last.cancelled == true and last.content == "partial ", "partial answer kept and marked stopped")
check(host.state["assistant.live"].busy == false, "not busy after cancel")
call(chat, "onOpen", "")
flushWatchers()
check(texts(panelState.chat.tree):find(trLookup("msg.stopped"), 1, true), "stopped answer is labelled in the panel")
call(chat, "onClose")

print("== backend crash without turn_end")
dispatchIpc("demo", "")
s = table.remove(host.streams, 1)
s.onLine('{"type":"turn_start","conversation_id":100,"model":"qwen3.8","pid":4343,"title":"x"}')
s.onLine('{"type":"exit","code":1}')
tick()
check(host.state["assistant.live"].busy == false, "exit line ends a turn that never reported turn_end")

print("== launcher")
call(launch, "onQuery", "")
check(launcherState.results and launcherState.results[1].id == "open", "empty query offers to open")
call(launch, "onQuery", "how do I change my wallpaper")
check(launcherState.results[1].id == "ask:how do I change my wallpaper", "query becomes an ask result")
local togglesBefore = #host.toggles
call(launch, "onActivate", launcherState.results[1].id)
check(host.ipc[#host.ipc].event == "ask", "activate dispatches ask")
check(#host.toggles == togglesBefore + 1 and host.toggles[#host.toggles] == "dadmin/assistant:chat", "ask opens the chat panel")
check(#host.streams == 1, "ask started a turn")
host.streams = {}

-- ------------------------------------------------------------------------------------ report
print("\n== CPU time per callback (Lua 5.5; Noctalia budget is 25 ms in Luau)")
local rows = {}
for name, ms in pairs(host.cpuMax) do
  if not name:find("runAsync") then rows[#rows + 1] = { name, ms } end
end
table.sort(rows, function(a, b) return a[2] > b[2] end)
for i = 1, math.min(8, #rows) do print(string.format("  %-40s %6.2f ms", rows[i][1], rows[i][2])) end
for _, r in ipairs(rows) do check(r[2] < 25, "callback over budget: " .. r[1] .. string.format(" %.1f ms", r[2])) end
if #host.logs > 0 then print("\nplugin log:"); for _, l in ipairs(host.logs) do print("  " .. l) end end
print(string.format("\n%d checks, %d failures", checks, #failures))
os.exit(#failures == 0 and 0 or 1)
