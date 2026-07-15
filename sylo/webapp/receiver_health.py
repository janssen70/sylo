from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..receiver.health import status_path

# Generous relative to the receiver's own ~10s heartbeat interval (plan
# section 11) -- wide enough to absorb a slow disk/GC pause without a false
# "down" reading, tight enough that a genuinely dead process (killed
# outright, host crash -- anything that skips a clean shutdown) is still
# flagged well within a minute.
_STALE_AFTER_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ReceiverHealthStatus:
    healthy: bool
    reason: str | None = None  # short description, shown when not healthy
    # UTC ISO timestamp reason applies "since" -- kept separate from `reason`
    # (rather than baked into that string) so the template can render it as
    # a <time datetime="..."> element and get the existing localtime.js
    # UTC-to-browser-local conversion (section 9 finding 1) for free.
    since: str | None = None


def read_receiver_health(index_dir: Path) -> ReceiverHealthStatus:
    """Best-effort read of the status file the receiver maintains (plan
    section 11) -- tolerant of it being missing entirely (receiver has
    never started even once) or malformed, since a webapp page render
    should never break because of it.
    """
    try:
        raw = status_path(index_dir).read_text()
    except OSError:
        return ReceiverHealthStatus(healthy=False, reason="Recording status unknown -- the receiver has not reported in yet.")

    try:
        data = json.loads(raw)
    except ValueError:
        return ReceiverHealthStatus(healthy=False, reason="Recording status unknown -- status file is malformed.")

    try:
        updated_at = datetime.fromisoformat(data["updated_at"])
    except (KeyError, TypeError, ValueError):
        return ReceiverHealthStatus(healthy=False, reason="Recording status unknown -- status file is malformed.")

    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds > _STALE_AFTER_SECONDS:
        return ReceiverHealthStatus(
            healthy=False,
            reason="Recording appears to be down -- no update from the receiver",
            since=data["updated_at"],
        )

    if data.get("state") == "error":
        return ReceiverHealthStatus(
            healthy=False,
            reason=f"Recording is not active: {data.get('error') or 'unknown error'}",
            since=data.get("error_since") or data["updated_at"],
        )

    return ReceiverHealthStatus(healthy=True)
