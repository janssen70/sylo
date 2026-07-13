import sqlite3
from pathlib import Path

from sylo.indexer.rebuild import rebuild_indexer
from sylo.timeutil import format_receipt_time
from datetime import datetime, timezone


def write_log(data_dir: Path, device: str, day: str, lines: list[str]) -> None:
    device_dir = data_dir / device
    device_dir.mkdir(parents=True, exist_ok=True)
    (device_dir / f"{day}.log").write_text("\n".join(lines) + "\n")


def test_rebuild_reconstructs_rows(tmp_path):
    data_dir = tmp_path / "raw"
    index_dir = tmp_path / "index"
    ts = format_receipt_time(datetime(2026, 7, 13, tzinfo=timezone.utc))
    write_log(
        data_dir,
        "10.0.0.1",
        "2026-07-13",
        [
            f"{ts} <34>Oct 11 22:14:15 mymachine su: rebuilt message one",
            f"{ts} <34>Oct 11 22:14:16 mymachine su: rebuilt message two",
        ],
    )

    counts = rebuild_indexer(data_dir, index_dir)
    assert counts == {"2026-07": 2}

    conn = sqlite3.connect(index_dir / "2026-07.sqlite3")
    try:
        rows = conn.execute(
            "SELECT source_ip, host, tag, message FROM messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("10.0.0.1", "mymachine", "su", "rebuilt message one"),
        ("10.0.0.1", "mymachine", "su", "rebuilt message two"),
    ]


def test_rebuild_replaces_corrupted_db(tmp_path):
    data_dir = tmp_path / "raw"
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True)
    corrupt_path = index_dir / "2026-07.sqlite3"
    corrupt_path.write_bytes(b"not a real sqlite file")

    ts = format_receipt_time(datetime(2026, 7, 13, tzinfo=timezone.utc))
    write_log(data_dir, "10.0.0.2", "2026-07-13", [f"{ts} <34>Oct 11 22:14:15 host su: fresh message"])

    counts = rebuild_indexer(data_dir, index_dir)
    assert counts == {"2026-07": 1}

    conn = sqlite3.connect(corrupt_path)
    try:
        rows = conn.execute("SELECT message FROM messages").fetchall()
    finally:
        conn.close()
    assert rows == [("fresh message",)]


def test_rebuild_month_filter_skips_other_months(tmp_path):
    data_dir = tmp_path / "raw"
    index_dir = tmp_path / "index"
    ts_july = format_receipt_time(datetime(2026, 7, 13, tzinfo=timezone.utc))
    ts_aug = format_receipt_time(datetime(2026, 8, 1, tzinfo=timezone.utc))
    write_log(data_dir, "10.0.0.3", "2026-07-13", [f"{ts_july} <34>Oct 11 22:14:15 host su: july"])
    write_log(data_dir, "10.0.0.3", "2026-08-01", [f"{ts_aug} <34>Oct 11 22:14:15 host su: august"])

    counts = rebuild_indexer(data_dir, index_dir, months={"2026-07"})
    assert counts == {"2026-07": 1}
    assert not (index_dir / "2026-08.sqlite3").exists()


def test_rebuild_handles_malformed_lines_gracefully(tmp_path):
    data_dir = tmp_path / "raw"
    index_dir = tmp_path / "index"
    ts = format_receipt_time(datetime(2026, 7, 13, tzinfo=timezone.utc))
    write_log(
        data_dir,
        "10.0.0.4",
        "2026-07-13",
        [
            "no-timestamp-separator-at-all",
            f"{ts} <34>Oct 11 22:14:15 host su: valid line",
        ],
    )

    counts = rebuild_indexer(data_dir, index_dir)
    assert counts == {"2026-07": 1}
