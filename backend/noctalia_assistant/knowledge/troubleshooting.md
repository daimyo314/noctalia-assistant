# Troubleshooting on CachyOS + Hyprland + Noctalia

> Where to look first (journalctl, hyprctl, noctalia log), and fixes for the common problems: updates/pacman, boot and snapshots, NVIDIA + AMD hybrid graphics, monitors/scaling, audio, network/Bluetooth, apps not launching, theming glitches, keyboard/input.

## First moves
1. Reproduce from a terminal: run the app by name to see its error output.
2. System log for this boot: `journalctl -b -p err` (errors), `journalctl -b -u <service>`; previous boot: `journalctl -b -1`.
3. Compositor: `hyprctl configerrors`, `hyprctl monitors`, `hyprctl clients`; log in `/run/user/$(id -u)/hypr/*/hyprland.log`.
4. Shell: `~/.cache/noctalia/noctalia.log`; `noctalia msg status`; `noctalia config validate`.
5. Was something updated? `grep -i upgraded /var/log/pacman.log | tail -30`. Snapshots: `snapper list`.

## Updates and pacman
- **Signature / keyring errors**: `sudo pacman -Sy archlinux-keyring cachyos-keyring && sudo pacman -Syu`.
- **"failed to synchronize"/timeouts**: `sudo cachyos-rate-mirrors` then retry; check `nmcli device status`.
- **"conflicting files"**: read which package owns them (`pacman -Qo <file>`); if unowned leftovers, move them aside or use `--overwrite '<glob>'` carefully.
- **Lock file**: no pacman/paru running (`pgrep -a pacman`) → `sudo rm /var/lib/pacman/db.lck`.
- **.pacnew files**: `sudo pacdiff` (pacman-contrib) to merge config changes.
- **Broken after an update**: reboot into the previous snapshot from the Limine menu (see cachyos-basics), or check `journalctl -b -p err`.
- **Kernel updated but module missing (nvidia)**: make sure the matching `linux-cachyos*-nvidia-open` package is installed for that kernel, then reboot.
- Never fix things with `pacman -Sy` + install; that is a partial upgrade.

## Boot
- Limine menu: choose kernel (linux-cachyos vs lts) or a snapshot entry. `Esc` may reveal the menu if hidden.
- Black screen after update on NVIDIA: boot the LTS kernel or a snapshot; verify `pacman -Q | grep nvidia` matches the kernel.
- Slow boot: `systemd-analyze blame`, `systemd-analyze critical-chain`.
- Emergency shell: check `/etc/fstab` UUIDs (`lsblk -f`).

## Graphics (NVIDIA, AMD and hybrid setups)
- Driver status: `nvidia-smi`; which GPU drives a display: `lspci -k` (kernel driver in use) and `hyprctl monitors` (description). Monitors plugged into the motherboard use the AMD iGPU; the GPU's ports use NVIDIA.
- Hyprland picks the primary GPU via `AQ_DRM_DEVICES=/dev/dri/card0:/dev/dri/card1` (set in `~/.config/uwsm/env` if needed); `ls -l /dev/dri/by-path/` maps cards to PCI slots. If the wrong GPU renders, set the desired card first.
- NVIDIA env for Wayland (in `~/.config/uwsm/env`): `LIBVA_DRIVER_NAME=nvidia`, `__GLX_VENDOR_LIBRARY_NAME=nvidia`, `NVD_BACKEND=direct`, optionally `GBM_BACKEND=nvidia-drm`. Electron apps: `ELECTRON_OZONE_PLATFORM_HINT=auto` (set).
- Flicker/glitches in Electron/Chromium: run with `--ozone-platform=wayland` or disable GPU compositing in the app.
- Screen sharing: `xdg-desktop-portal-hyprland` (installed with the Noctalia edition); Firefox/Discord pick a screen via the portal. `xdph.conf` allows tokens by default.
- Suspend/resume with NVIDIA: enable `nvidia-suspend.service nvidia-hibernate.service nvidia-resume.service` and `NVreg_PreserveVideoMemoryAllocations=1` if apps break after sleep.

## Monitors and scaling
- Layout: `~/.config/hypr/config/monitors.lua`.
- Blurry apps: XWayland apps under fractional scaling → prefer Wayland-native versions (Firefox/Electron have Wayland modes), keep `xwayland.force_zero_scaling = true`.
- Wrong refresh rate / mode: list with `hyprctl monitors all`, set `mode = "WxH@Hz"`.
- Monitor not detected after unplug/replug: `hyprctl monitors`, `hyprctl reload`, check cable/DP-MST; the fallback rule `output = ""` handles unknown monitors.

## Audio (PipeWire + WirePlumber)
- `wpctl status` (default sink/source marked with `*`), `wpctl set-default <id>`, volume keys go through `noctalia msg volume-*`.
- No sound: `systemctl --user status pipewire wireplumber pipewire-pulse`; unmute in control center or `pavucontrol`.
- Bluetooth headset: `bluetoothctl` (`power on`, `scan on`, `pair`, `connect`), or control center → Bluetooth; codec/profile in `pavucontrol` → Configuration.
- Mic: `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 80%`; `mic-mute` bound to the keyboard key.

## Network
- `nmcli device status`, `nmcli device wifi list`, `nmcli device wifi connect <SSID> --ask`, `nmcli connection show`, `nmcli connection up <name>`; GUI: control center → Wi-Fi.
- DNS problems: `resolvectl status`; VPNs: NetworkManager plugins (`networkmanager-openvpn`, `wireguard-tools`).
- Hostname: `hostnamectl set-hostname <name>`.

## Apps
- **Won't launch from the launcher**: run it in kitty; check `journalctl --user -b | grep -i <app>`; launcher runs `uwsm app -- <exec>`.
- **Missing icon/entry**: `.desktop` files live in `/usr/share/applications` and `~/.local/share/applications`; `update-desktop-database ~/.local/share/applications`.
- **Wrong default app**: `xdg-mime query default <mime>`; set with `xdg-mime default app.desktop <mime>`.
- **Electron app in X11 mode**: `ELECTRON_OZONE_PLATFORM_HINT=auto` is set; check the app's flags file (`~/.config/<app>-flags.conf`).
- **Discord screen share/audio**: use the Wayland/PipeWire-capable build (Vesktop) or Discord with the portal.
- **Steam UI issues**: `steam -forcedesktopscaling 1.5`; Proton logs `PROTON_LOG=1 %command%`.
- **Fonts look wrong**: `fc-match sans-serif`; Noctalia uses `[shell] font_family`; install Inter/Noto fonts (`ttf-inter`, `noto-fonts`, `noto-fonts-emoji`).

## Theming / Noctalia
- Colors did not update in an app: enable its template (Settings → Theme → Templates) and `noctalia msg templates-apply`; GTK apps need a restart; Firefox needs `noctalia firefox-theme install`.
- Bar disappeared: `noctalia msg bar-show`; shell crashed: `noctalia` in a terminal shows why; `~/.cache/noctalia/noctalia.log`.
- Config not applying: `noctalia config validate`; remember settings.toml (GUI) overrides config.toml.
- Cursor wrong size/theme in some apps: `XCURSOR_THEME`/`XCURSOR_SIZE` and `HYPRCURSOR_*` in `~/.config/uwsm/env`; GTK: `gsettings set org.gnome.desktop.interface cursor-theme Bibata-Modern-Ice`.

## Input & keyboard
- Layout/variant: `input.kb_layout`, `kb_variant`, `kb_options` in `inputs.lua` (e.g. `kb_options = "caps:escape"`); `noctalia msg keyboard-layout-cycle` switches.
- Keybind not working: `hyprctl binds | grep -i <key>`; conflicts with an app grabbing keys; check `hyprctl configerrors`.
- Gamepad/controller: Steam Input; `sudo pacman -S game-devices-udev`.
- Mouse acceleration: `input.accel_profile = "flat"` (set here), `sensitivity`.

## Performance
- `btop` for CPU/RAM/GPU; `nvidia-smi dmon`; `scxctl get` for the sched_ext scheduler (try `scx_lavd` for gaming via scx-manager).
- Disk full? `df -h`, `sudo btrfs filesystem usage /`, old snapshots `snapper list` (cleanup runs via timers), pacman cache `sudo paccache -r`.
- Hyprland blur/animations cost GPU time: lower `decoration.blur.passes` or disable in decorations.lua.
