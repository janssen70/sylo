from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReceiverConfig:
    # Syslog listeners bind on all interfaces (unlike the section-3 HTTP/UI,
    # which is localhost-only) since remote devices send to this port.
    bind_host: str = "0.0.0.0"
    udp_port: int = 514
    tcp_port: int = 514

    data_dir: Path = Path('./data/raw')

    # Shared bounded thread pool for actual file write/fsync calls (line 17).
    executor_workers: int = 6

    # Per-device asyncio.Queue bounds (line 20). Soft: warn + lag counter.
    # Hard: drop + drop counter, never blocks ingest.
    queue_soft_limit: int = 1000
    queue_hard_limit: int = 5000

    # Flush on whichever comes first (line 19).
    flush_max_messages: int = 200
    flush_idle_seconds: float = 1.0
    fsync_interval_seconds: float = 2.0

    # Longest single line accepted from a TCP stream before it's treated as
    # malformed and dropped, guarding against unbounded memory from a
    # connection that never sends a newline.
    tcp_max_line_bytes: int = 64 * 1024

    @classmethod
    def from_env(cls) -> 'ReceiverConfig':
        # NB: with slots=True, `cls.field` returns the slot descriptor, not
        # the default value -- so defaults must come from an instance.
        d = cls()
        return cls(
            bind_host=os.environ.get('SYLO_BIND_HOST', d.bind_host),
            udp_port=int(os.environ.get('SYLO_UDP_PORT', d.udp_port)),
            tcp_port=int(os.environ.get('SYLO_TCP_PORT', d.tcp_port)),
            data_dir=Path(os.environ.get('SYLO_DATA_DIR', str(d.data_dir))),
            executor_workers=int(os.environ.get('SYLO_EXECUTOR_WORKERS', d.executor_workers)),
            queue_soft_limit=int(os.environ.get('SYLO_QUEUE_SOFT_LIMIT', d.queue_soft_limit)),
            queue_hard_limit=int(os.environ.get('SYLO_QUEUE_HARD_LIMIT', d.queue_hard_limit)),
            flush_max_messages=int(os.environ.get('SYLO_FLUSH_MAX_MESSAGES', d.flush_max_messages)),
            flush_idle_seconds=float(os.environ.get('SYLO_FLUSH_IDLE_SECONDS', d.flush_idle_seconds)),
            fsync_interval_seconds=float(os.environ.get('SYLO_FSYNC_INTERVAL_SECONDS', d.fsync_interval_seconds)),
            tcp_max_line_bytes=int(os.environ.get('SYLO_TCP_MAX_LINE_BYTES', d.tcp_max_line_bytes)),
        )
