"""Windows service wrapper for the retention manager (plan sections 4/5).

Mirrors sylo/receiver/winservice.py exactly -- see that module's docstring
for the cross-thread stop-signalling rationale. Imports only from
sylo.retention (which itself only reaches into sylo.webapp.appdb for the
shared settings-table accessor, not the webapp process itself), so this
service's install/start/stop/restart is independent of both the receiver and
webapp services. Windows-only: relies on pywin32, which isn't
installed/importable on non-Windows platforms.

Usage (once pywin32 is available, i.e. on Windows):
    python -m sylo.retention.winservice install
    python -m sylo.retention.winservice start|stop|restart|remove
"""
from __future__ import annotations

import asyncio
import logging
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from .main import run

logger = logging.getLogger("sylo.retention.winservice")


class SyloRetentionService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SyloRetention"
    _svc_display_name_ = "Sylo Retention Manager"
    _svc_description_ = (
        "Periodically drops monthly message-index and raw-log partitions "
        "older than the configured retention window. Runs independently of "
        "the Sylo receiver and web UI services."
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
            # config is intentionally left unset here -- run() now loads it
            # itself, inside its own per-pass try/except, so a bad/transient
            # RetentionConfig.from_env() can never raise from this line and
            # take the service down before the loop's own retry logic gets a
            # chance to run (see main.py's run() docstring for the incident
            # that prompted this).
            self._loop.run_until_complete(run(stop_event=self._stop_event))
        except Exception:
            logger.exception("retention service crashed")
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
        servicemanager.PrepareToHostSingle(SyloRetentionService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SyloRetentionService)


if __name__ == "__main__":
    main()
