from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from .config import ReceiverConfig
from .envelope import MessageEnvelope, RawMessage
from .stats import DeviceStats, StatsRegistry

logger = logging.getLogger("sylo.receiver.device_writer")


def _sanitize_device_key(ip: str) -> str:
    # IPv6 addresses contain ':', which is invalid in Windows path segments.
    return ip.replace(":", "_")


def _write_sync(path: Path, lines: list[str], fsync: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        if fsync:
            os.fsync(f.fileno())


class DeviceWriter:
    """One per device (keyed by source IP): own queue + own writer coroutine.

    A slow/stalled write for this device only shares the small executor pool
    with other devices, never the event loop, so it cannot block ingest for
    any other device (plan line 18).
    """

    def __init__(
        self,
        device_key: str,
        config: ReceiverConfig,
        executor: ThreadPoolExecutor,
        stats: DeviceStats,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.device_key = device_key
        self._config = config
        self._executor = executor
        self._stats = stats
        self._loop = loop
        self._queue: asyncio.Queue[RawMessage] = asyncio.Queue(maxsize=config.queue_hard_limit)
        self._last_fsync = 0.0
        self._stopping = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = self._loop.create_task(self._run(), name=f"device-writer-{self.device_key}")

    def enqueue(self, raw_message: RawMessage) -> None:
        """Sync, non-blocking. Called directly from the ingest callback --
        no parsing happens here, only queueing (plan line 17)."""
        qsize = self._queue.qsize()
        if qsize >= self._config.queue_soft_limit:
            self._stats.lag_warnings += 1
            logger.warning("device %s queue backlog at %d", self.device_key, qsize)
        try:
            self._queue.put_nowait(raw_message)
        except asyncio.QueueFull:
            self._stats.dropped += 1
            logger.warning("device %s queue full, dropping message", self.device_key)
            return
        self._stats.queued = self._queue.qsize()

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            await self._task

    def _path_for(self, day: date) -> Path:
        return self._config.data_dir / _sanitize_device_key(self.device_key) / f"{day.isoformat()}.log"

    async def _flush(self, buffer: list[MessageEnvelope], force_fsync: bool = False) -> None:
        by_date: dict[date, list[str]] = {}
        for envelope in buffer:
            by_date.setdefault(envelope.receipt_time.date(), []).append(envelope.to_line())

        do_fsync = force_fsync or (
            time.monotonic() - self._last_fsync >= self._config.fsync_interval_seconds
        )
        for day, lines in by_date.items():
            path = self._path_for(day)
            try:
                await self._loop.run_in_executor(self._executor, _write_sync, path, lines, do_fsync)
            except OSError:
                logger.exception("device %s failed writing %s", self.device_key, path)
                continue
            self._stats.written += len(lines)
        if do_fsync:
            self._last_fsync = time.monotonic()

    async def _run(self) -> None:
        buffer: list[MessageEnvelope] = []
        while not self._stopping:
            try:
                raw_message = await asyncio.wait_for(
                    self._queue.get(), timeout=self._config.flush_idle_seconds
                )
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush(buffer)
                    buffer = []
                continue
            buffer.append(MessageEnvelope.from_raw(raw_message))
            self._stats.queued = self._queue.qsize()
            if len(buffer) >= self._config.flush_max_messages:
                await self._flush(buffer)
                buffer = []

        # Draining on shutdown: no more producers, so pull whatever remains
        # without waiting on the idle timer, then flush with a forced fsync.
        while not self._queue.empty():
            buffer.append(MessageEnvelope.from_raw(self._queue.get_nowait()))
        if buffer:
            await self._flush(buffer, force_fsync=True)


class DeviceRegistry:
    """Creates/looks up one DeviceWriter per source IP, lazily."""

    def __init__(
        self,
        config: ReceiverConfig,
        executor: ThreadPoolExecutor,
        stats_registry: StatsRegistry,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._config = config
        self._executor = executor
        self._stats_registry = stats_registry
        self._loop = loop
        self._writers: dict[str, DeviceWriter] = {}

    def get_or_create(self, device_key: str) -> DeviceWriter:
        writer = self._writers.get(device_key)
        if writer is None:
            writer = DeviceWriter(
                device_key,
                self._config,
                self._executor,
                self._stats_registry.for_device(device_key),
                self._loop,
            )
            writer.start()
            self._writers[device_key] = writer
        return writer

    async def stop_all(self) -> None:
        await asyncio.gather(*(w.stop() for w in self._writers.values()))
