"""End-to-end tests for the CLI the Noctalia plugin drives: `turn`, `set-key`, `history`, `info`, `models`.
Each test runs the real launcher in a subprocess against a throwaway config/state directory and a fake
streaming LiteLLM server. Run:  python3 -m unittest discover -s tests -v   (from the project root)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "backend" / "bin" / "noctalia-assistant"


class FakeServer(BaseHTTPRequestHandler):
    """model "slow": 200 one-word chunks, 50 ms apart. Otherwise: one tool round (knowledge list), then an answer."""

    def log_message(self, *a):
        pass

    def _sse(self, chunks, delay=0.0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for c in chunks:
                self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer test-key":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":{"message":"No api key passed in."}}'); return
        body = json.dumps({"data": [{"id": "qwen3.8"}, {"id": "qwen3.6"}, {"id": "slow"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        # Paths under /open act like Ollama/llama.cpp (no auth); everything else wants the test key.
        if not self.path.startswith("/open") and self.headers.get("Authorization") != "Bearer test-key":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":{"message":"No api key passed in."}}'); return
        d = lambda delta, fin=None: {"choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}  # noqa: E731
        if payload["model"] == "slow":
            self._sse([d({"content": f"word{i} "}) for i in range(200)] + [d({}, "stop")], delay=0.05)
            return
        if not any(m.get("role") == "tool" for m in payload["messages"]):
            self._sse([
                d({"reasoning_content": "Check the guide. "}),
                d({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "knowledge", "arguments": '{"action": "list"}'}}]}),
                d({}, "tool_calls"),
            ])
        else:
            self._sse([d({"content": "Use "}), d({"content": "`sudo pacman -Syu`."}), d({}, "stop")])


class Env:
    def __init__(self, port: int | None, key: str | None = "test-key", path: str = ""):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.config = base / "config"; self.config.mkdir()
        self.state = base / "state"; self.state.mkdir()
        self.run_dir = base / "run"; self.run_dir.mkdir()
        url = f"http://127.0.0.1:{port}{path}" if port else "http://127.0.0.1:9"
        (self.config / "config.toml").write_text(f'[llm]\nbase_url = "{url}"\nfallback_models = ["qwen3.6", "qwen3.8"]\n')
        if key:
            (self.config / "secrets.toml").write_text(f'api_key = "{key}"\n')
        self.env = {**os.environ, "NOCTALIA_ASSISTANT_CONFIG_DIR": str(self.config), "NOCTALIA_ASSISTANT_STATE_DIR": str(self.state)}
        self.env.pop("LITELLM_API_KEY", None)

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(LAUNCHER), *args], capture_output=True, text=True, env=self.env, timeout=60)

    def request(self, **req) -> Path:
        p = self.run_dir / f"request-{time.monotonic_ns()}.json"
        p.write_text(json.dumps(req))
        return p

    def turn(self, **req) -> list[dict]:
        p = self.request(**req)
        out = self.cli("turn", "--request", str(p))
        self.assert_clean = not p.exists()
        return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]

    def close(self):
        self.tmp.cleanup()


class TestTurnCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.e = Env(self.port)

    def tearDown(self):
        self.e.close()

    def test_tool_turn_streams_and_saves(self):
        events = self.e.turn(text="how do I update?", model="qwen3.6")
        self.assertTrue(self.e.assert_clean, "request file must be deleted")
        types = [ev["type"] for ev in events]
        self.assertEqual(types[0], "turn_start")
        self.assertEqual(types[-1], "turn_end")
        self.assertIn("reasoning_delta", types)
        call = next(ev for ev in events if ev["type"] == "tool_call")
        self.assertEqual((call["name"], call["summary"]), ("knowledge", "list"))
        self.assertTrue(next(ev for ev in events if ev["type"] == "tool_result")["ok"])
        self.assertEqual("".join(ev["text"] for ev in events if ev["type"] == "delta"), "Use `sudo pacman -Syu`.")
        end = events[-1]
        self.assertFalse(end["cancelled"]); self.assertIsNone(end["error"]); self.assertFalse(end["need_key"])
        cid = events[0]["conversation_id"]
        shown = json.loads(self.e.cli("history", "show", str(cid), "--json").stdout)
        self.assertEqual([m["role"] for m in shown["messages"]], ["user", "assistant"])
        self.assertEqual(shown["messages"][1]["tools"], [{"name": "knowledge", "summary": "list"}])
        # a follow-up in the same conversation sends the earlier turns as context
        events2 = self.e.turn(text="and then?", model="qwen3.6", conversation_id=cid)
        self.assertEqual(events2[0]["conversation_id"], cid)
        listed = json.loads(self.e.cli("history", "list", "--json").stdout)
        self.assertEqual(listed[0]["count"], 4)

    def test_sigterm_cancels_and_keeps_partial(self):
        p = self.e.request(text="long answer please", model="slow")
        proc = subprocess.Popen([str(LAUNCHER), "turn", "--request", str(p)], stdout=subprocess.PIPE, text=True, env=self.e.env)
        events = []
        for line in proc.stdout:
            events.append(json.loads(line))
            if sum(1 for ev in events if ev["type"] == "delta") == 5:
                proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)
        proc.stdout.close()
        self.assertEqual(events[-1]["type"], "turn_end")
        self.assertTrue(events[-1]["cancelled"])
        partial = "".join(ev["text"] for ev in events if ev["type"] == "delta")
        self.assertTrue(partial.startswith("word0 word1 word2 word3 word4"))
        self.assertLess(len(partial.split()), 200, "stream must stop early")
        shown = json.loads(self.e.cli("history", "show", str(events[0]["conversation_id"]), "--json").stdout)
        self.assertTrue(shown["messages"][-1]["cancelled"])
        self.assertEqual(shown["messages"][-1]["content"], partial)

    def test_missing_key_asks_for_one(self):
        e = Env(self.port, key=None)
        try:
            events = e.turn(text="hi", model="qwen3.6")
            self.assertTrue(events[-1]["need_key"])
            self.assertIn("API key", events[-1]["error"])
            from importlib import import_module  # the failed turn must not be fed back to the model as context
            sys.path.insert(0, str(ROOT / "backend"))
            os.environ["NOCTALIA_ASSISTANT_STATE_DIR"] = str(e.state)
            try:
                import importlib
                cfgmod = importlib.reload(import_module("noctalia_assistant.config"))
                hist_mod = importlib.reload(import_module("noctalia_assistant.history"))
                turn_mod = importlib.reload(import_module("noctalia_assistant.turn"))
                msgs = turn_mod._build_messages(hist_mod.History(), events[0]["conversation_id"], cfgmod.load_config())
                self.assertEqual([m["role"] for m in msgs], ["system", "user"])
            finally:
                os.environ.pop("NOCTALIA_ASSISTANT_STATE_DIR", None)
        finally:
            e.close()

    def test_keyless_server_works(self):
        e = Env(self.port, key=None, path="/open")
        try:
            events = e.turn(text="how do I update?", model="qwen3.6")
            self.assertEqual("".join(ev["text"] for ev in events if ev["type"] == "delta"), "Use `sudo pacman -Syu`.")
            self.assertFalse(events[-1]["need_key"])
        finally:
            e.close()

    def test_set_server_keeps_the_rest_of_the_config(self):
        cfg = self.e.config / "config.toml"
        cfg.write_text('# my notes\n[llm]\nbase_url = "http://old:4000"  # comment\ntemperature = 0.2\n\n[tools]\nenable_web = false\n')
        out = self.e.cli("set-server", "http://new-host:11434/")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "http://new-host:11434"))
        text = cfg.read_text()
        self.assertIn('base_url = "http://new-host:11434"', text)
        self.assertIn("# my notes", text); self.assertIn("temperature = 0.2", text); self.assertIn("enable_web = false", text)
        self.assertNotIn("old:4000", text)
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["base_url"], "http://new-host:11434")
        for bad in ("ftp://x", "not a url", 'http://a"b'):
            self.assertNotEqual(self.e.cli("set-server", bad).returncode, 0, bad)
        cfg.write_text("[tools]\nenable_web = false\n")  # no [llm] section yet
        self.assertEqual(self.e.cli("set-server", "https://api.example.com").returncode, 0)
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["base_url"], "https://api.example.com")

    def test_first_model_is_picked_when_none_is_set(self):
        (self.e.config / "config.toml").write_text(f'[llm]\nbase_url = "http://127.0.0.1:{self.port}"\n')
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["model"], "")
        out = json.loads(self.e.cli("models", "--json").stdout)
        self.assertEqual(out["model"], "qwen3.6")
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["model"], "qwen3.6")

    def test_private_notes_are_loaded(self):
        notes = self.e.config / "knowledge"; notes.mkdir()
        (notes / "my-machine.md").write_text("# My machine\n\n> Notes about my own setup.\n\nThe ultrawide is HDMI-A-1.\n")
        listing = self.e.cli("tool", "knowledge", '{"action": "list"}').stdout
        self.assertIn("my-machine: Notes about my own setup.", listing)
        self.assertIn("ultrawide is HDMI-A-1", self.e.cli("tool", "knowledge", '{"action": "search", "query": "ultrawide"}').stdout)

    def test_unreachable_server_reports_error(self):
        e = Env(None)
        try:
            events = e.turn(text="hi", model="qwen3.6")
            errs = [ev for ev in events if ev["type"] == "error"]
            self.assertTrue(errs and "cannot reach" in errs[0]["message"])
            self.assertEqual(events[-1]["type"], "turn_end")
        finally:
            e.close()

    def test_set_key_is_private_and_silent(self):
        e = Env(self.port, key=None)
        try:
            src = e.run_dir / "key.txt"
            src.write_text("sk-secret-value\n")
            out = e.cli("set-key", "--from-file", str(src))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("sk-secret-value", out.stdout + out.stderr)
            self.assertFalse(src.exists())
            secrets = e.config / "secrets.toml"
            self.assertEqual(secrets.stat().st_mode & 0o777, 0o600)
            self.assertIn('api_key = "sk-secret-value"', secrets.read_text())
            info = json.loads(e.cli("info", "--json").stdout)
            self.assertTrue(info["api_key_present"])
            bad = e.run_dir / "bad.txt"
            bad.write_text('has"quote')
            self.assertNotEqual(e.cli("set-key", "--from-file", str(bad)).returncode, 0)
        finally:
            e.close()

    def test_models_and_set_model(self):
        models = json.loads(self.e.cli("models", "--json").stdout)
        self.assertEqual((models["source"], models["models"]), ("endpoint", ["qwen3.6", "qwen3.8", "slow"]))
        self.assertEqual(self.e.cli("set-model", "qwen3.8").returncode, 0)
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["model"], "qwen3.8")
        nokey = Env(self.port, key=None)
        try:
            m = json.loads(nokey.cli("models", "--json").stdout)
            self.assertEqual(m["source"], "fallback")
            self.assertIn("API key", m["error"])
        finally:
            nokey.close()

    def test_model_resolution(self):
        sys.path.insert(0, str(ROOT / "backend"))
        from noctalia_assistant.config import order_models, resolve_model
        served = ["claude-opus-5-5", "qwen3.5:9b", "qwen3.6:35b-nvfp4", "qwen3.8:27b", "qwen3.8:27b-dflash2"]
        self.assertEqual(resolve_model("qwen3.6", served), "qwen3.6:35b-nvfp4")
        self.assertEqual(resolve_model("qwen3.8", served), "qwen3.8:27b")
        self.assertEqual(resolve_model("Qwen3.8:27B", served), "qwen3.8:27b")
        self.assertIsNone(resolve_model("llama9", served))
        self.assertEqual(order_models(served, ["qwen3.6", "qwen3.8"])[:3], ["qwen3.6:35b-nvfp4", "qwen3.8:27b", "qwen3.8:27b-dflash2"])
        # models --json repairs a configured short name and remembers the real id
        out = json.loads(self.e.cli("models", "--json").stdout)
        self.assertEqual(out["model"], "qwen3.6")  # the fake server really serves "qwen3.6"
        self.e.cli("set-model", "qwen3")
        out = json.loads(self.e.cli("models", "--json").stdout)
        self.assertEqual((out["model"], out["resolved_from"]), ("qwen3.6", "qwen3"))
        self.assertEqual(json.loads(self.e.cli("info", "--json").stdout)["model"], "qwen3.6")

    def test_demo_turn_needs_no_network(self):
        e = Env(None, key=None)
        try:
            events = e.turn(demo=True)
            self.assertIn("pacman", "".join(ev["text"] for ev in events if ev["type"] == "delta"))
            self.assertFalse(events[-1]["need_key"])
        finally:
            e.close()


if __name__ == "__main__":
    unittest.main()
