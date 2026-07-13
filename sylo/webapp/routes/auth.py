from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import auth
from ..deps import client_ip, get_config, get_optional_session, get_session

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/messages"):
    if get_optional_session(request) is not None:
        return RedirectResponse(url=next, status_code=303)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/messages"),
):
    config = get_config(request)
    limiter = request.app.state.rate_limiter
    ip = client_ip(request)
    templates = request.app.state.templates

    if limiter.is_locked(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Too many failed attempts. Try again later."},
            status_code=429,
        )

    user_id = auth.authenticate(config, username, password)
    if user_id is None:
        limiter.record_failure(ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid username or password."},
            status_code=401,
        )

    limiter.record_success(ip)
    session = auth.create_session(config, user_id)
    response = RedirectResponse(url=next or "/messages", status_code=303)
    response.set_cookie(
        config.session_cookie_name,
        session.token,
        max_age=config.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
    session: auth.Session = Depends(get_session),
):
    config = get_config(request)
    if not auth.verify_csrf(session, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf token")
    auth.destroy_session(config, session.token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(config.session_cookie_name)
    return response
