"""Covers the part of each Windows-service wrapper (receiver, webapp,
retention) that's testable off Windows: that the underlying run(config,
stop_event) coroutine shuts down promptly when the stop_event is set via
call_soon_threadsafe, the same way each module's SvcStop crosses from the
SCM's thread into that process's own event loop thread. pywin32 itself
(each winservice.py's only Windows-only import) isn't installed on
non-Windows platforms, so the ServiceFramework subclasses themselves are not
exercised here.
"""
import asyncio
import socket
import threading

import pytest

from sylo.receiver.config import ReceiverConfig
from sylo.receiver.main import run
from sylo.retention.config import RetentionConfig
from sylo.retention.main import run as retention_run
from sylo.webapp import appdb
from sylo.webapp.config import WebConfig
from sylo.webapp.main import run as webapp_run


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_run_stops_on_externally_signalled_stop_event(tmp_path, monkeypatch):
    # run() builds its indexer config from the environment (it takes no
    # indexer_config override), so point that at tmp_path to avoid touching
    # the real ./data/index.
    monkeypatch.setenv("SYLO_INDEX_DIR", str(tmp_path / "index"))
    config = ReceiverConfig(
        bind_host="127.0.0.1",
        udp_port=free_port(),
        tcp_port=free_port(),
        data_dir=tmp_path / "raw",
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    run_task = asyncio.ensure_future(run(config, stop_event=stop_event))
    await asyncio.sleep(0.2)
    assert not run_task.done()

    # Simulate SvcStop being invoked on a separate OS thread, as the SCM does.
    threading.Thread(target=lambda: loop.call_soon_threadsafe(stop_event.set)).start()

    await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_webapp_run_stops_on_externally_signalled_stop_event(tmp_path):
    config = WebConfig(
        bind_host="127.0.0.1",
        port=free_port(),
        app_db_path=tmp_path / "app.sqlite3",
        index_dir=tmp_path / "index",
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    run_task = asyncio.ensure_future(webapp_run(config, stop_event=stop_event))
    await asyncio.sleep(0.3)
    assert not run_task.done()

    threading.Thread(target=lambda: loop.call_soon_threadsafe(stop_event.set)).start()

    await asyncio.wait_for(run_task, timeout=5)


@pytest.mark.asyncio
async def test_retention_run_stops_promptly_instead_of_waiting_out_the_interval(tmp_path):
    config = RetentionConfig(
        data_dir=tmp_path / "raw",
        index_dir=tmp_path / "index",
        app_db_path=tmp_path / "app.sqlite3",
        run_interval_seconds=9999,  # would hang the test if the stop signal didn't cross threads
    )
    appdb.init_db(config.app_db_path)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    run_task = asyncio.ensure_future(retention_run(config, stop_event=stop_event))
    await asyncio.sleep(0.2)
    assert not run_task.done()

    threading.Thread(target=lambda: loop.call_soon_threadsafe(stop_event.set)).start()

    await asyncio.wait_for(run_task, timeout=2)
