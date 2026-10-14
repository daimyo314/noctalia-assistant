"""Configuration, paths and secrets.

Everything lives under XDG directories:
  ~/.config/noctalia-assistant/config.toml   user configuration (merged over DEFAULTS)
  ~/.config/noctalia-assistant/secrets.toml  api_key = "..."   (mode 600, never logged)
  ~/.local/state/noctalia-assistant/         history.db, state.json
NOCTALIA_ASSISTANT_CONFIG_DIR / NOCTALIA_ASSISTANT_STATE_DIR override both (used by the tests).
"""
from __future__ import annotations

import copy
import json
import os
import tomllib
from pathlib import Path
from typing import Any

APP = "noctalia-assistant"
HOME = Path.home()
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
XDG_STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")

CONFIG_DIR = Path(os.environ.get("NOCTALIA_ASSISTANT_CONFIG_DIR") or XDG_CONFIG / APP)
STATE_DIR = Path(os.environ.get("NOCTALIA_ASSISTANT_STATE_DIR") or XDG_STATE / APP)
CONFIG_FILE = CONFIG_DIR / "config.toml"
SECRETS_FILE = CONFIG_DIR / "secrets.toml"
STATE_FILE = STATE_DIR / "state.json"
HISTORY_DB = STATE_DIR / "history.db"

NOCTALIA_CONFIG_DIR = XDG_CONFIG / "noctalia"
NOCTALIA_CONFIG = NOCTALIA_CONFIG_DIR / "config.toml"
NOCTALIA_SETTINGS = XDG_STATE / "noctalia" / "settings.toml"
HYPR_DIR = XDG_CONFIG / "hypr"

PLUGIN_ID = "dadmin/assistant"
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share")
PLUGIN_LINK = XDG_DATA / "noctalia" / "plugins" / "assistant"

PKG_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = PKG_DIR / "knowledge"
USER_KNOWLEDGE_DIR = CONFIG_DIR / "knowledge"   # private notes about this machine; not part of the project

DEFAULTS: dict[str, Any] = {
    "llm": {
        # Any OpenAI-compatible server: LiteLLM, Ollama, vLLM, llama.cpp, LM Studio, OpenAI... "/v1" is added automatically.
        # Set it from the panel (model menu → Connection) or here.
        "base_url": "http://localhost:4000",
        # Preferred model. Short names resolve to the server's ids ("qwen3.6" → "qwen3.6:35b-nvfp4").
        # Empty = use the first model the server lists. The panel's model menu overrides this.
        "model": "",
        # Shown first in the model menu, and used when the server's model list can't be fetched.
        "fallback_models": [],
        # Where the API key comes from, in order: env var, key file, secrets.toml.
        "api_key_env": "LITELLM_API_KEY",
        "api_key_file": "",
        "temperature": 0.4,
        "max_tokens": 3000,
        "timeout_seconds": 180,
        "max_tool_rounds": 8,
        # Forward Qwen "thinking" tokens to the UI (collapsed by default).
        "show_reasoning": True,
        # Extra JSON merged into every chat request, e.g. to turn Qwen3 thinking off:
        # extra_body = { chat_template_kwargs = { enable_thinking = false } }
        "extra_body": {},
        # Rough budget for prior conversation turns sent as context.
        "history_char_budget": 24000,
    },
    "tools": {
        "enabled": True,
        "enable_web": True,
        "command_timeout": 20,
        "output_limit": 12000,
        "allowed_hosts": [
            "wiki.cachyos.org", "cachyos.org", "wiki.archlinux.org", "archlinux.org",
            "aur.archlinux.org", "man.archlinux.org", "wiki.hypr.land", "hypr.land",
            "docs.noctalia.dev", "noctalia.dev", "quickshell.org",
            "github.com", "raw.githubusercontent.com",
        ],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> dict[str, Any]:
        v = self.data.get(name, {})
        return v if isinstance(v, dict) else {}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot read {path}: {exc}") from exc


def load_config() -> Config:
    return Config(_deep_merge(DEFAULTS, _read_toml(CONFIG_FILE)))


def load_api_key(cfg: Config) -> str | None:
    """Resolve the API key without ever printing it."""
    env_name = cfg.get("llm.api_key_env") or ""
    if env_name and os.environ.get(env_name):
        return os.environ[env_name].strip()
    key_file = cfg.get("llm.api_key_file") or ""
    if key_file:
        try:
            return Path(os.path.expanduser(key_file)).read_text().strip() or None
        except OSError:
            pass
    secrets = _read_toml(SECRETS_FILE)
    key = secrets.get("api_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    inline = cfg.get("llm.api_key")
    if isinstance(inline, str) and inline.strip():
        return inline.strip()
    return None


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def current_model(cfg: Config) -> str:
    return load_state().get("model") or cfg.get("llm.model") or ""


def resolve_model(wanted: str, available: list[str]) -> str | None:
    """Map a short name like "qwen3.6" onto the server's id ("qwen3.6:35b-nvfp4"). None if nothing fits."""
    if not wanted or not available:
        return None
    if wanted in available:
        return wanted
    low = wanted.lower()
    by_lower = {m.lower(): m for m in available}
    if low in by_lower:
        return by_lower[low]
    for sep in (":", "-", "/", "_"):
        hits = sorted(m for m in available if m.lower().startswith(low + sep))
        if hits:
            return min(hits, key=len)
    hits = sorted(m for m in available if low in m.lower())
    return min(hits, key=len) if hits else None


def order_models(models: list[str], preferred: list[str]) -> list[str]:
    """Models matching the configured preferences first (in that order), then the rest alphabetically."""
    first: list[str] = []
    for want in preferred:
        low = want.lower()
        for m in models:
            if m not in first and (m.lower() == low or m.lower().startswith(low + ":") or m.lower().startswith(low + "-")):
                first.append(m)
    return first + sorted((m for m in models if m not in first), key=str.lower)


def write_api_key(key: str) -> None:
    """Store the key in secrets.toml with mode 600 (atomic; the file is never world-readable)."""
    key = key.strip()
    if not key or "\n" in key or '"' in key or "\\" in key:
        raise ValueError("the API key must be a single line without quotes or backslashes")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_FILE.with_name(".secrets.toml.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, ("# LiteLLM API key for the Noctalia Assistant. Keep this file private (mode 600).\n"
                      f'api_key = "{key}"\n').encode())
    finally:
        os.close(fd)
    os.replace(tmp, SECRETS_FILE)


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def set_base_url(url: str) -> str:
    """Write [llm] base_url into config.toml, keeping every other line (and comment) as it is."""
    import re
    from urllib.parse import urlparse
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or any(c in url for c in '"\\\n '):
        raise ValueError("the server address must look like http://host:port or https://host")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    text = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else ""
    line = f'base_url = "{url}"'
    llm = re.search(r"(?m)^\[llm\][ \t]*$", text)
    if llm:
        nxt = re.search(r"(?m)^\[", text[llm.end():])
        end = llm.end() + nxt.start() if nxt else len(text)
        section = text[llm.end():end]
        if re.search(r"(?m)^[ \t]*base_url[ \t]*=", section):
            section = re.sub(r"(?m)^[ \t]*base_url[ \t]*=.*$", lambda _m: line, section, count=1)
        else:
            section = "\n" + line + section
        text = text[:llm.end()] + section + text[end:]
    else:
        text = f"[llm]\n{line}\n\n" + text
    tomllib.loads(text)  # never write a config the backend can't read back
    tmp = CONFIG_FILE.with_name(".config.toml.tmp")
    tmp.write_text(text)
    tmp.replace(CONFIG_FILE)
    return url
