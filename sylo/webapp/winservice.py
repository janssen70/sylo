"""Windows service wrapper for the webapp (plan section 5).

Mirrors sylo/receiver/winservice.py exactly -- see that module's docstring
for the cross-thread stop-signalling rationale. Imports only from
sylo.webapp, so this service's install/start/stop/restart is independent of
the receiver service (plan line 58/section 1 line 24). Windows-only: relies
on pywin32, which isn't installed/importable on non-Windows platforms.

Usage (once pywin32 is available, i.e. on Windows):
    python -m sylo.webapp.winservice install
    python -m sylo.webapp.winservice start|stop|restart|remove
"""
from __future__ import annotations

import asyncio
import logging
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from .config import WebConfig
from .main import run

logger = logging.getLogger("sylo.webapp.winservice")


class SyloWebappService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SyloWebapp"
    _svc_display_name_ = "Sylo Web UI"
    _svc_description_ = (
        "Serves the Sylo message browser, live tail, and settings UI on "
        "127.0.0.1. Runs independently of the Sylo receiver service."
    )

    def __init__(self, args) -> None:
        super().__init__(args)
        self._wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        win32event.SetEvent(self._wait_stop)

    def SvcDoRun(self) -> None:
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(run(WebConfig.from_env(), stop_event=self._stop_event))
        except Exception:
            logger.exception("webapp service crashed")
            raise
        finally:
            self._loop.close()
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )


def main() -> None:
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SyloWebappService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SyloWebappService)


if __name__ == "__main__":
    main()
