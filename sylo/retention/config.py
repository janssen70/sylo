from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    # Same defaults/env vars as ReceiverConfig.data_dir and WebConfig's
    # index_dir/app_db_path -- retention reads/deletes the same on-disk
    # layout those processes already write to, out of the box.
    data_dir: Path = Path("./data/raw")
    index_dir: Path = Path("./data/index")
    app_db_path: Path = Path("./data/app.sqlite3")

    # How often the background loop runs a pass (plan line 52: daily).
    run_interval_seconds: float = 24 * 3600

    @classmethod
    def from_env(cls) -> "RetentionConfig":
        d = cls()  # slots=True: cls.field is a slot descriptor, not the default
        return cls(
            data_dir=Path(os.environ.get("SYLO_DATA_DIR", str(d.data_dir))),
            index_dir=Path(os.environ.get("SYLO_INDEX_DIR", str(d.index_dir))),
            app_db_path=Path(os.environ.get("SYLO_APP_DB", str(d.app_db_path))),
            run_interval_seconds=float(
                os.environ.get("SYLO_RETENTION_INTERVAL_SECONDS", d.run_interval_seconds)
            ),
        )
