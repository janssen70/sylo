from datetime import date
from pathlib import Path

import pytest

from sylo.retention.config import RetentionConfig
from sylo.retention.core import _delete_index_month, _delete_raw_month, _expired_month_keys, run_retention
from sylo.webapp import appdb


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def make_config(tmp_path: Path, **overrides) -> RetentionConfig:
    defaults = dict(
        data_dir=tmp_path / "raw",
        index_dir=tmp_path / "index",
        app_db_path=tmp_path / "app.sqlite3",
    )
    defaults.update(overrides)
    return RetentionConfig(**defaults)


def test_expired_month_keys_never_includes_current_month(tmp_path):
    index_dir = tmp_path / "index"
    touch(index_dir / "2024-01.sqlite3")
    touch(index_dir / "2026-07.sqlite3")  # "current" month in this test

    expired = _expired_month_keys(index_dir, retention_days=0, today=date(2026, 7, 14))
    assert expired == ["2024-01"]


def test_expired_month_keys_respects_retention_window(tmp_path):
    index_dir = tmp_path / "index"
    touch(index_dir / "2026-05.sqlite3")
    touch(index_dir / "2026-06.sqlite3")

    # 30-day retention on 2026-07-14: cutoff is 2026-06-14, so 2026-05 (ends
    # 05-31) is expired but 2026-06 (ends 06-30) is not yet.
    expired = _expired_month_keys(index_dir, retention_days=30, today=date(2026, 7, 14))
    assert expired == ["2026-05"]


def test_run_retention_drops_index_db_and_wal_shm_sidecars(tmp_path):
    config = make_config(tmp_path)
    touch(config.index_dir / "2024-01.sqlite3")
    touch(config.index_dir / "2024-01.sqlite3-wal")
    touch(config.index_dir / "2024-01.sqlite3-shm")
    touch(config.index_dir / "2026-07.sqlite3")  # current month, must survive

    appdb.init_db(config.app_db_path)
    appdb.set_setting(config.app_db_path, "retention_days", "365")

    summary = run_retention(config, today=date(2026, 7, 14))

    assert summary.dropped_months == ["2024-01"]
    assert summary.index_files_deleted == 3
    assert not (config.index_dir / "2024-01.sqlite3").exists()
    assert not (config.index_dir / "2024-01.sqlite3-wal").exists()
    assert not (config.index_dir / "2024-01.sqlite3-shm").exists()
    assert (config.index_dir / "2026-07.sqlite3").exists()


def test_run_retention_drops_only_matching_raw_daily_files(tmp_path):
    config = make_config(tmp_path)
    touch(config.index_dir / "2024-01.sqlite3")
    touch(config.data_dir / "10.0.0.1" / "2024-01-05.log")
    touch(config.data_dir / "10.0.0.1" / "2024-01-31.log")
    touch(config.data_dir / "10.0.0.1" / "2024-02-01.log")  # different month, must survive
    touch(config.data_dir / "10.0.0.2" / "2024-01-15.log")

    appdb.init_db(config.app_db_path)
    appdb.set_setting(config.app_db_path, "retention_days", "1")

    summary = run_retention(config, today=date(2026, 7, 14))

    assert summary.raw_files_deleted == 3
    assert not (config.data_dir / "10.0.0.1" / "2024-01-05.log").exists()
    assert not (config.data_dir / "10.0.0.1" / "2024-01-31.log").exists()
    assert not (config.data_dir / "10.0.0.2" / "2024-01-15.log").exists()
    assert (config.data_dir / "10.0.0.1" / "2024-02-01.log").exists()


def test_run_retention_never_touches_current_month_even_with_zero_retention(tmp_path):
    config = make_config(tmp_path)
    touch(config.index_dir / "2026-07.sqlite3")
    touch(config.data_dir / "10.0.0.1" / "2026-07-14.log")

    appdb.init_db(config.app_db_path)
    appdb.set_setting(config.app_db_path, "retention_days", "0")

    summary = run_retention(config, today=date(2026, 7, 14))

    assert summary.dropped_months == []
    assert (config.index_dir / "2026-07.sqlite3").exists()
    assert (config.data_dir / "10.0.0.1" / "2026-07-14.log").exists()


def test_delete_helpers_refuse_current_month_as_defense_in_depth(tmp_path):
    config = make_config(tmp_path)
    today = date(2026, 7, 14)
    with pytest.raises(AssertionError):
        _delete_index_month(config.index_dir, "2026-07", today)
    with pytest.raises(AssertionError):
        _delete_raw_month(config.data_dir, "2026-07", today)


def test_run_retention_reads_retention_days_from_settings_each_pass(tmp_path):
    config = make_config(tmp_path)
    touch(config.index_dir / "2026-06.sqlite3")
    appdb.init_db(config.app_db_path)

    today = date(2026, 7, 14)
    # Default settings (from appdb.init_db) is 365 days: 2026-06 shouldn't expire.
    assert run_retention(config, today=today).dropped_months == []

    appdb.set_setting(config.app_db_path, "retention_days", "10")
    assert run_retention(config, today=today).dropped_months == ["2026-06"]
