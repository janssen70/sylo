from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IndexerConfig:
    index_dir: Path = Path("./data/index")

    # Bounded queue feeding the single indexer task (line 20's mirror, line 36).
    queue_soft_limit: int = 2000
    queue_hard_limit: int = 10000

    # Batched commits (line 35): whichever comes first.
    flush_max_rows: int = 200
    flush_idle_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "IndexerConfig":
        d = cls()  # slots=True: cls.field would return the slot descriptor, not the default
        return cls(
            index_dir=Path(os.environ.get("SYLO_INDEX_DIR", str(d.index_dir))),
            queue_soft_limit=int(os.environ.get("SYLO_INDEX_QUEUE_SOFT_LIMIT", d.queue_soft_limit)),
            queue_hard_limit=int(os.environ.get("SYLO_INDEX_QUEUE_HARD_LIMIT", d.queue_hard_limit)),
            flush_max_rows=int(os.environ.get("SYLO_INDEX_FLUSH_MAX_ROWS", d.flush_max_rows)),
            flush_idle_seconds=float(os.environ.get("SYLO_INDEX_FLUSH_IDLE_SECONDS", d.flush_idle_seconds)),
        )
