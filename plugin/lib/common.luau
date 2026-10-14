-- Shared constants and helpers for every entry of dadmin/assistant.
-- Written in the Lua 5.1 subset of Luau so dev/mock.lua can exercise it with stock Lua.

local M = {}

M.PLUGIN = "dadmin/assistant"
M.SERVICE = M.PLUGIN .. ":brain"
M.PANEL_CHAT = M.PLUGIN .. ":chat"
M.PANEL_PINNED = M.PLUGIN .. ":pinned"

-- noctalia.state keys (plain data copied between entries)
M.KEYS = {
  info = "assistant.info",          -- service: key presence, model, model list, endpoint
  conv = "assistant.conv",          -- service: current conversation (finished messages)
  live = "assistant.live",          -- service: the answer being streamed right now
  history = "assistant.history",    -- service: conversation list
  openChat = "assistant.open.chat", -- panels: which panel is on screen
  openPinned = "assistant.open.pinned",
  draft = "assistant.draft",        -- panels: unsent composer text, shared when pinning
}

function M.tr(key, subst)
  return noctalia.tr(key, subst)
end

-- Send an event to the service's onIpc(event, payload). Argument-array form: no shell quoting.
function M.dispatch(event, payload)
  local argv = { "noctalia", "msg", "plugin", M.SERVICE, "all", event }
  if payload ~= nil then
    argv[#argv + 1] = tostring(payload)
  end
  return noctalia.runAsync(argv)
end

function M.backend()
  local b = noctalia.getConfig("backend")
  if type(b) ~= "string" or b == "" then
    b = "~/.local/bin/noctalia-assistant"
  end
  return noctalia.expandPath(b)
end

-- Private scratch directory for request/key/command files ($XDG_RUNTIME_DIR is mode 700).
function M.runtimeDir()
  local base = noctalia.getenv("XDG_RUNTIME_DIR")
  local dir
  if type(base) == "string" and base ~= "" then
    dir = base .. "/noctalia-assistant"
  else
    dir = (noctalia.pluginDataDir() or "/tmp") .. "/runtime"
  end
  noctalia.mkdirAll(dir)
  return dir
end

function M.shq(s)
  return "'" .. (string.gsub(tostring(s), "'", "'\\''")) .. "'"
end

function M.trim(s)
  if type(s) ~= "string" then
    return ""
  end
  return (string.gsub(s, "^%s*(.-)%s*$", "%1"))
end

function M.isTable(v)
  return type(v) == "table"
end

function M.idString(v)
  if type(v) == "number" then
    return string.format("%d", v)
  end
  return tostring(v or "")
end

-- One-line preview of an answer for notifications and history subtitles.
function M.preview(text, n)
  local s = tostring(text or "")
  s = string.gsub(s, "```.-```", "[code]")
  s = string.gsub(s, "[`*_#>|]", "")
  s = string.gsub(s, "%s+", " ")
  s = M.trim(s)
  n = n or 160
  if #s > n then
    s = string.sub(s, 1, n - 1) .. "…"
  end
  return s
end

-- Split markdown into prose and fenced code segments. ui.markdown does not wrap code blocks, so code is
-- rendered separately (wrapping monospace label + Copy / Run buttons). An unterminated fence (still
-- streaming) is treated as code up to the end of the text.
function M.splitMarkdown(text)
  local segs = {}
  local pos = 1
  local len = #text
  while pos <= len do
    local s, e, lang = string.find(text, "```([^\n`]*)\n", pos)
    if not s then
      break
    end
    local prose = string.sub(text, pos, s - 1)
    if string.find(prose, "%S") then
      segs[#segs + 1] = { kind = "md", text = M.trim(prose) }
    end
    local cs, ce = string.find(text, "\n?```", e + 1)
    local code
    if cs then
      code = string.sub(text, e + 1, cs - 1)
      pos = ce + 1
    else
      code = string.sub(text, e + 1)
      pos = len + 1
    end
    segs[#segs + 1] = { kind = "code", lang = string.lower(M.trim(lang)), text = code }
  end
  if pos <= len then
    local rest = string.sub(text, pos)
    if string.find(rest, "%S") then
      segs[#segs + 1] = { kind = "md", text = M.trim(rest) }
    end
  end
  return segs
end

local SHELL_LANGS = { bash = true, sh = true, zsh = true, fish = true, shell = true, console = true, terminal = true }

function M.isShell(lang)
  return SHELL_LANGS[lang or ""] == true
end

-- Drop "$ " prompts and comment-only lines so the command can be handed to a terminal as-is.
function M.runnable(code)
  local out = {}
  for line in string.gmatch(code .. "\n", "(.-)\n") do
    local l = string.gsub(line, "^%s*%$%s+", "")
    if string.find(l, "%S") and not string.find(l, "^%s*#") then
      out[#out + 1] = l
    end
  end
  return table.concat(out, "\n")
end

M.TOOL_GLYPHS = {
  run_command = "terminal-2",
  noctalia_action = "bolt",
  read_file = "file-text",
  knowledge = "book-2",
  fetch_docs = "world",
}

function M.toolGlyph(name)
  return M.TOOL_GLYPHS[name or ""] or "tool"
end

return M
