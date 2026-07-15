"""Read path for the message browser/search API and devices page.

Only ever opens the monthly index DBs read-only-in-spirit (short-lived
connections, no writes) -- never touches the raw text files or the
receiver process (plan line 45).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .config import WebConfig


@dataclass(slots=True)
class MessageFilter:
    host: list[str] | None = None
    severity: int | None = None
    facility: int | None = None
    start: str | None = None  # inclusive, format_receipt_time-comparable string
    end: str | None = None  # inclusive, format_receipt_time-comparable string
    text: str | None = None  # FTS5 query string
    malformed_only: bool = False


@dataclass(slots=True)
class SearchResult:
    rows: list[dict] = field(default_factory=list)
    has_more: bool = False


@dataclass(slots=True)
class DeviceInfo:
    source_ip: str
    host: str | None
    last_seen: str
    message_count: int


def _available_month_keys(index_dir: Path) -> list[str]:
    if not index_dir.exists():
        return []
    return sorted((p.stem for p in index_dir.glob("*.sqlite3") if len(p.stem) == 7), reverse=True)


def _relevant_month_keys(config: WebConfig, filt: MessageFilter) -> list[str]:
    available = _available_month_keys(config.index_dir)
    if filt.start is None and filt.end is None:
        # No explicit range: bound the scan to a small, predictable number
        # of recent months rather than silently searching all of history.
        return available[: config.recent_months_scanned]
    start_key = filt.start[:7] if filt.start else None
    end_key = filt.end[:7] if filt.end else None

    def in_range(key: str) -> bool:
        if start_key and key < start_key:
            return False
        if end_key and key > end_key:
            return False
        return True

    return [k for k in available if in_range(k)]


def _build_query(filt: MessageFilter, limit: int) -> tuple[str, list]:
    use_fts = bool(filt.text)
    params: list = []
    if use_fts:
        sql = (
            "SELECT m.id, m.receipt_time, m.source_ip, m.facility, m.severity, "
            "m.host, m.tag, m.message, m.malformed "
            "FROM messages_fts f JOIN messages m ON m.id = f.rowid "
            "WHERE messages_fts MATCH ?"
        )
        params.append(filt.text)
        prefix = "m."
    else:
        sql = (
            "SELECT id, receipt_time, source_ip, facility, severity, host, tag, message, malformed "
            "FROM messages WHERE 1=1"
        )
        prefix = ""

    if filt.host:
        placeholders = ",".join("?" for _ in filt.host)
        sql += f" AND {prefix}host IN ({placeholders})"
        params.extend(filt.host)
    if filt.severity is not None:
        sql += f" AND {prefix}severity = ?"
        params.append(filt.severity)
    if filt.facility is not None:
        sql += f" AND {prefix}facility = ?"
        params.append(filt.facility)
    if filt.start:
        sql += f" AND {prefix}receipt_time >= ?"
        params.append(filt.start)
    if filt.end:
        sql += f" AND {prefix}receipt_time <= ?"
        params.append(filt.end)
    if filt.malformed_only:
        sql += f" AND {prefix}malformed = 1"
    sql += f" ORDER BY {prefix}receipt_time DESC LIMIT ?"
    params.append(limit)
    return sql, params


def search_messages(config: WebConfig, filt: MessageFilter, offset: int, limit: int) -> SearchResult:
    """Pagination across N monthly DB files: each month is queried for its
    own top (offset+limit) matches (bounded, indexed), the per-month results
    are merged and globally re-sorted, then sliced to the requested page.
    This is exact for the page returned -- no single month can contribute
    more than offset+limit+1 rows to a global top-(offset+limit) plus a
    has-more probe -- but very deep pagination (large offset) against a
    wide time range does mean larger per-month queries; acceptable for a
    local admin browsing tool. The +1 over offset+limit is what lets
    has_more be computed correctly: without it, a month with more matches
    than the cap would have its extra rows silently cut off by the SQL
    LIMIT itself, before they ever reached the merge step.
    """
    month_keys = _relevant_month_keys(config, filt)
    per_month_limit = offset + limit + 1
    sql, params = _build_query(filt, per_month_limit)

    merged: list[dict] = []
    for month_key in month_keys:
        db_path = config.index_dir / f"{month_key}.sqlite3"
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            continue
        finally:
            conn.close()
        merged.extend(dict(r) for r in rows)

    merged.sort(key=lambda r: r["receipt_time"], reverse=True)
    has_more = len(merged) > offset + limit
    page = merged[offset : offset + limit]
    return SearchResult(rows=page, has_more=has_more)


def list_devices(config: WebConfig) -> list[DeviceInfo]:
    """Grouped by hostname (falling back to source_ip for rows with no
    parsed host, e.g. malformed input) rather than by source_ip alone --
    the receiver's per-device file/queue isolation stays keyed on source IP
    (section 1's security property: a spoofed hostname must not be able to
    claim another device's on-disk identity), but a device on DHCP getting
    a new IP would otherwise show up here as a second, disconnected entry.
    Grouping this read-only listing by hostname instead keeps one row per
    device across an IP change, without touching the write path at all
    (plan section 9, finding 3).

    source_ip is picked arbitrarily among rows sharing a device_key in a
    given month (SQLite's bare-column-in-GROUP-BY behavior), same caveat
    the old host-picking logic had -- updated below to the most recent
    row's source_ip once merged across months, same as host was before.
    """
    month_keys = _available_month_keys(config.index_dir)[: config.recent_months_scanned]

    aggregated: dict[str, DeviceInfo] = {}
    for month_key in month_keys:
        db_path = config.index_dir / f"{month_key}.sqlite3"
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT COALESCE(host, source_ip) AS device_key, source_ip, host, "
                "COUNT(*) AS message_count, MAX(receipt_time) AS last_seen "
                "FROM messages GROUP BY device_key"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        finally:
            conn.close()

        for row in rows:
            existing = aggregated.get(row["device_key"])
            if existing is None:
                aggregated[row["device_key"]] = DeviceInfo(
                    row["source_ip"], row["host"], row["last_seen"], row["message_count"]
                )
            else:
                existing.message_count += row["message_count"]
                if row["last_seen"] > existing.last_seen:
                    existing.last_seen = row["last_seen"]
                    existing.host = row["host"]
                    existing.source_ip = row["source_ip"]

    return sorted(aggregated.values(), key=lambda d: d.last_seen, reverse=True)
