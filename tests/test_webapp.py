import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from sylo.indexer.schema import apply_schema, insert_message
from sylo.webapp.app import create_app
from sylo.webapp.config import WebConfig


def make_client(tmp_path, **overrides) -> TestClient:
    defaults = dict(
        app_db_path=tmp_path / "app.sqlite3",
        index_dir=tmp_path / "index",
        login_rate_limit_attempts=3,
        login_rate_limit_window_seconds=60,
        login_rate_limit_lockout_seconds=60,
    )
    defaults.update(overrides)
    config = WebConfig(**defaults)
    app = create_app(config, initial_admin_password="testpass123")
    return TestClient(app)


def login(client: TestClient) -> None:
    # TestClient follows redirects by default, so a successful login lands
    # on the final page (200), not the intermediate 303.
    r = client.post("/login", data={"username": "admin", "password": "testpass123"})
    assert r.status_code == 200


def csrf_token(client: TestClient, page_url: str) -> str:
    r = client.get(page_url)
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m, f"no csrf token found on {page_url}"
    return m.group(1)


def test_healthz_no_auth_required(tmp_path):
    with make_client(tmp_path) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_unauthenticated_page_redirects_to_login(tmp_path):
    with make_client(tmp_path) as client:
        r = client.get("/messages", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login")


def test_unauthenticated_api_returns_401(tmp_path):
    with make_client(tmp_path) as client:
        r = client.get("/api/messages")
        assert r.status_code == 401


def test_root_redirects_to_messages(tmp_path):
    with make_client(tmp_path) as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/messages"


def test_login_wrong_password_rejected(tmp_path):
    with make_client(tmp_path) as client:
        r = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
        assert "Invalid username or password" in r.text


def test_login_success_sets_cookie_and_redirects(tmp_path):
    with make_client(tmp_path) as client:
        r = client.post(
            "/login", data={"username": "admin", "password": "testpass123", "next": "/devices"}, follow_redirects=False
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/devices"
        assert "sylo_session" in r.cookies


def test_login_rate_limiting_locks_out(tmp_path):
    with make_client(tmp_path) as client:
        for _ in range(3):
            client.post("/login", data={"username": "admin", "password": "wrong"})
        r = client.post("/login", data={"username": "admin", "password": "testpass123"})
        assert r.status_code == 429
        assert "Too many failed attempts" in r.text


def test_already_logged_in_login_page_redirects(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        r = client.get("/login", follow_redirects=False)
        assert r.status_code == 303


def test_logout_requires_valid_csrf(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        r = client.post("/logout", data={"csrf_token": "bogus"})
        assert r.status_code == 403

        token = csrf_token(client, "/settings/retention")
        r = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

        r = client.get("/messages", follow_redirects=False)
        assert r.status_code == 303


def test_retention_settings_csrf_and_update(tmp_path):
    with make_client(tmp_path) as client:
        login(client)

        r = client.post("/settings/retention", data={"retention_days": "30", "csrf_token": "bogus"})
        assert r.status_code == 403

        token = csrf_token(client, "/settings/retention")
        r = client.post("/settings/retention", data={"retention_days": "30", "csrf_token": token})
        assert r.status_code == 200
        assert "Saved." in r.text
        assert 'value="30"' in r.text

        r = client.post("/settings/retention", data={"retention_days": "not-a-number", "csrf_token": token})
        assert r.status_code == 400

        r = client.post("/settings/retention", data={"retention_days": "0", "csrf_token": token})
        assert r.status_code == 400


def test_devices_page_renders(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        r = client.get("/devices")
        assert r.status_code == 200
        assert "No devices seen yet." in r.text


def test_messages_page_and_api_reflect_seeded_data(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True)
    conn = sqlite3.connect(index_dir / "2026-07.sqlite3")
    apply_schema(conn)
    insert_message(
        conn,
        receipt_time="2026-07-13T00:00:00.000000+00:00",
        source_ip="10.0.0.1",
        facility=4,
        severity=2,
        host="myhost",
        tag="su",
        message="hello from seed",
        malformed=False,
    )
    conn.commit()
    conn.close()

    with make_client(tmp_path, index_dir=index_dir) as client:
        login(client)

        r = client.get("/messages")
        assert r.status_code == 200
        assert "hello from seed" in r.text

        r = client.get("/messages/results")
        assert r.status_code == 200
        assert "hello from seed" in r.text

        r = client.get("/api/messages")
        assert r.status_code == 200
        body = r.json()
        assert body["rows"][0]["message"] == "hello from seed"
        assert body["has_more"] is False

        r = client.get("/api/messages", params={"text": "seed"})
        assert r.json()["rows"][0]["message"] == "hello from seed"

        r = client.get("/api/messages", params={"host": "nonexistent-host"})
        assert r.json()["rows"] == []


def test_api_messages_limit_capped_at_max_page_size(tmp_path):
    with make_client(tmp_path, max_page_size=10) as client:
        login(client)
        r = client.get("/api/messages", params={"limit": 9999})
        assert r.status_code == 200
        assert r.json()["limit"] == 10


@pytest.mark.parametrize("path", ["/messages", "/devices", "/settings/retention", "/api/messages"])
def test_all_protected_routes_require_session(tmp_path, path):
    with make_client(tmp_path) as client:
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (303, 401)
