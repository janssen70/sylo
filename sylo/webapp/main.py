from __future__ import annotations

import asyncio
import logging
import os
import signal

import uvicorn

from .app import create_app
from .config import WebConfig

logger = logging.getLogger("sylo.webapp")


async def run(config: WebConfig | None = None, stop_event: asyncio.Event | None = None) -> None:
    """stop_event is caller-supplied by the Windows service wrapper
    (winservice.py), the same convention as receiver.main.run and
    retention.main.run -- SvcStop runs on a thread handed to it by the
    Service Control Manager, separate from the thread running this event
    loop, so it signals shutdown via loop.call_soon_threadsafe(stop_event.set)
    rather than setting the event directly.

    Uses uvicorn.Server.serve() directly instead of the uvicorn.run()
    convenience wrapper, since the latter installs its own signal handlers
    and owns the asyncio.run() call -- neither is compatible with being
    driven by an externally-supplied stop_event. Signal handling is
    reinstated here instead, matching receiver.main.run.
    """
    config = config or WebConfig.from_env()
    app = create_app(config, initial_admin_password=os.environ.get("SYLO_ADMIN_PASSWORD"))
    # timeout_graceful_shutdown bounds how long uvicorn waits for open
    # connections to close on their own during shutdown -- without it, an
    # open live-tail SSE connection (section 3), which is designed to stay
    # open indefinitely, would block shutdown forever: found when the
    # SyloWebapp service failed to stop/exit (and its exe stayed locked on
    # disk through an uninstall) while a browser tab was still on the
    # live-tail page.
    server = uvicorn.Server(
        uvicorn.Config(
            app, host=config.bind_host, port=config.port, log_level="info", timeout_graceful_shutdown=5
        )
    )

    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # signal handlers on the event loop aren't available on Windows

    async def _watch_stop() -> None:
        await stop_event.wait()
        server.should_exit = True

    watcher = asyncio.ensure_future(_watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
