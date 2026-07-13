"""Auth model per plan section 6: single local admin, bcrypt-hashed password
in a real `users` table, server-side sessions (random token, HTTP-only
cookie), CSRF tokens bound to the session, and a login rate limiter.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

from . import appdb
from .config import WebConfig


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def ensure_default_admin(config: WebConfig, initial_password: Optional[str] = None) -> Optional[str]:
    """First-run bootstrap: create the 'admin' user if none exists.

    Returns the generated password if one was generated (caller should log
    it once so there's a way to log in), or None if a user already existed
    or an explicit initial_password was supplied.
    """
    if appdb.count_users(config.app_db_path) > 0:
        return None
    generated = None
    password = initial_password
    if not password:
        password = secrets.token_urlsafe(18)
        generated = password
    appdb.create_user(config.app_db_path, "admin", hash_password(password))
    return generated


def authenticate(config: WebConfig, username: str, password: str) -> Optional[int]:
    """Returns user_id on success, None on failure. Rate limiting is the
    caller's job (LoginRateLimiter below) -- kept separate since it's
    per-IP/process-lifetime state, not something that belongs in the DB
    layer."""
    user = appdb.get_user_by_username(config.app_db_path, username)
    if user is None:
        # Compare against a throwaway hash anyway so the unknown-username
        # and wrong-password paths take comparable time.
        bcrypt.checkpw(password.encode("utf-8"), bcrypt.gensalt())
        return None
    if verify_password(password, user["password_hash"]):
        return user["id"]
    return None


@dataclass(slots=True)
class Session:
    token: str
    user_id: int
    username: str
    csrf_token: str


def create_session(config: WebConfig, user_id: int) -> Session:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=config.session_ttl_seconds)).isoformat()
    appdb.create_session(config.app_db_path, token, user_id, csrf_token, expires_at)
    user = appdb.get_user_by_id(config.app_db_path, user_id)
    return Session(token, user_id, user["username"], csrf_token)


def get_session(config: WebConfig, token: Optional[str]) -> Optional[Session]:
    if not token:
        return None
    row = appdb.get_session(config.app_db_path, token)
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        appdb.delete_session(config.app_db_path, token)
        return None
    user = appdb.get_user_by_id(config.app_db_path, row["user_id"])
    if user is None:
        appdb.delete_session(config.app_db_path, token)
        return None
    return Session(token, row["user_id"], user["username"], row["csrf_token"])


def destroy_session(config: WebConfig, token: str) -> None:
    appdb.delete_session(config.app_db_path, token)


def verify_csrf(session: Session, submitted_token: Optional[str]) -> bool:
    return bool(submitted_token) and secrets.compare_digest(session.csrf_token, submitted_token)


class LoginRateLimiter:
    """In-memory sliding-window limiter keyed by client IP.

    Process-local state is intentional: this gates a single local-admin
    login form (plan line 63), not a distributed service, so a process
    restart clearing counters is an acceptable simplification. A
    threading.Lock (not asyncio.Lock) because sync route handlers run in
    Starlette's threadpool, potentially concurrently across threads.
    """

    def __init__(self, max_attempts: int, window_seconds: int, lockout_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> bool:
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return False
            if until <= time.monotonic():
                del self._locked_until[key]
                return False
            return True

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            attempts = [t for t in self._attempts.get(key, []) if now - t < self._window_seconds]
            attempts.append(now)
            if len(attempts) >= self._max_attempts:
                self._locked_until[key] = now + self._lockout_seconds
                attempts = []
            self._attempts[key] = attempts

    def record_success(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
            self._locked_until.pop(key, None)
