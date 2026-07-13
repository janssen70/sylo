from sylo.webapp import appdb, auth
from sylo.webapp.config import WebConfig


def make_config(tmp_path, **overrides) -> WebConfig:
    defaults = dict(app_db_path=tmp_path / "app.sqlite3")
    defaults.update(overrides)
    return WebConfig(**defaults)


def test_hash_and_verify_password():
    hashed = auth.hash_password("hunter2")
    assert hashed != "hunter2"
    assert auth.verify_password("hunter2", hashed)
    assert not auth.verify_password("wrong", hashed)


def test_ensure_default_admin_creates_once(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    generated = auth.ensure_default_admin(config)
    assert generated is not None
    assert appdb.count_users(config.app_db_path) == 1
    assert auth.ensure_default_admin(config) is None
    assert appdb.count_users(config.app_db_path) == 1


def test_ensure_default_admin_uses_explicit_password(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    generated = auth.ensure_default_admin(config, initial_password="fixedpw123")
    assert generated is None
    assert auth.authenticate(config, "admin", "fixedpw123") is not None


def test_authenticate_success_and_failure(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    auth.ensure_default_admin(config, initial_password="correctpw")
    assert auth.authenticate(config, "admin", "correctpw") is not None
    assert auth.authenticate(config, "admin", "wrongpw") is None
    assert auth.authenticate(config, "ghost", "whatever") is None


def test_session_create_get_destroy(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    auth.ensure_default_admin(config, initial_password="correctpw")
    uid = auth.authenticate(config, "admin", "correctpw")

    session = auth.create_session(config, uid)
    fetched = auth.get_session(config, session.token)
    assert fetched is not None
    assert fetched.user_id == uid
    assert fetched.username == "admin"

    auth.destroy_session(config, session.token)
    assert auth.get_session(config, session.token) is None


def test_get_session_rejects_unknown_or_missing_token(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    assert auth.get_session(config, None) is None
    assert auth.get_session(config, "does-not-exist") is None


def test_get_session_rejects_expired(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    uid = appdb.create_user(config.app_db_path, "admin", auth.hash_password("pw"))
    appdb.create_session(config.app_db_path, "tok", uid, "csrf", "2000-01-01T00:00:00+00:00")
    assert auth.get_session(config, "tok") is None
    # expired session should also have been purged
    assert appdb.get_session(config.app_db_path, "tok") is None


def test_verify_csrf(tmp_path):
    config = make_config(tmp_path)
    appdb.init_db(config.app_db_path)
    auth.ensure_default_admin(config, initial_password="pw")
    uid = auth.authenticate(config, "admin", "pw")
    session = auth.create_session(config, uid)
    assert auth.verify_csrf(session, session.csrf_token)
    assert not auth.verify_csrf(session, "wrong-token")
    assert not auth.verify_csrf(session, None)
    assert not auth.verify_csrf(session, "")


def test_login_rate_limiter_locks_after_threshold():
    limiter = auth.LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
    key = "1.2.3.4"
    assert not limiter.is_locked(key)
    for _ in range(2):
        limiter.record_failure(key)
    assert not limiter.is_locked(key)
    limiter.record_failure(key)
    assert limiter.is_locked(key)


def test_login_rate_limiter_success_clears_state():
    limiter = auth.LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
    key = "1.2.3.4"
    limiter.record_failure(key)
    limiter.record_failure(key)
    limiter.record_success(key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert not limiter.is_locked(key)


def test_login_rate_limiter_keys_are_independent():
    limiter = auth.LoginRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=60)
    for _ in range(2):
        limiter.record_failure("1.1.1.1")
    assert limiter.is_locked("1.1.1.1")
    assert not limiter.is_locked("2.2.2.2")
