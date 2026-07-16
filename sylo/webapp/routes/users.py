from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import appdb, auth
from ..deps import get_config, require_admin

router = APIRouter()

_VALID_ROLES = {"admin", "viewer"}


def _render_users_page(
    request: Request,
    session: auth.Session,
    *,
    error: str | None = None,
    revealed: dict | None = None,
    status_code: int = 200,
):
    config = get_config(request)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "session": session,
            "users": appdb.list_users(config.app_db_path),
            "error": error,
            "revealed": revealed,
        },
        status_code=status_code,
    )


@router.get("/settings/users", response_class=HTMLResponse)
def users_page(request: Request, session: auth.Session = Depends(require_admin)):
    return _render_users_page(request, session)


@router.post("/settings/users", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    session: auth.Session = Depends(require_admin),
):
    config = get_config(request)

    if not auth.verify_csrf(session, csrf_token):
        return _render_users_page(request, session, error="Invalid or expired form, please retry.", status_code=403)

    username = username.strip()
    if role not in _VALID_ROLES:
        return _render_users_page(request, session, error="Role must be admin or viewer.", status_code=400)
    if not username or not password:
        return _render_users_page(request, session, error="Username and password are required.", status_code=400)

    try:
        appdb.create_user(config.app_db_path, username, auth.hash_password(password), role=role)
    except sqlite3.IntegrityError:
        return _render_users_page(request, session, error=f"Username '{username}' is already taken.", status_code=400)

    return _render_users_page(request, session, revealed={"username": username, "password": password})


@router.post("/settings/users/{user_id}/reset-password", response_class=HTMLResponse)
def reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    csrf_token: str = Form(...),
    session: auth.Session = Depends(require_admin),
):
    config = get_config(request)

    if not auth.verify_csrf(session, csrf_token):
        return _render_users_page(request, session, error="Invalid or expired form, please retry.", status_code=403)

    user = appdb.get_user_by_id(config.app_db_path, user_id)
    if user is None:
        return _render_users_page(request, session, error="User not found.", status_code=404)
    if not new_password:
        return _render_users_page(request, session, error="New password is required.", status_code=400)

    appdb.set_user_password(config.app_db_path, user_id, auth.hash_password(new_password))
    return _render_users_page(request, session, revealed={"username": user["username"], "password": new_password})


@router.post("/settings/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: int,
    csrf_token: str = Form(...),
    session: auth.Session = Depends(require_admin),
):
    config = get_config(request)

    if not auth.verify_csrf(session, csrf_token):
        return _render_users_page(request, session, error="Invalid or expired form, please retry.", status_code=403)

    user = appdb.get_user_by_id(config.app_db_path, user_id)
    if user is None:
        return _render_users_page(request, session, error="User not found.", status_code=404)

    if user["role"] == "admin" and user["is_active"] and appdb.count_active_admins(config.app_db_path) <= 1:
        return _render_users_page(
            request, session, error="Cannot deactivate the last remaining admin.", status_code=400
        )

    appdb.set_user_active(config.app_db_path, user_id, False)
    appdb.delete_sessions_for_user(config.app_db_path, user_id)

    if user_id == session.user_id:
        # The acting admin just deactivated themselves -- their own session
        # was just deleted above, so there's nothing left to redirect back to.
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(config.session_cookie_name)
        return response
    return RedirectResponse(url="/settings/users", status_code=303)


@router.post("/settings/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    csrf_token: str = Form(...),
    session: auth.Session = Depends(require_admin),
):
    config = get_config(request)

    if not auth.verify_csrf(session, csrf_token):
        return _render_users_page(request, session, error="Invalid or expired form, please retry.", status_code=403)

    user = appdb.get_user_by_id(config.app_db_path, user_id)
    if user is None:
        return _render_users_page(request, session, error="User not found.", status_code=404)
    if user["is_active"]:
        return _render_users_page(
            request, session, error="Deactivate a user before deleting it.", status_code=400
        )

    appdb.delete_user(config.app_db_path, user_id)
    return RedirectResponse(url="/settings/users", status_code=303)
