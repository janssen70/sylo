"""Live-tail SSE tests.

The unit test below pins the last_id sentinel bug found during manual
smoke testing: the very first poll for a month must be distinguishable
from "seeded with 0 rows so far," otherwise the second poll re-seeds and
silently skips whatever landed in between (see routes/messages.py).

The end-to-end test spawns a real uvicorn process rather than using
FastAPI's TestClient: TestClient's sync-over-async bridge fully drains a
streaming response before handing back control, which deadlocks against
this endpoint's intentionally-infinite generator. A real socket doesn't
have that problem, and it's what production actually looks like.
"""
from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx

from sylo.indexer.schema import apply_schema, insert_message
from sylo.webapp.routes.messages import _poll_new_rows


def test_poll_new_rows_first_call_seeds_without_reporting(tmp_path):
    db_path = tmp_path / "2026-07.sqlite3"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    conn.commit()

    rows, last_id = _poll_new_rows(db_path, None)
    assert rows == []
    assert last_id == 0


def test_poll_new_rows_reports_rows_inserted_between_polls(tmp_path):
    db_path = tmp_path / "2026-07.sqlite3"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    conn.commit()

    _, seeded_id = _poll_new_rows(db_path, None)
    assert seeded_id == 0

    insert_message(
        conn,
        receipt_time="2026-07-13T00:00:00.000000+00:00",
        source_ip="10.0.0.1",
        facility=4,
        severity=2,
        host="host",
        tag="su",
        message="new row",
        malformed=False,
    )
    conn.commit()

    # This is the regression case: a second poll using the seeded value (0)
    # must NOT be treated as "still unseeded" and must return the new row.
    rows, new_last_id = _poll_new_rows(db_path, seeded_id)
    assert [r["message"] for r in rows] == ["new row"]
    assert new_last_id == 1


def test_poll_new_rows_only_returns_rows_after_last_id(tmp_path):
    db_path = tmp_path / "2026-07.sqlite3"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    for i in range(3):
        insert_message(
            conn,
            receipt_time=f"2026-07-13T00:00:0{i}.000000+00:00",
            source_ip="10.0.0.1",
            facility=4,
            severity=2,
            host="host",
            tag="su",
            message=f"row {i}",
            malformed=False,
        )
    conn.commit()

    rows, last_id = _poll_new_rows(db_path, 1)
    assert [r["message"] for r in rows] == ["row 1", "row 2"]
    assert last_id == 3


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_live_tail_end_to_end_over_real_socket(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    db_path = index_dir / f"{month_key}.sqlite3"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    conn.commit()

    port = _free_port()
    env = {
        "SYLO_WEB_BIND_HOST": "127.0.0.1",
        "SYLO_WEB_PORT": str(port),
        "SYLO_APP_DB": str(tmp_path / "app.sqlite3"),
        "SYLO_INDEX_DIR": str(index_dir),
        "SYLO_SSE_POLL_INTERVAL_SECONDS": "0.2",
        "SYLO_ADMIN_PASSWORD": "testpass123",
    }
    import os

    full_env = dict(os.environ)
    full_env.update(env)

    proc = subprocess.Popen(
        [sys.executable, "-m", "sylo.webapp.main"],
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                if httpx.get(f"{base}/healthz", timeout=0.5).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("server did not come up in time")

        client = httpx.Client(base_url=base)
        client.post("/login", data={"username": "admin", "password": "testpass123"})

        with client.stream("GET", "/messages/stream", timeout=10) as r:
            assert r.status_code == 200
            lines = r.iter_lines()
            next(lines)  # first keep-alive: confirms the seed poll ran

            insert_message(
                conn,
                receipt_time="2026-07-13T23:59:59.000000+00:00",
                source_ip="10.0.0.9",
                facility=4,
                severity=2,
                host="tailhost",
                tag="sshd",
                message="live tail e2e test",
                malformed=False,
            )
            conn.commit()

            found = False
            for _ in range(30):
                if "live tail e2e test" in next(lines):
                    found = True
                    break
            assert found, "new message never appeared on the live tail stream"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
