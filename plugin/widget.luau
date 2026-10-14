-- [[widget]] "button": bar button. Click toggles the assistant, right-click starts a new chat.
-- The glyph switches to the primary color while an answer is being written.
local C = require("./lib/common.luau")
local K = C.KEYS

local function paint()
  local live = noctalia.state.get(K.live)
  local busy = type(live) == "table" and live.busy == true
  barWidget.setGlyph("sparkles")
  barWidget.setGlyphColor(busy and "primary" or "on_surface")
  barWidget.setTooltip(busy and C.tr("widget.busy") or C.tr("widget.tooltip"))
end

noctalia.state.watch(K.live, function() paint() end)

function update()
  noctalia.setUpdateInterval(2000)
  paint()
end

local function anyOpen()
  return noctalia.state.get(K.openChat) == true or noctalia.state.get(K.openPinned) == true
end

function onClick()
  if noctalia.state.get(K.openPinned) == true then
    noctalia.togglePanel(C.PANEL_PINNED)
  else
    noctalia.togglePanel(C.PANEL_CHAT)
  end
end

function onRightClick()
  C.dispatch("new")
  if not anyOpen() then
    noctalia.togglePanel(C.PANEL_CHAT)
  end
end
