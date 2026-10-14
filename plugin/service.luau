-- Assistant brain ([[service]] "brain"): owns the conversation and runs one backend process per message.
--
-- Panels, the bar button and the launcher talk to it with
--   noctalia msg plugin dadmin/assistant:brain all <event> [payload]
-- and read what it publishes in noctalia.state (see lib/common.luau KEYS).
-- Every callback must stay well under Noctalia's 25 ms CPU budget, so streamed lines only mark state dirty;
-- update() publishes at most every BUSY_INTERVAL ms.

local C = require("./lib/common.luau")
local K = C.KEYS
local tr = C.tr

local MAX_MESSAGES = 80      -- messages published to the panels; older ones stay in the history database
local MAX_REASONING = 24000  -- characters of model "thinking" kept for display
local BUSY_INTERVAL = 100
local IDLE_INTERVAL = 2000
local STALL_SECONDS = 300    -- no output for this long while answering: give up
local CANCEL_GRACE = 6       -- seconds to wait for a cancelled backend to report back

local info = {
  ready = false, apiKey = false, model = "", models = {}, modelsSource = "", modelsError = nil,
  baseUrl = "", backendError = nil, keyState = nil, keyError = nil, serverState = nil, serverError = nil, rev = 0,
}
local conv = { id = nil, title = "", messages = {}, hidden = 0, rev = 0 }
local live = { busy = false, content = "", reasoning = "", tools = {}, status = "", error = nil, rev = 0 }
local history = { items = {}, rev = 0 }
local dirty = {}
local turn = { seq = 0, pid = nil, lastLineAt = 0, cancelRequested = false, cancelAt = 0 }
local infoFetchedAt = 0

local TOOL_STATUS = {
  run_command = "status.tool.run_command",
  noctalia_action = "status.tool.noctalia_action",
  read_file = "status.tool.read_file",
  knowledge = "status.tool.knowledge",
  fetch_docs = "status.tool.fetch_docs",
}

local function mark(name)
  dirty[name] = true
end

local function publish()
  if dirty.info then
    info.rev = info.rev + 1
    noctalia.state.set(K.info, info)
  end
  if dirty.conv then
    conv.rev = conv.rev + 1
    local msgs = conv.messages
    local out = { id = conv.id, title = conv.title, rev = conv.rev, hidden = conv.hidden, messages = msgs }
    if #msgs > MAX_MESSAGES then
      local trimmed = {}
      for i = #msgs - MAX_MESSAGES + 1, #msgs do
        trimmed[#trimmed + 1] = msgs[i]
      end
      out.messages = trimmed
      out.hidden = conv.hidden + (#msgs - MAX_MESSAGES)
    end
    noctalia.state.set(K.conv, out)
  end
  if dirty.live then
    live.rev = live.rev + 1
    noctalia.state.set(K.live, live)
  end
  if dirty.history then
    history.rev = history.rev + 1
    noctalia.state.set(K.history, history)
  end
  dirty = {}
end

local function setBusy(busy)
  noctalia.setUpdateInterval(busy and BUSY_INTERVAL or IDLE_INTERVAL)
end

local function anyPanelOpen()
  return noctalia.state.get(K.openChat) == true or noctalia.state.get(K.openPinned) == true
end

local function decode(res)
  if type(res) ~= "table" or res.exitCode ~= 0 then
    return nil
  end
  local data = noctalia.json.decode(res.stdout or "")
  if type(data) ~= "table" then
    return nil
  end
  return data
end

local function backendFailure(res)
  local detail = ""
  if type(res) == "table" then
    detail = C.trim(res.stderr or "")
    if res.timedOut then
      detail = tr("error.timeout")
    end
  end
  return tr("error.backend", { path = C.backend(), detail = detail })
end

-- ------------------------------------------------------------------------------------------- info
local refreshModels

local function refreshInfo(withModels)
  noctalia.runAsync({ C.backend(), "info", "--json" }, function(res)
    local data = decode(res)
    info.ready = true
    if not data then
      info.backendError = backendFailure(res)
      mark("info")
      publish()
      return
    end
    info.backendError = nil
    info.apiKey = data.api_key_present == true
    if type(data.model) == "string" and data.model ~= "" then
      info.model = data.model
    end
    info.baseUrl = data.base_url or ""
    if #info.models == 0 and type(data.fallback_models) == "table" then
      info.models = data.fallback_models
      info.modelsSource = "fallback"
    end
    infoFetchedAt = os.time()
    mark("info")
    publish()
    if withModels then
      refreshModels()
    end
  end, 10000)
end

refreshModels = function()
  noctalia.runAsync({ C.backend(), "models", "--json" }, function(res)
    local data = decode(res)
    if not data then
      info.modelsError = backendFailure(res)
    else
      if type(data.models) == "table" and #data.models > 0 then
        info.models = data.models
      end
      info.modelsSource = data.source or "fallback"
      info.modelsError = data.error
      if type(data.model) == "string" and data.model ~= "" then
        info.model = data.model
      end
    end
    mark("info")
    publish()
  end, 20000)
end

-- ---------------------------------------------------------------------------------- conversations
local function openConversation(id)
  if id == nil or live.busy then
    return
  end
  noctalia.runAsync({ C.backend(), "history", "show", C.idString(id), "--json", "--limit", "200" }, function(res)
    local data = decode(res)
    if not data then
      return
    end
    conv = { id = data.id, title = data.title or "", messages = data.messages or {}, hidden = 0, rev = conv.rev }
    mark("conv")
    publish()
  end, 10000)
end

local function refreshHistory(restoreRecent)
  noctalia.runAsync({ C.backend(), "history", "list", "--json", "--limit", "40" }, function(res)
    local data = decode(res)
    if not data then
      return
    end
    history.items = data
    mark("history")
    publish()
    -- After a shell restart, pick up where the user left off if the last chat is recent.
    if restoreRecent and conv.id == nil and #conv.messages == 0 and data[1] ~= nil then
      local updated = tonumber(data[1].updated) or 0
      if os.time() - updated < 6 * 3600 then
        openConversation(data[1].id)
      end
    end
  end, 10000)
end

local function deleteConversation(id)
  if id == nil then
    return
  end
  noctalia.runAsync({ C.backend(), "history", "delete", C.idString(id) }, function()
    if conv.id == id and not live.busy then
      conv = { id = nil, title = "", messages = {}, hidden = 0, rev = conv.rev }
      mark("conv")
    end
    refreshHistory(false)
  end, 10000)
end

-- ---------------------------------------------------------------------------------------- turns
local function killBackend()
  if turn.pid ~= nil then
    noctalia.runAsync({ "kill", "-TERM", C.idString(turn.pid) })
  end
end

local function finishTurn(ev)
  if not live.busy then
    return
  end
  local tools = {}
  for _, t in ipairs(live.tools) do
    tools[#tools + 1] = { name = t.name, summary = t.summary, ok = t.ok }
  end
  local err = ev.error
  if err == nil then
    err = live.error
  end
  local msg = {
    role = "assistant",
    content = live.content,
    reasoning = live.reasoning,
    tools = tools,
    error = err,
    cancelled = ev.cancelled == true or turn.cancelRequested,
    needKey = ev.need_key == true,
    needModel = ev.need_model == true,
  }
  if C.trim(msg.content) ~= "" or err ~= nil or #tools > 0 then
    conv.messages[#conv.messages + 1] = msg
  end
  if ev.conversation_id ~= nil then
    conv.id = ev.conversation_id
  end
  live = { busy = false, content = "", reasoning = "", tools = {}, status = "", error = nil, rev = live.rev }
  turn.pid = nil
  turn.cancelRequested = false
  mark("conv")
  mark("live")
  setBusy(false)
  publish()
  refreshHistory(false)
  if msg.needKey then
    refreshInfo(false)
  elseif msg.needModel then
    refreshModels()
  end
  if not msg.cancelled and noctalia.getConfig("notify_when_closed") ~= false and not anyPanelOpen() then
    if C.trim(msg.content) ~= "" then
      noctalia.notify(tr("notify.title"), C.preview(msg.content, 180))
    elseif err ~= nil then
      noctalia.notifyError(tr("notify.title"), tostring(err))
    end
  end
end

local function onLine(seq, line)
  if seq ~= turn.seq then
    return
  end
  turn.lastLineAt = os.time()
  local ev = noctalia.json.decode(line)
  if type(ev) ~= "table" then
    return
  end
  local t = ev.type
  if t == "delta" then
    live.content = live.content .. (ev.text or "")
    live.status = ""
    mark("live")
  elseif t == "reasoning_delta" then
    if #live.reasoning < MAX_REASONING then
      live.reasoning = live.reasoning .. (ev.text or "")
      mark("live")
    end
  elseif t == "tool_call" then
    live.tools[#live.tools + 1] = { id = ev.id, name = ev.name, summary = ev.summary or "", pending = true }
    live.status = tr(TOOL_STATUS[ev.name or ""] or "status.tool.other")
    mark("live")
  elseif t == "tool_result" then
    for _, tl in ipairs(live.tools) do
      if tl.id == ev.id then
        tl.pending = false
        tl.ok = ev.ok ~= false
      end
    end
    live.status = tr("status.thinking")
    mark("live")
  elseif t == "notice" then
    live.status = ev.text or ""
    mark("live")
  elseif t == "error" then
    live.error = ev.message
    mark("live")
  elseif t == "turn_start" then
    turn.pid = ev.pid
    if ev.conversation_id ~= nil then
      conv.id = ev.conversation_id
    end
    if type(ev.title) == "string" and ev.title ~= "" then
      conv.title = ev.title
    end
    mark("conv")
    if turn.cancelRequested then
      killBackend()
    end
  elseif t == "turn_end" then
    finishTurn(ev)
  elseif t == "exit" then
    -- printed by the shell wrapper after the backend exits; only matters if turn_end never came
    if live.busy then
      finishTurn({ error = tr("error.exited", { code = tostring(ev.code) }) })
    end
  end
end

local function startTurn(text, demo)
  text = C.trim(text)
  if live.busy or (text == "" and not demo) then
    return
  end
  turn.seq = turn.seq + 1
  local seq = turn.seq
  local path = C.runtimeDir() .. "/request-" .. string.format("%d", noctalia.nowMs()) .. ".json"
  local request = { text = text, conversation_id = conv.id, model = info.model, demo = demo == true }
  local ok = noctalia.writeFile(path, noctalia.json.encode(request))
  if text ~= "" then
    conv.messages[#conv.messages + 1] = { role = "user", content = text }
    mark("conv")
  end
  live = {
    busy = true, content = "", reasoning = "", tools = {}, status = tr("status.thinking"), error = nil,
    rev = live.rev, startedAt = os.time(),
  }
  turn.pid = nil
  turn.cancelRequested = false
  turn.lastLineAt = os.time()
  mark("live")
  if not ok then
    finishTurn({ error = tr("error.request") })
    return
  end
  -- The wrapper's final line marks the end of the stream even if the backend crashes.
  local cmd = C.shq(C.backend()) .. " turn --request " .. C.shq(path)
    .. "; printf '{\"type\":\"exit\",\"code\":%s}\\n' \"$?\""
  local started = noctalia.runStream(cmd, function(line)
    onLine(seq, line)
  end)
  if not started then
    finishTurn({ error = tr("error.start") })
    return
  end
  setBusy(true)
  publish()
end

local function cancelTurn()
  if not live.busy or turn.cancelRequested then
    return
  end
  turn.cancelRequested = true
  turn.cancelAt = os.time()
  live.status = tr("status.stopping")
  mark("live")
  publish()
  killBackend()
end

local function newConversation()
  if live.busy then
    cancelTurn()
  end
  conv = { id = nil, title = "", messages = {}, hidden = 0, rev = conv.rev }
  mark("conv")
  publish()
end

local function setModel(name)
  name = C.trim(name)
  if name == "" then
    return
  end
  info.model = name
  mark("info")
  publish()
  noctalia.runAsync({ C.backend(), "set-model", name }, function() end, 10000)
end

local function setServer(url)
  url = C.trim(url)
  if url == "" or url == info.baseUrl then
    return
  end
  info.serverState = "saving"
  info.serverError = nil
  mark("info")
  publish()
  noctalia.runAsync({ C.backend(), "set-server", url }, function(res)
    if type(res) == "table" and res.exitCode == 0 then
      info.serverState = "saved"
      info.baseUrl = C.trim(res.stdout or url)
      info.models = {}
      info.modelsError = nil
      mark("info")
      publish()
      refreshInfo(true)
    else
      info.serverState = "error"
      info.serverError = (type(res) == "table" and C.trim(res.stderr or "")) or ""
      mark("info")
      publish()
    end
  end, 10000)
end

local function setKey(path)
  if type(path) ~= "string" or path == "" then
    return
  end
  info.keyState = "saving"
  info.keyError = nil
  mark("info")
  publish()
  noctalia.runAsync({ C.backend(), "set-key", "--from-file", path }, function(res)
    if type(res) == "table" and res.exitCode == 0 then
      info.keyState = "saved"
      info.apiKey = true
      mark("info")
      publish()
      refreshInfo(true)
    else
      info.keyState = "error"
      info.keyError = (type(res) == "table" and C.trim(res.stderr or "")) or ""
      mark("info")
      publish()
    end
  end, 10000)
end

-- ------------------------------------------------------------------------------------- panels
local function toggle()
  if noctalia.state.get(K.openPinned) == true then
    noctalia.togglePanel(C.PANEL_PINNED)
  else
    noctalia.togglePanel(C.PANEL_CHAT)
  end
end

local function show()
  if not anyPanelOpen() then
    noctalia.togglePanel(C.PANEL_CHAT)
  end
end

-- ---------------------------------------------------------------------------------------- hooks
function onIpc(event, payload)
  if event == "send" then
    startTurn(payload or "", false)
  elseif event == "ask" then
    show()
    startTurn(payload or "", false)
  elseif event == "demo" then
    show()
    startTurn(payload or "", true)
  elseif event == "cancel" then
    cancelTurn()
  elseif event == "new" then
    newConversation()
  elseif event == "open" then
    openConversation(tonumber(payload))
  elseif event == "delete" then
    deleteConversation(tonumber(payload))
  elseif event == "model" then
    setModel(payload or "")
  elseif event == "refresh" then
    refreshInfo(true)
  elseif event == "set_key" then
    setKey(payload)
  elseif event == "set_server" then
    setServer(payload or "")
  elseif event == "toggle" then
    toggle()
  elseif event == "show" then
    show()
  elseif event == "opened" then
    if info.modelsSource ~= "endpoint" or os.time() - infoFetchedAt > 60 then
      refreshInfo(true)
    end
  else
    noctalia.log("assistant: unknown event " .. tostring(event))
  end
end

function update()
  if live.busy then
    local now = os.time()
    if turn.cancelRequested and now - turn.cancelAt > CANCEL_GRACE then
      finishTurn({ cancelled = true })
    elseif now - turn.lastLineAt > STALL_SECONDS then
      killBackend()
      finishTurn({ error = tr("error.stalled") })
    end
  end
  publish()
end

function onExit()
  if live.busy then
    killBackend()
  end
end

-- ----------------------------------------------------------------------------------------- start
-- noctalia.state outlives a service reload, so keep showing the conversation the user was in.
local previous = noctalia.state.get(K.conv)
if type(previous) == "table" and previous.id ~= nil then
  conv.id = previous.id
  conv.title = previous.title or ""
  conv.rev = tonumber(previous.rev) or 0
end
setBusy(false)
mark("info")
mark("conv")
mark("live")
mark("history")
publish()
refreshInfo(true)
if conv.id ~= nil then
  openConversation(conv.id)
  refreshHistory(false)
else
  refreshHistory(true)
end
