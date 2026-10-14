"""Tools the agent may call.

Safety model:
  * run_command      read-only inspection only; strict per-binary allowlist, no shell, no pipes.
  * noctalia_action  harmless UI actions through `noctalia msg` (panels, theme mode, volume...).
  * read_file        text files under a few readable roots, secrets excluded.
  * knowledge        the bundled CachyOS / Hyprland / Noctalia knowledge base.
  * fetch_docs       GET on an allowlist of documentation hosts, HTML stripped to text.
Anything that changes the system (pacman -S, editing configs, systemctl enable...) is never run:
the model is instructed to propose it in a ```bash block that the UI can hand to a terminal.
"""
from __future__ import annotations

import html
import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import config as cfgmod
from .config import KNOWLEDGE_DIR

HOME = Path.home()

_SHELL_META = re.compile(r"[|;&<>`]|\$\(|\$\{|\\n")
_SECRET_HINT = re.compile(r"(secret|token|credential|passw|\.pem$|\.key$|id_(rsa|ed25519|ecdsa)|\.env$|\.netrc$|clipboard)", re.I)

READ_ROOTS = [HOME, Path("/etc"), Path("/usr"), Path("/proc"), Path("/sys"), Path("/var/log"), Path("/run/user"), Path("/boot"), Path("/opt")]
DENY_DIRS = [HOME / ".ssh", HOME / ".gnupg", HOME / ".local/share/keyrings", HOME / ".mozilla", HOME / ".config/BraveSoftware",
             HOME / ".config/google-chrome", HOME / ".pki", cfgmod.SECRETS_FILE, HOME / ".local/state/noctalia/clipboard",
             HOME / ".claude", HOME / ".config/discord", HOME / ".steam", HOME / ".local/share/Steam"]


def _path_ok(raw: str) -> tuple[bool, str]:
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    for d in DENY_DIRS:
        try:
            if rp == d or rp.is_relative_to(d):
                return False, f"access to {d} is not allowed"
        except ValueError:
            pass
    if _SECRET_HINT.search(str(rp)) and not str(rp).startswith(("/usr/", "/proc/", "/sys/")):
        return False, "path looks like it holds secrets; refusing"
    if not any(rp == r or rp.is_relative_to(r) for r in READ_ROOTS):
        return False, f"{rp} is outside the readable roots"
    return True, str(rp)


# --------------------------------------------------------------------------------------
# run_command allowlist
# --------------------------------------------------------------------------------------
PLAIN_OK = {
    "uname", "hostnamectl", "lsblk", "df", "free", "lscpu", "lspci", "lsusb", "uptime", "id", "whoami", "date",
    "which", "fc-list", "fc-match", "lsmod", "dmesg", "getent", "locale", "sensors", "glxinfo", "vulkaninfo",
    "du", "wc", "stat", "ls", "head", "tail", "cat", "grep", "find", "file", "man", "nvidia-smi", "hwinfo",
    "inxi", "Hyprland", "hyprland", "qs", "noctalia", "noctalia-greeter", "cachyos-rate-mirrors", "checkupdates",
    "scxctl", "chwd", "snapper", "btrfs", "timedatectl", "localectl", "loginctl", "wpctl", "pactl", "brightnessctl",
    "nmcli", "ip", "ss", "ping", "systemctl", "journalctl", "pacman", "paccache", "pacman-conf", "flatpak",
    "paru", "yay", "xdg-mime", "xdg-settings", "gsettings", "kreadconfig6", "cat", "printf", "echo", "true",
    "tree", "realpath", "readlink", "sha256sum", "md5sum", "lsattr", "mount", "findmnt", "swapon", "zramctl",
    "lsof", "ps", "pgrep", "top", "nproc", "arch", "env-diff", "hyprctl", "wayland-info", "xrandr", "kscreen-doctor",
    "pw-cli", "pw-dump", "bluetoothctl", "rfkill", "upower", "powerprofilesctl", "cpupower", "lshw", "smartctl",
    "vainfo", "nvidia-settings", "mkinitcpio", "limine", "bootctl", "efibootmgr", "fwupdmgr", "getfacl",
}
# per-binary verb rules: (allowed first-arg set | None), (forbidden tokens)
FORBIDDEN_TOKENS: dict[str, set[str]] = {
    "systemctl": {"start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask", "edit", "kill",
                  "daemon-reload", "daemon-reexec", "set-environment", "unset-environment", "import-environment",
                  "isolate", "poweroff", "reboot", "suspend", "hibernate", "hybrid-sleep", "halt", "set-default",
                  "reset-failed", "set-property", "revert", "link", "preset", "preset-all", "switch-root"},
    "journalctl": {"--vacuum-size", "--vacuum-time", "--vacuum-files", "--rotate", "--flush", "--sync", "--relinquish-var"},
    "nmcli": {"up", "down", "add", "delete", "modify", "clone", "edit", "connect", "disconnect", "reapply", "on", "off",
              "rescan", "hotspot", "set", "reload", "load", "import", "export", "migrate", "hostname", "permissions"},
    "ip": {"add", "del", "delete", "set", "flush", "change", "replace", "append", "prepend"},
    "snapper": {"create", "delete", "modify", "undochange", "rollback", "cleanup", "create-config", "delete-config",
                "set-config", "setup-quota", "xadiff"},
    "btrfs": {"delete", "create", "snapshot", "set-default", "resize", "balance", "defragment", "replace", "device", "scrub", "check", "rescue", "restore", "property"},
    "pacman": {"-S", "-Sy", "-Syu", "-Su", "-R", "-Rs", "-Rns", "-U", "-D", "-Sc", "-Scc", "-Syy", "-Syyu", "--sync", "--remove", "--upgrade", "--database", "--noconfirm"},
    "paru": {"-S", "-Syu", "-R", "-U", "-Sc", "--noconfirm"},
    "yay": {"-S", "-Syu", "-R", "-U", "-Sc", "--noconfirm"},
    "flatpak": {"install", "uninstall", "update", "remote-add", "remote-delete", "override", "repair", "run", "kill", "permission-set", "permission-reset", "mask", "pin"},
    "hyprctl": {"dispatch", "keyword", "reload", "kill", "setcursor", "setprop", "seterror", "notify", "switchxkblayout", "output", "plugin", "hyprpaper", "setcursor", "dismissnotify", "--batch"},
    "wpctl": {"set-volume", "set-mute", "set-default", "set-profile", "set-route", "settings", "clear-default", "set-log-level"},
    "pactl": {"set-sink-volume", "set-source-volume", "set-sink-mute", "set-source-mute", "set-default-sink", "set-default-source", "load-module", "unload-module", "move-sink-input", "suspend-sink", "exit", "set-card-profile", "set-port-latency-offset", "set-sink-port", "set-source-port"},
    "brightnessctl": {"set", "s"},
    "bluetoothctl": {"power", "pair", "connect", "disconnect", "remove", "trust", "untrust", "block", "unblock", "scan", "agent", "default-agent", "discoverable", "pairable", "advertise"},
    "rfkill": {"block", "unblock", "toggle"},
    "timedatectl": {"set-time", "set-timezone", "set-local-rtc", "set-ntp", "timesync-status"},
    "localectl": {"set-locale", "set-keymap", "set-x11-keymap"},
    "loginctl": {"lock-session", "unlock-session", "lock-sessions", "unlock-sessions", "terminate-session", "kill-session", "kill-user", "terminate-user", "enable-linger", "disable-linger", "attach", "flush-devices", "terminate-seat"},
    "upower": {"--wakeups"},
    "powerprofilesctl": {"set", "launch"},
    "cpupower": {"frequency-set", "set", "idle-set"},
    "fwupdmgr": {"update", "install", "downgrade", "activate", "unlock", "clear-results", "enable-remote", "disable-remote", "modify-remote", "modify-config", "reinstall", "switch-branch", "set-approved-firmware", "block-firmware", "unblock-firmware"},
    "efibootmgr": {"-b", "-B", "-c", "-C", "-o", "-n", "-N", "-a", "-A", "-t", "-T", "--create", "--delete-bootnum", "--bootorder", "--bootnext"},
    "limine": {"bios-install", "enroll-config"},
    "mkinitcpio": {"-p", "-P", "-g", "-k", "--preset", "--allpresets", "--generate"},
    "bootctl": {"install", "update", "remove", "set-default", "set-oneshot", "set-timeout", "set-timeout-oneshot", "random-seed", "unlink", "cleanup"},
    "find": {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"},
    "gsettings": {"set", "reset", "reset-recursively", "writable"},
    "xdg-settings": {"set"},
    "xdg-mime": {"default", "install", "uninstall"},
    "noctalia": {"--daemon", "-d", "dmenu", "firefox-theme"},
    "qs": {"kill", "call"},
    "smartctl": {"-t", "--test", "-s", "--smart", "-o", "-S", "-X"},
    "scxctl": {"start", "stop", "switch", "set"},
    "chwd": {"-i", "--install", "-r", "--remove", "-a", "--autoconfigure", "-f", "--force"},
    "nvidia-smi": {"-pm", "-e", "-p", "-r", "--gpu-reset", "-c", "-lgc", "-rgc", "-pl", "--power-limit", "-mig", "-am", "--applications-clocks", "-ac", "-rac", "--reset-applications-clocks", "-cc", "--compute-mode", "--persistence-mode"},
    "nvidia-settings": {"-a", "--assign", "-l", "--load-config-only"},
}
NOCTALIA_READ = {"status", "color-scheme-get", "theme-mode-get", "wallpaper-get", "wifi-status", "bluetooth-status",
                 "notification-dnd-status", "log-level-status", "workspace-alert-status", "plugins"}


def _validate_command(argv: list[str]) -> str | None:
    if not argv:
        return "empty command"
    prog = os.path.basename(argv[0])
    args = argv[1:]
    if prog not in PLAIN_OK:
        if len(args) == 1 and args[0] in ("--help", "-h", "--version", "-V", "-v", "help", "version"):
            return None
        return f"'{prog}' is not in the read-only allowlist. Ask the user to run it, or propose it in a bash block."
    for a in args:
        if a in FORBIDDEN_TOKENS.get(prog, set()):
            return f"'{prog} {a}' changes system state; propose it in a bash block for the user instead."
    if prog == "pacman":
        flags = [a for a in args if a.startswith("-") and not a.startswith("--")]
        for f in flags:
            body = f.lstrip("-")
            if not body:
                continue
            op = body[0]
            if op == "Q" or op == "F" or op == "T":
                continue
            if op == "S" and body[1:] and set(body[1:]) <= set("sigl") and "y" not in body and "u" not in body:
                continue
            return f"pacman {f} is not read-only; propose it in a bash block for the user instead."
        if not flags:
            return "pacman needs a query flag such as -Q, -Qi, -Ss, -Si"
    if prog in ("paru", "yay"):
        if not any(a.startswith("-Q") or a.startswith("-Ss") or a.startswith("-Si") or a.startswith("-G") for a in args):
            return f"{prog} is only allowed for -Q*/-Ss/-Si queries"
    if prog == "noctalia":
        if args[:1] == ["msg"]:
            if len(args) < 2 or args[1] not in NOCTALIA_READ:
                return "only read-only `noctalia msg` queries are allowed here; use the noctalia_action tool for UI actions"
            if args[1] == "plugins" and args[2:3] not in (["list"], ["source"]):
                return "only `noctalia msg plugins list|source list` is allowed"
        elif args[:1] == ["config"] and args[1:2] not in (["export"], ["validate"], ["settings-count"]):
            return "only `noctalia config export|validate` are allowed"
        elif args[:1] == ["theme"] and not any(a in ("--list-templates", "-h", "--help") for a in args):
            return "only `noctalia theme --list-templates` is allowed here"
    if prog == "hyprctl" and args:
        verbs = [a for a in args if not a.startswith("-")]
        if verbs and verbs[0] not in {"monitors", "clients", "workspaces", "activeworkspace", "activewindow", "binds", "version",
                                      "getoption", "devices", "layers", "splash", "cursorpos", "systeminfo", "configerrors",
                                      "globalshortcuts", "instances", "layouts", "animations", "rollinglog", "decorations", "descriptions", "workspacerules"}:
            return f"hyprctl {verbs[0]} is not a read-only query"
    if prog in ("qs",) and args[:1] not in (["list"], ["ipc"], ["--version"], ["-V"], ["log"]):
        return "only `qs list`, `qs log`, `qs ipc show` are allowed"
    if prog == "qs" and args[:1] == ["ipc"] and args[1:2] != ["show"]:
        return "only `qs ipc show` is allowed"
    if prog == "man":
        if any(a.startswith("-") and a not in ("-P", "-k", "-f", "-w", "--where") for a in args):
            return "man: only plain page lookups and -k/-f are allowed"
    if prog in ("cat", "head", "tail", "ls", "stat", "grep", "find", "wc", "file", "du", "tree", "realpath", "readlink", "sha256sum", "md5sum", "lsattr", "getfacl"):
        paths = [a for a in args if not a.startswith("-")]
        if prog == "grep" and paths:
            paths = paths[1:]  # first positional is the pattern
        if prog == "find" and paths:
            # positional path(s) come before the first predicate
            paths = [a for a in paths if not a.startswith(("-", "!", "("))]
        for pth in paths:
            if prog == "find" and pth in ("-name", "-iname", "-type", "-maxdepth"):
                continue
            if pth in ("-",):
                continue
            ok, why = _path_ok(pth)
            if not ok:
                return why
    return None


def run_command(command: str, timeout: int = 20, limit: int = 12000) -> str:
    command = (command or "").strip()
    if not command:
        return "error: empty command"
    if _SHELL_META.search(command):
        return ("error: shell operators (| ; & > < $ `) are not supported. Run one plain command per call; "
                "read-only commands only.")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"error: cannot parse command: {exc}"
    why = _validate_command(argv)
    if why:
        return f"refused: {why}"
    env = dict(os.environ)
    env.update({"PAGER": "cat", "MANPAGER": "cat", "GIT_PAGER": "cat", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0",
                "LANG": env.get("LANG", "C.UTF-8"), "NO_COLOR": "1", "TERM": "dumb"})
    env.pop("LITELLM_API_KEY", None)
    if argv[0] == "man":
        argv = ["man", "-P", "cat"] + [a for a in argv[1:] if a not in ("-P", "cat")]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL,
                              errors="replace")
    except FileNotFoundError:
        return f"error: {argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {timeout}s"
    out = proc.stdout
    if proc.stderr.strip():
        out += ("\n[stderr]\n" + proc.stderr) if out else proc.stderr
    out = out.strip() or "(no output)"
    if len(out) > limit:
        out = out[:limit] + f"\n... [truncated, {len(out) - limit} more chars]"
    return f"exit code {proc.returncode}\n{out}"


# --------------------------------------------------------------------------------------
# noctalia_action
# --------------------------------------------------------------------------------------
NOCTALIA_ACTIONS = {
    "panel-open", "panel-toggle", "panel-close", "settings-open", "settings-toggle", "settings-close", "settings-open-plugin",
    "settings-open-widget", "theme-mode-set", "theme-mode-toggle", "theme-mode-get", "color-scheme-get", "color-scheme-set",
    "templates-apply", "wallpaper-next", "wallpaper-previous", "wallpaper-random", "wallpaper-set", "wallpaper-get",
    "notification-show", "notification-dnd-set", "notification-dnd-toggle", "notification-dnd-status", "notification-clear-active",
    "osd-enable", "osd-disable", "osd-toggle", "volume-up", "volume-down", "volume-set", "volume-mute", "volume-osd",
    "mic-mute", "mic-volume-up", "mic-volume-down", "mic-volume-set", "brightness-up", "brightness-down", "brightness-set",
    "brightness-list-backlight-devices", "media", "caffeine-enable", "caffeine-disable", "caffeine-toggle",
    "nightlight-enable", "nightlight-disable", "nightlight-toggle", "nightlight-force-toggle", "bar-show", "bar-hide", "bar-toggle",
    "bar-auto-hide-set", "dock-show", "dock-hide", "dock-toggle", "desktop-widgets-show", "desktop-widgets-hide",
    "desktop-widgets-toggle", "desktop-widgets-edit", "desktop-widgets-exit", "window-switcher", "keyboard-layout-cycle",
    "wifi-enable", "wifi-disable", "wifi-toggle", "wifi-status", "bluetooth-enable", "bluetooth-disable", "bluetooth-toggle",
    "bluetooth-status", "clipboard-copy", "clipboard-text", "config-reload", "greeter-sync", "status", "power-set", "power-cycle",
    "workspace-switch", "dpms-on", "effects-profile-set", "screenshot-region", "screenshot-fullscreen", "plugins",
}


def noctalia_action(command: str, timeout: int = 15) -> str:
    command = (command or "").strip()
    if command.startswith("noctalia "):
        command = command[len("noctalia "):].strip()
    if command.startswith("msg "):
        command = command[4:].strip()
    if _SHELL_META.search(command):
        return "error: shell operators are not allowed"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"error: {exc}"
    if not argv:
        return "error: empty action"
    if argv[0] not in NOCTALIA_ACTIONS:
        return (f"refused: '{argv[0]}' is not an allowed UI action (session/power-off/dpms-off/network-toggle/plugin "
                f"management are excluded). Allowed: {', '.join(sorted(NOCTALIA_ACTIONS))}")
    if argv[0] == "plugins" and argv[1:2] not in (["list"], ["source"]):
        return "refused: only `plugins list` is allowed"
    try:
        proc = subprocess.run(["noctalia", "msg", *argv], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return "error: noctalia binary not found"
    except subprocess.TimeoutExpired:
        return "error: noctalia did not answer in time (is the shell running?)"
    out = (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()
    return f"exit code {proc.returncode}\n{out or '(done)'}"


# --------------------------------------------------------------------------------------
# read_file
# --------------------------------------------------------------------------------------
def read_file(path: str, limit: int = 20000, start_line: int = 1, max_lines: int = 400) -> str:
    ok, why = _path_ok(path)
    if not ok:
        return f"refused: {why}"
    p = Path(why)
    if p.is_dir():
        try:
            entries = sorted(os.listdir(p))
        except OSError as exc:
            return f"error: {exc}"
        return f"{p} is a directory with {len(entries)} entries:\n" + "\n".join(entries[:300])
    try:
        if p.stat().st_size > 5_000_000:
            return "error: file is larger than 5 MB"
        text = p.read_text(errors="replace")
    except OSError as exc:
        return f"error: {exc}"
    if "\x00" in text[:4000]:
        return "error: binary file"
    lines = text.splitlines()
    s = max(1, int(start_line or 1))
    chunk = lines[s - 1:s - 1 + max(1, int(max_lines or 400))]
    body = "\n".join(f"{s + i:5d}  {ln}" for i, ln in enumerate(chunk))
    if len(body) > limit:
        body = body[:limit] + "\n... [truncated]"
    more = "" if s - 1 + len(chunk) >= len(lines) else f"\n... ({len(lines) - (s - 1 + len(chunk))} more lines; call again with start_line={s + len(chunk)})"
    return f"{p} ({len(lines)} lines)\n{body}{more}"


# --------------------------------------------------------------------------------------
# knowledge base
# --------------------------------------------------------------------------------------
def _kb_articles() -> dict[str, str]:
    """Bundled articles plus the user's private notes (~/.config/noctalia-assistant/knowledge/*.md, same name wins)."""
    out: dict[str, str] = {}
    for d in (KNOWLEDGE_DIR, cfgmod.USER_KNOWLEDGE_DIR):
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                out[f.stem] = f.read_text(errors="replace")
    return out


def kb_index() -> list[tuple[str, str]]:
    """(name, first heading / summary line) for every article."""
    idx = []
    for name, text in _kb_articles().items():
        summary = ""
        for ln in text.splitlines():
            if ln.startswith("> "):
                summary = ln[2:].strip()
                break
        idx.append((name, summary))
    return idx


def knowledge(action: str = "search", name: str = "", query: str = "") -> str:
    arts = _kb_articles()
    action = (action or "search").lower()
    if action == "list":
        return "\n".join(f"- {n}: {s}" for n, s in kb_index()) or "(no articles)"
    if action == "read":
        if name not in arts:
            return f"unknown article '{name}'. Available: {', '.join(arts)}"
        return arts[name][:30000]
    q = (query or name or "").strip().lower()
    if not q:
        return "search needs a query"
    terms = [t for t in re.findall(r"[a-z0-9+#.\-]{2,}", q) if t not in {"the", "how", "do", "to", "in", "on", "is", "my", "and", "of", "for", "with", "what", "where", "can"}]
    if not terms:
        return "query too generic"
    scored: list[tuple[float, str, str]] = []
    for aname, text in arts.items():
        sections = re.split(r"\n(?=#{1,4} )", text)
        for sec in sections:
            low = sec.lower()
            score = 0.0
            for t in terms:
                c = low.count(t)
                if c:
                    score += 1 + min(c, 6) * 0.3
                    if t in low.split("\n", 1)[0]:
                        score += 1.5
            if score:
                scored.append((score, aname, sec.strip()))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "no matching knowledge; try fetch_docs on the CachyOS / Arch / Hyprland / Noctalia wiki"
    out = []
    used = 0
    for score, aname, sec in scored[:6]:
        piece = sec if len(sec) <= 2500 else sec[:2500] + "\n..."
        out.append(f"### [{aname}]\n{piece}")
        used += len(piece)
        if used > 9000:
            break
    return "\n\n".join(out)


# --------------------------------------------------------------------------------------
# fetch_docs
# --------------------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "iframe"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "tr", "table", "section", "article", "blockquote", "dd", "dt"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "pre":
            self._pre += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "pre" and self._pre:
            self._pre -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data if self._pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return html.unescape(raw).strip()


def fetch_docs(url: str, allowed_hosts: list[str], limit: int = 15000) -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        return f"refused: {host} is not an allowed documentation host ({', '.join(allowed_hosts)})"
    if host in ("github.com",) and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 noctalia-assistant/0.1", "Accept": "text/html,text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - host allowlisted above
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(1_500_000)
    except urllib.error.HTTPError as exc:
        return f"error: HTTP {exc.code} for {url}"
    except (urllib.error.URLError, OSError) as exc:
        return f"error: {exc}"
    text = data.decode("utf-8", "replace")
    if "html" in ctype or text.lstrip()[:1] == "<":
        ex = _TextExtractor()
        ex.feed(text)
        text = ex.text()
    if len(text) > limit:
        text = text[:limit] + f"\n... [truncated at {limit} chars]"
    return f"source: {url}\n\n{text}"


# --------------------------------------------------------------------------------------
# schema + dispatcher
# --------------------------------------------------------------------------------------
TOOLS_SCHEMA: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "run_command",
        "description": ("Run ONE read-only inspection command on this machine (no shell, no pipes). Allowed: pacman -Q*/-Ss/-Si, "
                        "hyprctl queries (monitors, clients, binds, getoption...), systemctl status/is-active/list-units, journalctl, "
                        "noctalia msg status|theme-mode-get|wallpaper-get, uname, lsblk, df, free, lspci, nmcli device status, "
                        "wpctl status, snapper list, cat/ls/grep/head on config files, man <page>, <cmd> --help. "
                        "Commands that change state are refused: propose those in a ```bash block instead."),
        "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "e.g. 'hyprctl monitors -j' or 'pacman -Qi kitty'"}}, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "noctalia_action",
        "description": ("Perform a harmless Noctalia shell UI action via `noctalia msg`. Examples: 'theme-mode-set light', "
                        "'theme-mode-toggle', 'panel-open control-center wifi', 'settings-open', 'wallpaper-random', "
                        "'volume-set 40', 'notification-dnd-toggle', 'notification-show \"Title\" \"Body\"', 'panel-toggle launcher'. "
                        "Use it when the user asks you to do something in the desktop shell."),
        "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "the `noctalia msg` sub-command and arguments"}}, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file (numbered lines) such as ~/.config/hypr/config/binds.lua, ~/.config/noctalia/config.toml or /etc/pacman.conf. Directories list their entries.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "first line to return (default 1)"},
            "max_lines": {"type": "integer", "description": "how many lines (default 400)"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "knowledge",
        "description": ("Search or read the built-in knowledge base about CachyOS, pacman/AUR, Hyprland (Lua config, keybinds, "
                        "window rules), Noctalia (bar, launcher, control center, theming, IPC, plugins), Windows-to-Linux equivalents "
                        "and troubleshooting. Use action='search' with a query first; 'read' a whole article when you need detail."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["search", "read", "list"]},
            "query": {"type": "string"},
            "name": {"type": "string", "description": "article name for action=read"}}, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "fetch_docs",
        "description": "Fetch a documentation page as text. Allowed hosts: wiki.cachyos.org, wiki.archlinux.org, wiki.hypr.land, docs.noctalia.dev, man.archlinux.org, aur.archlinux.org, github.com. Use for up-to-date details the knowledge base lacks.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    }},
]


class ToolRunner:
    def __init__(self, cfg: cfgmod.Config):
        self.cfg = cfg
        tools = cfg.section("tools")
        self.timeout = int(tools.get("command_timeout", 20))
        self.limit = int(tools.get("output_limit", 12000))
        self.enable_web = bool(tools.get("enable_web", True))
        self.allowed_hosts = list(tools.get("allowed_hosts", []))

    def schema(self) -> list[dict[str, Any]]:
        if not self.cfg.get("tools.enabled", True):
            return []
        return [t for t in TOOLS_SCHEMA if self.enable_web or t["function"]["name"] != "fetch_docs"]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "run_command":
            return run_command(str(args.get("command", "")), self.timeout, self.limit)
        if name == "noctalia_action":
            return noctalia_action(str(args.get("command", "")))
        if name == "read_file":
            return read_file(str(args.get("path", "")), self.limit, int(args.get("start_line") or 1), int(args.get("max_lines") or 400))
        if name == "knowledge":
            return knowledge(str(args.get("action", "search")), str(args.get("name", "")), str(args.get("query", "")))
        if name == "fetch_docs":
            if not self.enable_web:
                return "refused: web access is disabled in config.toml ([tools] enable_web)"
            return fetch_docs(str(args.get("url", "")), self.allowed_hosts, self.limit)
        return f"error: unknown tool {name}"


def summarize_args(name: str, args: dict[str, Any]) -> str:
    if name in ("run_command", "noctalia_action"):
        return str(args.get("command", ""))[:120]
    if name == "read_file":
        return str(args.get("path", ""))[:120]
    if name == "knowledge":
        return (args.get("query") or args.get("name") or args.get("action") or "")[:120]
    if name == "fetch_docs":
        return str(args.get("url", ""))[:120]
    return json.dumps(args)[:120]
