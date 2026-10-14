"""CLI entry point: `noctalia-assistant <command>`.

The Noctalia plugin (dadmin/assistant) drives the agent through these commands:
  turn --request FILE           stream one chat turn as JSON lines
  info --json                   key presence, model, endpoint (no network)
  models --json                 models listed by the LiteLLM endpoint
  set-model NAME                remember the selected model
  set-server URL                set the model server address
  set-key --from-file FILE      store an API key with mode 600, then delete FILE
  history list|show|delete      conversation history (sqlite)
  run FILE                      show a suggested command, ask for Enter, run it (opened in a terminal)
Humans get: ask, doctor, context, prompt, tool.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path

from . import __version__
from . import config as cfgmod


def _print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------- plugin commands
def cmd_turn(args: argparse.Namespace) -> int:
    from .turn import run
    return run(args.request)


def cmd_info(args: argparse.Namespace) -> int:
    cfg = cfgmod.load_config()
    data = {
        "version": __version__,
        "api_key_present": cfgmod.load_api_key(cfg) is not None,
        "base_url": cfg.get("llm.base_url"),
        "model": cfgmod.current_model(cfg),
        "fallback_models": list(cfg.get("llm.fallback_models", [])),
        "config_file": str(cfgmod.CONFIG_FILE),
        "secrets_file": str(cfgmod.SECRETS_FILE),
    }
    if args.json:
        _print_json(data)
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from .llm import LLMClient, LLMError
    cfg = cfgmod.load_config()
    fallback = list(cfg.get("llm.fallback_models", []))
    out = {"model": cfgmod.current_model(cfg), "models": fallback, "source": "fallback", "error": None}
    try:
        models = LLMClient(cfg.get("llm.base_url"), cfgmod.load_api_key(cfg), timeout=10).list_models()
        if models:
            preferred = [cfg.get("llm.model") or ""] + fallback
            out.update(models=cfgmod.order_models(models, preferred), source="endpoint")
            if out["model"] not in models:
                # Not a real id on this server (or none chosen yet): use the closest match, else the first listed model.
                fixed = cfgmod.resolve_model(out["model"], models) or next(
                    (m for m in (cfgmod.resolve_model(w, models) for w in preferred) if m), None) or out["models"][0]
                if fixed:
                    out["resolved_from"] = out["model"]
                    out["model"] = fixed
                    state = cfgmod.load_state()
                    state["model"] = fixed
                    cfgmod.save_state(state)
    except LLMError as exc:
        out["error"] = str(exc)
    if args.json:
        _print_json(out)
        return 0
    if out["error"]:
        print(f"error: {out['error']}", file=sys.stderr)
    for m in out["models"]:
        print(("* " if m == out["model"] else "  ") + m)
    return 0 if not out["error"] else 1


def cmd_set_model(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not name:
        print("model name is empty", file=sys.stderr)
        return 2
    state = cfgmod.load_state()
    state["model"] = name
    cfgmod.save_state(state)
    print(name)
    return 0


def cmd_set_server(args: argparse.Namespace) -> int:
    try:
        url = cfgmod.set_base_url(args.url)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(url)
    return 0


def cmd_set_key(args: argparse.Namespace) -> int:
    src = Path(args.from_file)
    try:
        key = src.read_text().strip()
    except OSError as exc:
        print(f"cannot read key file: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            src.unlink()
        except OSError:
            pass
    try:
        cfgmod.write_api_key(key)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"saved to {cfgmod.SECRETS_FILE}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    from .history import History
    hist = History()
    if args.action == "list":
        items = hist.list(args.limit)
        if args.json:
            _print_json(items)
        else:
            for c in items:
                print(f"{c['id']:>5}  {c['count']:>3} msgs  {c['title']}")
        return 0
    if args.id is None:
        print("history show/delete needs an id", file=sys.stderr)
        return 2
    if args.action == "delete":
        hist.delete(args.id)
        return 0
    if not hist.exists(args.id):
        print(f"no conversation {args.id}", file=sys.stderr)
        return 1
    msgs = hist.messages(args.id)[-args.limit:]
    conv = next((c for c in hist.list(1000) if c["id"] == args.id), {"title": ""})
    payload = {
        "id": args.id,
        "title": conv.get("title", ""),
        "messages": [
            {"role": m["role"], "content": m["content"], "tools": m["meta"].get("tools", []),
             "error": m["meta"].get("error"), "cancelled": bool(m["meta"].get("cancelled"))}
            for m in msgs if m["role"] in ("user", "assistant")
        ],
    }
    if args.json:
        _print_json(payload)
    else:
        for m in payload["messages"]:
            print(f"--- {m['role']}\n{m['content']}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Interactive runner opened in a terminal by the panel's "Run in terminal" button."""
    path = Path(args.file)
    try:
        command = path.read_text()
    except OSError as exc:
        print(f"cannot read command file: {exc}")
        input("Press Enter to close.")
        return 2
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    bold, dim, reset = "\033[1m", "\033[2m", "\033[0m"
    print(f"{bold}The assistant suggested running:{reset}\n")
    for line in command.strip().splitlines():
        print(f"    {line}")
    print(f"\n{dim}Read it first. Press Enter to run it, or Ctrl+C to cancel.{reset}")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was run.")
        try:
            input("Press Enter to close.")
        except (KeyboardInterrupt, EOFError):
            pass
        return 1
    code = subprocess.call(["bash", "-c", command])
    print(f"\n{dim}[exit code {code}]{reset} Press Enter to close.")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    return code


# ------------------------------------------------------------------------- human commands
def cmd_context(_: argparse.Namespace) -> int:
    from .context import build_context
    print(build_context(force=True))
    return 0


def cmd_prompt(_: argparse.Namespace) -> int:
    from .prompt import system_prompt
    print(system_prompt())
    return 0


def cmd_tool(args: argparse.Namespace) -> int:
    from .tools import ToolRunner
    cfg = cfgmod.load_config()
    payload = json.loads(args.json) if args.json else {}
    print(ToolRunner(cfg).execute(args.name, payload))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """One-shot question from the terminal; streams the answer. Handy for testing without the panel."""
    from .llm import LLMClient, LLMError, run_agent
    from .prompt import system_prompt
    from .tools import ToolRunner, summarize_args
    cfg = cfgmod.load_config()
    key = cfgmod.load_api_key(cfg)
    if not key:
        print(f"no API key: put api_key = \"...\" in {cfgmod.SECRETS_FILE}", file=sys.stderr)
        return 2
    client = LLMClient(cfg.get("llm.base_url"), key, float(cfg.get("llm.timeout_seconds", 180)))
    model = args.model or cfgmod.current_model(cfg)
    tools = ToolRunner(cfg)
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": " ".join(args.text)}]

    def emit(ev: dict) -> None:
        t = ev["type"]
        if t == "delta":
            sys.stdout.write(ev["text"]); sys.stdout.flush()
        elif t == "reasoning_delta" and args.show_thinking:
            sys.stderr.write(ev["text"]); sys.stderr.flush()
        elif t == "tool_call":
            sys.stderr.write(f"\n[tool] {ev['name']}: {summarize_args(ev['name'], ev.get('args', {}))}\n")
        elif t == "tool_result":
            sys.stderr.write(f"[tool] → {ev['result'][:200].replace(chr(10), ' ')}\n")
        elif t in ("error", "notice"):
            sys.stderr.write(f"\n[{t}] {ev.get('message') or ev.get('text')}\n")

    try:
        run_agent(client, model, messages, tools.schema(), tools.execute, emit, threading.Event(),
                  max_rounds=int(cfg.get("llm.max_tool_rounds", 8)), temperature=float(cfg.get("llm.temperature", 0.4)),
                  max_tokens=int(cfg.get("llm.max_tokens", 3000)), extra_body=cfg.get("llm.extra_body") or None)
    except LLMError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    print()
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .llm import LLMClient, LLMError
    cfg = cfgmod.load_config()
    ok = True

    def row(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'ok' if good else '!!'}] {label}{(' — ' + detail) if detail else ''}")

    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10)

    print(f"noctalia-assistant {__version__}")
    row("noctalia running", run(["noctalia", "msg", "status"]).returncode == 0)
    link = cfgmod.PLUGIN_LINK
    row("plugin installed", (link / "plugin.toml").exists(), str(link))
    plugins = run(["noctalia", "msg", "plugins", "list"]).stdout
    line = next((ln for ln in plugins.splitlines() if ln.startswith(cfgmod.PLUGIN_ID + " ")), "")
    row("plugin enabled", bool(line) and "disabled" not in line, line.strip() or "not listed by noctalia")
    row("config.toml", cfgmod.CONFIG_FILE.exists(), str(cfgmod.CONFIG_FILE))
    key = cfgmod.load_api_key(cfg)
    print(f"  [--] API key {'saved' if key else 'not set (fine if your server needs none)'}")
    if cfgmod.SECRETS_FILE.exists():
        mode = oct(cfgmod.SECRETS_FILE.stat().st_mode & 0o777)
        row("secrets.toml permissions 600", mode == "0o600", mode)
    try:
        models = LLMClient(cfg.get("llm.base_url"), key, timeout=10).list_models()
        row(f"server {cfg.get('llm.base_url')}", True, f"{len(models)} models: {', '.join(models[:8])}{'...' if len(models) > 8 else ''}")
    except LLMError as exc:
        row(f"server {cfg.get('llm.base_url')}", False, f"{exc} Fix it in the panel: model menu → Connection.")
    hypr = cfgmod.HYPR_DIR / "config" / "assistant.lua"
    row("Hyprland hotkey", hypr.exists() and "dadmin/assistant" in hypr.read_text(), str(hypr))
    binds = run(["hyprctl", "binds", "-j"]).stdout
    try:
        live = any(b.get("modmask") == 64 and b.get("key") == "I" for b in json.loads(binds or "[]"))
    except json.JSONDecodeError:
        live = False
    row("Super + I bound in Hyprland", live)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="noctalia-assistant", description="Noctalia Assistant backend")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("turn", help="stream one chat turn as JSON lines (used by the Noctalia plugin)")
    t.add_argument("--request", required=True); t.set_defaults(fn=cmd_turn)
    i = sub.add_parser("info", help="key presence, model and endpoint"); i.add_argument("--json", action="store_true"); i.set_defaults(fn=cmd_info)
    m = sub.add_parser("models", help="list models from the endpoint"); m.add_argument("--json", action="store_true"); m.set_defaults(fn=cmd_models)
    sm = sub.add_parser("set-model", help="remember the selected model"); sm.add_argument("name"); sm.set_defaults(fn=cmd_set_model)
    ss = sub.add_parser("set-server", help="set the model server address ([llm] base_url in config.toml)")
    ss.add_argument("url"); ss.set_defaults(fn=cmd_set_server)
    sk = sub.add_parser("set-key", help="store the API key (mode 600) from a file, then delete the file")
    sk.add_argument("--from-file", required=True); sk.set_defaults(fn=cmd_set_key)
    h = sub.add_parser("history", help="conversation history")
    h.add_argument("action", choices=["list", "show", "delete"]); h.add_argument("id", nargs="?", type=int)
    h.add_argument("--json", action="store_true"); h.add_argument("--limit", type=int, default=40); h.set_defaults(fn=cmd_history)
    r = sub.add_parser("run", help="confirm and run a suggested command (opened in a terminal by the panel)")
    r.add_argument("file"); r.set_defaults(fn=cmd_run)

    sub.add_parser("context", help="print the live system context").set_defaults(fn=cmd_context)
    sub.add_parser("prompt", help="print the full system prompt").set_defaults(fn=cmd_prompt)
    tl = sub.add_parser("tool", help="run one tool directly, e.g. tool run_command '{\"command\":\"uname -a\"}'")
    tl.add_argument("name"); tl.add_argument("json", nargs="?"); tl.set_defaults(fn=cmd_tool)
    a = sub.add_parser("ask", help="ask one question from the terminal"); a.add_argument("text", nargs="+"); a.add_argument("--model")
    a.add_argument("--show-thinking", action="store_true"); a.set_defaults(fn=cmd_ask)
    sub.add_parser("doctor", help="check the installation").set_defaults(fn=cmd_doctor)
    args = ap.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
