from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from .. import appdb, auth
from ..deps import get_config, require_admin

router = APIRouter()


@router.get("/settings/retention", response_class=HTMLResponse)
def retention_form(request: Request, session: auth.Session = Depends(require_admin)):
    config = get_config(request)
    retention_days = appdb.get_setting(config.app_db_path, "retention_days", "365")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "retention.html",
        {"session": session, "retention_days": retention_days, "error": None, "saved": False},
    )


@router.post("/settings/retention", response_class=HTMLResponse)
def retention_submit(
    request: Request,
    retention_days: str = Form(...),
    csrf_token: str = Form(...),
    session: auth.Session = Depends(require_admin),
):
    config = get_config(request)
    templates = request.app.state.templates

    if not auth.verify_csrf(session, csrf_token):
        return templates.TemplateResponse(
            request,
            "retention.html",
            {
                "session": session,
                "retention_days": retention_days,
                "error": "Invalid or expired form, please retry.",
                "saved": False,
            },
            status_code=403,
        )

    try:
        days = int(retention_days)
        if days < 1:
            raise ValueError
    except ValueError:
        return templates.TemplateResponse(
            request,
            "retention.html",
            {
                "session": session,
                "retention_days": retention_days,
                "error": "Retention must be a positive whole number of days.",
                "saved": False,
            },
            status_code=400,
        )

    appdb.set_setting(config.app_db_path, "retention_days", str(days))
    return templates.TemplateResponse(
        request,
        "retention.html",
        {"session": session, "retention_days": str(days), "error": None, "saved": True},
    )
