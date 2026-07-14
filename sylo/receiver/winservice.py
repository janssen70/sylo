"""Windows service wrapper for the syslog receiver (plan line 24).

Imports only from sylo.receiver -- no dependency on sylo.webapp, so the
receiver service can be installed, started, stopped, and restarted with no
regard for whether the UI service is even installed. Windows-only: relies
on pywin32, which isn't installed/importable on non-Windows platforms.

Usage (once pywin32 is available, i.e. on Windows):
    python -m sylo.receiver.winservice install
    python -m sylo.receiver.winservice start|stop|restart|remove
"""
from __future__ import annotations

import asyncio
import logging
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from .config import ReceiverConfig
from .main import run

logger = logging.getLogger("sylo.receiver.winservice")


class SyloReceiverService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SyloReceiver"
    _svc_display_name_ = "Sylo Syslog Receiver"
    _svc_description_ = (
        "Receives and records syslog messages over UDP/TCP 514. "
        "Runs independently of the Sylo web UI service."
    )

    def __init__(self, args) -> None:
        super().__init__(args)
        self._wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        # Cross from the SCM's stop-request thread into the receiver's own
        # event loop thread -- see the docstring on receiver.main.run.
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
            self._loop.run_until_complete(run(ReceiverConfig.from_env(), stop_event=self._stop_event))
        except Exception:
            logger.exception("receiver service crashed")
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
        servicemanager.PrepareToHostSingle(SyloReceiverService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SyloReceiverService)


if __name__ == "__main__":
    main()
