"""One assistant turn as a short-lived streaming process.

The Noctalia plugin service starts `noctalia-assistant turn --request FILE` with noctalia.runStream() and reads one
JSON object per stdout line:

  turn_start   {conversation_id, model, pid, title}
  delta        {text}                      answer text
  reasoning_delta {text}                   Qwen "thinking" text
  tool_call    {id, name, summary}
  tool_result  {id, name, ok}
  notice       {text}
  error        {message}
  turn_end     {conversation_id, cancelled, error, need_key, need_model}

The request file (written by the plugin into $XDG_RUNTIME_DIR) is deleted as soon as it is read. SIGTERM cancels the
turn: whatever was generated so far is saved to history and a turn_end with cancelled=true is still emitted.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import config as cfgmod
from .history import History
from .llm import LLMClient, LLMError, run_agent
from .prompt import system_prompt
from .tools import ToolRunner, summarize_args

class TurnCancelled(BaseException):
    """Raised from the SIGTERM handler. BaseException so generic `except Exception` blocks don't swallow it."""


class Turn:
    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.critical = False      # while True, SIGTERM only flags the cancel (never interrupts a DB write)
        self.broken_pipe = False
        self.partial = ""
        self.tools: list[dict[str, Any]] = []
        self.reasoning_chars = 0

    # -------------------------------------------------------------------- output
    def emit(self, event: dict[str, Any]) -> None:
        if self.broken_pipe:
            return
        try:
            sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            # The plugin stopped reading (shell reloaded). Finish quietly; history is still saved.
            self.broken_pipe = True
            self.cancel.set()
            try:
                sys.stdout = open(os.devnull, "w")
            except OSError:
                pass

    def agent_event(self, ev: dict[str, Any]) -> None:
        t = ev["type"]
        if t == "delta":
            self.partial += ev["text"]
        elif t == "reasoning_delta":
            self.reasoning_chars += len(ev["text"])
        elif t == "tool_call":
            summary = summarize_args(ev["name"], ev.get("args", {}))
            self.tools.append({"name": ev["name"], "summary": summary})
            ev = {"type": "tool_call", "id": ev["id"], "name": ev["name"], "summary": summary}
        elif t == "tool_result":
            res = str(ev.get("result", ""))
            ev = {"type": "tool_result", "id": ev["id"], "name": ev["name"],
                  "ok": not res.startswith(("refused", "error", "tool error"))}
        self.emit(ev)

    # -------------------------------------------------------------------- signals
    def install_signal_handler(self) -> None:
        def on_term(signum, frame):  # noqa: ARG001
            self.cancel.set()
            if not self.critical:
                raise TurnCancelled()
        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)


def _build_messages(hist: History, cid: int, cfg: cfgmod.Config) -> list[dict[str, Any]]:
    budget = int(cfg.get("llm.history_char_budget", 24000))
    prior = [m for m in hist.messages(cid)
             if m["role"] in ("user", "assistant") and not m["meta"].get("local") and m["content"].strip()]
    kept: list[dict[str, Any]] = []
    used = 0
    for m in reversed(prior):
        used += len(m["content"])
        if used > budget and kept:
            break
        kept.append({"role": m["role"], "content": m["content"]})
    kept.reverse()
    return [{"role": "system", "content": system_prompt()}, *kept]


DEMO_ANSWER = (
    "Here's how software installation works on **CachyOS** compared to Windows:\n\n"
    "- Apps come from **repositories**, not downloaded installers.\n"
    "- `pacman` installs, updates and removes everything, including the OS itself.\n"
    "- The **AUR** holds community packages; you need a helper such as `paru` for it.\n\n"
    "To install the helper and an app from the AUR:\n\n"
    "```bash\nsudo pacman -S paru\nparu -S spotify\n```\n\n"
    "Update the whole system with one command, and never run `pacman -Sy <pkg>` on its own:\n\n"
    "```bash\nsudo pacman -Syu\n```\n\n"
    "| Windows | CachyOS |\n|---|---|\n| Microsoft Store | `pacman` / `paru` |\n| Windows Update | `sudo pacman -Syu` |\n"
    "| System Restore | snapper snapshots in the boot menu |\n"
)


def _demo(turn: Turn) -> str:
    """Canned, network-free turn for testing the panel end to end (`noctalia msg plugin dadmin/assistant:brain all demo`)."""
    for chunk in ("The user is new to Arch-style package management. ", "Check which helpers exist first."):
        turn.agent_event({"type": "reasoning_delta", "text": chunk})
        time.sleep(0.15)
    turn.agent_event({"type": "tool_call", "id": "demo_1", "name": "run_command", "args": {"command": "pacman -Q paru flatpak"}})
    time.sleep(0.6)
    turn.agent_event({"type": "tool_result", "id": "demo_1", "name": "run_command", "result": "exit code 1\nerror: package 'paru' was not found"})
    words = DEMO_ANSWER.split(" ")
    for i, w in enumerate(words):
        if turn.cancel.is_set():
            break
        turn.agent_event({"type": "delta", "text": w + (" " if i < len(words) - 1 else "")})
        time.sleep(0.03)
    return turn.partial


def run(request_path: str) -> int:
    turn = Turn()
    turn.install_signal_handler()
    path = Path(request_path)
    try:
        req = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        turn.emit({"type": "error", "message": f"cannot read request: {exc}"})
        turn.emit({"type": "turn_end", "conversation_id": None, "cancelled": False, "error": str(exc)})
        return 2
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    text = str(req.get("text") or "").strip()
    demo = bool(req.get("demo"))
    if demo and not text:
        text = "How do I install software here? (demo)"
    cfg = cfgmod.load_config()
    model = str(req.get("model") or "") or cfgmod.current_model(cfg)
    hist = History()
    cid = req.get("conversation_id")
    try:
        cid = int(cid) if cid is not None else None
    except (TypeError, ValueError):
        cid = None

    turn.critical = True
    if cid is None or not hist.exists(cid):
        cid = hist.create(model)
    if text:
        hist.add_message(cid, "user", text)
    title = next((c["title"] for c in hist.list(200) if c["id"] == cid), "")
    turn.critical = False
    turn.emit({"type": "turn_start", "conversation_id": cid, "model": model, "pid": os.getpid(), "title": title})

    content, cancelled, error, need_key, need_model = "", False, None, False, False
    try:
        if not text:
            error = "empty message"
        elif demo:
            content = _demo(turn)
            cancelled = turn.cancel.is_set()
        else:
            if not model:
                need_model = True
                raise LLMError("No model is selected yet. Pick one in the model menu.", kind="model")
            # The key is optional: servers such as Ollama or llama.cpp need none. A 401 asks for one.
            client = LLMClient(cfg.get("llm.base_url"), cfgmod.load_api_key(cfg), float(cfg.get("llm.timeout_seconds", 180)))
            tools = ToolRunner(cfg)
            messages = _build_messages(hist, cid, cfg)
            content, cancelled = run_agent(
                client, model, messages, tools.schema(), tools.execute, turn.agent_event, turn.cancel,
                max_rounds=int(cfg.get("llm.max_tool_rounds", 8)),
                temperature=float(cfg.get("llm.temperature", 0.4)),
                max_tokens=int(cfg.get("llm.max_tokens", 3000)),
                extra_body=cfg.get("llm.extra_body") or None,
            )
    except TurnCancelled:
        cancelled = True
        content = turn.partial
    except LLMError as exc:
        error = str(exc)
        content = turn.partial
        if exc.kind == "key":
            need_key = True
        if exc.kind == "model":
            need_model = True
    except Exception as exc:  # keep the stream well-formed no matter what
        error = f"internal error: {exc}"
        content = turn.partial
        import traceback
        traceback.print_exc(file=sys.stderr)

    turn.critical = True
    if error:
        turn.emit({"type": "error", "message": error})
    if content.strip() or error:
        meta: dict[str, Any] = {"model": model, "tools": turn.tools, "cancelled": cancelled}
        if error:
            meta["error"] = error
        if demo:
            meta["demo"] = True
        if turn.reasoning_chars:
            meta["reasoning_chars"] = turn.reasoning_chars
        hist.add_message(cid, "assistant", content, meta)
    turn.emit({"type": "turn_end", "conversation_id": cid, "cancelled": cancelled, "error": error,
               "need_key": need_key, "need_model": need_model})
    return 0
