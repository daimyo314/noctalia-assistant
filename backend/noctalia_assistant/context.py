"""Live system context injected into the system prompt.

Reads the real machine: CachyOS release, kernels, Hyprland + Noctalia versions, monitors, GPUs,
the user's Hyprland Lua keybinds (parsed from ~/.config/hypr/config/*.lua), Noctalia's effective
configuration, network devices and a few CachyOS specifics (snapper, limine, scx, AUR helpers).
Cached for a minute; cheap to rebuild.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

from .config import HYPR_DIR

_CACHE: dict[str, Any] = {"at": 0.0, "text": ""}


def _run(argv: list[str], timeout: float = 4.0) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"}).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _first_line(s: str) -> str:
    return s.splitlines()[0].strip() if s else ""


# ---------------------------------------------------------------------------- basics
def os_release() -> str:
    try:
        for ln in Path("/etc/os-release").read_text().splitlines():
            if ln.startswith("PRETTY_NAME="):
                return ln.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "CachyOS"


def kernels() -> dict[str, Any]:
    running = _run(["uname", "-r"])
    installed = [ln.split()[0] for ln in _run(["pacman", "-Q"]).splitlines() if ln.startswith("linux-") and "headers" not in ln and "firmware" not in ln]
    return {"running": running, "installed": installed}


def hyprland_version() -> str:
    out = _run(["hyprctl", "version", "-j"])
    try:
        data = json.loads(out)
        return data.get("tag") or data.get("version") or _first_line(_run(["hyprctl", "version"]))
    except json.JSONDecodeError:
        return _first_line(_run(["hyprctl", "version"]))


def noctalia_version() -> str:
    v = _first_line(_run(["noctalia", "--version"])) or "unknown"
    return re.sub(r"^noctalia\s+", "", v)


def monitors() -> list[dict[str, Any]]:
    out = _run(["hyprctl", "monitors", "-j"])
    try:
        mons = json.loads(out)
    except json.JSONDecodeError:
        return []
    res = []
    for m in mons:
        scale = float(m.get("scale") or 1)
        res.append({
            "name": m.get("name"), "description": (m.get("description") or "").strip(),
            "mode": f"{m.get('width')}x{m.get('height')}@{round(float(m.get('refreshRate') or 0))}",
            "logical": f"{int(m.get('width', 0) / scale)}x{int(m.get('height', 0) / scale)}", "scale": scale,
            "position": f"{m.get('x')},{m.get('y')}", "focused": bool(m.get("focused")),
            "workspace": (m.get("activeWorkspace") or {}).get("name"),
        })
    return res


def gpus() -> list[str]:
    return [re.sub(r"^\S+\s+", "", ln) for ln in _run(["lspci"]).splitlines() if re.search(r"VGA|3D|Display", ln)]


def cpu() -> str:
    for ln in _run(["lscpu"]).splitlines():
        if ln.startswith("Model name"):
            return ln.split(":", 1)[1].strip()
    return ""


def memory() -> str:
    for ln in _run(["free", "-h"]).splitlines():
        if ln.startswith("Mem:"):
            parts = ln.split()
            return f"{parts[1]} total, {parts[2]} used"
    return ""


def network() -> list[str]:
    return [ln for ln in _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"]).splitlines() if ln and not ln.startswith(("lo:", "p2p"))]


def installed(pkgs: list[str]) -> dict[str, str]:
    out = _run(["pacman", "-Q", *pkgs])
    have = {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2:
            have[parts[0]] = parts[1]
    return have


def cachyos_facts() -> dict[str, Any]:
    pk = installed(["limine", "grub", "systemd-boot", "snapper", "limine-snapper-sync", "cachyos-snapper-support", "scx-manager",
                    "scx-scheds", "ananicy-cpp", "zram-generator", "chwd", "cachyos-kernel-manager", "cachyos-hello",
                    "cachyos-packageinstaller", "cachyos-rate-mirrors", "paru", "yay", "flatpak", "octopi", "nvidia-utils",
                    "nvidia-open-dkms", "linux-cachyos-nvidia-open", "mesa", "uwsm", "kitty", "dolphin", "firefox", "noctalia-greeter",
                    "greetd", "sddm", "pipewire", "wireplumber", "networkmanager", "bluez", "steam", "wine-cachyos-opt", "proton-cachyos-slr",
                    "cachyos-gaming-meta", "quickshell", "gnome-text-editor", "visual-studio-code-bin", "discord", "btop", "satty", "hyprpicker"])
    root_fs = _run(["findmnt", "-no", "FSTYPE", "/"])
    snapper_cfgs = [ln.split("│")[0].strip() for ln in _run(["snapper", "list-configs"]).splitlines()[2:] if ln.strip()] if "snapper" in pk else []
    scx = _run(["scxctl", "get"]) if shutil.which("scxctl") else ""
    return {
        "packages": pk, "root_fs": root_fs, "snapper_configs": snapper_cfgs, "scx": scx or "n/a",
        "aur_helper": next((h for h in ("paru", "yay") if h in pk), None),
        "bootloader": next((b for b in ("limine", "grub", "systemd-boot") if b in pk), "unknown"),
        "uwsm": "uwsm" in pk, "shell": os.environ.get("SHELL", ""),
    }


# ------------------------------------------------------------------- hyprland lua parsing
def hypr_variables() -> dict[str, str]:
    env: dict[str, str] = {}
    for f in ("variables.lua", "colors.lua"):
        p = HYPR_DIR / "config" / f
        try:
            text = p.read_text()
        except OSError:
            continue
        for m in re.finditer(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*("([^"]*)"|(\d+))\s*(?:--.*)?$', text, re.M):
            env[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(4)
    return env


def _split_top(s: str, sep: str) -> list[str]:
    parts, depth, cur, i, q = [], 0, "", 0, None
    while i < len(s):
        ch = s[i]
        if q:
            cur += ch
            if ch == q and s[i - 1] != "\\":
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif depth == 0 and s.startswith(sep, i):
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return parts


def _lua_str(expr: str, env: dict[str, Any]) -> str:
    out = []
    for p in _split_top(expr.strip(), ".."):
        p = p.strip()
        if len(p) >= 2 and p[0] in "\"'" and p[-1] == p[0]:
            out.append(p[1:-1])
        elif p in env:
            out.append(str(env[p]))
        else:
            m = re.match(r"^(\w+)\s*%\s*(\d+)$", p)
            if m and m.group(1) in env:
                try:
                    out.append(str(int(env[m.group(1)]) % int(m.group(2))))
                    continue
                except ValueError:
                    pass
            out.append("{" + p + "}")
    return "".join(out)


_ACTION_MAP = [
    (r"window\.close\(", "Close window"), (r"window\.float\(", "Toggle floating"),
    (r"fullscreen\(\{\s*mode\s*=\s*1", "Maximize (keep bar)"), (r"fullscreen\(", "Fullscreen"),
    (r'layout\("togglesplit"', "Toggle split direction"), (r"window\.cycle_next", "Cycle windows"),
    (r"window\.drag\(", "Drag window (mouse)"), (r"window\.resize\(", "Resize window (mouse)"),
    (r"workspace\.toggle_special", "Toggle scratchpad (special workspace)"), (r"window\.pseudo", "Pseudo-tile"),
    (r"zoomfunction\(-", "Zoom out"), (r"zoomfunction\(", "Zoom in"), (r"exit\(", "Exit Hyprland"),
]


def _describe_action(expr: str, env: dict[str, Any]) -> str:
    e = expr.strip()
    m = re.search(r"exec_cmd\((.*)\)\s*$", e, re.S)
    if m:
        cmd = _lua_str(m.group(1), env)
        cmd = re.sub(r"^uwsm app -- ", "", cmd)
        return f"run `{cmd}`"
    for pat, desc in _ACTION_MAP:
        if re.search(pat, e):
            return desc
    m = re.search(r"focus\(\{\s*direction\s*=\s*\"(\w+)\"", e)
    if m:
        return f"Focus {m.group(1)}"
    m = re.search(r"focus\(\{\s*monitor\s*=\s*(\w+)", e)
    if m:
        target = env.get(m.group(1), m.group(1))
        return f"Focus monitor {target}" if target else f"Focus monitor ({m.group(1)} is unset — no effect)"
    m = re.search(r"focus\(\{\s*workspace\s*=\s*(.+?)\s*\}", e)
    if m:
        return f"Go to workspace {_lua_str(m.group(1), env)}"
    m = re.search(r"window\.move\(\{\s*direction\s*=\s*\"(\w)\"", e)
    if m:
        return "Move window " + {"u": "up", "d": "down", "l": "left", "r": "right"}.get(m.group(1), m.group(1))
    m = re.search(r"window\.move\(\{\s*monitor\s*=\s*(.+?)\s*\}", e)
    if m:
        target = _lua_str(m.group(1), env)
        return f"Move window to monitor {target}" if target else f"Move window to monitor ({m.group(1)} is unset — no effect)"
    m = re.search(r"window\.move\(\{\s*workspace\s*=\s*(.+?)\s*\}", e)
    if m:
        return f"Move window to workspace {_lua_str(m.group(1), env)}"
    return re.sub(r"^hl\.dsp\.", "", e)[:80]


def keybinds() -> list[dict[str, str]]:
    """Parse hl.bind(...) calls from the user's Lua config into (section, keys, action)."""
    env: dict[str, Any] = hypr_variables()
    binds: list[dict[str, str]] = []
    files = sorted((HYPR_DIR / "config").glob("*.lua")) + [HYPR_DIR / "hyprland.lua"]
    for f in files:
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        section = f.stem
        local_env = dict(env)
        i = 0
        while i < len(lines):
            ln = lines[i]
            m = re.match(r"^\s*local\s+(\w+)\s*=\s*(\"[^\"]*\"|'[^']*')\s*(?:--.*)?$", ln)
            if m:
                local_env[m.group(1)] = m.group(2)[1:-1]
            m = re.match(r"^\s*-{2,}\s*-*\s*([A-Z][A-Z &/]+?)\s*-{2,}\s*$", ln)
            if m:
                section = m.group(1).title()
            m = re.match(r"^\s*--\s*([A-Z][^-].{2,60})$", ln)
            if m and "hl." not in ln:
                section = m.group(1).strip()
            mfor = re.match(r"^\s*for\s+(\w+)\s*=\s*(\d+)\s*,\s*(\w+)\s+do", ln)
            if mfor:
                var, start, stop = mfor.group(1), int(mfor.group(2)), mfor.group(3)
                try:
                    stop_n = int(local_env.get(stop, stop))
                except ValueError:
                    stop_n = start
                block = []
                j = i + 1
                while j < len(lines) and not re.match(r"^\s*end\s*$", lines[j]):
                    block.append(lines[j])
                    j += 1
                for n in range(start, min(stop_n, 10) + 1):
                    loop_env = dict(local_env)
                    loop_env[var] = n
                    for bl in block:
                        mk = re.match(r"^\s*local\s+(\w+)\s*=\s*(.+?)\s*$", bl)
                        if mk:
                            loop_env[mk.group(1)] = _lua_str(mk.group(2), loop_env)
                        _collect_bind(bl, loop_env, section, binds)
                i = j + 1
                continue
            _collect_bind(ln, local_env, section, binds)
            i += 1
    return binds


def _collect_bind(line: str, env: dict[str, Any], section: str, out: list[dict[str, str]]) -> None:
    m = re.search(r"hl\.bind\((.*)\)\s*(?:--.*)?$", line)
    if not m:
        return
    inner = m.group(1)
    args = _split_top(inner, ",")
    if len(args) < 2:
        return
    keys = _lua_str(args[0], env).replace("+", " + ")
    keys = re.sub(r"\s+", " ", keys).strip()
    keys = keys.replace("SUPER", "Super").replace("SHIFT", "Shift").replace("CONTROL", "Ctrl").replace("ALT", "Alt")
    action = _describe_action(",".join(args[1:]), env)
    flags = ""
    if re.search(r"repeating\s*=\s*true", inner):
        flags = " (repeats while held)"
    out.append({"section": section, "keys": keys, "action": action + flags})


def keybinds_markdown() -> str:
    rows = keybinds()
    if not rows:
        return "(no hl.bind entries found under ~/.config/hypr/config)"
    out, cur = [], None
    for r in rows:
        if r["section"] != cur:
            cur = r["section"]
            out.append(f"\n**{cur}**")
        out.append(f"- `{r['keys']}` → {r['action']}")
    return "\n".join(out).strip()


# ------------------------------------------------------------------- noctalia settings
def noctalia_config() -> dict[str, Any]:
    out = _run(["noctalia", "config", "export"], timeout=6)
    try:
        return tomllib.loads(out) if out else {}
    except tomllib.TOMLDecodeError:
        return {}


def noctalia_summary(cfg: dict[str, Any]) -> str:
    if not cfg:
        return "(noctalia config export unavailable)"
    theme = cfg.get("theme", {})
    shell = cfg.get("shell", {})
    bars = {k: v for k, v in cfg.get("bar", {}).items() if isinstance(v, dict)}
    lines = [
        f"- theme: mode={theme.get('mode', 'dark')} source={theme.get('source', 'builtin')} scheme={theme.get('wallpaper_scheme', '')} builtin={theme.get('builtin', '')}",
        f"- templates enabled: {', '.join(theme.get('templates', {}).get('builtin_ids', []))}; user templates: {', '.join(theme.get('templates', {}).get('user', {}).keys()) or 'none'}",
        f"- ui_scale={cfg.get('accessibility', {}).get('ui_scale', 1.0)} font_family={shell.get('font_family', 'sans-serif')} panel transparency={shell.get('panel', {}).get('transparency_mode', 'solid')}",
        f"- wallpaper dir: {cfg.get('wallpaper', {}).get('directory', '~/Pictures/Wallpapers')}",
    ]
    for name, b in bars.items():
        lines.append(f"- bar '{name}': position={b.get('position', 'top')} thickness={b.get('thickness', 30)} start={b.get('start', [])} center={b.get('center', [])} end={b.get('end', [])}")
    widgets = {k: v for k, v in cfg.get("widget", {}).items() if isinstance(v, dict) and v.get("type") == "custom_button"}
    if widgets:
        lines.append("- custom bar buttons: " + "; ".join(f"{k} ({v.get('label') or v.get('glyph')}: {v.get('actions', {}).get('left', '')})" for k, v in widgets.items()))
    plugins = _run(["noctalia", "msg", "plugins", "list"])
    enabled = [ln.split()[0] for ln in plugins.splitlines() if ln.strip() and "disabled" not in ln]
    lines.append(f"- enabled plugins: {', '.join(enabled) if enabled else 'none'}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------ build
def build_context(force: bool = False) -> str:
    now = time.time()
    if not force and _CACHE["text"] and now - _CACHE["at"] < 60:
        return _CACHE["text"]
    k = kernels()
    facts = cachyos_facts()
    pk = facts["packages"]
    hv = hypr_variables()
    mons = monitors()
    ncfg = noctalia_config()
    nv_pkg = next((p for p in pk if p.startswith("nvidia")), None)
    lines = [
        f"### Machine ({os.uname().nodename}, user {os.environ.get('USER', '')})",
        f"- OS: {os_release()} (Arch-based, rolling). Running kernel: {k['running']}. Installed kernels: {', '.join(k['installed']) or 'unknown'}",
        f"- CPU: {cpu()}; RAM: {memory()}",
        f"- GPUs: {'; '.join(gpus()) or 'unknown'}" + (f" — NVIDIA driver {pk[nv_pkg]}" if nv_pkg else ""),
        f"- Root filesystem: {facts['root_fs']}; snapper configs: {', '.join(facts['snapper_configs']) or 'none'}; bootloader: {facts['bootloader']}"
        + ("; limine-snapper-sync installed (snapshots bootable from the Limine menu)" if "limine-snapper-sync" in pk else ""),
        f"- Scheduler (sched_ext): {facts['scx']}; ananicy-cpp: {'yes' if 'ananicy-cpp' in pk else 'no'}; zram: {'yes' if 'zram-generator' in pk else 'no'}",
        f"- AUR helper: {facts['aur_helper'] or 'NONE installed (suggest `sudo pacman -S paru` — paru is in the CachyOS repos)'}; flatpak: {'yes' if 'flatpak' in pk else 'not installed'}",
        f"- Login shell: {facts['shell']}; terminal: {hv.get('TERMINAL', 'kitty')}; file manager: {hv.get('FILE_MANAGER', '?')}; browser: {hv.get('BROWSER', '?')}; editor: {hv.get('EDITOR', '?')}",
        f"- Session: Hyprland {hyprland_version()} (Lua config in ~/.config/hypr/hyprland.lua + ~/.config/hypr/config/*.lua){' launched through UWSM (apps run as systemd user units)' if facts['uwsm'] else ''}",
        f"- Desktop shell: Noctalia {noctalia_version()} (native Wayland shell; config ~/.config/noctalia/config.toml, GUI settings in ~/.local/state/noctalia/settings.toml); greeter: {'noctalia-greeter' if 'noctalia-greeter' in pk else 'other'}",
        f"- Network: {', '.join(network()) or 'unknown'}",
        f"- Workspaces per monitor (NUM_WPM): {hv.get('NUM_WPM', '?')}; monitors defined: {hv.get('MONITOR1', '')} {hv.get('MONITOR2', '')}",
        "",
        "### Monitors (hyprctl)",
    ]
    for m in mons:
        lines.append(f"- {m['name']}: {m['description']} — {m['mode']} scale {m['scale']} → logical {m['logical']} at {m['position']}{' (focused)' if m['focused'] else ''}, workspace {m['workspace']}")
    lines += ["", "### Noctalia configuration (effective)", noctalia_summary(ncfg), "", "### Hyprland keybinds (parsed from the user's Lua config)", keybinds_markdown()]
    text = "\n".join(lines)
    _CACHE.update(at=now, text=text)
    return text
