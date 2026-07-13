"""One SQLite file per month (plan line 30). Columns are limited to exactly
what section 3's search API needs and what the rebuild-from-text recovery
path (line 37) can fully reconstruct -- source_port/transport live on the
in-memory MessageEnvelope but aren't persisted here, since they aren't in
the text files and dropping them keeps rebuild lossless.
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
"""

INSERT_SQL = """
INSERT INTO messages (receipt_time, source_ip, facility, severity, host, tag, message, malformed)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def apply_schema(conn) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL (vs FULL) skips an fsync on every commit under WAL, relying on
    # the WAL for crash consistency -- same throughput/durability tradeoff
    # already made for the receiver's periodic-fsync write path.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
