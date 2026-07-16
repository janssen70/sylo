import re

from fastapi.testclient import TestClient

from sylo.webapp import appdb
from sylo.webapp.app import create_app
from sylo.webapp.config import WebConfig

# WebConfig.url_prefix's fixed default -- see sylo/webapp/config.py.
PREFIX = "/sylo"


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


def login(client: TestClient, username: str = "admin", password: str = "testpass123") -> None:
    r = client.post(f"{PREFIX}/login", data={"username": username, "password": password})
    assert r.status_code == 200


def logout(client: TestClient) -> None:
    csrf = csrf_token(client, f"{PREFIX}/messages")
    r = client.post(f"{PREFIX}/logout", data={"csrf_token": csrf})
    assert r.status_code == 200


def csrf_token(client: TestClient, page_url: str) -> str:
    r = client.get(page_url)
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m, f"no csrf token found on {page_url}"
    return m.group(1)


def create_viewer(client: TestClient, username="viewer1", password="viewerpass123", role="viewer"):
    csrf = csrf_token(client, f"{PREFIX}/settings/users")
    r = client.post(
        f"{PREFIX}/settings/users",
        data={"username": username, "role": role, "password": password, "csrf_token": csrf},
    )
    assert r.status_code == 200, r.text
    assert password in r.text
    return username, password


def test_admin_can_create_viewer_with_reveal_panel(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        username, _ = create_viewer(client)
        user = appdb.get_user_by_username(tmp_path / "app.sqlite3", username)
        assert user["role"] == "viewer"
        assert user["is_active"] == 1


def test_viewer_cannot_access_admin_routes(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        username, password = create_viewer(client)
        logout(client)
        login(client, username, password)

        assert client.get(f"{PREFIX}/messages").status_code == 200
        assert client.get(f"{PREFIX}/settings/users").status_code == 403
        assert client.get(f"{PREFIX}/settings/retention").status_code == 403


def test_duplicate_username_rejected(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        csrf = csrf_token(client, f"{PREFIX}/settings/users")
        r = client.post(
            f"{PREFIX}/settings/users",
            data={"username": "admin", "role": "viewer", "password": "x", "csrf_token": csrf},
        )
        assert r.status_code == 400
        assert "already taken" in r.text


def test_deactivate_kills_existing_session(tmp_path):
    with make_client(tmp_path) as admin_client, make_client(tmp_path) as viewer_client:
        login(admin_client)
        username, password = create_viewer(admin_client)
        login(viewer_client, username, password)
        assert viewer_client.get(f"{PREFIX}/messages").status_code == 200

        user_id = appdb.get_user_by_username(tmp_path / "app.sqlite3", username)["id"]
        csrf = csrf_token(admin_client, f"{PREFIX}/settings/users")
        r = admin_client.post(f"{PREFIX}/settings/users/{user_id}/deactivate", data={"csrf_token": csrf})
        assert r.status_code == 200

        r = viewer_client.get(f"{PREFIX}/messages", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith(f"{PREFIX}/login")


def test_cannot_deactivate_last_admin(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        user_id = appdb.get_user_by_username(tmp_path / "app.sqlite3", "admin")["id"]
        csrf = csrf_token(client, f"{PREFIX}/settings/users")
        r = client.post(f"{PREFIX}/settings/users/{user_id}/deactivate", data={"csrf_token": csrf})
        assert r.status_code == 400
        assert "last remaining admin" in r.text


def test_delete_requires_deactivation_first(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        username, _ = create_viewer(client)
        user_id = appdb.get_user_by_username(tmp_path / "app.sqlite3", username)["id"]
        csrf = csrf_token(client, f"{PREFIX}/settings/users")

        r = client.post(f"{PREFIX}/settings/users/{user_id}/delete", data={"csrf_token": csrf})
        assert r.status_code == 400
        assert "Deactivate a user" in r.text

        client.post(f"{PREFIX}/settings/users/{user_id}/deactivate", data={"csrf_token": csrf})
        r = client.post(f"{PREFIX}/settings/users/{user_id}/delete", data={"csrf_token": csrf}, follow_redirects=False)
        assert r.status_code == 303
        assert appdb.get_user_by_id(tmp_path / "app.sqlite3", user_id) is None


def test_reset_password_reveals_new_password_once(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        username, _ = create_viewer(client)
        user_id = appdb.get_user_by_username(tmp_path / "app.sqlite3", username)["id"]
        csrf = csrf_token(client, f"{PREFIX}/settings/users")
        r = client.post(
            f"{PREFIX}/settings/users/{user_id}/reset-password",
            data={"new_password": "newpassword456", "csrf_token": csrf},
        )
        assert r.status_code == 200
        assert "newpassword456" in r.text

        logout(client)
        login(client, username, "newpassword456")


def test_self_service_password_change(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        csrf = csrf_token(client, f"{PREFIX}/account/password")
        r = client.post(
            f"{PREFIX}/account/password",
            data={"current_password": "testpass123", "new_password": "newadminpw789", "csrf_token": csrf},
        )
        assert r.status_code == 200
        assert "Password changed" in r.text

        logout(client)
        login(client, "admin", "newadminpw789")


def test_self_service_password_change_rejects_wrong_current_password(tmp_path):
    with make_client(tmp_path) as client:
        login(client)
        csrf = csrf_token(client, f"{PREFIX}/account/password")
        r = client.post(
            f"{PREFIX}/account/password",
            data={"current_password": "wrongpw", "new_password": "newadminpw789", "csrf_token": csrf},
        )
        assert r.status_code == 401
        assert "Current password is incorrect" in r.text
