"""
Append-only audit log backed by local SQLite, per the project's data
tier spec. Every ACCEPT / REJECT / CORRECT action gets one row here —
this is the trail your Human Review Efficiency metric will later be
measured against, so every field here matters for the evaluation
report in Month 6.
"""

import sqlite3
import datetime

DB_PATH = "audit_log.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reason TEXT,
            corrected_field TEXT,
            corrected_value TEXT,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def log_action(record_id, action, reviewer, reason=None, corrected_field=None, corrected_value=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO audit_log (record_id, action, reviewer, reason, corrected_field, corrected_value, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            action,
            reviewer,
            reason,
            corrected_field,
            corrected_value,
            datetime.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def get_all_logs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT record_id, action, reviewer, reason, timestamp FROM audit_log ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows
