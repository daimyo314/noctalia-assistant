-- [[panel]] "pinned": the same chat as a persistent panel that stays open while you use other windows.
local ui_panel = require("./lib/panel.luau")
ui_panel.setup({ pinned = true, panel = panel })

function onOpen(context) ui_panel.onOpen(context) end
function onClose() ui_panel.onClose() end
function update() ui_panel.update() end
