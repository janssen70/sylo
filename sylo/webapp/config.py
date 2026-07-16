from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WebConfig:
    # Localhost-only in v1 (plan line 41); LAN bind is a future flag, not a
    # behavior change to anything else in this config.
    bind_host: str = "127.0.0.1"
    # 8514 (not any registered/well-known IANA port, and distinct from the
    # very commonly-already-bound 8080/8000/3000/etc. dev-tool ports) --
    # loosely themed on syslog's own port 514, chosen after a real deployment
    # hit 8080 already in use by other software on the target machine.
    # Configurable via SYLO_WEB_PORT; this is only the applied default.
    port: int = 8514

    # Separate from the monthly message-index DBs: users/sessions/settings
    # have a different lifecycle (never rotated/dropped), so they don't
    # belong in a per-month file.
    app_db_path: Path = Path("./data/app.sqlite3")
    index_dir: Path = Path("./data/index")

    session_cookie_name: str = "sylo_session"
    session_ttl_seconds: int = 12 * 3600
    sse_poll_interval_seconds: float = 1.5

    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900
    login_rate_limit_lockout_seconds: int = 900

    default_page_size: int = 50
    max_page_size: int = 500

    # Fixed mount point for reverse-proxy deployment (e.g. nginx forwarding
    # a location block's full, untouched request line to this backend --
    # not stripped/rewritten, so the app must own routes/links at this same
    # path itself). Deliberately not env-configurable: one fixed deployment,
    # one fixed prefix. Change this default if a different mount point is
    # ever needed.
    url_prefix: str = "/sylo"

    # How many of the most recent monthly index DBs the devices list and
    # default (no time range given) message search scan -- bounds a single
    # request to a small, predictable number of SQLite files to open.
    recent_months_scanned: int = 3

    @classmethod
    def from_env(cls) -> "WebConfig":
        d = cls()  # slots=True: cls.field is a slot descriptor, not the default
        return cls(
            bind_host=os.environ.get("SYLO_WEB_BIND_HOST", d.bind_host),
            port=int(os.environ.get("SYLO_WEB_PORT", d.port)),
            app_db_path=Path(os.environ.get("SYLO_APP_DB", str(d.app_db_path))),
            index_dir=Path(os.environ.get("SYLO_INDEX_DIR", str(d.index_dir))),
            session_cookie_name=os.environ.get("SYLO_SESSION_COOKIE_NAME", d.session_cookie_name),
            session_ttl_seconds=int(os.environ.get("SYLO_SESSION_TTL_SECONDS", d.session_ttl_seconds)),
            sse_poll_interval_seconds=float(
                os.environ.get("SYLO_SSE_POLL_INTERVAL_SECONDS", d.sse_poll_interval_seconds)
            ),
            login_rate_limit_attempts=int(
                os.environ.get("SYLO_LOGIN_RATE_LIMIT_ATTEMPTS", d.login_rate_limit_attempts)
            ),
            login_rate_limit_window_seconds=int(
                os.environ.get("SYLO_LOGIN_RATE_LIMIT_WINDOW_SECONDS", d.login_rate_limit_window_seconds)
            ),
            login_rate_limit_lockout_seconds=int(
                os.environ.get("SYLO_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", d.login_rate_limit_lockout_seconds)
            ),
            default_page_size=int(os.environ.get("SYLO_DEFAULT_PAGE_SIZE", d.default_page_size)),
            max_page_size=int(os.environ.get("SYLO_MAX_PAGE_SIZE", d.max_page_size)),
            recent_months_scanned=int(os.environ.get("SYLO_RECENT_MONTHS_SCANNED", d.recent_months_scanned)),
        )
