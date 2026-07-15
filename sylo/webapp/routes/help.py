from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import auth
from ..deps import get_session

router = APIRouter()


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request, session: auth.Session = Depends(get_session)):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "help.html", {"session": session})
