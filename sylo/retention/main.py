from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .config import RetentionConfig
from .core import RetentionSummary, run_retention

logger = logging.getLogger("sylo.retention")

# Backoff used when a pass fails before it even gets a usable interval to
# sleep on (e.g. config loading itself raised) -- short, so a transient
# startup race clears quickly, but nonzero so a persistently broken
# environment doesn't spin the loop.
_SETUP_FAILURE_RETRY_SECONDS = 60.0


def _log_summary(summary: RetentionSummary) -> None:
    logger.info(
        "retention pass complete: months=%s index_files=%d raw_files=%d",
        summary.dropped_months,
        summary.index_files_deleted,
        summary.raw_files_deleted,
    )


async def run(config: RetentionConfig | None = None, stop_event: asyncio.Event | None = None) -> None:
    """Periodic background loop (plan line 52), independent of the receiver
    and UI processes -- its own module/entry point, own process, touching
    only the on-disk data/index layout and the control-plane settings DB.
    stop_event follows the same external-signalling convention as
    receiver.main.run, for the same reason: a future service wrapper's
    SvcStop needs to cross from the SCM's thread into this loop's thread via
    call_soon_threadsafe.

    Loading config is deliberately re-attempted inside the loop's own
    try/except on every pass, rather than resolved once up front, so that a
    failure there (or anywhere else in a pass -- run_retention already
    tolerates missing data/index directories on its own, see core.py) is
    just another caught, logged, retried pass -- never an exception that
    escapes run() and takes the whole service down with it. A real
    deployment hit exactly the up-front version of this: the retention
    service crashed on its very first start, seconds after install and
    before app.sqlite3 existed yet, and -- with no service recovery action
    configured (see sylo.iss) -- simply stayed dead from then on. Mirrors
    the "never let a startup problem kill the process" philosophy already
    applied to the receiver (plan section 11).
    """
    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # signal handlers on the event loop aren't available on Windows

    while True:
        wait_seconds = _SETUP_FAILURE_RETRY_SECONDS
        try:
            active_config = config or RetentionConfig.from_env()
            summary = await loop.run_in_executor(None, run_retention, active_config)
            _log_summary(summary)
            wait_seconds = active_config.run_interval_seconds
        except Exception:
            logger.exception("retention pass failed -- will retry")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            continue
        break


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sylo retention manager")
    parser.add_argument(
        "--once", action="store_true", help="run a single retention pass and exit, instead of looping daily"
    )
    args = parser.parse_args()

    if args.once:
        _log_summary(run_retention(RetentionConfig.from_env()))
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
