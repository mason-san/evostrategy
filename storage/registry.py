"""SQLite-backed local registry for documents, reconciliation and review audit.

Tables
- documents             Stage 1 source documents (full payload, provenance)
- links                 Stage 2 document links (rebuilt on every reconciliation run)
- transactions          Linked document groups (rebuilt on every run)
- reconciliation_cases  Discrepancy cases; reviewed statuses survive reruns
- review_actions        Append-only reviewer audit trail, hash-chained so that
                        any later edit or deletion of a row is detectable
- runs                  One row per reconciliation run
- settings              User configuration (budgets, cash balance, headcount)
- forecast_snapshots    Every distinct forecast produced, with the exact verified
                        inputs it was built from (for traceability)

Schema changes are additive only (CREATE TABLE IF NOT EXISTS / ADD COLUMN), so
an existing registry is upgraded in place and no data is lost.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from utils.config import REGISTRY_DB

REVIEW_STATUS = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "CORRECT": "CORRECTED"}


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_registry(db_path: Path = REGISTRY_DB) -> None:
    """Create the local registry tables if they do not exist."""
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_cases (
                case_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS review_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                action TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT,
                corrected_value TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY, source_name TEXT, source_path TEXT,
                extraction_method TEXT, extraction_confidence REAL,
                low_confidence INTEGER DEFAULT 0, payload TEXT NOT NULL,
                ingested_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS links (
                link_id TEXT PRIMARY KEY, left_document_id TEXT NOT NULL,
                right_document_id TEXT NOT NULL, relationship TEXT NOT NULL,
                status TEXT NOT NULL, confidence REAL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, summary TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS forecast_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT NOT NULL,
                horizon INTEGER NOT NULL, input_hash TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(review_actions)")}
        for column in ("field", "prev_hash", "entry_hash"):
            if column not in columns:
                connection.execute(f"ALTER TABLE review_actions ADD COLUMN {column} TEXT")


# --------------------------------------------------------------------------- documents

def upsert_documents(documents: Iterable[dict[str, Any]], db_path: Path = REGISTRY_DB) -> None:
    """Persist Stage 1 source documents (idempotent per document_id)."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        for document in documents:
            connection.execute(
                """INSERT INTO documents(document_id, source_name, source_path,
                extraction_method, extraction_confidence, low_confidence, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(document_id) DO UPDATE SET
                source_name=excluded.source_name, source_path=excluded.source_path,
                extraction_method=excluded.extraction_method,
                extraction_confidence=excluded.extraction_confidence,
                low_confidence=excluded.low_confidence, payload=excluded.payload,
                ingested_at=CURRENT_TIMESTAMP""",
                (
                    document["document_id"],
                    document.get("source_name"),
                    document.get("source_path"),
                    document.get("extraction_method"),
                    document.get("extraction_confidence"),
                    int(bool(document.get("low_confidence"))),
                    json.dumps(document, default=str),
                ),
            )


def get_documents(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    """Return every stored source document payload."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT payload FROM documents ORDER BY document_id").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def get_document(document_id: str, db_path: Path = REGISTRY_DB) -> dict[str, Any] | None:
    """Return one stored source document payload."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM documents WHERE document_id=?", (document_id,)
        ).fetchone()
    return json.loads(row["payload"]) if row else None


# --------------------------------------------------------------------------- cases

def upsert_cases(cases: list[dict[str, Any]], db_path: Path = REGISTRY_DB) -> None:
    """Persist reconciliation cases without duplicating reruns.

    A case a reviewer has already acted on keeps its reviewed status, so a
    rerun never silently overwrites a human decision.
    """
    init_registry(db_path)
    with _connect(db_path) as connection:
        for case in cases:
            connection.execute(
                """INSERT INTO reconciliation_cases(case_id, transaction_id, status, payload)
                VALUES (?, ?, ?, ?) ON CONFLICT(case_id) DO UPDATE SET
                status = CASE WHEN EXISTS (SELECT 1 FROM review_actions r
                                           WHERE r.case_id = excluded.case_id)
                         THEN reconciliation_cases.status ELSE excluded.status END,
                payload=excluded.payload, transaction_id=excluded.transaction_id,
                updated_at=CURRENT_TIMESTAMP""",
                (case["case_id"], case["transaction_id"], case["status"], json.dumps(case, default=str)),
            )


def replace_run_results(
    *,
    cases: list[dict[str, Any]],
    links: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    summary: dict[str, Any],
    db_path: Path = REGISTRY_DB,
) -> None:
    """Store one full reconciliation run.

    Links and transactions are rebuilt. Cases are upserted; unreviewed cases
    that the new run no longer produces are removed, reviewed ones are kept.
    """
    init_registry(db_path)
    upsert_cases(cases, db_path)
    with _connect(db_path) as connection:
        current = [case["case_id"] for case in cases]
        placeholders = ",".join("?" for _ in current) or "''"
        connection.execute(
            f"""DELETE FROM reconciliation_cases WHERE case_id NOT IN ({placeholders})
            AND case_id NOT IN (SELECT DISTINCT case_id FROM review_actions)""",
            current,
        )
        connection.execute("DELETE FROM links")
        for link in links:
            connection.execute(
                "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    link["link_id"], link["left_document_id"], link["right_document_id"],
                    link["relationship"], link["status"], link["confidence"],
                    json.dumps(link, default=str),
                ),
            )
        connection.execute("DELETE FROM transactions")
        for transaction in transactions:
            connection.execute(
                "INSERT INTO transactions VALUES (?, ?)",
                (transaction["transaction_id"], json.dumps(transaction, default=str)),
            )
        connection.execute("INSERT INTO runs(summary) VALUES (?)", (json.dumps(summary),))


def _case_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    payload["computed_status"] = payload.get("status")
    payload["status"] = row["status"]
    payload["updated_at"] = row["updated_at"]
    return payload


def get_cases(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    """Return persisted reconciliation cases ordered by most recent update."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT payload, status, updated_at FROM reconciliation_cases ORDER BY updated_at DESC, case_id"
        ).fetchall()
    return [_case_from_row(row) for row in rows]


def get_case(case_id: str, db_path: Path = REGISTRY_DB) -> dict[str, Any] | None:
    """Return one case with its effective (possibly reviewed) status."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT payload, status, updated_at FROM reconciliation_cases WHERE case_id=?",
            (case_id,),
        ).fetchone()
    return _case_from_row(row) if row else None


def get_links(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT payload FROM links").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def get_transactions(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT payload FROM transactions").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def get_last_run(db_path: Path = REGISTRY_DB) -> dict[str, Any] | None:
    init_registry(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT summary, created_at FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {**json.loads(row["summary"]), "created_at": row["created_at"]} if row else None


# --------------------------------------------------------------------------- review

def log_review_action(
    case_id: str,
    action: str,
    reviewer: str,
    reason: str | None = None,
    corrected_value: str | None = None,
    db_path: Path = REGISTRY_DB,
    field: str | None = None,
) -> None:
    """Append a reviewer action and update the case status."""
    init_registry(db_path)
    if action not in REVIEW_STATUS:
        raise ValueError(f"Unsupported review action: {action}")
    with _connect(db_path) as connection:
        last = connection.execute(
            "SELECT entry_hash FROM review_actions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = (last["entry_hash"] if last else None) or GENESIS_HASH
        created_at = connection.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()["now"]
        entry = {"case_id": case_id, "action": action, "reviewer": reviewer, "reason": reason,
                 "corrected_value": corrected_value, "field": field, "created_at": created_at}
        connection.execute(
            """INSERT INTO review_actions
            (case_id, action, reviewer, reason, corrected_value, field, created_at, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, action, reviewer, reason, corrected_value, field, created_at,
             prev_hash, _entry_hash(prev_hash, entry)),
        )
        connection.execute(
            "UPDATE reconciliation_cases SET status=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?",
            (REVIEW_STATUS[action], case_id),
        )


GENESIS_HASH = "0" * 64
_HASHED_FIELDS = ("case_id", "action", "reviewer", "reason", "corrected_value", "field", "created_at")


def _entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    """SHA-256 over the previous hash and this entry's content."""
    body = json.dumps({key: entry.get(key) for key in _HASHED_FIELDS}, sort_keys=True)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def verify_audit_chain(db_path: Path = REGISTRY_DB) -> dict[str, Any]:
    """Recompute the hash chain; any edited, inserted or deleted row breaks it.

    Rows written before the chain existed (no hash) are reported as legacy.
    """
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = [dict(r) for r in connection.execute("SELECT * FROM review_actions ORDER BY id")]
    previous, legacy, problems = GENESIS_HASH, 0, []
    for row in rows:
        if not row.get("entry_hash"):
            legacy += 1
            continue
        if row["prev_hash"] != previous:
            problems.append({"id": row["id"], "problem": "chain broken before this entry (row deleted or reordered)"})
        if _entry_hash(row["prev_hash"], row) != row["entry_hash"]:
            problems.append({"id": row["id"], "problem": "entry content was changed after it was written"})
        previous = row["entry_hash"]
    return {"entries": len(rows), "chained": len(rows) - legacy, "legacy_unchained": legacy,
            "intact": not problems, "problems": problems, "head": previous}


def get_review_actions(
    case_id: str | None = None, db_path: Path = REGISTRY_DB
) -> list[dict[str, Any]]:
    """Return audit actions, optionally limited to one case."""
    init_registry(db_path)
    query = (
        "SELECT id, case_id, action, reviewer, reason, corrected_value, field, created_at, entry_hash "
        "FROM review_actions"
    )
    parameters: tuple[str, ...] = ()
    if case_id:
        query += " WHERE case_id = ?"
        parameters = (case_id,)
    query += " ORDER BY id DESC"
    with _connect(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------- settings

def get_setting(key: str, default: Any = None, db_path: Path = REGISTRY_DB) -> Any:
    init_registry(db_path)
    with _connect(db_path) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value: Any, db_path: Path = REGISTRY_DB) -> None:
    init_registry(db_path)
    with _connect(db_path) as connection:
        connection.execute(
            """INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET
            value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
            (key, json.dumps(value)),
        )


# --------------------------------------------------------------------------- forecast snapshots

def save_forecast_snapshot(metric: str, horizon: int, input_hash: str, payload: dict[str, Any],
                           db_path: Path = REGISTRY_DB) -> int:
    """Store a forecast unless the same inputs were already stored; return its id."""
    init_registry(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM forecast_snapshots WHERE metric=? AND horizon=? AND input_hash=? ORDER BY id DESC LIMIT 1",
            (metric, horizon, input_hash),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO forecast_snapshots(metric, horizon, input_hash, payload) VALUES (?, ?, ?, ?)",
            (metric, horizon, input_hash, json.dumps(payload, default=str)),
        )
        return int(cursor.lastrowid)


def get_forecast_snapshots(limit: int = 50, db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    init_registry(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, metric, horizon, input_hash, payload, created_at FROM forecast_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{**{k: row[k] for k in ("id", "metric", "horizon", "input_hash", "created_at")},
             **json.loads(row["payload"])} for row in rows]


KEEP_BACKUPS = 5


def reset_registry(db_path: Path = REGISTRY_DB) -> Path | None:
    """Start a fresh registry (demo loads, ``pipeline.py reset``).

    The previous database is never simply deleted: it is moved to
    ``backups/`` next to it (the newest few are kept), so reviewer decisions
    and audit history can be restored if a reset was a mistake.
    """
    backup = None
    if db_path.exists():
        from datetime import datetime

        folder = db_path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"{db_path.stem}-{datetime.now():%Y%m%d-%H%M%S-%f}{db_path.suffix}"
        db_path.replace(backup)
        for old in sorted(folder.glob(f"{db_path.stem}-*{db_path.suffix}"))[:-KEEP_BACKUPS]:
            old.unlink()
    init_registry(db_path)
    return backup
