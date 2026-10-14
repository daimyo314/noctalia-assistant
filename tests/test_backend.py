"""Backend tests without a real model: a fake SSE server exercises streaming + tool calling end to end.
Run:  cd backend && python3 -m unittest discover -s ../tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from noctalia_assistant import context, tools  # noqa: E402
from noctalia_assistant.llm import LLMClient, LLMError, run_agent  # noqa: E402


class FakeLiteLLM(BaseHTTPRequestHandler):
    """Round 1: stream a tool call (knowledge list). Round 2: stream text. Also serves /v1/models."""
    calls: list[dict] = []

    def log_message(self, *a):  # silence
        pass

    def _sse(self, chunks):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for c in chunks:
                self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):  # client cancelled mid-stream
            pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer test-key":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":{"message":"No api key passed in."}}'); return
        body = json.dumps({"data": [{"id": "qwen3.8"}, {"id": "qwen3.6"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n))
        FakeLiteLLM.calls.append(payload)
        has_tool_result = any(m.get("role") == "tool" for m in payload["messages"])
        d = lambda delta, fin=None: {"choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}  # noqa: E731
        if not has_tool_result:
            self._sse([
                d({"role": "assistant", "reasoning_content": "Let me check the KB. "}),
                d({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "knowledge", "arguments": ""}}]}),
                d({"tool_calls": [{"index": 0, "function": {"arguments": '{"action": "li'}}]}),
                d({"tool_calls": [{"index": 0, "function": {"arguments": 'st"}'}}]}),
                d({}, "tool_calls"),
            ])
        else:
            self._sse([d({"content": "Here is "}), d({"content": "the answer: `pacman -Syu`."}), d({}, "stop")])


class ServerMixin:
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeLiteLLM)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()


class TestLLM(ServerMixin, unittest.TestCase):
    def test_models_and_auth(self):
        good = LLMClient(f"http://127.0.0.1:{self.port}", "test-key")
        self.assertEqual(good.list_models(), ["qwen3.6", "qwen3.8"])
        bad = LLMClient(f"http://127.0.0.1:{self.port}/v1", None)
        with self.assertRaises(LLMError) as ctx:
            bad.list_models()
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("API key", str(ctx.exception))
        self.assertEqual(ctx.exception.kind, "key")

    def test_agent_tool_loop(self):
        FakeLiteLLM.calls.clear()
        client = LLMClient(f"http://127.0.0.1:{self.port}", "test-key")
        events: list[dict] = []
        executed: list[tuple[str, dict]] = []

        def exec_tool(name, args):
            executed.append((name, args))
            return "articles: a, b"

        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
        text, cancelled = run_agent(client, "qwen3.6", messages, tools.TOOLS_SCHEMA, exec_tool, events.append, threading.Event(), max_rounds=3)
        self.assertFalse(cancelled)
        self.assertEqual(text, "Here is the answer: `pacman -Syu`.")
        self.assertEqual(executed, [("knowledge", {"action": "list"})])
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["reasoning_delta", "tool_call", "tool_result", "delta", "delta"])
        self.assertEqual(len(FakeLiteLLM.calls), 2)
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(messages[2]["tool_calls"][0]["function"]["arguments"], '{"action": "list"}')
        self.assertIn("tools", FakeLiteLLM.calls[0])

    def test_cancel(self):
        client = LLMClient(f"http://127.0.0.1:{self.port}", "test-key")
        cancel = threading.Event()
        cancel.set()
        text, cancelled = run_agent(client, "qwen3.6", [{"role": "user", "content": "x"}], None, lambda n, a: "", lambda e: None, cancel)
        self.assertTrue(cancelled)


class TestTools(unittest.TestCase):
    def test_run_command_allow_and_deny(self):
        self.assertTrue(tools.run_command("uname -r").startswith("exit code 0"))
        self.assertIn("refused", tools.run_command("pacman -Syu"))
        self.assertIn("refused", tools.run_command("systemctl --user restart pipewire"))
        self.assertIn("refused", tools.run_command("rm -rf /"))
        self.assertIn("refused", tools.run_command("hyprctl dispatch exec kitty"))
        self.assertIn("refused", tools.run_command("nmcli connection up home"))
        self.assertIn("error", tools.run_command("cat /etc/hostname | wc -l"))
        self.assertIn("refused", tools.run_command("cat ~/.ssh/id_ed25519"))
        self.assertTrue(tools.run_command("pacman -Q hyprland").startswith("exit code"))
        self.assertTrue(tools.run_command("pacman -Ss ^kitty$").startswith("exit code"))
        self.assertIn("exit code 0", tools.run_command("cat /etc/os-release"))

    def test_read_file_guards(self):
        self.assertIn("refused", tools.read_file("~/.gnupg/pubring.kbx"))
        self.assertIn("refused", tools.read_file("/root/.bashrc"))
        out = tools.read_file("/etc/os-release", max_lines=2)
        self.assertIn("(", out)
        self.assertIn("    1  ", out)

    def test_noctalia_action_guard(self):
        self.assertIn("refused", tools.noctalia_action("session shutdown"))
        self.assertIn("refused", tools.noctalia_action("dpms-off"))
        self.assertIn("refused", tools.noctalia_action("plugins enable x/y"))
        self.assertTrue(tools.noctalia_action("noctalia msg theme-mode-get").startswith("exit code"))

    def test_knowledge(self):
        idx = tools.kb_index()
        self.assertGreaterEqual(len(idx), 6)
        self.assertIn("pacman", tools.knowledge("search", query="how do I install software").lower())
        self.assertIn("Super", tools.knowledge("read", name="windows-to-linux"))
        self.assertIn("unknown article", tools.knowledge("read", name="nope"))

    def test_fetch_docs_allowlist(self):
        self.assertIn("refused", tools.fetch_docs("https://evil.example.com/x", ["wiki.cachyos.org"]))


class TestContext(unittest.TestCase):
    def test_lua_concat(self):
        env = {"mainMod": "SUPER", "i": 3, "noctCall": "noctalia msg "}
        self.assertEqual(context._lua_str('mainMod .. " + SHIFT + " .. i % 10', env), "SUPER + SHIFT + 3")
        self.assertEqual(context._lua_str('noctCall .. "panel-toggle launcher"', env), "noctalia msg panel-toggle launcher")
        self.assertEqual(context._lua_str('"XF86AudioPlay"', env), "XF86AudioPlay")

    def test_keybinds_parse_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            cfgdir = Path(d) / "config"; cfgdir.mkdir()
            (cfgdir / "variables.lua").write_text('TERMINAL = "kitty"\nNUM_WPM = 2\nMONITOR1 = "HDMI-A-1"\n')
            (cfgdir / "binds.lua").write_text(
                'local mainMod = "SUPER"\nlocal launchPrefix = "uwsm app -- "\n'
                '---------------------------\n---- WINDOW MANAGEMENT ----\n---------------------------\n'
                'hl.bind(mainMod .. " + Q", hl.dsp.window.close())\n'
                'hl.bind(mainMod .. " + Return", hl.dsp.exec_cmd(launchPrefix .. TERMINAL))\n'
                'for i = 1, NUM_WPM do\n    local key = i % 10\n    hl.bind(mainMod .. " + ALT + " .. key, hl.dsp.focus({ workspace = i }))\nend\n'
                'hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("noctalia msg volume-up"), { locked = true, repeating = true })\n')
            (Path(d) / "hyprland.lua").write_text('require("config.binds")\n')
            old = context.HYPR_DIR
            context.HYPR_DIR = Path(d)
            try:
                binds = context.keybinds()
            finally:
                context.HYPR_DIR = old
        by_keys = {b["keys"]: b for b in binds}
        self.assertEqual(by_keys["Super + Q"]["action"], "Close window")
        self.assertEqual(by_keys["Super + Q"]["section"], "Window Management")
        self.assertEqual(by_keys["Super + Return"]["action"], "run `kitty`")
        self.assertEqual(by_keys["Super + Alt + 1"]["action"], "Go to workspace 1")
        self.assertEqual(by_keys["Super + Alt + 2"]["action"], "Go to workspace 2")
        self.assertIn("repeats", by_keys["XF86AudioRaiseVolume"]["action"])

    def test_live_context_has_machine_facts(self):
        text = context.build_context(force=True)
        self.assertIn("### Machine", text)
        self.assertIn("Hyprland keybinds", text)


if __name__ == "__main__":
    unittest.main()
