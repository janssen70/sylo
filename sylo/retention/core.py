"""Retention pass: drop whole monthly partitions once they've aged out
(plan section 4). Deletion granularity is the whole month, on both sides of
the storage layout -- the monthly index DB (line 30) and every per-device
daily raw file whose date falls inside that month (line 22) -- never
row-by-row or file-by-file within a still-live month.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ..webapp import appdb
from .config import RetentionConfig

logger = logging.getLogger("sylo.retention")


@dataclass(slots=True)
class RetentionSummary:
    dropped_months: list[str] = field(default_factory=list)
    index_files_deleted: int = 0
    raw_files_deleted: int = 0


def _month_end(month_key: str) -> date:
    year, month = (int(p) for p in month_key.split("-"))
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _available_month_keys(index_dir: Path) -> list[str]:
    if not index_dir.exists():
        return []
    return sorted(p.stem for p in index_dir.glob("*.sqlite3") if len(p.stem) == 7)


def _expired_month_keys(index_dir: Path, retention_days: int, today: date) -> list[str]:
    cutoff = today - timedelta(days=retention_days)
    current_month_key = today.strftime("%Y-%m")
    expired = []
    for month_key in _available_month_keys(index_dir):
        if month_key == current_month_key:
            continue  # safeguard (plan line 53): never the active partition
        if _month_end(month_key) < cutoff:
            expired.append(month_key)
    return expired


def _delete_index_month(index_dir: Path, month_key: str, today: date) -> int:
    assert month_key != today.strftime("%Y-%m"), "refusing to delete the current/active partition"
    deleted = 0
    # WAL mode (schema.py) leaves -wal/-shm sidecar files alongside the main
    # db file; drop those too or they'd linger as orphaned, unopenable junk.
    for suffix in ("", "-wal", "-shm"):
        path = index_dir / f"{month_key}.sqlite3{suffix}"
        if path.exists():
            path.unlink()
            deleted += 1
    return deleted


def _delete_raw_month(data_dir: Path, month_key: str, today: date) -> int:
    assert month_key != today.strftime("%Y-%m"), "refusing to delete the current/active partition"
    deleted = 0
    if not data_dir.exists():
        return deleted
    for device_dir in data_dir.iterdir():
        if not device_dir.is_dir():
            continue
        for log_file in device_dir.glob(f"{month_key}-*.log"):
            log_file.unlink()
            deleted += 1
    return deleted


def run_retention(config: RetentionConfig, today: date | None = None) -> RetentionSummary:
    """One retention pass. retention_days is read fresh from the control-plane
    settings table on every pass (rather than cached) since it's UI-editable
    at any time (plan line 50) and this process polls rather than being
    notified of changes.

    init_db is idempotent (CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE) and
    called here rather than assumed already run -- retention must work even
    if it starts before the webapp process ever has (plan line 52's
    "independent of receiver and UI" cuts both ways: this process can't
    depend on the UI having initialized app.sqlite3 first).
    """
    today = today or date.today()
    appdb.init_db(config.app_db_path)
    retention_days = int(appdb.get_setting(config.app_db_path, "retention_days", "365"))

    summary = RetentionSummary()
    for month_key in _expired_month_keys(config.index_dir, retention_days, today):
        summary.index_files_deleted += _delete_index_month(config.index_dir, month_key, today)
        summary.raw_files_deleted += _delete_raw_month(config.data_dir, month_key, today)
        summary.dropped_months.append(month_key)
        logger.info("retention: dropped month %s", month_key)
    return summary
