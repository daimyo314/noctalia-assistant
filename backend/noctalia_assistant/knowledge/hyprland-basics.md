# Hyprland on CachyOS: concepts, Lua config, workflow

> How the Hyprland tiling compositor works (workspaces per monitor, tiling vs floating, special workspace), how the Lua config under ~/.config/hypr is organised, keybind/window-rule syntax, hyprctl, and tips for people used to Windows.

## Mental model
- Hyprland is a **Wayland compositor with dynamic tiling**: new windows split the screen automatically (dwindle layout). You can float any window (`Super + Alt + Space` here), fullscreen it, or send it to the **special workspace** (a hidden scratchpad you toggle in/out).
- **Workspaces** replace Windows' virtual desktops. In this config each monitor has its own set (`NUM_WPM` workspaces per monitor, named `m~1`, `m~2` ... relative to the monitor). Switching focus between monitors: `Super + 1/2/3`.
- **Focus follows keyboard**: `Super + arrows` move focus; `Super + Shift + arrows` move the window in that direction; `Super + Ctrl + arrows` change workspace.
- **Groups** (tabbed windows) exist (`togglegroup`) but are not bound by default here.
- The bar, launcher, notifications, lock screen, wallpaper and OSDs are NOT Hyprland: they come from **Noctalia**. Hyprland only manages windows, monitors, input and keybinds.
- `hyprctl` is the CLI to query/control the running compositor: `hyprctl monitors`, `hyprctl clients`, `hyprctl workspaces`, `hyprctl activewindow`, `hyprctl binds`, `hyprctl getoption general:gaps_out`, `hyprctl dispatch <dispatcher> <args>`, `hyprctl keyword <option> <value>` (temporary), `hyprctl reload`, `hyprctl configerrors`.

## Config layout (Lua, since Hyprland 0.55)
CachyOS' Noctalia edition ships a **Lua** config, not the old `hyprland.conf` syntax:
```
~/.config/hypr/hyprland.lua        # entry point: require("config.<file>") for each part
~/.config/hypr/config/variables.lua    # TERMINAL, FILE_MANAGER, BROWSER, EDITOR, MONITOR1/2, NUM_WPM
~/.config/hypr/config/binds.lua        # all keybinds (hl.bind)
~/.config/hypr/config/monitors.lua     # hl.monitor({ output=, mode=, position=, scale= })
~/.config/hypr/config/windowrules.lua  # hl.window_rule({...})
~/.config/hypr/config/decorations.lua  # gaps, borders, rounding, blur, opacity
~/.config/hypr/config/animations.lua   # hl.curve / hl.animation
~/.config/hypr/config/autostart.lua    # hl.on("hyprland.start", function() hl.exec_cmd("noctalia") end)
~/.config/hypr/config/inputs.lua       # mouse/touchpad, gestures
~/.config/hypr/config/misc.lua, workspaces.lua, environment.lua, colors.lua
```
Hyprland reloads automatically when these files change. Syntax check without reloading: `luac -p ~/.config/hypr/config/binds.lua`. Errors show as a red bar/notification and in `hyprctl configerrors`.

### Keybinds
```lua
local mainMod = "SUPER"
hl.bind(mainMod .. " + Return", hl.dsp.exec_cmd("uwsm app -- kitty"))
hl.bind(mainMod .. " + Q",      hl.dsp.window.close())
hl.bind(mainMod .. " + F",      hl.dsp.window.fullscreen())
hl.bind(mainMod .. " + Left",   hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + SHIFT + Left", hl.dsp.window.move({ direction = "l" }))
hl.bind(mainMod .. " + CONTROL + 2",  hl.dsp.focus({ workspace = "m~2" }))
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("noctalia msg volume-up"), { locked = true, repeating = true })
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd("noctalia msg plugin dadmin/assistant:brain all toggle")) -- this assistant
```
Modifiers: SUPER (Windows key), SHIFT, CONTROL, ALT. Key names: letters, `Return`, `Space`, `Escape`, `Tab`, `Print`, `Left/Right/Up/Down`, `period`, `comma`, `minus`, `code:NN` for keycodes, `mouse:272` (left button), `mouse_up/mouse_down` (wheel). Options table: `{ locked = true }` (works on lock screen), `{ repeating = true }`, `{ release = true }`.
Dispatchers live under `hl.dsp.*`: `exec_cmd(cmd)`, `window.close()`, `window.float({action="toggle"})`, `window.fullscreen({mode=1})` (maximize keeping the bar), `window.move({direction|workspace|monitor})`, `window.pin()`, `focus({direction|monitor|workspace|window})`, `workspace.toggle_special()`, `layout("togglesplit")`, `global("app:shortcut")`.
Run any dispatcher live: `hyprctl dispatch 'hl.dsp.window.close()'` (Lua mode syntax).

### Window rules
```lua
hl.window_rule({ match = { class = "^(pavucontrol)$" }, float = true, center = true, size = { "40%", "60%" } })
hl.window_rule({ match = { title = "^Picture-in-Picture$" }, float = true, pin = true, keep_aspect_ratio = true })
hl.window_rule({ match = { class = "^steam_app.*$" }, workspace = "name:gaming", fullscreen = true })
hl.window_rule({ match = { float = true }, center = true, persistent_size = true })
```
Find a window's class/title: `hyprctl clients` or `hyprctl activewindow`. Effects: `float`, `tile`, `center`, `size`, `move`, `pin`, `fullscreen`, `maximize`, `workspace`, `monitor`, `opacity`, `no_blur`, `no_border`, `rounding`, `idle_inhibit`, `no_focus`, `keep_aspect_ratio`, `persistent_size`.
Layer rules (for shell surfaces such as bars and launchers; find namespaces with `hyprctl layers`): `hl.layer_rule({ match = { namespace = "^rofi$" }, blur = true, ignore_alpha = 0.3 })`.

### Monitors
```lua
hl.monitor({ output = "HDMI-A-1", mode = "7680x2160@60", position = "0x0", scale = "2" })
hl.monitor({ output = "",         mode = "preferred",     position = "auto", scale = "auto" }) -- fallback
```
`hyprctl monitors` lists names, modes and scales. Scale 2 halves the logical resolution (a 7680×2160 panel becomes 3840×1080 logical). Fractional scales like 1.5 work on Wayland-native apps; XWayland apps can look blurry (`xwayland.force_zero_scaling = true` helps).

### Look & feel
`decorations.lua`: `general.gaps_in/gaps_out/border_size`, `col.active_border`, `decoration.rounding`, `active_opacity`/`inactive_opacity`, `blur { size, passes }`. Colors are `rgba(RRGGBBAA)` strings. Noctalia can also generate `~/.config/hypr/noctalia.lua` with palette colors when its `hyprland` template is enabled.

### Environment variables
With UWSM (used here), put session env vars in `~/.config/uwsm/env` (`export NAME=value`), not in `environment.lua`. Apps are launched with `uwsm app -- <cmd>` so each runs in its own systemd user unit (see them with `systemctl --user list-units 'app-*'`).

## Everyday workflow for a Windows user
- Open apps: `Super + Space` (Noctalia launcher, type to search), or the bound shortcuts (terminal `Super + Return`, files `Super + E`, browser `Super + W`).
- Windows tile automatically; make one float with `Super + Alt + Space`, maximize with `Super + D`, fullscreen with `Super + F`, close with `Super + Q`. Force-kill a frozen window: `Super + Escape` (hyprctl kill, then click the window).
- Move windows with `Super + left-drag`, resize with `Super + right-drag` or drag borders (`resize_on_border`).
- Alt+Tab cycles windows; `Super + Tab` opens Noctalia's window switcher.
- Workspaces: `Super + Ctrl + 1..3` per monitor, `Super + Ctrl + ←/→` next/previous, `Super + Ctrl + ↓` next empty. Scroll the wheel with `Super` held to cycle.
- Scratchpad: `Super + Shift + S` sends a window there, `Super + S` shows/hides it (great for a music player or notes).
- Screenshots: `Print` (region, opens satty for annotation), `Super + Print` (full screen); color picker `Super + P`.
- Zoom the screen: `Super + Plus/Minus`.
- Lock: `Super + L`; session menu (logout/reboot/shutdown): `Super + Alt + C`.
Always confirm exact keys from the live keybind list in this assistant's context (parsed from binds.lua).

## Troubleshooting Hyprland
- Config error on save: `hyprctl configerrors`; fix and it reloads.
- Logs: `$XDG_RUNTIME_DIR/hypr/<instance>/hyprland.log` (`ls /run/user/1000/hypr/`).
- App won't start from the launcher: try it in a terminal to read the error; `uwsm app -- <cmd>` mirrors what the launcher does.
- Screen tearing / VRR: `misc.vrr` (0 off, 1 on, 2 fullscreen only, 3 fullscreen game). NVIDIA: `env = NVD_BACKEND,direct` and `LIBVA_DRIVER_NAME=nvidia` for video accel; `__GL_GSYNC_ALLOWED=1` for G-Sync.
- XWayland app blurry: `xwayland.force_zero_scaling = true` (already set) plus the app's own DPI setting.
- Cursor issues: `cursor.no_hardware_cursors = 1` (in inputs.lua, commented out by default).
