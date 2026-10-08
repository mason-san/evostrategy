"""Assistant chat history.

Kept in its own SQLite file (not the reconciliation registry) so that loading
demo data or resetting the workspace never deletes a user's conversations.
Chats hold questions and answers only; the figures in them were computed from
verified data at the time and each answer records its own evidence.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from utils import config

TITLE_LENGTH = 48


def _db() -> Path:
    return config.PROCESSED_DIR / "chats.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _db()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
                    result_json TEXT, error TEXT, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id, id);
                """
            )
            yield connection
    finally:
        connection.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create(title: str = "New chat") -> dict[str, Any]:
    conversation = {"id": uuid4().hex, "title": title[:TITLE_LENGTH] or "New chat", "created_at": _now()}
    with _connect() as db:
        db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)",
                   (conversation["id"], conversation["title"], conversation["created_at"], conversation["created_at"]))
    return {**conversation, "updated_at": conversation["created_at"], "message_count": 0}


def list_all() -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            """SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count
               FROM conversations c LEFT JOIN chat_messages m ON m.conversation_id = c.id
               GROUP BY c.id ORDER BY c.updated_at DESC, c.rowid DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def get(conversation_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            return None
        messages = db.execute(
            "SELECT id, role, content, result_json, error, created_at FROM chat_messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return {
        **dict(row),
        "messages": [
            {"id": m["id"], "role": m["role"], "text": m["content"], "error": m["error"], "created_at": m["created_at"],
             "result": json.loads(m["result_json"]) if m["result_json"] else None}
            for m in messages
        ],
    }


def add_message(conversation_id: str, role: str, content: str = "", result: dict[str, Any] | None = None,
                error: str | None = None) -> None:
    with _connect() as db:
        db.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, result_json, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, json.dumps(result) if result else None, error, _now()),
        )
        db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))


def history(conversation_id: str) -> list[dict[str, str]]:
    """Prior successful turns as plain text, for the model."""
    conversation = get(conversation_id)
    return [{"role": m["role"], "content": m["text"]} for m in (conversation or {}).get("messages", [])
            if not m["error"] and m["text"]]


def rename(conversation_id: str, title: str) -> bool:
    with _connect() as db:
        return db.execute("UPDATE conversations SET title = ? WHERE id = ?",
                          (title.strip()[:TITLE_LENGTH] or "New chat", conversation_id)).rowcount > 0


def delete(conversation_id: str) -> bool:
    with _connect() as db:
        return db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount > 0
