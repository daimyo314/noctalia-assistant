"""Minimal OpenAI-compatible streaming client (stdlib only) and the tool-calling agent loop.

Works against a LiteLLM proxy: POST {base}/v1/chat/completions with stream=true,
server-sent events, incremental tool_calls, and Qwen's `reasoning_content` deltas.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlparse

Emit = Callable[[dict[str, Any]], None]


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None, kind: str | None = None):
        super().__init__(message)
        self.status = status
        self.kind = kind


class LLMClient:
    def __init__(self, base_url: str, api_key: str | None, timeout: float = 180.0):
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        self.base = urlparse(url)
        if self.base.scheme not in ("http", "https") or not self.base.hostname:
            raise LLMError(f"invalid base_url: {base_url!r}")
        self.api_key = api_key
        self.timeout = timeout

    # -- transport -----------------------------------------------------------------
    def _connect(self, timeout: float | None = None) -> http.client.HTTPConnection:
        host = self.base.hostname or "localhost"
        port = self.base.port
        cls = http.client.HTTPSConnection if self.base.scheme == "https" else http.client.HTTPConnection
        return cls(host, port, timeout=timeout or self.timeout)

    def _path(self, suffix: str) -> str:
        return (self.base.path.rstrip("/") + "/v1" + suffix) or ("/v1" + suffix)

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": "noctalia-assistant/0.1"}
        if json_body:
            h["Content-Type"] = "application/json"
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _error_from(status: int, body: bytes) -> LLMError:
        text = body.decode("utf-8", "replace").strip()
        try:
            data = json.loads(text)
            msg = data.get("error", {}).get("message") if isinstance(data, dict) else None
            if msg:
                text = str(msg)
        except json.JSONDecodeError:
            pass
        text = text[:400]
        if status in (401, 403):
            return LLMError("The server needs an API key, or rejected the saved one. Set it under Connection in the model menu.", status, kind="key")
        elif status == 404:
            text = "Model or route not found (404). Pick another model or check base_url. " + text
        elif status == 400 and "model" in text.lower() and ("invalid" in text.lower() or "not found" in text.lower()):
            return LLMError("The server doesn't offer this model. Choose another one from the model menu.", 400, kind="model")
        return LLMError(f"HTTP {status}: {text}", status)

    # -- endpoints -----------------------------------------------------------------
    def list_models(self) -> list[str]:
        conn = self._connect(timeout=10)
        try:
            conn.request("GET", self._path("/models"), headers=self._headers())
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise self._error_from(resp.status, body)
            data = json.loads(body)
        except (OSError, http.client.HTTPException) as exc:
            raise LLMError(f"cannot reach {self.base.netloc}: {exc}") from exc
        finally:
            conn.close()
        items = data.get("data") if isinstance(data, dict) else data
        ids = [str(m.get("id")) for m in (items or []) if isinstance(m, dict) and m.get("id")]
        return sorted(set(ids), key=str.lower)

    def stream_chat(self, payload: dict[str, Any], cancel: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        conn = self._connect()
        try:
            try:
                conn.request("POST", self._path("/chat/completions"), body=body, headers=self._headers(True))
                resp = conn.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                raise LLMError(f"cannot reach {self.base.netloc}: {exc}") from exc
            if resp.status != 200:
                raise self._error_from(resp.status, resp.read())
            ctype = resp.getheader("Content-Type", "")
            if "text/event-stream" not in ctype:
                # Non-streaming fallback: emit the whole completion as one chunk.
                data = json.loads(resp.read() or b"{}")
                for choice in data.get("choices", []):
                    msg = choice.get("message", {})
                    yield {"choices": [{"index": 0, "delta": msg, "finish_reason": choice.get("finish_reason")}]}
                return
            while True:
                if cancel is not None and cancel.is_set():
                    return
                try:
                    line = resp.readline()
                except (OSError, http.client.HTTPException) as exc:
                    raise LLMError(f"stream interrupted: {exc}") from exc
                if not line:
                    return
                line = line.strip()
                if not line or line.startswith(b":"):
                    continue
                if line.startswith(b"data:"):
                    chunk = line[5:].strip()
                    if chunk == b"[DONE]":
                        return
                    try:
                        yield json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
        finally:
            conn.close()


# -- agent loop ----------------------------------------------------------------------
def _parse_args(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {"value": val}
    except json.JSONDecodeError:
        # Some models emit two concatenated JSON objects or trailing junk; salvage the first object.
        depth, start = 0, None
        for i, ch in enumerate(raw):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        val = json.loads(raw[start:i + 1])
                        return val if isinstance(val, dict) else {"value": val}
                    except json.JSONDecodeError:
                        break
        return {"_raw": raw}


def run_agent(
    client: LLMClient,
    model: str,
    messages: list[dict[str, Any]],
    tools_schema: list[dict[str, Any]] | None,
    exec_tool: Callable[[str, dict[str, Any]], str],
    emit: Emit,
    cancel: threading.Event,
    *,
    max_rounds: int = 8,
    temperature: float = 0.4,
    max_tokens: int = 3000,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Drive one assistant turn, executing tool calls until the model answers.

    `messages` is mutated in place (assistant/tool messages appended).
    Returns (final_text, cancelled).
    """
    full_text = ""
    for _round in range(max_rounds + 1):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools_schema:
            payload["tools"] = tools_schema
            payload["tool_choice"] = "auto"
        if extra_body:
            payload.update(extra_body)

        content = ""
        tool_calls: dict[int, dict[str, str]] = {}
        finish: str | None = None
        started = time.monotonic()
        for chunk in client.stream_chat(payload, cancel):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            ch = choices[0]
            delta = ch.get("delta") or {}
            text = delta.get("content")
            if text:
                content += text
                full_text += text
                emit({"type": "delta", "text": text})
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                emit({"type": "reasoning_delta", "text": reasoning})
            for tc in delta.get("tool_calls") or []:
                idx = int(tc.get("index", 0) or 0)
                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    # names normally arrive whole; tolerate servers that split them into fragments
                    slot["name"] = fn["name"] if (not slot["name"] or fn["name"].startswith(slot["name"])) else slot["name"] + fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
        if cancel.is_set():
            return full_text, True

        if not tool_calls:
            messages.append({"role": "assistant", "content": content})
            return full_text, False

        calls = []
        for i, tc in sorted(tool_calls.items()):
            calls.append({
                "id": tc["id"] or f"call_{int(started)}_{i}",
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
            })
        messages.append({"role": "assistant", "content": content or None, "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            args = _parse_args(call["function"]["arguments"])
            emit({"type": "tool_call", "id": call["id"], "name": name, "args": args})
            if cancel.is_set():
                return full_text, True
            try:
                result = exec_tool(name, args)
            except Exception as exc:  # tool bugs must not kill the turn
                result = f"tool error: {exc}"
            emit({"type": "tool_result", "id": call["id"], "name": name, "result": result[:600]})
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": result})
        _ = finish
    emit({"type": "notice", "text": "Stopped after too many tool calls in one turn."})
    return full_text, False
