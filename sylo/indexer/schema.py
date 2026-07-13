"""One SQLite file per month (plan line 30). Columns are limited to exactly
what section 3's search API needs and what the rebuild-from-text recovery
path (line 37) can fully reconstruct -- source_port/transport live on the
in-memory MessageEnvelope but aren't persisted here, since they aren't in
the text files and dropping them keeps rebuild lossless.

messages_fts is an external-content FTS5 table (content='messages') over the
free-text-searchable columns -- external content means FTS5 doesn't keep its
own copy of the column text, it looks it up from `messages` by rowid when
needed (snippets etc). That requires the caller to keep it in sync manually
on insert; there's deliberately no UPDATE/DELETE trigger since this app
never updates or selectively deletes rows -- retention drops an entire
month's DB file at once (plan line 51), so insert-only sync is sufficient.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    receipt_time TEXT NOT NULL,
    source_ip TEXT NOT NULL,
    facility INTEGER,
    severity INTEGER,
    host TEXT,
    tag TEXT,
    message TEXT NOT NULL,
    malformed INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_receipt_time ON messages(receipt_time);
CREATE INDEX IF NOT EXISTS idx_messages_host_time ON messages(host, receipt_time);
CREATE INDEX IF NOT EXISTS idx_messages_severity_time ON messages(severity, receipt_time);
CREATE INDEX IF NOT EXISTS idx_messages_facility_time ON messages(facility, receipt_time);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message, host, tag,
    content='messages', content_rowid='id'
);
"""

INSERT_SQL = """
INSERT INTO messages (receipt_time, source_ip, facility, severity, host, tag, message, malformed)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_FTS_SQL = """
INSERT INTO messages_fts (rowid, message, host, tag) VALUES (?, ?, ?, ?)
"""


def apply_schema(conn) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL (vs FULL) skips an fsync on every commit under WAL, relying on
    # the WAL for crash consistency -- same throughput/durability tradeoff
    # already made for the receiver's periodic-fsync write path.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()


def insert_message(
    conn,
    *,
    receipt_time: str,
    source_ip: str,
    facility,
    severity,
    host,
    tag,
    message: str,
    malformed: bool,
) -> int:
    """Insert one row into `messages` and keep `messages_fts` in sync.
    Shared by the live indexer and the rebuild-from-text path so both
    produce an identical index for the same input. Raises sqlite3.Error on
    failure -- callers wrap each row in their own try/except (plan line 33)."""
    cursor = conn.execute(
        INSERT_SQL,
        (receipt_time, source_ip, facility, severity, host, tag, message, int(malformed)),
    )
    conn.execute(INSERT_FTS_SQL, (cursor.lastrowid, message, host, tag))
    return cursor.lastrowid
