"""In-memory overload counters (plan line 20 and its indexer mirror, line 36).

Single-threaded (event loop) access only, no locking needed. Exposed here as
a plain registry so a future section-3 health endpoint can read it without
depending on the receiver or indexer internals.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class QueueStats:
    queued: int = 0
    lag_warnings: int = 0
    dropped: int = 0
    written: int = 0


class StatsRegistry:
    """Per-key stats, e.g. one entry per device. The indexer, which has no
    per-device concept, just holds a single QueueStats directly instead."""

    def __init__(self) -> None:
        self._entries: dict[str, QueueStats] = {}

    def for_device(self, device_key: str) -> QueueStats:
        stats = self._entries.get(device_key)
        if stats is None:
            stats = QueueStats()
            self._entries[device_key] = stats
        return stats

    def snapshot(self) -> dict[str, QueueStats]:
        return dict(self._entries)
