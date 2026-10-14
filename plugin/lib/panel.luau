-- Chat panel UI, shared by the "chat" (closes on outside click) and "pinned" (persistent) panel entries.
-- Pure view: it renders what the brain service publishes in noctalia.state and sends user actions back
-- to the service over plugin IPC. Colors use Noctalia's 16 palette roles so the panel follows the theme.

local C = require("./common.luau")
local K = C.KEYS
local tr = C.tr

local P = {}

local WRAP = 448            -- text width inside the 520 px panel (padding + scrollbar)
local PAD = 16

local panelApi = nil
local pinned = false
local isOpen = false
local view = "chat"         -- chat | history | models | key
local draft = ""
local composerSeq = 0
local scrollRev = 0
local stick = true
local dots = 0
local expanded = {}         -- message key -> thinking expanded
local copied = nil          -- key of the last Copy button pressed (shows a check for 2 s)
local copiedAt = 0
local confirmDelete = nil
local keyDraft = ""
local serverDraft = ""
local keySeq = 0
local pendingUser = nil     -- optimistic bubble until the service picks the message up
local lastFp = ""
local segCache = {}
local segCacheSize = 0

local render  -- forward declarations
local saveConnection

local function get(key)
  local v = noctalia.state.get(key)
  if type(v) == "table" then
    return v
  end
  return nil
end

-- True when the assistant cannot talk to a model server yet (wrong address, server down, key missing or rejected).
local function needsConnection(info)
  return info ~= nil and info.ready and info.backendError == nil and info.modelsError ~= nil
end

local function fingerprint()
  local info, conv, live, hist = get(K.info), get(K.conv), get(K.live), get(K.history)
  return table.concat({
    tostring(info and info.rev or -1), tostring(conv and conv.rev or -1),
    tostring(live and live.rev or -1), tostring(hist and hist.rev or -1),
  }, ":")
end

local function segments(text)
  local hit = segCache[text]
  if hit then
    return hit
  end
  if segCacheSize > 300 then
    segCache = {}
    segCacheSize = 0
  end
  local s = C.splitMarkdown(text)
  segCache[text] = s
  segCacheSize = segCacheSize + 1
  return s
end

-- ------------------------------------------------------------------------------------- actions
local function setView(v)
  view = v
  confirmDelete = nil
  if v == "chat" then
    scrollRev = scrollRev + 1
    stick = true
  end
  render()
end

local function send(text)
  text = C.trim(text or draft)
  local live = get(K.live)
  if text == "" or (live and live.busy) or pendingUser then
    return
  end
  C.dispatch("send", text)
  pendingUser = text
  draft = ""
  composerSeq = composerSeq + 1  -- a fresh key gives a cleared, focused input
  view = "chat"
  stick = true
  scrollRev = scrollRev + 1
  render()
end

local function newChat()
  C.dispatch("new")
  pendingUser = nil
  expanded = {}
  setView("chat")
end

local function copyText(text, key)
  noctalia.copyToClipboard(text, "text/plain")
  copied = key
  copiedAt = os.time()
  render()
end

local function runInTerminal(code)
  local cmd = C.runnable(code)
  if cmd == "" then
    return
  end
  local path = C.runtimeDir() .. "/run-" .. string.format("%d", noctalia.nowMs()) .. ".sh"
  if noctalia.writeFile(path, cmd .. "\n") then
    noctalia.runInTerminal(C.shq(C.backend()) .. " run " .. C.shq(path))
    if not pinned then
      panelApi.close()  -- get out of the way of the terminal; the pinned panel stays
    end
  end
end

saveConnection = function()
  local url = C.trim(serverDraft)
  local k = C.trim(keyDraft)
  keyDraft = ""
  serverDraft = ""
  keySeq = keySeq + 1  -- recreate both fields (the key field empty)
  if url ~= "" then
    C.dispatch("set_server", url)
  end
  if k ~= "" then
    -- The key goes through a file in $XDG_RUNTIME_DIR (mode 700), never through a command line.
    local path = C.runtimeDir() .. "/key-" .. string.format("%d", noctalia.nowMs()) .. ".txt"
    if noctalia.writeFile(path, k) then
      C.dispatch("set_key", path)
    end
  end
  render()
end

local function togglePin()
  noctalia.state.set(K.draft, draft)
  if pinned then
    panelApi.close()
    noctalia.togglePanel(C.PANEL_CHAT)
  else
    noctalia.togglePanel(C.PANEL_PINNED)
    panelApi.close()
  end
end

-- ---------------------------------------------------------------------------------- components
local function iconButton(glyph, tooltip, onClick, selected)
  return ui.button({
    glyph = glyph, variant = "ghost", controlSize = "sm", tooltip = tooltip,
    selected = selected == true, onClick = onClick,
  })
end

local function header(info, live)
  local model = (info and info.model ~= nil and info.model ~= "") and info.model or tr("header.no_model")
  local dot = "primary"
  local tip = tr("header.model_tip")
  if info and info.backendError then
    dot, tip = "error", info.backendError
  elseif needsConnection(info) then
    dot, tip = "error", tr("header.no_connection")
  elseif live and live.busy then
    dot = "tertiary"
  end
  return ui.row({ key = "header", gap = 10, align = "center" }, {
    ui.column({ width = 36, height = 36, radius = 12, fill = "primary/0.18", align = "center", justify = "center" }, {
      ui.glyph({ name = "sparkles", size = 20, color = "primary" }),
    }),
    ui.column({ gap = 2, flexGrow = 1, align = "start" }, {
      ui.label({ text = tr("title"), fontSize = 15, fontWeight = "semibold" }),
      ui.row({ gap = 6, align = "center", tooltip = tip, onClick = function() setView("models") end }, {
        ui.box({ width = 8, height = 8, radius = 4, fill = dot }),
        ui.label({ text = model, fontSize = 11, color = "on_surface_variant", maxWidth = 200, maxLines = 1 }),
        ui.glyph({ name = "chevron-down", size = 12, color = "on_surface_variant" }),
      }),
    }),
    iconButton("message-plus", tr("header.new"), newChat),
    iconButton("history", tr("header.history"), function()
      setView(view == "history" and "chat" or "history")
    end, view == "history"),
    iconButton(pinned and "pinned-off" or "pin", pinned and tr("header.unpin") or tr("header.pin"), togglePin),
    iconButton("x", tr("header.close"), function() panelApi.close() end),
  })
end

local function userBubble(m, key)
  return ui.row({ key = key, align = "start" }, {
    ui.spacer({ flexGrow = 1 }),
    ui.column({ fill = "primary/0.18", radius = 14, paddingH = 12, paddingV = 8 }, {
      ui.label({ text = m.content or "", maxWidth = WRAP - 70, maxLines = 0 }),
    }),
  })
end

local function toolChip(t, key)
  local failed = t.ok == false
  local glyph = C.toolGlyph(t.name)
  if t.pending == true then
    glyph = "loader-2"
  elseif failed then
    glyph = "alert-circle"
  end
  local text = (t.summary ~= nil and t.summary ~= "") and t.summary or (t.name or "")
  local kind = C.TOOL_GLYPHS[t.name or ""] and t.name or "other"
  return ui.row({
    key = key, gap = 6, align = "center", paddingH = 8, paddingV = 4, radius = 8,
    fill = "secondary/0.14", tooltip = tr("tool." .. kind) .. ": " .. text,
  }, {
    ui.glyph({ name = glyph, size = 13, color = failed and "error" or "secondary" }),
    ui.label({ text = text, fontSize = 11, color = "on_surface_variant", maxWidth = WRAP - 50, maxLines = 1 }),
  })
end

local function thinkingBlock(m, key, streaming)
  if noctalia.getConfig("show_thinking") == false then
    return nil
  end
  local text = m.reasoning or ""
  if text == "" then
    return nil
  end
  local open = expanded[key] == true
  local label
  if streaming and C.trim(m.content or "") == "" then
    label = tr("msg.thinking_now")
  else
    label = tr("msg.thought", { n = C.idString(math.floor(#text / 4)) })
  end
  local kids = {
    ui.row({ gap = 6, align = "center", onClick = function()
      expanded[key] = not open
      render()
    end }, {
      ui.glyph({ name = "brain", size = 13, color = "tertiary" }),
      ui.label({ text = label, fontSize = 11, color = "tertiary" }),
      ui.glyph({ name = open and "chevron-up" or "chevron-down", size = 12, color = "tertiary" }),
    }),
  }
  if open then
    kids[#kids + 1] = ui.label({ text = text, fontSize = 12, opacity = 0.75, maxWidth = WRAP, maxLines = 0 })
  end
  return ui.column({ key = key .. ":think", gap = 6, align = "start" }, kids)
end

local function codeBlock(seg, key)
  local bar = {
    ui.label({ text = seg.lang ~= "" and seg.lang or tr("code.code"), fontSize = 11, opacity = 0.65, flexGrow = 1 }),
    ui.button({
      glyph = copied == key and "check" or "copy", variant = "ghost", controlSize = "sm", tooltip = tr("code.copy"),
      onClick = function() copyText(seg.text, key) end,
    }),
  }
  if C.isShell(seg.lang) then
    bar[#bar + 1] = ui.button({
      glyph = "terminal-2", variant = "ghost", controlSize = "sm", tooltip = tr("code.run"),
      onClick = function() runInTerminal(seg.text) end,
    })
  end
  local code = string.gsub(seg.text, "%s+$", "")
  return ui.column({ key = key, gap = 2, paddingH = 10, paddingV = 6, radius = 10, fill = "surface_variant/0.55", border = "outline/0.35", borderWidth = 1 }, {
    ui.row({ gap = 2, align = "center" }, bar),
    ui.label({ text = code, fontFamily = "monospace", fontSize = 12, maxWidth = WRAP - 24, maxLines = 0 }),
  })
end

local function assistantMessage(m, key, streaming)
  local cells = {}
  local tools = m.tools
  if type(tools) == "table" and #tools > 0 then
    local chips = {}
    for i, t in ipairs(tools) do
      chips[#chips + 1] = toolChip(t, key .. ":t" .. i)
    end
    cells[#cells + 1] = ui.column({ key = key .. ":tools", gap = 4, align = "start" }, chips)
  end
  local think = thinkingBlock(m, key, streaming)
  if think then
    cells[#cells + 1] = think
  end
  local content = m.content or ""
  if content ~= "" then
    local segs = streaming and C.splitMarkdown(content) or segments(content)
    for i, seg in ipairs(segs) do
      local sk = key .. ":s" .. i
      if seg.kind == "code" then
        cells[#cells + 1] = codeBlock(seg, sk)
      else
        cells[#cells + 1] = ui.markdown({ key = sk, text = seg.text, width = WRAP })
      end
    end
  end
  if streaming and (content == "" or (m.status ~= nil and m.status ~= "")) then
    local status = (m.status ~= nil and m.status ~= "") and m.status or tr("status.thinking")
    cells[#cells + 1] = ui.row({ key = key .. ":wait", gap = 8, align = "center" }, {
      ui.glyph({ name = "loader-2", size = 14, color = "primary" }),
      ui.label({ text = status .. string.rep(".", dots), fontSize = 12, opacity = 0.8 }),
    })
  end
  if m.error ~= nil and m.error ~= "" then
    cells[#cells + 1] = ui.row({ key = key .. ":err", gap = 6, align = "start", paddingH = 10, paddingV = 8, radius = 10, fill = "error/0.12" }, {
      ui.glyph({ name = "alert-circle", size = 14, color = "error" }),
      ui.label({ text = tostring(m.error), fontSize = 12, maxWidth = WRAP - 40, maxLines = 0 }),
    })
  end
  if not streaming then
    local foot = {}
    if m.cancelled then
      foot[#foot + 1] = ui.label({ text = tr("msg.stopped"), fontSize = 11, opacity = 0.6 })
    end
    foot[#foot + 1] = ui.spacer({ flexGrow = 1 })
    if m.needKey then
      foot[#foot + 1] = ui.button({ text = tr("connect.fix"), glyph = "plug-connected", variant = "primary", controlSize = "sm", onClick = function() setView("key") end })
    elseif m.needModel then
      foot[#foot + 1] = ui.button({ text = tr("models.choose"), glyph = "robot", variant = "primary", controlSize = "sm", onClick = function() setView("models") end })
    end
    if C.trim(content) ~= "" then
      foot[#foot + 1] = ui.button({
        glyph = copied == key and "check" or "copy", variant = "ghost", controlSize = "sm", tooltip = tr("msg.copy"),
        onClick = function() copyText(content, key) end,
      })
    end
    cells[#cells + 1] = ui.row({ key = key .. ":foot", gap = 6, align = "center" }, foot)
  end
  return ui.column({ key = key, gap = 8 }, cells)
end

local function connectCard(info, autofocus)
  local problem = info and info.modelsError
  local kids = {
    ui.row({ gap = 8, align = "center" }, {
      ui.glyph({ name = "plug-connected", size = 16, color = "primary" }),
      ui.label({ text = tr("connect.title"), fontWeight = "semibold" }),
    }),
    ui.label({ text = tr("connect.body"), fontSize = 12, opacity = 0.8, maxWidth = WRAP - 30, maxLines = 0 }),
  }
  if problem then
    kids[#kids + 1] = ui.row({ gap = 6, align = "start" }, {
      ui.glyph({ name = "alert-circle", size = 14, color = "error" }),
      ui.label({ text = tostring(problem), fontSize = 11.5, maxWidth = WRAP - 50, maxLines = 0 }),
    })
  end
  kids[#kids + 1] = ui.label({ text = tr("connect.server"), fontSize = 12, fontWeight = "medium" })
  kids[#kids + 1] = ui.input({
    key = "server" .. keySeq, value = (info and info.baseUrl) or "", placeholder = "http://localhost:4000",
    focus = autofocus, onChange = function(v) serverDraft = v end,
    onSubmit = function(v)
      serverDraft = v
      saveConnection()
    end,
  })
  kids[#kids + 1] = ui.label({ text = tr("connect.key"), fontSize = 12, fontWeight = "medium" })
  kids[#kids + 1] = ui.row({ gap = 8, align = "center" }, {
    ui.input({
      key = "apikey" .. keySeq, password = true, flexGrow = 1,
      placeholder = (info and info.apiKey) and tr("connect.key_saved") or tr("connect.key_placeholder"),
      onChange = function(v) keyDraft = v end,
      onSubmit = function(v)
        keyDraft = v
        saveConnection()
      end,
    }),
    ui.button({ text = tr("connect.save"), variant = "primary", onClick = function() saveConnection() end }),
  })
  local status = nil
  if info and (info.serverState == "saving" or info.keyState == "saving") then
    status = ui.label({ text = tr("connect.saving"), fontSize = 12, opacity = 0.8 })
  elseif info and info.serverState == "error" then
    status = ui.label({ text = tr("connect.server_error", { detail = info.serverError or "" }), fontSize = 12, color = "error", maxWidth = WRAP - 30, maxLines = 0 })
  elseif info and info.keyState == "error" then
    status = ui.label({ text = tr("connect.key_error", { detail = info.keyError or "" }), fontSize = 12, color = "error", maxWidth = WRAP - 30, maxLines = 0 })
  elseif info and (info.serverState == "saved" or info.keyState == "saved") and info.modelsSource == "endpoint" then
    status = ui.label({ text = tr("connect.connected", { n = C.idString(#(info.models or {})) }), fontSize = 12, color = "primary" })
  end
  if status then
    kids[#kids + 1] = status
  end
  kids[#kids + 1] = ui.label({ text = tr("connect.where"), fontSize = 11, opacity = 0.6, maxWidth = WRAP - 30, maxLines = 0 })
  return ui.column({ key = "connectcard", gap = 8, padding = 14, radius = 14, fill = "surface_variant/0.45", border = "outline/0.35", borderWidth = 1 }, kids)
end

local SUGGESTIONS = {
  { glyph = "keyboard", key = "suggest.shortcuts" },
  { glyph = "package", key = "suggest.install" },
  { glyph = "brand-windows", key = "suggest.windows" },
  { glyph = "palette", key = "suggest.lightmode" },
  { glyph = "layout-grid", key = "suggest.workspaces" },
  { glyph = "cpu", key = "suggest.nvidia" },
}

local function welcome(info)
  local kids = {
    ui.column({ key = "hero", gap = 10, align = "center" }, {
      ui.column({ width = 64, height = 64, radius = 22, fill = "primary/0.18", align = "center", justify = "center" }, {
        ui.glyph({ name = "sparkles", size = 32, color = "primary" }),
      }),
      ui.label({ text = tr("welcome.title"), fontSize = 17, fontWeight = "semibold", textAlign = "center" }),
      ui.label({ text = tr("welcome.body"), fontSize = 12.5, opacity = 0.75, maxWidth = WRAP - 20, maxLines = 0, textAlign = "center" }),
    }),
  }
  if needsConnection(info) then
    kids[#kids + 1] = connectCard(info, false)
  end
  local list = {}
  for i, s in ipairs(SUGGESTIONS) do
    local q = tr(s.key)
    list[#list + 1] = ui.button({
      key = "suggest" .. i, text = q, glyph = s.glyph, variant = "outline", contentAlign = "start",
      onClick = function() send(q) end,
    })
  end
  kids[#kids + 1] = ui.column({ key = "suggestions", gap = 8 }, list)
  return ui.column({ key = "welcome", gap = 22, paddingV = 20 }, kids)
end

local function banner(text)
  return ui.row({ key = "banner", gap = 8, align = "start", paddingH = 12, paddingV = 10, radius = 10, fill = "error/0.12" }, {
    ui.glyph({ name = "alert-circle", size = 16, color = "error" }),
    ui.label({ text = text, fontSize = 12, maxWidth = WRAP - 40, maxLines = 0 }),
  })
end

-- ---------------------------------------------------------------------------------------- views
local function chatView(info, conv, live, rows)
  local items = {}
  local msgs = (conv and conv.messages) or {}
  local offset = tonumber(conv and conv.hidden) or 0
  if offset > 0 then
    items[#items + 1] = ui.label({ key = "hidden", text = tr("msg.hidden", { n = C.idString(offset) }), fontSize = 11, opacity = 0.6, textAlign = "center" })
  end
  for i, m in ipairs(msgs) do
    local key = "m" .. C.idString(offset + i)
    if m.role == "user" then
      items[#items + 1] = userBubble(m, key)
    else
      items[#items + 1] = assistantMessage(m, key, false)
    end
  end
  local busy = live and live.busy
  if pendingUser and not busy then
    items[#items + 1] = userBubble({ content = pendingUser }, "pending")
    items[#items + 1] = assistantMessage({ content = "", status = tr("status.sending") }, "live", true)
  elseif busy then
    items[#items + 1] = assistantMessage(live, "live", true)
  end
  if info and info.backendError then
    rows[#rows + 1] = banner(info.backendError)
  end
  if #items == 0 then
    -- The welcome screen reads top-down: its own scroll node, never pinned to the bottom.
    rows[#rows + 1] = ui.scroll({ key = "welcome-scroll", flexGrow = 1 }, { welcome(info) })
  else
    rows[#rows + 1] = ui.scroll({
      key = "messages", flexGrow = 1, gap = 16, stickToBottom = stick, scrollToBottomRev = scrollRev,
      onScroll = function(offsetPx, maxPx)
        stick = (tonumber(offsetPx) or 0) >= (tonumber(maxPx) or 0) - 4
      end,
    }, items)
  end
  local composer = {
    ui.input({
      key = "composer" .. composerSeq, value = draft, placeholder = tr("composer.placeholder"),
      multiline = true, submitOnEnter = true, focus = true, flexGrow = 1, height = 64,
      onChange = function(t) draft = t end,
      onSubmit = function(t) send(t) end,
    }),
  }
  if busy then
    composer[#composer + 1] = ui.button({ glyph = "player-stop-filled", variant = "destructive", tooltip = tr("composer.stop"), onClick = function() C.dispatch("cancel") end })
  else
    composer[#composer + 1] = ui.button({ glyph = "send", variant = "primary", tooltip = tr("composer.send"), enabled = pendingUser == nil, onClick = function() send(draft) end })
  end
  rows[#rows + 1] = ui.row({ key = "composer-row", gap = 8, align = "end" }, composer)
  rows[#rows + 1] = ui.label({ key = "hint", text = tr("composer.hint"), fontSize = 10.5, opacity = 0.5, textAlign = "center" })
end

local function backRow(title, extra)
  local kids = {
    iconButton("arrow-left", tr("common.back"), function() setView("chat") end),
    ui.label({ text = title, fontWeight = "semibold", flexGrow = 1 }),
  }
  if extra then
    kids[#kids + 1] = extra
  end
  return ui.row({ key = "back", gap = 8, align = "center" }, kids)
end

local function historyView(conv, hist, rows)
  rows[#rows + 1] = backRow(tr("history.title"), ui.button({ text = tr("header.new"), glyph = "message-plus", variant = "outline", controlSize = "sm", onClick = newChat }))
  local items = (hist and hist.items) or {}
  local list = {}
  if #items == 0 then
    list[1] = ui.label({ text = tr("history.empty"), opacity = 0.7 })
  end
  for _, h in ipairs(items) do
    local id = h.id
    local idStr = C.idString(id)
    if confirmDelete == id then
      list[#list + 1] = ui.row({ key = "h" .. idStr, gap = 8, align = "center", padding = 10, radius = 10, fill = "error/0.14" }, {
        ui.label({ text = tr("history.confirm"), flexGrow = 1, maxLines = 1 }),
        ui.button({ text = tr("common.cancel"), variant = "ghost", controlSize = "sm", onClick = function()
          confirmDelete = nil
          render()
        end }),
        ui.button({ text = tr("common.delete"), variant = "destructive", controlSize = "sm", onClick = function()
          confirmDelete = nil
          C.dispatch("delete", idStr)
          render()
        end }),
      })
    else
      local current = conv ~= nil and conv.id == id
      local when = os.date("%b %d, %H:%M", math.floor(tonumber(h.updated) or 0))
      list[#list + 1] = ui.row({
        key = "h" .. idStr, gap = 8, align = "center", padding = 10, radius = 10,
        fill = current and "primary/0.14" or "surface_variant/0.35",
        onClick = function()
          C.dispatch("open", idStr)
          pendingUser = nil
          setView("chat")
        end,
      }, {
        ui.column({ gap = 2, flexGrow = 1 }, {
          ui.label({ text = (h.title ~= nil and h.title ~= "") and h.title or tr("history.untitled"), fontWeight = "medium", maxWidth = WRAP - 70, maxLines = 1 }),
          ui.label({ text = tr("history.meta", { n = C.idString(tonumber(h.count) or 0), when = when }), fontSize = 11, opacity = 0.6 }),
        }),
        iconButton("trash", tr("common.delete"), function()
          confirmDelete = id
          render()
        end),
      })
    end
  end
  rows[#rows + 1] = ui.scroll({ key = "history", flexGrow = 1, gap = 6 }, list)
end

local function modelsView(info, rows)
  rows[#rows + 1] = backRow(tr("models.title"), iconButton("refresh", tr("models.refresh"), function() C.dispatch("refresh") end))
  local list = {}
  local models = (info and info.models) or {}
  for i, m in ipairs(models) do
    local current = info and info.model == m
    list[#list + 1] = ui.button({
      key = "model" .. i, text = m, glyph = current and "check" or "robot", variant = current and "primary" or "outline",
      contentAlign = "start", onClick = function()
        C.dispatch("model", m)
        setView("chat")
      end,
    })
  end
  if #models == 0 then
    list[1] = ui.label({ text = tr("models.none"), opacity = 0.7 })
  end
  if info and info.modelsError then
    list[#list + 1] = ui.label({ text = tr("models.error", { detail = tostring(info.modelsError) }), fontSize = 11, opacity = 0.7, maxWidth = WRAP, maxLines = 0 })
  elseif info and info.modelsSource == "fallback" then
    list[#list + 1] = ui.label({ text = tr("models.fallback"), fontSize = 11, opacity = 0.7, maxWidth = WRAP, maxLines = 0 })
  end
  list[#list + 1] = ui.separator({ spacing = 8 })
  list[#list + 1] = ui.label({ text = tr("models.connection"), fontWeight = "semibold" })
  list[#list + 1] = ui.label({ text = tr("models.endpoint", { url = (info and info.baseUrl) or "" }), fontSize = 12, opacity = 0.8, maxWidth = WRAP, maxLines = 0 })
  list[#list + 1] = ui.row({ gap = 6, align = "center" }, {
    ui.glyph({ name = needsConnection(info) and "plug-connected-x" or "plug-connected", size = 14, color = needsConnection(info) and "error" or "primary" }),
    ui.label({ text = needsConnection(info) and tr("models.not_connected") or ((info and info.apiKey) and tr("models.key_ok") or tr("models.key_none")), fontSize = 12 }),
  })
  list[#list + 1] = ui.row({ gap = 8 }, {
    ui.button({ text = tr("connect.change"), glyph = "plug-connected", variant = "outline", controlSize = "sm", onClick = function() setView("key") end }),
    ui.button({ text = tr("models.settings"), glyph = "settings", variant = "ghost", controlSize = "sm", onClick = function() noctalia.openSettings() end }),
  })
  rows[#rows + 1] = ui.scroll({ key = "models", flexGrow = 1, gap = 8 }, list)
end

local function keyView(info, rows)
  rows[#rows + 1] = backRow(tr("connect.title"))
  rows[#rows + 1] = ui.scroll({ key = "keywrap", flexGrow = 1, gap = 12 }, { connectCard(info, true) })
end

render = function()
  if not isOpen or panelApi == nil then
    return
  end
  local info, conv, live, hist = get(K.info), get(K.conv), get(K.live), get(K.history)
  if pendingUser and live and live.busy then
    pendingUser = nil
  end
  lastFp = fingerprint()
  local rows = { header(info, live), ui.separator({}) }
  if view == "history" then
    historyView(conv, hist, rows)
  elseif view == "models" then
    modelsView(info, rows)
  elseif view == "key" then
    keyView(info, rows)
  else
    chatView(info, conv, live, rows)
  end
  panelApi.render(ui.column({ padding = PAD, gap = 12, flexGrow = 1 }, rows))
end

-- ---------------------------------------------------------------------------------- lifecycle
function P.setup(opts)
  panelApi = opts.panel
  pinned = opts.pinned == true
  local keys = { K.info, K.conv, K.live, K.history }
  for _, k in ipairs(keys) do
    noctalia.state.watch(k, function()
      if isOpen and fingerprint() ~= lastFp then
        render()
      end
    end)
  end
end

function P.onOpen(_context)
  isOpen = true
  noctalia.state.set(pinned and K.openPinned or K.openChat, true)
  local handoff = noctalia.state.get(K.draft)
  if type(handoff) == "string" and handoff ~= "" then
    draft = handoff
    noctalia.state.set(K.draft, "")
  end
  composerSeq = composerSeq + 1
  if view ~= "key" then
    view = "chat"
  end
  stick = true
  scrollRev = scrollRev + 1
  panelApi.setWantsSecondTicks(true)
  C.dispatch("opened")
  render()
end

function P.onClose()
  isOpen = false
  confirmDelete = nil
  noctalia.state.set(pinned and K.openPinned or K.openChat, false)
end

function P.update()
  if not isOpen then
    return
  end
  local live = get(K.live)
  local changed = false
  if (live and live.busy) or pendingUser then
    dots = (dots % 3) + 1
    changed = true
  end
  if copied ~= nil and os.time() - copiedAt >= 2 then
    copied = nil
    changed = true
  end
  if changed or fingerprint() ~= lastFp then
    render()
  end
end

return P
