"""SQLite-backed idempotent reconciliation registry."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from utils.config import REGISTRY_DB


def init_registry(db_path: Path = REGISTRY_DB) -> None:
    """Create the local registry tables if they do not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reconciliation_cases (
            case_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS review_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
            action TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT,
            corrected_value TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )


def upsert_cases(cases: list[dict[str, Any]], db_path: Path = REGISTRY_DB) -> None:
    """Persist reconciliation cases without duplicating reruns."""
    init_registry(db_path)
    with sqlite3.connect(db_path) as connection:
        for case in cases:
            case_id = case["case_id"]
            connection.execute(
                """INSERT INTO reconciliation_cases(case_id, transaction_id, status, payload)
                VALUES (?, ?, ?, ?) ON CONFLICT(case_id) DO UPDATE SET
                status=excluded.status, payload=excluded.payload, updated_at=CURRENT_TIMESTAMP""",
                (case_id, case["transaction_id"], case["status"], json.dumps(case)),
            )


def get_cases(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    """Return persisted reconciliation cases ordered by most recent update."""
    init_registry(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT payload FROM reconciliation_cases ORDER BY updated_at DESC"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def log_review_action(
    case_id: str,
    action: str,
    reviewer: str,
    reason: str | None = None,
    corrected_value: str | None = None,
    db_path: Path = REGISTRY_DB,
) -> None:
    """Append a reviewer action and update the case status."""
    init_registry(db_path)
    status_by_action = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "CORRECT": "CORRECTED"}
    if action not in status_by_action:
        raise ValueError(f"Unsupported review action: {action}")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO review_actions
            (case_id, action, reviewer, reason, corrected_value)
            VALUES (?, ?, ?, ?, ?)""",
            (case_id, action, reviewer, reason, corrected_value),
        )
        connection.execute(
            "UPDATE reconciliation_cases SET status=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?",
            (status_by_action[action], case_id),
        )


def get_review_actions(
    case_id: str | None = None, db_path: Path = REGISTRY_DB
) -> list[dict[str, Any]]:
    """Return audit actions, optionally limited to one case."""
    init_registry(db_path)
    query = (
        "SELECT case_id, action, reviewer, reason, corrected_value, created_at "
        "FROM review_actions"
    )
    parameters: tuple[str, ...] = ()
    if case_id:
        query += " WHERE case_id = ?"
        parameters = (case_id,)
    query += " ORDER BY id DESC"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    keys = ("case_id", "action", "reviewer", "reason", "corrected_value", "created_at")
    return [dict(zip(keys, row)) for row in rows]
