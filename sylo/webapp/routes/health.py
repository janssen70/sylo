"""No auth required (plan line 46): a supervisor must be able to poll this
without first logging in, and it must stay cheap -- no DB/receiver checks.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
