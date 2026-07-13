"""In-memory overload counters (plan line 20).

Single-threaded (event loop) access only, no locking needed. Exposed here as
a plain registry so a future section-3 health endpoint can read it without
the receiver depending on the HTTP layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeviceStats:
    queued: int = 0
    lag_warnings: int = 0
    dropped: int = 0
    written: int = 0


class StatsRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, DeviceStats] = {}

    def for_device(self, device_key: str) -> DeviceStats:
        stats = self._devices.get(device_key)
        if stats is None:
            stats = DeviceStats()
            self._devices[device_key] = stats
        return stats

    def snapshot(self) -> dict[str, DeviceStats]:
        return dict(self._devices)
