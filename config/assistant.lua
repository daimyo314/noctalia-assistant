-- Noctalia Assistant — hotkey. Installed by noctalia-assistant/install.sh.
-- Change the key here (Hyprland reloads automatically). Remove the require() line from hyprland.lua to disable.
-- The service decides which panel to toggle (the normal sheet, or the pinned one if it is open).

hl.bind("SUPER + I", hl.dsp.exec_cmd("noctalia msg plugin dadmin/assistant:brain all toggle"))
