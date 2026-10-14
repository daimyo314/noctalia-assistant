# Assistant (dadmin/assistant)

A Noctalia 5 plugin: a desktop assistant for CachyOS + Hyprland + Noctalia, built for someone moving from Windows.
It answers in a full-height panel on the right edge, knows this machine's real configuration (keybinds, monitors,
packages, Noctalia settings), can perform harmless shell actions (dark/light mode, open panels, volume), and suggests
system changes as commands you review and run yourself.

## Pieces

| Entry | Kind | What it does |
|---|---|---|
| `brain` | service | Owns the conversation; runs `noctalia-assistant turn` once per message and streams the reply |
| `chat` | panel | The chat sheet; closes when you click elsewhere |
| `pinned` | panel | The same chat, persistent, for following steps in another window |
| `button` | bar widget | Click toggles the panel, right-click starts a new chat, lights up while answering |
| `ask` | launcher provider | `/ask <question>` in the launcher |

## Use

- `Super + I`, the bar button, or `noctalia msg plugin dadmin/assistant:brain all toggle`
- `/ask how do I change my wallpaper` in the launcher
- Model and API key: click the model name under the title
- `noctalia msg plugin dadmin/assistant:brain all demo` streams a canned answer (no network), useful for testing

## Requirements

The Python backend from this project (`~/.local/bin/noctalia-assistant`, stdlib only) and an OpenAI-compatible
endpoint (LiteLLM). Backend settings live in `~/.config/noctalia-assistant/config.toml`.
