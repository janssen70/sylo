from sylo.webapp import appdb


def test_init_db_seeds_default_settings(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    assert appdb.get_setting(db_path, "retention_days") == "365"
    assert appdb.count_users(db_path) == 0


def test_create_and_fetch_user(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "admin", "hashed")
    assert appdb.count_users(db_path) == 1
    user = appdb.get_user_by_username(db_path, "admin")
    assert user["id"] == uid
    assert user["password_hash"] == "hashed"
    assert appdb.get_user_by_id(db_path, uid)["username"] == "admin"
    assert appdb.get_user_by_username(db_path, "nobody") is None


def test_session_lifecycle(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "admin", "hashed")
    appdb.create_session(db_path, "tok", uid, "csrf", "2099-01-01T00:00:00+00:00")
    session = appdb.get_session(db_path, "tok")
    assert session["user_id"] == uid
    assert session["csrf_token"] == "csrf"
    appdb.delete_session(db_path, "tok")
    assert appdb.get_session(db_path, "tok") is None


def test_purge_expired_sessions(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "admin", "hashed")
    appdb.create_session(db_path, "expired", uid, "csrf", "2000-01-01T00:00:00+00:00")
    appdb.create_session(db_path, "fresh", uid, "csrf", "2099-01-01T00:00:00+00:00")
    appdb.purge_expired_sessions(db_path, "2026-01-01T00:00:00+00:00")
    assert appdb.get_session(db_path, "expired") is None
    assert appdb.get_session(db_path, "fresh") is not None


def test_settings_roundtrip(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    appdb.set_setting(db_path, "retention_days", "30")
    assert appdb.get_setting(db_path, "retention_days") == "30"
    assert appdb.get_setting(db_path, "nonexistent", "fallback") == "fallback"


def test_create_user_defaults_to_viewer_role_and_active(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "alice", "hashed")
    user = appdb.get_user_by_id(db_path, uid)
    assert user["role"] == "viewer"
    assert user["is_active"] == 1


def test_create_user_explicit_role(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "admin", "hashed", role="admin")
    assert appdb.get_user_by_id(db_path, uid)["role"] == "admin"


def test_list_users_ordered_by_username(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    appdb.create_user(db_path, "bob", "hashed")
    appdb.create_user(db_path, "alice", "hashed")
    usernames = [u["username"] for u in appdb.list_users(db_path)]
    assert usernames == ["alice", "bob"]


def test_set_user_password(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "alice", "old-hash")
    appdb.set_user_password(db_path, uid, "new-hash")
    assert appdb.get_user_by_id(db_path, uid)["password_hash"] == "new-hash"


def test_set_user_active(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "alice", "hashed")
    appdb.set_user_active(db_path, uid, False)
    assert appdb.get_user_by_id(db_path, uid)["is_active"] == 0
    appdb.set_user_active(db_path, uid, True)
    assert appdb.get_user_by_id(db_path, uid)["is_active"] == 1


def test_delete_sessions_for_user(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "alice", "hashed")
    appdb.create_session(db_path, "tok1", uid, "csrf", "2099-01-01T00:00:00+00:00")
    appdb.create_session(db_path, "tok2", uid, "csrf", "2099-01-01T00:00:00+00:00")
    appdb.delete_sessions_for_user(db_path, uid)
    assert appdb.get_session(db_path, "tok1") is None
    assert appdb.get_session(db_path, "tok2") is None


def test_delete_user_removes_user_and_sessions(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    uid = appdb.create_user(db_path, "alice", "hashed")
    appdb.create_session(db_path, "tok", uid, "csrf", "2099-01-01T00:00:00+00:00")
    appdb.delete_user(db_path, uid)
    assert appdb.get_user_by_id(db_path, uid) is None
    assert appdb.get_session(db_path, "tok") is None


def test_count_active_admins(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    appdb.init_db(db_path)
    admin1 = appdb.create_user(db_path, "admin1", "hashed", role="admin")
    appdb.create_user(db_path, "admin2", "hashed", role="admin")
    appdb.create_user(db_path, "viewer1", "hashed", role="viewer")
    assert appdb.count_active_admins(db_path) == 2
    appdb.set_user_active(db_path, admin1, False)
    assert appdb.count_active_admins(db_path) == 1
