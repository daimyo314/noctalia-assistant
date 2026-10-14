# Noctalia Assistant

A desktop assistant that is part of the CachyOS **Noctalia** desktop: a native Noctalia 5 plugin panel on the
right edge (`Super + I`), themed and animated by Noctalia itself, backed by a focused agent that runs on the model
server of your choice and knows *your* machine (its real keybinds, monitors, packages and Noctalia configuration).
It is built to help people moving from Windows.

```
 Super + I ─► noctalia msg plugin dadmin/assistant:brain all toggle
                         │
 ┌─ Noctalia 5 (native shell) ─────────────────────────────────────────────────┐
 │  plugin dadmin/assistant                                                    │
 │   brain  (service) ── owns the chat, publishes noctalia.state ──┐           │
 │   chat / pinned (panels) ◄── render ui.* trees ◄────────────────┘           │
 │   button (bar widget) · ask (launcher: /ask …)                              │
 └──────────────┬──────────────────────────────────────────────────────────────┘
                │ runStream: one process per message, JSON lines on stdout
 ┌──────────────▼──────────────────────────────────────────────────────────────┐
 │ backend/  noctalia-assistant turn  (python, stdlib only)                    │
 │ live context · guarded tools · knowledge base · sqlite history              │
 └──────────────┬──────────────────────────────────────────────────────────────┘
                ▼ OpenAI-compatible streaming
        your model server: LiteLLM, Ollama, vLLM, llama.cpp, LM Studio, OpenAI, …
```

## Install

```bash
~/myagent_home/noctalia-assistant/install.sh
```

No packages and no sudo: Noctalia 5 runs the plugin, and the backend uses only Python's standard library.
The installer is idempotent. It also removes the earlier Quickshell-based build if it finds it. It links the plugin
into `~/.local/share/noctalia/plugins/assistant` and enables it, puts its button on the bar, adds
`~/.config/hypr/config/assistant.lua` (`Super + I`), and adds an "Assistant" launcher entry. `uninstall.sh` reverts
all of it (`--purge` also deletes config, API key and history).

Then connect it to your model server (next section). Check everything with:

```bash
noctalia-assistant doctor
```

## Connect it to your model server

The assistant works with any server that speaks the OpenAI API: a LiteLLM proxy, Ollama, vLLM, llama.cpp,
LM Studio, OpenAI, and others. On first open, the panel shows a **Connect to your model server** card.

1. Press `Super + I`.
2. Enter the **Server address**, for example `http://localhost:11434` for Ollama or `http://my-server:4000` for LiteLLM.
3. Enter an **API key** only if your server needs one, then press **Save**.
4. The model menu (click the model name under the title) lists the server's models. The first one is selected
   until you pick another.

To change it later, click the model name, then **Server and API key**. The address is stored in
`~/.config/noctalia-assistant/config.toml` (`[llm] base_url`) and the key in `secrets.toml` beside it (mode 600).
From a terminal: `noctalia-assistant set-server http://localhost:11434`.

Models that handle tool calls well give the best results, because the assistant checks your system with tools.

## Use

| Action | How |
|---|---|
| Open / close | `Super + I`, the sparkles button in the bar, "Assistant" in the launcher, `Esc` |
| Ask from the launcher | `/ask how do I change my wallpaper` |
| Send / newline / stop | `Enter` / `Shift+Enter` / the stop button (the partial answer is kept) |
| Model, server, API key | click the model name under the title |
| Keep it open while you work | the pin button (switches to a persistent panel) |
| Past conversations | the clock button |
| Run a suggested command | the terminal button on a shell code block opens a terminal that shows the command and waits for Enter |
| Panel options | Settings → Plugins → Assistant (gear): show thinking, notify when closed |

## What the agent can do

- **Sees the machine**: OS and kernels, Hyprland and Noctalia versions, monitors and scales, GPUs, network,
  snapper/Limine, the effective Noctalia config, and every `hl.bind(...)` in your Lua config, as readable keybinds.
- **Tools** (all guarded): `run_command` (read-only allowlist), `noctalia_action` (harmless `noctalia msg` UI
  actions such as theme mode, panels, wallpaper, volume and Do Not Disturb), `read_file`, `knowledge` (bundled
  articles on CachyOS, Hyprland Lua, Noctalia, Windows→Linux, troubleshooting, this desktop), and `fetch_docs`
  (CachyOS, Arch, Hyprland and Noctalia docs only).
- **Never changes the system itself**: installs, config edits and service changes come back as ```bash blocks.

## Layout

```
plugin/      Noctalia plugin: plugin.toml, service.luau, chat.luau, pinned.luau, widget.luau, launcher.luau,
             lib/panel.luau (UI), lib/common.luau, translations/en.json
backend/     python package noctalia_assistant (turn, llm, tools, context, history, prompt, knowledge/*.md)
             Private notes about your own machine go in ~/.config/noctalia-assistant/knowledge/*.md (not in the repo).
config/      Hyprland hotkey snippet, launcher entry, example backend config
dev/         mockhost.lua: runs the plugin under a mock Noctalia host and validates every UI prop/color/glyph
tests/       backend unit + end-to-end tests with a fake streaming LiteLLM server
```

## Develop

```bash
python3 -m unittest discover -s tests -v                          # backend (no model needed)
lua dev/mockhost.lua                                               # plugin under a mock host (no Luau needed)
noctalia plugins lint plugin                                       # Noctalia's own manifest/settings lint
noctalia msg plugin dadmin/assistant:brain all demo                # stream a canned answer into the live panel
grep assistant ~/.cache/noctalia/noctalia.log                      # plugin log; .luau edits hot-reload
```

Backend configuration reference: `config/config.example.toml` (`~/.config/noctalia-assistant/config.toml`).

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md). Use, copy, change and share it freely for any noncommercial purpose:
personal use, hobby projects, study, and charities, schools and public institutions. Selling it or using it to make
money is not permitted.
