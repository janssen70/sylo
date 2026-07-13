from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import auth
from ..deps import get_config, get_session
from ..queries import list_devices

router = APIRouter()


@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request, session: auth.Session = Depends(get_session)):
    config = get_config(request)
    devices = list_devices(config)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "devices.html", {"session": session, "devices": devices})
