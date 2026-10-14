-- [[panel]] "chat": the assistant as a full-height sheet on the right; closes when you click elsewhere.
local ui_panel = require("./lib/panel.luau")
ui_panel.setup({ pinned = false, panel = panel })

function onOpen(context) ui_panel.onOpen(context) end
function onClose() ui_panel.onClose() end
function update() ui_panel.update() end
