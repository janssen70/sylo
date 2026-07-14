from __future__ import annotations

import asyncio
import logging
import signal

from .config import ReceiverConfig
from .server import SyslogServer

logger = logging.getLogger('sylo.receiver')


async def run(config: ReceiverConfig | None = None, stop_event: asyncio.Event | None = None) -> None:
    """stop_event is caller-supplied by the Windows service wrapper
    (winservice.py), whose SvcStop runs on a thread handed to it by the
    Service Control Manager -- separate from the thread that owns this
    event loop -- and so must reach into the loop via call_soon_threadsafe
    rather than setting an event created (and thus thread-affined) here."""
    config = config or ReceiverConfig.from_env()
    server = SyslogServer(config)
    await server.start()

    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # signal handlers on the event loop aren't available on Windows

    await stop_event.wait()
    logger.info('shutting down, draining device writers')
    await server.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    asyncio.run(run())


if __name__ == '__main__':
    main()
