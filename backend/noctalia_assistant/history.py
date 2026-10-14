"""Conversation persistence (sqlite, WAL)."""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from .config import HISTORY_DB, STATE_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
"""


class History:
    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(HISTORY_DB, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def create(self, model: str = "") -> int:
        now = time.time()
        cur = self.db.execute("INSERT INTO conversations(title, model, created, updated) VALUES ('', ?, ?, ?)", (model, now, now))
        self.db.commit()
        return int(cur.lastrowid)

    def add_message(self, conv_id: int, role: str, content: str, meta: dict[str, Any] | None = None) -> int:
        now = time.time()
        cur = self.db.execute("INSERT INTO messages(conversation_id, role, content, meta, created) VALUES (?,?,?,?,?)",
                              (conv_id, role, content, json.dumps(meta or {}), now))
        self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conv_id))
        row = self.db.execute("SELECT title FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if row is not None and not row["title"] and role == "user":
            title = " ".join(content.strip().split())[:64]
            self.db.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
        self.db.commit()
        return int(cur.lastrowid)

    def messages(self, conv_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT id, role, content, meta, created FROM messages WHERE conversation_id=? ORDER BY id", (conv_id,)).fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"], "meta": json.loads(r["meta"] or "{}"), "created": r["created"]} for r in rows]

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT c.id, c.title, c.model, c.updated, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n "
            "FROM conversations c WHERE n > 0 ORDER BY c.updated DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "title": r["title"] or "Untitled", "model": r["model"], "updated": r["updated"], "count": r["n"]} for r in rows]

    def delete(self, conv_id: int) -> None:
        self.db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        self.db.commit()

    def exists(self, conv_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM conversations WHERE id=?", (conv_id,)).fetchone() is not None

    def set_model(self, conv_id: int, model: str) -> None:
        self.db.execute("UPDATE conversations SET model=? WHERE id=?", (model, conv_id))
        self.db.commit()
