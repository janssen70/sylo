"""Control-plane SQLite DB: users, sessions, settings.

Deliberately separate from the monthly message-index DBs (sylo/indexer) --
this data has a different lifecycle (never rotated or dropped by retention)
and section 3's read path must never touch it while reading messages.

Every call opens and closes its own short-lived connection rather than
sharing one across requests/threads -- simplest way to stay correct under
FastAPI's threadpool-per-sync-route-handler model without adding locking,
and traffic here (single local admin, occasional page loads) is far too low
for connection-open overhead to matter.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "retention_days": "365",
}


@contextmanager
def connect(app_db_path: Path):
    app_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(app_db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def init_db(app_db_path: Path) -> None:
    with connect(app_db_path) as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()


def count_users(app_db_path: Path) -> int:
    with connect(app_db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(app_db_path: Path, username: str, password_hash: str) -> int:
    with connect(app_db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cursor.lastrowid


def get_user_by_username(app_db_path: Path, username: str) -> Optional[sqlite3.Row]:
    with connect(app_db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_id(app_db_path: Path, user_id: int) -> Optional[sqlite3.Row]:
    with connect(app_db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_session(app_db_path: Path, token: str, user_id: int, csrf_token: str, expires_at: str) -> None:
    with connect(app_db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token, user_id, csrf_token, datetime.now(timezone.utc).isoformat(), expires_at),
        )
        conn.commit()


def get_session(app_db_path: Path, token: str) -> Optional[sqlite3.Row]:
    with connect(app_db_path) as conn:
        return conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()


def delete_session(app_db_path: Path, token: str) -> None:
    with connect(app_db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def purge_expired_sessions(app_db_path: Path, now_iso: str) -> None:
    with connect(app_db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso,))
        conn.commit()


def get_setting(app_db_path: Path, key: str, default: Optional[str] = None) -> Optional[str]:
    with connect(app_db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(app_db_path: Path, key: str, value: str) -> None:
    with connect(app_db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
