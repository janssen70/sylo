from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("sylo.receiver.health")

STATUS_FILENAME = "receiver_status.json"


def status_path(index_dir: Path) -> Path:
    return index_dir / STATUS_FILENAME


class ReceiverHealth:
    """Persists the receiver's own startup/running state to a small JSON
    file so the webapp -- a separate process that, per plan section 3,
    only ever touches SQLite/files, never the receiver directly -- can
    detect and report when recording isn't actually happening (plan
    section 11).

    Written atomically (temp file + rename) so a concurrent reader never
    sees a half-written file. error_since is deliberately held steady
    across repeated retries of the *same* ongoing failure (only reset when
    a different error appears, or the receiver recovers) rather than
    refreshed on every attempt, so the UI can show "failing since X"
    accurately instead of that timestamp perpetually reading "just now".
    """

    def __init__(self, index_dir: Path) -> None:
        self._path = status_path(index_dir)
        self._error_since: str | None = None
        self._last_error: str | None = None

    def mark_running(self) -> None:
        self._error_since = None
        self._last_error = None
        self._write("running", None)

    def mark_failed(self, error: str) -> None:
        if error != self._last_error:
            self._last_error = error
            self._error_since = datetime.now(timezone.utc).isoformat()
        self._write("error", error)

    def _write(self, state: str, error: str | None) -> None:
        data = {
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
            "error_since": self._error_since,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data))
            tmp_path.replace(self._path)
        except OSError:
            logger.exception("failed to write receiver status file %s", self._path)
