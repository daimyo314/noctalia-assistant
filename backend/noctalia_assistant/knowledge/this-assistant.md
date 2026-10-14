# The assistant itself: Noctalia plugin, backend, configuration

> How this assistant is built (a native Noctalia 5 plugin plus a Python backend that talks to a LiteLLM endpoint), how to open it, change the model or API key, pin it, and debug it.

## Architecture
- **Plugin `dadmin/assistant`** (Noctalia 5 Luau plugin, installed at `~/.local/share/noctalia/plugins/assistant`, a link to the `plugin/` folder of the project checkout). Entries:
  - `brain` (service): owns the conversation; runs `~/.local/bin/noctalia-assistant turn` once per message and streams the reply.
  - `chat` (panel): the full-height sheet on the right edge; closes on Esc or a click elsewhere.
  - `pinned` (panel): the same chat as a persistent panel that stays open while you work in other windows.
  - `button` (bar widget): the sparkles icon in the bar; click toggles, right-click starts a new chat; turns to the primary color while answering.
  - `ask` (launcher provider): `/ask <question>` in the launcher.
- **Backend** `~/.local/bin/noctalia-assistant` (Python 3, stdlib only): builds the live system context (versions, monitors, parsed Hyprland keybinds, Noctalia config), calls the model with tools, stores conversations in `~/.local/state/noctalia-assistant/history.db`.
- **Model server**: any OpenAI-compatible endpoint (LiteLLM, Ollama, vLLM, llama.cpp, LM Studio, OpenAI and others), set as `[llm] base_url`. The model list comes from the server.
- **Theme**: the panel uses Noctalia's own controls and palette roles, so colors, fonts, scaling, glass transparency and animations follow Noctalia automatically. There is no separate theme file.

## Opening it
- `Super + I` (bound in `~/.config/hypr/config/assistant.lua` to `noctalia msg plugin dadmin/assistant:brain all toggle`)
- the sparkles button in the bar, "Assistant" in the launcher, or `/ask your question` in the launcher
- `noctalia msg panel-toggle dadmin/assistant:chat` opens the sheet directly

## In the panel
- Enter sends, Shift+Enter adds a line, Esc closes. The stop button cancels an answer (the partial answer is kept).
- Click the model name under the title for the model list, the connection status, **Server and API key**, and plugin settings.
- The clock icon lists past conversations (open or delete). The pin icon switches to the persistent panel.
- Code blocks have **Copy**; shell blocks also have **Run in terminal**, which opens a terminal that shows the command and waits for Enter before running it.

## Configuration
- Model server: model menu → **Server and API key** in the panel, or `noctalia-assistant set-server URL`. Any OpenAI-compatible server works (LiteLLM, Ollama, vLLM, llama.cpp, LM Studio, OpenAI). The key is optional.
- Backend: `~/.config/noctalia-assistant/config.toml` (`[llm] base_url, model, fallback_models, temperature, max_tokens, show_reasoning, extra_body`; `[tools] enabled, enable_web, command_timeout, allowed_hosts`).
- API key: `~/.config/noctalia-assistant/secrets.toml` → `api_key = "sk-..."` (mode 600), written safely by the panel.
- Private notes about this machine: `~/.config/noctalia-assistant/knowledge/*.md`, searched like the built-in articles.
- Plugin settings (Settings → Plugins → Assistant, gear): show model thinking, notify when an answer finishes while closed, backend path.
- Panel placement can be changed like any Noctalia panel in Settings → Plugins → Assistant.

## Tools the assistant can use
`run_command` (read-only allowlist), `noctalia_action` (harmless `noctalia msg` UI actions), `read_file` (config files), `knowledge` (this knowledge base), `fetch_docs` (CachyOS/Arch/Hyprland/Noctalia docs). It never runs state-changing commands itself.

## Troubleshooting
- `noctalia-assistant doctor` checks the plugin, key, endpoint and hotkey.
- `noctalia msg plugins list | grep assistant` shows whether the plugin is enabled; enable with `noctalia msg plugins enable dadmin/assistant`.
- Plugin errors appear in `~/.cache/noctalia/noctalia.log` (search for `assistant`).
- `noctalia msg plugin dadmin/assistant:brain all demo` streams a canned answer without the network, to test the panel.
- `noctalia-assistant ask "question"` answers in the terminal, bypassing the panel.
