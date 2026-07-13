import sqlite3

from sylo.indexer.schema import apply_schema, insert_message
from sylo.webapp.config import WebConfig
from sylo.webapp.queries import MessageFilter, list_devices, search_messages


def seed_month(index_dir, month_key, rows):
    index_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_dir / f"{month_key}.sqlite3")
    apply_schema(conn)
    for row in rows:
        insert_message(conn, **row)
    conn.commit()
    conn.close()


def base_row(**overrides):
    row = dict(
        receipt_time="2026-07-13T00:00:00.000000+00:00",
        source_ip="10.0.0.1",
        facility=4,
        severity=2,
        host="hostA",
        tag="su",
        message="default message",
        malformed=False,
    )
    row.update(overrides)
    return row


def test_pagination_across_single_month(tmp_path):
    index_dir = tmp_path / "index"
    rows = [
        base_row(receipt_time=f"2026-07-13T00:00:0{i}.000000+00:00", message=f"event {i}")
        for i in range(6)
    ]
    seed_month(index_dir, "2026-07", rows)
    config = WebConfig(index_dir=index_dir, recent_months_scanned=3)

    page1 = search_messages(config, MessageFilter(), offset=0, limit=3)
    assert [r["message"] for r in page1.rows] == ["event 5", "event 4", "event 3"]
    assert page1.has_more

    page2 = search_messages(config, MessageFilter(), offset=3, limit=3)
    assert [r["message"] for r in page2.rows] == ["event 2", "event 1", "event 0"]
    assert not page2.has_more


def test_filters_host_severity_facility(tmp_path):
    index_dir = tmp_path / "index"
    rows = [
        base_row(host="hostA", severity=2, facility=4, message="from A"),
        base_row(host="hostB", severity=6, facility=9, message="from B"),
    ]
    seed_month(index_dir, "2026-07", rows)
    config = WebConfig(index_dir=index_dir)

    assert [r["message"] for r in search_messages(config, MessageFilter(host="hostB"), 0, 10).rows] == ["from B"]
    assert [r["message"] for r in search_messages(config, MessageFilter(severity=6), 0, 10).rows] == ["from B"]
    assert [r["message"] for r in search_messages(config, MessageFilter(facility=4), 0, 10).rows] == ["from A"]


def test_free_text_search_uses_fts(tmp_path):
    index_dir = tmp_path / "index"
    rows = [
        base_row(message="authentication failure for root"),
        base_row(message="session opened for bob"),
    ]
    seed_month(index_dir, "2026-07", rows)
    config = WebConfig(index_dir=index_dir)

    result = search_messages(config, MessageFilter(text="authentication"), 0, 10)
    assert [r["message"] for r in result.rows] == ["authentication failure for root"]


def test_time_range_filter(tmp_path):
    index_dir = tmp_path / "index"
    rows = [
        base_row(receipt_time="2026-07-01T00:00:00.000000+00:00", message="early"),
        base_row(receipt_time="2026-07-20T00:00:00.000000+00:00", message="late"),
    ]
    seed_month(index_dir, "2026-07", rows)
    config = WebConfig(index_dir=index_dir)

    result = search_messages(
        config,
        MessageFilter(start="2026-07-10T00:00:00.000000+00:00"),
        0,
        10,
    )
    assert [r["message"] for r in result.rows] == ["late"]


def test_time_range_restricts_which_months_are_scanned(tmp_path):
    index_dir = tmp_path / "index"
    seed_month(
        index_dir,
        "2026-06",
        [base_row(receipt_time="2026-06-15T00:00:00.000000+00:00", message="june event")],
    )
    seed_month(
        index_dir,
        "2026-07",
        [base_row(receipt_time="2026-07-15T00:00:00.000000+00:00", message="july event")],
    )
    config = WebConfig(index_dir=index_dir, recent_months_scanned=1)

    # No range given: only the most recent month is scanned.
    result = search_messages(config, MessageFilter(), 0, 10)
    assert [r["message"] for r in result.rows] == ["july event"]

    # Explicit range covering June should reach it despite recent_months_scanned=1.
    result = search_messages(
        config,
        MessageFilter(start="2026-06-01T00:00:00.000000+00:00", end="2026-06-30T23:59:59.000000+00:00"),
        0,
        10,
    )
    assert [r["message"] for r in result.rows] == ["june event"]


def test_search_across_multiple_months_merges_and_sorts(tmp_path):
    index_dir = tmp_path / "index"
    seed_month(index_dir, "2026-06", [base_row(receipt_time="2026-06-15T00:00:00.000000+00:00", message="june")])
    seed_month(index_dir, "2026-07", [base_row(receipt_time="2026-07-15T00:00:00.000000+00:00", message="july")])
    config = WebConfig(index_dir=index_dir, recent_months_scanned=2)

    result = search_messages(config, MessageFilter(), 0, 10)
    assert [r["message"] for r in result.rows] == ["july", "june"]


def test_malformed_only_filter(tmp_path):
    index_dir = tmp_path / "index"
    rows = [
        base_row(message="clean", malformed=False),
        base_row(message="garbage", malformed=True),
    ]
    seed_month(index_dir, "2026-07", rows)
    config = WebConfig(index_dir=index_dir)

    result = search_messages(config, MessageFilter(malformed_only=True), 0, 10)
    assert [r["message"] for r in result.rows] == ["garbage"]


def test_list_devices_aggregates_across_months(tmp_path):
    index_dir = tmp_path / "index"
    seed_month(
        index_dir,
        "2026-06",
        [base_row(source_ip="10.0.0.1", host="hostA", receipt_time="2026-06-01T00:00:00.000000+00:00")],
    )
    seed_month(
        index_dir,
        "2026-07",
        [
            base_row(source_ip="10.0.0.1", host="hostA", receipt_time="2026-07-01T00:00:00.000000+00:00"),
            base_row(source_ip="10.0.0.2", host="hostB", receipt_time="2026-07-02T00:00:00.000000+00:00"),
        ],
    )
    config = WebConfig(index_dir=index_dir, recent_months_scanned=2)

    devices = list_devices(config)
    by_ip = {d.source_ip: d for d in devices}
    assert by_ip["10.0.0.1"].message_count == 2
    assert by_ip["10.0.0.1"].last_seen == "2026-07-01T00:00:00.000000+00:00"
    assert by_ip["10.0.0.2"].message_count == 1
    assert devices[0].source_ip == "10.0.0.2"  # last_seen 2026-07-02, most recent first


def test_no_index_dir_returns_empty(tmp_path):
    config = WebConfig(index_dir=tmp_path / "does-not-exist")
    result = search_messages(config, MessageFilter(), 0, 10)
    assert result.rows == []
    assert not result.has_more
    assert list_devices(config) == []
