"""SQLite history store — action log and session conversation context."""

import os
import sqlite3

DB_PATH = "history.db"


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                action      TEXT NOT NULL,
                repo        TEXT,
                status      TEXT NOT NULL,
                summary     TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_context (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                turn        INTEGER NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def log_step(session_id, action, repo, status, summary):
    token = os.environ.get("GITHUB_TOKEN", "")
    for value in [action, repo or "", status, summary or ""]:
        assert token not in str(value), "SECURITY INVARIANT VIOLATED: token in DB write"

    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO action_log (session_id, timestamp, action, repo, status, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, timestamp, action, repo, status, summary),
        )
        conn.commit()
    finally:
        conn.close()


def add_context_turn(session_id, turn, role, content):
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO session_context (session_id, turn, role, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, turn, role, content, timestamp),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_context(session_id, last_n=10):
    conn = _get_conn()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM session_context
            WHERE session_id = ?
            ORDER BY turn DESC
            LIMIT ?
            """,
            (session_id, last_n),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        conn.close()


init_db()
