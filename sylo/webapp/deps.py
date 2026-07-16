from __future__ import annotations

from fastapi import HTTPException, Request

from . import auth
from .config import WebConfig


class NotAuthenticated(Exception):
    pass


def get_config(request: Request) -> WebConfig:
    return request.app.state.config


def get_optional_session(request: Request) -> auth.Session | None:
    config = get_config(request)
    token = request.cookies.get(config.session_cookie_name)
    return auth.get_session(config, token)


def get_session(request: Request) -> auth.Session:
    session = get_optional_session(request)
    if session is None:
        raise NotAuthenticated()
    return session


def require_admin(request: Request) -> auth.Session:
    session = get_session(request)
    if not session.is_admin:
        raise HTTPException(status_code=403, detail="admin access required")
    return session


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
