# Noctalia desktop shell: bar, launcher, control center, theming, IPC, plugins

> Noctalia v5 is the native Wayland shell around Hyprland here: what each surface is, how it is configured (TOML), how wallpaper-based theming and app templates work, the `noctalia msg` IPC, hooks, and plugins.

## What Noctalia provides (and what it does not)
Noctalia owns the desktop *shell*: **bar(s)** with widgets, **launcher**, **control center** (Wi-Fi, Bluetooth, audio, media, notifications, brightness, night light, power profiles), **notifications** (toasts + history + Do Not Disturb), **OSDs** (volume/brightness popups), **wallpaper** manager + picker, **lock screen**, **session** panel (lock/logout/suspend/reboot/shutdown), **clipboard history**, **window switcher**, **dock** (optional), **desktop widgets**, **settings window**, **screenshots** (piped to `satty`), a **polkit agent**, **theming** (Material You palette from the wallpaper) and **templates** that recolor other apps. Since v5 it is a native C++/OpenGL program (no Qt/QML); the old v4 was built on Quickshell.
Window management, tiling and keybinds belong to Hyprland. File management is Dolphin. Login screen is `noctalia-greeter`.

## Opening things (default binds on this machine, confirm in the keybind list)
- Launcher `Super + Space`; emoji picker `Super + .` (launcher with `/emo`); other launcher prefixes: type `/` to see them (calculator, wallpapers `/wall`, clipboard, etc.).
- Control center `Super + X`; notifications tab `Super + A`; settings window `Super + Z`; wallpaper picker `Super + Shift + W`; clipboard history `Super + V`; session panel `Super + Alt + C`; lock `Super + L`; window switcher `Super + Tab`.
- Everything is also reachable from the bar: launcher button, clock (calendar), tray, network, volume, notifications bell, session button. Right-click widgets for options; some widgets have hover tooltips.

## Configuration files (TOML, hot-reloaded)
- `~/.config/noctalia/config.toml` — your config (the CachyOS defaults come from `/etc/skel/.config/noctalia/config.toml`). Any `*.toml` in `~/.config/noctalia/` is merged.
- `~/.local/state/noctalia/settings.toml` — values changed through the **Settings GUI**; these override config.toml (bar layout, theme mode, wallpaper paths, launcher options...). Prefer the GUI for those.
- `noctalia config export` prints the effective merged config; `noctalia config validate` checks syntax.
- Logs: `~/.cache/noctalia/noctalia.log`. Restart the shell: `pkill noctalia; noctalia &` (or `noctalia msg config-reload` for config only). It is started by Hyprland in `autostart.lua`.
- Key sections: `[bar.default]` (position, thickness, `start`/`center`/`end` widget lists, capsule groups), `[widget.<name>]` (per-widget options, custom widgets), `[shell]` (font_family, launcher, panel transparency `glass|soft|solid`, screenshots, session actions), `[theme]` (mode dark/light, source `wallpaper|builtin|community|custom`, `wallpaper_scheme` like `m3-tonal-spot`, `[theme.templates]`), `[wallpaper]`, `[hooks]`, `[accessibility] ui_scale`.

### Custom bar buttons
```toml
[widget.mybutton]
type = "custom_button"
glyph = "terminal-2"          # Tabler icon name
label = "Term"
tooltip = "Open a terminal"
color = "secondary"
  [widget.mybutton.actions]
  left = "exec uwsm app -- kitty"     # exec <cmd>, or a noctalia msg command name
```
Then add `"mybutton"` to a bar list (`start`/`center`/`end`) via Settings → Bar, or in `[bar.default]` if settings.toml does not override the layout. This machine already uses custom buttons for monitor profiles (Full / Work / Half). Glyph names come from the Tabler icon set (`/usr/share/noctalia/assets/fonts/tabler.json`).

## Theming
- **Palette**: `[theme] source = "wallpaper"` derives a Material 3 palette from the current wallpaper (`wallpaper_scheme` picks the flavour: `m3-tonal-spot`, `m3-vibrant`, `m3-expressive`, `m3-neutral`...). Alternatives: `builtin` palettes (e.g. `Noctalia`), `community` palettes (e.g. `Oxocarbon`), or a `custom` scheme folder. Dark/light: `noctalia msg theme-mode-toggle` or Settings.
- **Templates** recolor other applications whenever the palette changes. Built-in: kitty, alacritty, foot, ghostty, wezterm, btop, gtk3/gtk4, qt (qt5ct/qt6ct), kcolorscheme (KDE apps like Dolphin), starship, helix, emacs, hyprland (writes `~/.config/hypr/noctalia.lua`), cava... Community templates cover Discord, VS Code, Obsidian, Firefox (`pywalfox`), Steam, Spotify (spicetify), Claude Code and more. Enable in Settings → Theme → Templates or `[theme.templates] builtin_ids = [...] community_ids = [...]`. Re-apply manually: `noctalia msg templates-apply`.
- **Your own template**: `[theme.templates.user.<id>]` with `input_path`, `output_path`, optional `post_hook`. Template syntax: `{{colors.primary.default.hex}}` (modes `dark|light|default`, formats `hex|hex_stripped|rgb|rgba|hsl|red|green|blue`), `{{mode}}`, `{{image}}`.
- Firefox: `noctalia firefox-theme install`. GTK apps: gtk3/gtk4 templates + `nwg-look`; Qt apps: qt template via `qt6ct` (`QT_QPA_PLATFORMTHEME=qt6ct` is set).
- Cursor theme: Bibata-Modern-Ice (`XCURSOR_THEME`, `HYPRCURSOR_THEME` in `~/.config/uwsm/env`).

## Wallpapers
Directory: `[wallpaper] directory` (Settings → Wallpaper). Picker `Super + Shift + W`, or `noctalia msg wallpaper-set <path>`, `wallpaper-random`, `wallpaper-next`. Per-monitor wallpapers are supported. Changing the wallpaper re-generates the palette and re-renders templates when source = wallpaper.

## Notifications, DND, OSD
`noctalia msg notification-dnd-toggle`, `notification-clear-history`, `notification-show "Title" "Body"` (internal notification), `osd-toggle`. History and DND live in the control center (`Super + A`). Apps use the standard freedesktop notification D-Bus API, so no extra daemon (like dunst/mako) must run.

## IPC: `noctalia msg`
Everything scriptable: `noctalia msg --help` lists ~150 commands. Frequently useful: `panel-toggle launcher|control-center|clipboard|wallpaper|session`, `settings-open [section]`, `theme-mode-set dark|light`, `theme-mode-toggle`, `wallpaper-set <path>`, `volume-up|down|set|mute`, `brightness-up|down|set`, `media toggle|next|previous`, `screenshot-region|screenshot-fullscreen`, `session lock|logout|suspend|reboot|shutdown`, `caffeine-toggle`, `nightlight-toggle`, `bar-toggle`, `dock-toggle`, `window-switcher`, `status` (JSON), `config-reload`, `templates-apply`, `color-scheme-set`, `dpms-off`, `power-set performance|balanced|power-saver`.
Bind any of them in `binds.lua` with `hl.dsp.exec_cmd("noctalia msg ...")`.
`noctalia dmenu -p "Prompt"` turns the launcher into a dmenu replacement for scripts.

## Hooks (run commands on shell events)
```toml
[hooks]
started = "notify-send 'Noctalia' 'ready'"
wallpaper_changed = "echo $NOCTALIA_WALLPAPER_PATH > ~/.cache/current-wallpaper"
theme_mode_changed = ["echo mode=$NOCTALIA_THEME_MODE"]
```
Events: started, wallpaper_changed, colors_changed, theme_mode_changed, session_locked/unlocked, logging_out, rebooting, shutting_down, wifi_enabled/disabled, bluetooth_enabled/disabled, battery_*, power_profile_changed.

## Plugins
Noctalia has a Lua (Luau) plugin system: bar widgets, control-center shortcuts, launcher providers, panels, desktop widgets, background services. Browse and enable in Settings → Plugins (community source is preconfigured) or `noctalia msg plugins list|enable|disable <author/plugin>`. Plugin settings: `noctalia msg settings-open-plugin <id>`. Plugins live under `~/.local/state/noctalia/plugins/`. Popular: keybind-cheatsheet, todo, pomodoro, color_picker, file-search, audio-switcher, game-launcher, claude-companion. This assistant is itself a plugin (`dadmin/assistant`, installed by hand under `~/.local/share/noctalia/plugins/`).

## Lock screen and greeter
`Super + L` locks (Noctalia session lock; widgets configurable in Settings → Lock screen). Login is `noctalia-greeter` on greetd; `noctalia msg greeter-sync` copies wallpaper/colors/monitor layout to the greeter (auto_sync is on here).

## Screenshots & clipboard
`Print` = region screenshot piped into **satty** (annotate, copy, save); `Super + Print` = full screen. Config: `[shell.screenshot]` (copy_to_clipboard, save_to_file, pipe_command). Clipboard history `Super + V` (text and images; `clipboard_image_action_command = "satty -f -"` opens images in satty). `wl-copy`/`wl-paste` are the command-line clipboard tools.
