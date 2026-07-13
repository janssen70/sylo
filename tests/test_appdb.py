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
