from __future__ import annotations

import asyncio
import logging
import signal

from ..indexer.config import IndexerConfig
from .config import ReceiverConfig
from .health import ReceiverHealth
from .server import SyslogServer

logger = logging.getLogger('sylo.receiver')

# How long to wait between failed start attempts (plan section 11) -- fixed
# rather than exponential-with-backoff for now: simpler, and a failure like
# a port blocked by another process or an EDR product tends to persist for a
# long time (until someone fixes the underlying cause) rather than clearing
# up within seconds, so there's little to gain from retrying faster early on.
# Revisit if this ever proves too noisy in logs over a multi-day outage.
_RETRY_INTERVAL_SECONDS = 30.0

# How often to refresh the status file's heartbeat while running normally --
# short enough that the webapp (polling this file, plan section 11) notices
# a hard-killed process (no clean stop, e.g. SIGKILL or a host crash) within
# a bounded time, long enough that it's not meaningful I/O overhead.
_HEARTBEAT_INTERVAL_SECONDS = 10.0


async def _interruptible_sleep(stop_event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


async def _start_with_retry(
    config: ReceiverConfig,
    indexer_config: IndexerConfig,
    health: ReceiverHealth,
    stop_event: asyncio.Event,
) -> SyslogServer | None:
    """Keeps retrying SyslogServer.start() on failure instead of letting the
    exception propagate and kill the process -- prompted by a real incident
    (plan section 11) where a corporate EDR product silently blocked the
    receiver from binding its port: that failure was never going to clear up
    within the process's own lifetime, but also isn't something worth
    crashing (and, on Linux, crash-looping against systemd's Restart=
    policy) over. Once the underlying cause is fixed externally, this picks
    back up on its own on the next retry -- no manual restart needed.

    Returns the successfully-started server, or None if told to stop while
    still retrying (i.e. it never got to serve anything).
    """
    while not stop_event.is_set():
        server = SyslogServer(config, indexer_config)
        try:
            await server.start()
            health.mark_running()
            return server
        except Exception as exc:
            logger.exception("receiver failed to start, will retry in %.0fs", _RETRY_INTERVAL_SECONDS)
            health.mark_failed(str(exc))
            try:
                await server.stop()
            except Exception:
                logger.exception("error cleaning up after failed start")
            await _interruptible_sleep(stop_event, _RETRY_INTERVAL_SECONDS)
    return None


async def _heartbeat_loop(health: ReceiverHealth, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await _interruptible_sleep(stop_event, _HEARTBEAT_INTERVAL_SECONDS)
        if not stop_event.is_set():
            health.mark_running()


async def run(config: ReceiverConfig | None = None, stop_event: asyncio.Event | None = None) -> None:
    """stop_event is caller-supplied by the Windows service wrapper
    (winservice.py), whose SvcStop runs on a thread handed to it by the
    Service Control Manager -- separate from the thread that owns this
    event loop -- and so must reach into the loop via call_soon_threadsafe
    rather than setting an event created (and thus thread-affined) here."""
    config = config or ReceiverConfig.from_env()
    indexer_config = IndexerConfig.from_env()
    health = ReceiverHealth(indexer_config.index_dir)

    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # signal handlers on the event loop aren't available on Windows

    server = await _start_with_retry(config, indexer_config, health, stop_event)
    if server is None:
        return  # told to stop before ever starting successfully

    heartbeat_task = asyncio.ensure_future(_heartbeat_loop(health, stop_event))
    await stop_event.wait()
    heartbeat_task.cancel()
    logger.info('shutting down, draining device writers')
    await server.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    asyncio.run(run())


if __name__ == '__main__':
    main()
