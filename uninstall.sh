#!/usr/bin/env bash
# Removes everything install.sh added. Keeps your conversation history, config and API key unless --purge.
set -uo pipefail
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"; DATA="${XDG_DATA_HOME:-$HOME/.local/share}"; STATE="${XDG_STATE_HOME:-$HOME/.local/state}"
pgrep -x noctalia >/dev/null && noctalia msg plugins disable dadmin/assistant >/dev/null 2>&1
rm -f "$DATA/noctalia/plugins/assistant" "$DATA/applications/noctalia-assistant.desktop" "$HOME/.local/bin/noctalia-assistant"
rm -f "$CFG/hypr/config/assistant.lua"
[ -f "$CFG/hypr/hyprland.lua" ] && sed -i '/require("config\.assistant")/d' "$CFG/hypr/hyprland.lua"
if [ -f "$CFG/noctalia/config.toml" ]; then
  python3 - "$CFG/noctalia/config.toml" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
s2 = re.sub(r'\n*# --- Noctalia Assistant \(plugin.*?# --- end Noctalia Assistant -+\n', '\n', s, flags=re.S)
s2 = re.sub(r'\n*# --- Noctalia Assistant integration.*?# --- end Noctalia Assistant integration -+\n', '\n', s2, flags=re.S)
if s2 != s: p.write_text(s2)
PY
fi
[ -f "$STATE/noctalia/settings.toml" ] && sed -i -E 's/"assistant",\s*//; s/,\s*"assistant"//' "$STATE/noctalia/settings.toml"
pgrep -x noctalia >/dev/null && noctalia msg config-reload >/dev/null 2>&1
if [ "${1:-}" = "--purge" ]; then rm -rf "$CFG/noctalia-assistant" "$STATE/noctalia-assistant"; echo "purged config, API key and history"; fi
echo "Noctalia Assistant removed."
