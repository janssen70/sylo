"""Plan section 11: the receiver must retry a failed start (e.g. its port
already claimed by something else, or blocked outright by an EDR product,
per that section's prompting incident) instead of letting the exception
kill the process, and must record that failure to a status file the webapp
can read.
"""
import asyncio
import itertools
import json
import socket
from datetime import datetime, timedelta

import pytest

import sylo.receiver.health as health_module
from sylo.receiver.config import ReceiverConfig
from sylo.receiver.health import ReceiverHealth, status_path
from sylo.receiver.main import run


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_records_running_state(tmp_path):
    health = ReceiverHealth(tmp_path)
    health.mark_running()
    data = json.loads(status_path(tmp_path).read_text())
    assert data["state"] == "running"
    assert data["error"] is None
    assert data["error_since"] is None


def test_health_keeps_error_since_steady_across_repeated_same_failure(tmp_path, monkeypatch):
    # datetime.now() calls made microseconds apart can land in the same
    # underlying clock tick on Windows and compare equal -- a fixed,
    # monotonically-increasing fake clock makes the "did error_since move"
    # assertions below deterministic instead of occasionally flaky.
    counter = itertools.count()

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, tzinfo=tz) + timedelta(microseconds=next(counter))

    monkeypatch.setattr(health_module, "datetime", _FixedDatetime)

    health = ReceiverHealth(tmp_path)
    health.mark_failed("boom")
    first = json.loads(status_path(tmp_path).read_text())["error_since"]
    assert first is not None

    health.mark_failed("boom")  # same error again -- error_since must not move
    second = json.loads(status_path(tmp_path).read_text())["error_since"]
    assert second == first

    health.mark_failed("different failure")  # a new failure resets it
    third = json.loads(status_path(tmp_path).read_text())["error_since"]
    assert third != first

    health.mark_running()  # recovering clears both error and error_since
    data = json.loads(status_path(tmp_path).read_text())
    assert data["state"] == "running"
    assert data["error"] is None
    assert data["error_since"] is None


@pytest.mark.asyncio
async def test_run_retries_bind_failure_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("SYLO_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setattr("sylo.receiver.main._RETRY_INTERVAL_SECONDS", 0.05)

    udp_port = free_port()
    config = ReceiverConfig(
        bind_host="127.0.0.1",
        udp_port=udp_port,
        tcp_port=free_port(),
        data_dir=tmp_path / "raw",
    )

    # Occupy the UDP port first so the receiver's own bind attempt fails,
    # exactly like another process (or an EDR product) already holding it.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", udp_port))

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(run(config, stop_event=stop_event))
    try:
        # Generous budgets (not just the ~0.1s the happy path needs) since
        # under a full-suite run other tests' disk/thread contention can
        # slow this down noticeably -- the loops break as soon as the
        # condition is met either way, so this costs nothing in the common case.
        for _ in range(200):
            await asyncio.sleep(0.05)
            status_file = status_path(tmp_path / "index")
            if status_file.exists() and json.loads(status_file.read_text())["state"] == "error":
                break
        else:
            pytest.fail("receiver never recorded an error status")
        assert not run_task.done(), "a failed start must not kill the process"

        blocker.close()  # free the port -- the retry loop should now succeed

        for _ in range(200):
            await asyncio.sleep(0.05)
            data = json.loads(status_file.read_text())
            if data["state"] == "running":
                break
        else:
            pytest.fail("receiver never recovered after the port freed up")
        assert data["error"] is None
    finally:
        blocker.close()
        stop_event.set()
        await asyncio.wait_for(run_task, timeout=2)
