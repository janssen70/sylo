from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .config import RetentionConfig
from .core import RetentionSummary, run_retention

logger = logging.getLogger("sylo.retention")


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
    """
    config = config or RetentionConfig.from_env()
    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # signal handlers on the event loop aren't available on Windows

    while True:
        try:
            summary = await loop.run_in_executor(None, run_retention, config)
            _log_summary(summary)
        except Exception:
            logger.exception("retention pass failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.run_interval_seconds)
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
