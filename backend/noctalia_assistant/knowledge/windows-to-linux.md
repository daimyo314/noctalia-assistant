# Coming from Windows: equivalents on CachyOS + Hyprland + Noctalia

> A translation table from Windows habits (Explorer, Task Manager, Control Panel, registry, .exe installers, drive letters, Win+key shortcuts) to their equivalents on this desktop.

## Keyboard: the Windows key is `Super`
| Windows | Here |
|---|---|
| Start menu / search (Win) | `Super + Space` launcher (type to search apps, files, calculator, emoji `/emo`) |
| Win + E (Explorer) | `Super + E` → Dolphin |
| Win + L (lock) | `Super + L` |
| Win + D / Win + M | no desktop to show; use workspaces or minimize-to-scratchpad `Super + Shift + S` (`Super + S` brings it back) |
| Win + Tab / Alt + Tab | `Super + Tab` window switcher / `Alt + Tab` cycle |
| Win + Ctrl + ←/→ (virtual desktops) | `Super + Ctrl + ←/→` workspaces; `Super + Ctrl + 1..3` direct |
| Win + Shift + S (snip) | `Print` region screenshot (annotate in satty), `Super + Print` full screen |
| Win + V (clipboard history) | `Super + V` |
| Win + . (emoji) | `Super + .` |
| Win + A (quick settings) / Win + N | `Super + X` control center / `Super + A` notifications |
| Win + I (Settings) | `Super + Z` Noctalia settings |
| Win + X → Task Manager, Ctrl+Shift+Esc | `Ctrl + Shift + Escape` opens `btop` in kitty |
| Win + R (Run) | `Super + Space` then type a command, or `Super + Return` terminal |
| Alt + F4 | `Super + Q` |
| Win + ↑ maximize / Win + ↓ | `Super + D` maximize (keeps the bar), `Super + F` fullscreen |
| Snap windows (Win + ←/→) | automatic tiling; `Super + Shift + arrows` move, `Super + J` toggle split direction, `Super + Alt + Space` float |
| Win + P (project/monitor) | monitors are configured in `~/.config/hypr/config/monitors.lua` (`hyprctl monitors` shows them) |
| Print Screen | same idea (`Print`) |
| Win + Plus (Magnifier) | `Super + Plus / Minus` zoom |
| Ctrl + Alt + Del | `Super + Alt + C` session panel (lock/logout/suspend/reboot/shutdown) |

## Applications and system tools
| Windows | Here |
|---|---|
| File Explorer | **Dolphin** (`Super + E`). Hidden files: `Ctrl + H`. Network shares: `smb://server/share` in the address bar. |
| Notepad | `gnome-text-editor`; in the terminal `micro`/`nano` |
| Calculator | `gnome-calculator` (`Super + C`), or type math in the launcher |
| Edge / Chrome | Firefox (`Super + W`); install others with pacman/paru |
| Task Manager | `btop` (`Ctrl + Shift + Esc`), `htop`, `ps aux`, `systemctl --user list-units` |
| Control Panel / Settings | Noctalia Settings (`Super + Z`) for the desktop; `nwg-look` (GTK look), `qt6ct` (Qt look); everything else is config files + commands |
| Device Manager | `lspci -k`, `lsusb`, `chwd -l` (driver profiles) |
| Windows Update | `sudo pacman -Syu` (everything: OS + apps), reboot only for kernel/driver updates |
| Microsoft Store / installers (.exe/.msi) | `cachyos-packageinstaller` (GUI), `sudo pacman -S <pkg>` (repos), `paru -S <pkg>` (AUR), `flatpak` (optional). Never download random .exe/.deb files. |
| Add/Remove Programs | `sudo pacman -Rns <pkg>`; list with `pacman -Qe` |
| Services (services.msc) | `systemctl` / `systemctl --user` |
| Event Viewer | `journalctl -b`, `journalctl -b -p err`, `journalctl -u <unit>` |
| Registry / Group Policy | text config files: `~/.config/<app>` for the user, `/etc` for the system |
| System Restore | snapper snapshots + Limine boot menu (boot an older snapshot) |
| Disk Management | `lsblk`, `gnome-disks`/`partitionmanager` (install), `sudo btrfs filesystem usage /` |
| Defrag / chkdsk | not needed on Btrfs/SSD; `sudo btrfs scrub start /` verifies checksums |
| Antivirus | not needed for normal desktop use; keep the system updated, install from repos |
| Command Prompt / PowerShell | kitty terminal with zsh or fish; `sudo` instead of "Run as administrator" |
| Programs & Program Files | `/usr/bin`, `/usr/lib`, `/usr/share` (managed by pacman; never edit by hand) |
| C:\Users\you | `/home/you` = `~`; Desktop/Documents/Downloads/Pictures inside |
| AppData\Roaming, Local | `~/.config` (settings), `~/.local/share` (data), `~/.cache` (cache), `~/.local/state` |
| Drive letters (C:, D:) | one tree from `/`; other disks/USB appear under `/run/media/<user>/<label>` (Dolphin sidebar) or wherever mounted; `lsblk -f` |
| Network drives | Dolphin `smb://`, `sftp://`; permanent mounts in `/etc/fstab` |
| Fonts folder | `~/.local/share/fonts` (then `fc-cache -f`) or `sudo pacman -S ttf-...` |
| Printers | CUPS: `sudo pacman -S cups system-config-printer && sudo systemctl enable --now cups` |
| Bluetooth / Wi-Fi settings | control center (`Super + X`) → Wi-Fi/Bluetooth tabs; CLI `nmcli`, `bluetoothctl` |
| Sound settings | control center → Audio; `pavucontrol` for per-app routing; `wpctl status` |
| Display settings | `monitors.lua` (Hyprland) / `hyprctl monitors`; scale instead of DPI % |
| Startup apps | `~/.config/hypr/config/autostart.lua`, or `~/.config/autostart/*.desktop` (XDG autostart via UWSM) |
| Shortcuts (.lnk) | `.desktop` files in `~/.local/share/applications` (launcher indexes them) |
| Default apps | `xdg-mime default <app>.desktop <mime>`, `xdg-settings set default-web-browser firefox.desktop`, or Dolphin → Open With → Remember |
| Environment variables | `~/.config/uwsm/env` (session), shell rc files (`~/.zshrc`, `~/.config/fish/config.fish`) |
| Wallpaper / themes | Noctalia wallpaper picker `Super + Shift + W`; palette follows the wallpaper; light/dark toggle in Settings |

## Running Windows software and games
- **Steam** (installed): enable Proton for all titles in Steam → Settings → Compatibility; `proton-cachyos` (CachyOS' tuned Proton) can be selected per game. `cachyos-gaming-meta` pulls gamemode, mangohud, gamescope, wine, winetricks, lutris deps.
- **Wine** for non-Steam Windows apps (`wine-cachyos-opt` is installed); `winecfg`, `winetricks`. **Lutris**/**Heroic**/**Bottles** (install via pacman/paru/flatpak) manage launchers and prefixes.
- Check protondb.com / areweanticheatyet.com for game compatibility; kernel anti-cheat titles usually do not run.
- Office: LibreOffice (`sudo pacman -S libreoffice-fresh`) or OnlyOffice; MS Office in a browser or via Wine (limited).
- Adobe/Autodesk generally do not run; alternatives: GIMP, Krita, Inkscape, Darktable, Blender, Kdenlive, DaVinci Resolve (native).
- Hardware: NVIDIA works with the open driver installed here (`nvidia-smi`), AMD/Intel via Mesa out of the box.

## Habits that change
- **Install from repositories**, update the whole system with one command, reboot rarely.
- **Case-sensitive paths**, forward slashes, no drive letters, hidden files start with `.`.
- **Root vs user**: use `sudo` per command; never log in as root; never `sudo` GUI apps.
- **Everything is a file**: settings live in readable text files you can back up (`~/.config`).
- **Windows tile**: stop arranging windows by hand; use workspaces per task and the scratchpad.
- **No reboot after most changes**; Hyprland and Noctalia reload configs live.
- **Terminal is a first-class tool**, not a fallback: copy `Ctrl + Shift + C`, paste `Ctrl + Shift + V` in kitty.
