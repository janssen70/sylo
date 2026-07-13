"""Rebuild the SQLite index from the raw text files (plan line 37 recovery).

Offline/synchronous by design -- meant to be run against a lost/corrupted
index while the receiver is stopped, not as part of the live asyncio
pipeline. Reuses the exact same parser as live ingest so a rebuilt index is
equivalent to one built at ingest time, modulo source_port/transport which
were never persisted to SQLite in the first place (see schema.py).
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from ..parser import parse_syslog
from .schema import INSERT_SQL, apply_schema

logger = logging.getLogger("sylo.indexer.rebuild")


def rebuild_indexer(
    data_dir: Path, index_dir: Path, months: Optional[set[str]] = None
) -> dict[str, int]:
    """Deletes and recreates each targeted month's DB before reinserting --
    this path assumes the existing DB (if any) for that month is corrupt or
    gone. Returns a dict of month_key -> rows inserted."""
    counts: dict[str, int] = {}
    rebuilt_months: set[str] = set()
    connections: dict[str, sqlite3.Connection] = {}
    try:
        for device_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            source_ip = device_dir.name
            for log_file in sorted(device_dir.glob("*.log")):
                month_key = log_file.stem[:7]
                if months is not None and month_key not in months:
                    continue
                conn = connections.get(month_key)
                if conn is None:
                    db_path = index_dir / f"{month_key}.sqlite3"
                    if month_key not in rebuilt_months and db_path.exists():
                        db_path.unlink()
                    rebuilt_months.add(month_key)
                    index_dir.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(db_path)
                    apply_schema(conn)
                    connections[month_key] = conn
                inserted = _rebuild_file(conn, log_file, source_ip)
                conn.commit()
                counts[month_key] = counts.get(month_key, 0) + inserted
    finally:
        for conn in connections.values():
            conn.close()
    return counts


def _rebuild_file(conn: sqlite3.Connection, log_file: Path, source_ip: str) -> int:
    inserted = 0
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            timestamp_str, sep, raw_str = line.partition(" ")
            if not sep:
                logger.warning("skipping line with no timestamp separator in %s", log_file)
                continue
            fields = parse_syslog(raw_str.encode("utf-8"))
            try:
                conn.execute(
                    INSERT_SQL,
                    (
                        timestamp_str,
                        source_ip,
                        fields.facility,
                        fields.severity,
                        fields.host,
                        fields.tag,
                        fields.message,
                        int(fields.malformed),
                    ),
                )
                inserted += 1
            except sqlite3.Error:
                logger.exception("failed to insert rebuilt row from %s", log_file)
    return inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="raw text files root (receiver's data_dir)")
    parser.add_argument("--index-dir", type=Path, required=True, help="target directory for rebuilt monthly DBs")
    parser.add_argument("--month", action="append", dest="months", help="YYYY-MM to rebuild (repeatable); default: all")
    args = parser.parse_args()

    months = set(args.months) if args.months else None
    counts = rebuild_indexer(args.data_dir, args.index_dir, months)
    for month_key, count in sorted(counts.items()):
        logger.info("rebuilt %s: %d rows", month_key, count)


if __name__ == "__main__":
    main()
