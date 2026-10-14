-- [[launcher_provider]] "ask": type "/ask <question>" in the launcher to send it to the assistant.
local C = require("./lib/common.luau")

function onQuery(text)
  local q = C.trim(text)
  if q == "" then
    launcher.setResults(text, {
      { id = "open", title = C.tr("launcher.open"), subtitle = C.tr("launcher.open_sub"), glyph = "sparkles" },
    })
    return
  end
  launcher.setResults(text, {
    { id = "ask:" .. q, title = q, subtitle = C.tr("launcher.ask_sub"), glyph = "sparkles" },
  })
end

function onActivate(id)
  if id == "open" then
    C.dispatch("show")
    return
  end
  local q = string.match(id or "", "^ask:(.*)$")
  if q ~= nil and C.trim(q) ~= "" then
    C.dispatch("ask", q)
  end
end
