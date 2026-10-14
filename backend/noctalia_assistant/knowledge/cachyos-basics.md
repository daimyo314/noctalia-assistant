# CachyOS basics: packages, kernels, repos, snapshots

> What CachyOS adds on top of Arch: optimized repos, its own kernels and schedulers, chwd driver detection, Btrfs + snapper + Limine snapshots, and how to install, update and remove software safely.

## What CachyOS is
CachyOS is an Arch Linux based rolling-release distribution. Everything from the Arch wiki applies. CachyOS adds:
- **Optimized repositories** (`cachyos`, `cachyos-v3`, `cachyos-v4`, `cachyos-znver4`) with packages compiled for x86-64-v3/v4 CPUs, plus its own kernels and tools. Configured in `/etc/pacman.conf`; mirrors in `/etc/pacman.d/cachyos-mirrorlist` (and `cachyos-v3-mirrorlist`, `cachyos-v4-mirrorlist`).
- **CachyOS kernels** (`linux-cachyos` with the BORE scheduler by default, `linux-cachyos-lts`, `-bore`, `-eevdf`, `-rt-bore`, `-server`, `-hardened`). Matching NVIDIA modules are prebuilt per kernel: `linux-cachyos-nvidia-open`, `linux-cachyos-lts-nvidia-open`.
- **sched_ext schedulers** (`scx-scheds`, `scx-manager` GUI, `scxctl`): optional userspace CPU schedulers such as `scx_lavd` (gaming/latency), `scx_bpfland`, `scx_rusty`. `scxctl get` shows what is running.
- **chwd** (CachyOS Hardware Detection): installs GPU/driver profiles. `chwd -l` lists profiles, `sudo chwd -a pci` / `sudo chwd --autoconfigure` applies.
- **ananicy-cpp** (auto process priorities), **zram-generator** (compressed swap), tuned sysctls (`cachyos-settings`).
- GUI helpers: `cachyos-hello` (welcome app: apps, tweaks, links), `cachyos-kernel-manager` (install kernels, configure sched_ext), `cachyos-packageinstaller` (install curated app groups), `cachyos-rate-mirrors` (rank the fastest mirrors).
- **Btrfs by default** with `snapper` snapshots (`cachyos-snapper-support`) and `limine-snapper-sync`, so snapshots appear in the Limine boot menu and the system can be booted from a snapshot.

## pacman in one page (the package manager)
| Task | Command |
|---|---|
| Update everything (do this regularly, never partially) | `sudo pacman -Syu` |
| Install a package | `sudo pacman -S <name>` |
| Remove a package with its unneeded deps | `sudo pacman -Rns <name>` |
| Search the repos | `pacman -Ss <term>` |
| Info about a repo package | `pacman -Si <name>` |
| Info about an installed package | `pacman -Qi <name>` |
| List installed / explicitly installed | `pacman -Q` / `pacman -Qe` |
| Which package owns a file | `pacman -Qo /usr/bin/kitty` |
| Files of a package | `pacman -Ql <name>` |
| Which package provides a file (needs `sudo pacman -Fy` once) | `pacman -F <filename>` |
| Orphans (no longer needed deps) | `pacman -Qdtq` then `sudo pacman -Rns $(pacman -Qdtq)` |
| Clean old package cache | `sudo paccache -r` (keeps 3 versions) |
| Downgrade from cache | `sudo pacman -U /var/cache/pacman/pkg/<pkg-old-version>.pkg.tar.zst` |

Rules of thumb:
- **Never run `pacman -Sy <pkg>` without `u`** (partial upgrade); always `-Syu`.
- Read pacman's output: `.pacnew` files in `/etc` mean a config default changed; compare with `pacdiff` (from `pacman-contrib`).
- If a keyring/signature error appears: `sudo pacman -Sy archlinux-keyring cachyos-keyring` then `sudo pacman -Syu`.
- "unable to lock database": no other pacman is running → `sudo rm /var/lib/pacman/db.lck`.
- Slow downloads: `sudo cachyos-rate-mirrors` (or `rate-mirrors`), then retry.
- Kernel updates need a reboot to take effect; the previous kernel keeps working until then.

## AUR (Arch User Repository)
The AUR holds community build scripts, not binaries. Use an AUR helper; CachyOS ships `paru` in its repos: `sudo pacman -S paru`. Then `paru -S <name>` (searches repos + AUR), `paru -Syu` updates both. Review PKGBUILDs when prompted; AUR packages are unsupported and can break on updates. Prefer official repo or CachyOS repo packages when available. Do not run paru as root.

## Flatpak (optional)
Not installed by default here. `sudo pacman -S flatpak`, then `flatpak install flathub <app-id>`. Good for proprietary desktop apps; command-line tools belong in pacman.

## Kernels
- `uname -r` shows the running kernel. Installed kernels: `pacman -Q | grep '^linux-'`.
- Keep `linux-cachyos-lts` installed as a fallback next to `linux-cachyos`; choose at boot in the Limine menu.
- NVIDIA users: install the matching `linux-cachyos*-nvidia-open` package for each kernel (the open kernel module). `nvidia-utils` provides the userspace driver; `nvidia-smi` shows driver status.
- `cachyos-kernel-manager` is the GUI for all of this.

## Btrfs, snapper and Limine snapshots
- The root filesystem is Btrfs with subvolumes (typically `@` for `/`, `@home` for `/home`). `sudo btrfs filesystem usage /` shows real space (df can be misleading with Btrfs).
- `snapper list` (config `root`) shows snapshots; pacman hooks create pre/post snapshots around package operations; timeline snapshots may also be enabled (`/etc/snapper/configs/root`).
- To recover from a bad update: reboot, pick a snapshot in the Limine boot menu (`limine-snapper-sync` keeps the menu in sync), verify the system works, then make it permanent with `sudo snapper rollback` or the snapper-rollback tooling and reboot. Take a manual snapshot before risky changes: `sudo snapper -c root create -d "before X"`.
- Limine (bootloader) config lives in `/boot/limine.conf` (generated). CachyOS provides `/etc/default/limine` and the `limine-update` / `limine-mkinitcpio-hook` tooling; kernel parameters go there rather than editing the generated file by hand. Check which files exist before advising.

## Shell, terminal and editors
- CachyOS defaults to `fish` with `cachyos-fish-config`; this machine's login shell is whatever `echo $SHELL` prints (zsh with `cachyos-zsh-config` is common). `chsh -s /usr/bin/fish` changes it.
- Default terminal on this desktop: `kitty` (Super + Return). `btop` is the task manager; `micro`/`nano`/`vim` are terminal editors; `gnome-text-editor` is the GUI editor here.
- `sudo` runs a command as root (the user's own password). There is no separate "administrator account".

## Useful system commands
- Hardware: `lspci`, `lsusb`, `lscpu`, `free -h`, `lsblk`, `inxi -Fxz` (if installed), `sensors` (lm_sensors), `nvidia-smi`.
- Services: `systemctl status <unit>`, `systemctl --user status <unit>`, `systemctl list-units --failed`.
- Logs: `journalctl -b -p err` (errors this boot), `journalctl -b -1` (previous boot), `journalctl -u <unit> -f`.
- Disk: `df -h`, `sudo btrfs filesystem usage /`, `du -sh ~/.cache`.
- Network: `nmcli device status`, `nmcli device wifi list`, `nmcli device wifi connect <ssid> --ask`, `ip -brief addr`.
- Time/locale: `timedatectl`, `localectl`.
