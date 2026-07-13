import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from sylo.indexer.config import IndexerConfig
from sylo.indexer.core import Indexer
from sylo.receiver.envelope import MessageEnvelope
from sylo.stats import QueueStats


def make_envelope(message: str, host: str = "myhost", **overrides) -> MessageEnvelope:
    defaults = dict(
        receipt_time=datetime.now(timezone.utc),
        source_ip="10.0.0.1",
        source_port=514,
        transport="udp",
        raw=b"raw",
        facility=4,
        severity=2,
        host=host,
        tag="su",
        message=message,
        malformed=False,
    )
    defaults.update(overrides)
    return MessageEnvelope(**defaults)


def query_all(index_dir, month_key: str):
    conn = sqlite3.connect(index_dir / f"{month_key}.sqlite3")
    try:
        return conn.execute(
            "SELECT receipt_time, source_ip, facility, severity, host, tag, message, malformed FROM messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_flush_on_idle_writes_row(tmp_path):
    config = IndexerConfig(index_dir=tmp_path, flush_idle_seconds=0.05, flush_max_rows=100)
    loop = asyncio.get_running_loop()
    indexer = Indexer(config, QueueStats(), loop)
    indexer.start()

    indexer.enqueue(make_envelope("hello indexer"))
    await asyncio.sleep(0.3)
    await indexer.stop()

    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = query_all(tmp_path, month_key)
    assert len(rows) == 1
    assert rows[0][6] == "hello indexer"


@pytest.mark.asyncio
async def test_flush_on_count_threshold(tmp_path):
    config = IndexerConfig(index_dir=tmp_path, flush_idle_seconds=10, flush_max_rows=5)
    loop = asyncio.get_running_loop()
    indexer = Indexer(config, QueueStats(), loop)
    indexer.start()

    for i in range(5):
        indexer.enqueue(make_envelope(f"msg{i}"))
    await asyncio.sleep(0.2)
    await indexer.stop()

    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = query_all(tmp_path, month_key)
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_hard_cap_drops_without_blocking(tmp_path):
    config = IndexerConfig(index_dir=tmp_path, flush_idle_seconds=10, queue_hard_limit=3, queue_soft_limit=1)
    loop = asyncio.get_running_loop()
    stats = QueueStats()
    indexer = Indexer(config, stats, loop)
    indexer.start()

    for i in range(20):
        indexer.enqueue(make_envelope(f"msg{i}"))

    assert stats.dropped > 0
    assert stats.lag_warnings > 0
    await indexer.stop()


@pytest.mark.asyncio
async def test_malformed_envelope_does_not_break_batch(tmp_path):
    config = IndexerConfig(index_dir=tmp_path, flush_idle_seconds=0.05, flush_max_rows=100)
    loop = asyncio.get_running_loop()
    indexer = Indexer(config, QueueStats(), loop)
    indexer.start()

    indexer.enqueue(make_envelope("good message before"))
    indexer.enqueue(make_envelope(None, malformed=True))  # message column is NOT NULL -- forces a per-row failure
    indexer.enqueue(make_envelope("good message after"))
    await asyncio.sleep(0.3)
    await indexer.stop()

    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = query_all(tmp_path, month_key)
    messages = [r[6] for r in rows]
    assert "good message before" in messages
    assert "good message after" in messages
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_indexes_created(tmp_path):
    config = IndexerConfig(index_dir=tmp_path, flush_idle_seconds=0.05)
    loop = asyncio.get_running_loop()
    indexer = Indexer(config, QueueStats(), loop)
    indexer.start()
    indexer.enqueue(make_envelope("hello"))
    await asyncio.sleep(0.2)
    await indexer.stop()

    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    conn = sqlite3.connect(tmp_path / f"{month_key}.sqlite3")
    try:
        names = {row[1] for row in conn.execute("PRAGMA index_list(messages)")}
    finally:
        conn.close()
    assert {
        "idx_messages_receipt_time",
        "idx_messages_host_time",
        "idx_messages_severity_time",
        "idx_messages_facility_time",
    } <= names
