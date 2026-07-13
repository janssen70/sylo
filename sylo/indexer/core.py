from __future__ import annotations

import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..receiver.envelope import MessageEnvelope
from ..stats import QueueStats
from ..timeutil import format_receipt_time
from .config import IndexerConfig
from .schema import INSERT_SQL, apply_schema

logger = logging.getLogger("sylo.indexer")


def _insert_batch(
    connections: dict[str, sqlite3.Connection],
    index_dir: Path,
    month_key: str,
    envelopes: list[MessageEnvelope],
) -> int:
    """Runs on the indexer's single executor thread. `connections` is only
    ever touched from that one thread, so the plain dict is safe without
    locking -- each message's insert is wrapped individually (plan line 33)
    so one bad row can't drop the rest of the batch or the whole flush."""
    conn = connections.get(month_key)
    if conn is None:
        index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(index_dir / f"{month_key}.sqlite3")
        apply_schema(conn)
        connections[month_key] = conn

    inserted = 0
    for envelope in envelopes:
        try:
            conn.execute(
                INSERT_SQL,
                (
                    format_receipt_time(envelope.receipt_time),
                    envelope.source_ip,
                    envelope.facility,
                    envelope.severity,
                    envelope.host,
                    envelope.tag,
                    envelope.message,
                    int(envelope.malformed),
                ),
            )
            inserted += 1
        except sqlite3.Error:
            logger.exception("indexer: failed to insert one row, skipping")
    conn.commit()
    return inserted


def _close_all(connections: dict[str, sqlite3.Connection]) -> None:
    for conn in connections.values():
        conn.close()


class Indexer:
    """Single shared task/queue for the whole process (unlike the receiver's
    per-device writers) -- there's one SQLite index, not one per device.

    Fed by the receiver's per-device writers, which hand over the
    MessageEnvelope they already parsed for the text file -- the indexer
    does not re-parse raw bytes.
    """

    def __init__(self, config: IndexerConfig, stats: QueueStats, loop: asyncio.AbstractEventLoop) -> None:
        self._config = config
        self._stats = stats
        self._loop = loop
        self._queue: asyncio.Queue[MessageEnvelope] = asyncio.Queue(maxsize=config.queue_hard_limit)
        # Own executor, separate from the receiver's file-write pool, so a
        # stalled/slow SQLite disk can't eat into the receiver's write
        # capacity (plan line 34). A single worker is enough since SQLite
        # writes are serialized per connection anyway.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sylo-indexer")
        self._connections: dict[str, sqlite3.Connection] = {}
        self._stopping = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = self._loop.create_task(self._run(), name="indexer")

    def enqueue(self, envelope: MessageEnvelope) -> None:
        """Sync, non-blocking. Slow/backed-up indexing must never delay
        ingest or the per-device writer that called this (plan line 34)."""
        qsize = self._queue.qsize()
        if qsize >= self._config.queue_soft_limit:
            self._stats.lag_warnings += 1
            logger.warning("indexer queue backlog at %d", qsize)
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            self._stats.dropped += 1
            logger.warning("indexer queue full, dropping message from indexing")
            return
        self._stats.queued = self._queue.qsize()

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            await self._task
        await self._loop.run_in_executor(self._executor, _close_all, self._connections)
        self._executor.shutdown(wait=True)

    async def _flush(self, buffer: list[MessageEnvelope]) -> None:
        by_month: dict[str, list[MessageEnvelope]] = {}
        for envelope in buffer:
            month_key = envelope.receipt_time.strftime("%Y-%m")
            by_month.setdefault(month_key, []).append(envelope)

        for month_key, envelopes in by_month.items():
            try:
                inserted = await self._loop.run_in_executor(
                    self._executor, _insert_batch, self._connections, self._config.index_dir, month_key, envelopes
                )
            except sqlite3.Error:
                logger.exception("indexer failed writing batch for month %s", month_key)
                self._stats.dropped += len(envelopes)
                continue
            self._stats.written += inserted

    async def _run(self) -> None:
        buffer: list[MessageEnvelope] = []
        while not self._stopping:
            try:
                envelope = await asyncio.wait_for(
                    self._queue.get(), timeout=self._config.flush_idle_seconds
                )
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush(buffer)
                    buffer = []
                continue
            buffer.append(envelope)
            self._stats.queued = self._queue.qsize()
            if len(buffer) >= self._config.flush_max_rows:
                await self._flush(buffer)
                buffer = []

        # Draining on shutdown: no more producers, pull whatever remains
        # without waiting on the idle timer.
        while not self._queue.empty():
            buffer.append(self._queue.get_nowait())
        if buffer:
            await self._flush(buffer)
