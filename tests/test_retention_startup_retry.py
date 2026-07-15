"""A real deployment hit the retention service crashing on its very first
start (seconds after install, before app.sqlite3 existed yet) and -- with no
service recovery action configured -- staying dead from then on. run() must
survive a failure anywhere in a pass, including config loading itself,
instead of letting it escape and take the whole service down (mirrors the
receiver's startup-retry behavior, plan section 11).
"""
import asyncio

import pytest

from sylo.retention import main as retention_main
from sylo.retention.config import RetentionConfig


@pytest.mark.asyncio
async def test_run_recovers_from_a_failing_config_load_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(retention_main, "_SETUP_FAILURE_RETRY_SECONDS", 0.05)

    real_config = RetentionConfig(
        data_dir=tmp_path / "raw",
        index_dir=tmp_path / "index",
        app_db_path=tmp_path / "app.sqlite3",
    )
    attempts = {"count": 0}

    def flaky_from_env():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("simulated startup race")
        return real_config

    monkeypatch.setattr(RetentionConfig, "from_env", flaky_from_env)

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(retention_main.run(stop_event=stop_event))
    try:
        for _ in range(200):
            await asyncio.sleep(0.02)
            if real_config.app_db_path.exists():
                break
        else:
            pytest.fail("retention loop never recovered from the failed config load")

        assert not run_task.done(), "a failing config load must not crash the loop"
        assert attempts["count"] >= 2, "should have retried after the first failure"
    finally:
        stop_event.set()
        await asyncio.wait_for(run_task, timeout=2)
