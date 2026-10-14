#!/usr/bin/env bash
# Noctalia Assistant installer — idempotent, user-level (no sudo). Re-run after pulling changes.
#   1. removes the old Quickshell-based panel if present (service, links, theme template)
#   2. links the backend launcher       -> ~/.local/bin/noctalia-assistant
#   3. creates ~/.config/noctalia-assistant/{config.toml,secrets.toml}
#   4. links the Noctalia plugin         -> ~/.local/share/noctalia/plugins/assistant  and enables dadmin/assistant
#   5. puts the plugin's bar button on the bar ([widget.assistant] in ~/.config/noctalia/config.toml, backup kept)
#   6. adds ~/.config/hypr/config/assistant.lua (Super + I) and requires it from hyprland.lua (backup kept)
#   7. installs an "Assistant" launcher entry
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}"
STAMP="$(date +%Y%m%d%H%M%S)"
PLUGIN_ID="dadmin/assistant"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
info() { printf '  \033[34m·\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
backup() { [ -f "$1" ] && cp -a "$1" "$1.bak.noctalia-assistant.$STAMP" && info "backup: $1.bak.noctalia-assistant.$STAMP" || true; }
running() { pgrep -x noctalia >/dev/null; }

echo "Noctalia Assistant — install from $HERE"
NCONF="$CFG/noctalia/config.toml"
NSET="$STATE/noctalia/settings.toml"

# 1. Migrate away from the Quickshell build (v0.1) -------------------------------------------
if [ -f "$CFG/systemd/user/noctalia-assistant.service" ]; then
  systemctl --user disable --now noctalia-assistant.service >/dev/null 2>&1 || true
  rm -f "$CFG/systemd/user/noctalia-assistant.service"
  systemctl --user daemon-reload
  ok "removed the old Quickshell service"
fi
if [ -L "$CFG/quickshell/noctalia-assistant" ]; then
  rm -f "$CFG/quickshell/noctalia-assistant"
  rmdir "$CFG/quickshell" 2>/dev/null || true
  ok "removed the old Quickshell config link"
fi
if [ -f "$CFG/noctalia/templates/noctalia-assistant.json" ]; then
  rm -f "$CFG/noctalia/templates/noctalia-assistant.json"
  rmdir "$CFG/noctalia/templates" 2>/dev/null || true
  rm -f "$CFG/noctalia-assistant/theme.json"
  ok "removed the old theme template (the plugin follows Noctalia's palette directly)"
fi

# 2. Backend launcher ------------------------------------------------------------------------
mkdir -p "$HOME/.local/bin"
ln -sfn "$HERE/backend/bin/noctalia-assistant" "$HOME/.local/bin/noctalia-assistant"
ok "backend: ~/.local/bin/noctalia-assistant"

# 3. Config + secrets ------------------------------------------------------------------------
mkdir -p "$CFG/noctalia-assistant" "$STATE/noctalia-assistant"
if [ ! -f "$CFG/noctalia-assistant/config.toml" ]; then
  cp "$HERE/config/config.example.toml" "$CFG/noctalia-assistant/config.toml"
  ok "config: $CFG/noctalia-assistant/config.toml (defaults)"
else
  info "config exists: $CFG/noctalia-assistant/config.toml"
fi
if [ ! -f "$CFG/noctalia-assistant/secrets.toml" ]; then
  ( umask 077; printf '# LiteLLM API key for the Noctalia Assistant. Keep this file private (mode 600).\napi_key = ""\n' > "$CFG/noctalia-assistant/secrets.toml" )
fi
chmod 600 "$CFG/noctalia-assistant/secrets.toml"

# 4. Noctalia plugin -------------------------------------------------------------------------
mkdir -p "$DATA/noctalia/plugins"
ln -sfn "$HERE/plugin" "$DATA/noctalia/plugins/assistant"
ok "plugin: $DATA/noctalia/plugins/assistant -> $HERE/plugin"
noctalia plugins lint "$HERE/plugin" >/dev/null && ok "plugin lint passed" || warn "plugin lint reported problems: noctalia plugins lint $HERE/plugin"
if running; then
  noctalia msg config-reload >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do   # the local source is rescanned asynchronously
    noctalia msg plugins list 2>/dev/null | grep -q "^$PLUGIN_ID " && break
    sleep 1
  done
  if noctalia msg plugins list 2>/dev/null | grep -q "^$PLUGIN_ID .*disabled"; then
    noctalia msg plugins enable "$PLUGIN_ID" >/dev/null && ok "plugin enabled: $PLUGIN_ID"
  elif noctalia msg plugins list 2>/dev/null | grep -q "^$PLUGIN_ID "; then
    info "plugin already enabled"
  else
    warn "Noctalia does not list $PLUGIN_ID yet; enable it later in Settings → Plugins"
  fi
else
  warn "Noctalia is not running; enable the plugin later with: noctalia msg plugins enable $PLUGIN_ID"
fi

# 5. Bar button ------------------------------------------------------------------------------
if [ -f "$NCONF" ]; then
  if grep -q 'Noctalia Assistant integration\|Noctalia Assistant (plugin' "$NCONF"; then
    current_type=$(sed -n '/^\[widget.assistant\]/,/^\[/p' "$NCONF" | grep -m1 '^type' || true)
  else
    current_type=""
  fi
  if [ "$current_type" != 'type = "dadmin/assistant:button"' ]; then
    backup "$NCONF"
    tmp="$(mktemp)"
    python3 - "$NCONF" "$tmp" <<'PY'
import re, sys, pathlib
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
s = src.read_text()
s = re.sub(r'\n*# --- Noctalia Assistant integration.*?# --- end Noctalia Assistant integration -+\n', '\n', s, flags=re.S)
s = re.sub(r'\n*# --- Noctalia Assistant \(plugin.*?# --- end Noctalia Assistant -+\n', '\n', s, flags=re.S)
block = ('\n# --- Noctalia Assistant (plugin dadmin/assistant, added by noctalia-assistant/install.sh) -----\n'
         '[widget.assistant]\n'
         'type = "dadmin/assistant:button"\n'
         '# --- end Noctalia Assistant -------------------------------------------------------------\n')
dst.write_text(s.rstrip() + '\n' + block)
PY
    if noctalia config validate "$tmp" >/dev/null 2>&1; then
      cp "$tmp" "$NCONF"; ok "bar: [widget.assistant] now uses the plugin's button"
    else
      warn "Noctalia rejected the merged config; $NCONF left unchanged"
    fi
    rm -f "$tmp"
  else
    info "bar button already configured"
  fi
fi
if [ -f "$NSET" ] && grep -qE '^\s*end\s*=\s*\[' "$NSET" && ! grep -qE '"assistant"' "$NSET"; then
  backup "$NSET"
  python3 - "$NSET" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
def add(m):
    items = [x.strip() for x in m.group(2).split(",") if x.strip()]
    spacers = [k for k, x in enumerate(items) if x.startswith('"spacer')]
    items.insert(spacers[0] + 1 if spacers else 0, '"assistant"')
    return f'{m.group(1)}[ {", ".join(items)} ]'
p.write_text(re.sub(r'(^\s*end\s*=\s*)\[([^\]]*)\]', add, s, count=1, flags=re.M))
PY
  ok "bar: 'assistant' added to the right side of the bar"
fi

# 6. Hyprland hotkey -------------------------------------------------------------------------
HYPR="$CFG/hypr"
if [ -d "$HYPR/config" ] && [ -f "$HYPR/hyprland.lua" ]; then
  if [ ! -f "$HYPR/config/assistant.lua" ] || grep -q "Installed by noctalia-assistant/install.sh" "$HYPR/config/assistant.lua"; then
    cp "$HERE/config/assistant.lua" "$HYPR/config/assistant.lua"; ok "Hyprland: $HYPR/config/assistant.lua (Super + I)"
  else
    info "Hyprland snippet was edited by you; not overwritten ($HYPR/config/assistant.lua)"
  fi
  command -v luac >/dev/null && { luac -p "$HYPR/config/assistant.lua" || warn "assistant.lua has a Lua syntax error"; }
  if ! grep -qE '^\s*require\("config\.assistant"\)' "$HYPR/hyprland.lua"; then
    backup "$HYPR/hyprland.lua"
    printf '\nrequire("config.assistant") -- Noctalia Assistant hotkey (added by noctalia-assistant/install.sh)\n' >> "$HYPR/hyprland.lua"
    ok "Hyprland: require(\"config.assistant\") added to hyprland.lua"
  fi
else
  warn "no Lua Hyprland config at $HYPR; bind a key to: noctalia msg plugin $PLUGIN_ID:brain all toggle"
fi

# 7. Launcher entry --------------------------------------------------------------------------
mkdir -p "$DATA/applications"
cp "$HERE/config/noctalia-assistant.desktop" "$DATA/applications/noctalia-assistant.desktop"
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
ok "launcher entry: Assistant (and /ask in the launcher)"

running && noctalia msg config-reload >/dev/null 2>&1 || true
echo
echo "  Next: press Super + I and enter your model server's address (and an API key if it needs one)."
echo "  Check everything:  noctalia-assistant doctor"
