from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ... import timeutil
from .. import auth
from ..config import WebConfig
from ..deps import get_config, get_session
from ..queries import MessageFilter, list_devices, search_messages

router = APIRouter()


def _normalize_bound(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return timeutil.format_receipt_time(dt)


def _parse_filter(
    host: list[str] | None,
    severity: int | None,
    facility: int | None,
    start: str | None,
    end: str | None,
    text: str | None,
) -> MessageFilter:
    return MessageFilter(
        host=host or None,
        severity=severity,
        facility=facility,
        start=_normalize_bound(start),
        end=_normalize_bound(end),
        text=text or None,
    )


def _filters_context(host, severity, facility, start, end, text) -> dict:
    return {"host": host or [], "severity": severity, "facility": facility, "start": start, "end": end, "text": text}


@router.get("/api/messages")
def api_messages(
    request: Request,
    host: list[str] | None = Query(None),
    severity: int | None = None,
    facility: int | None = None,
    start: str | None = None,
    end: str | None = None,
    text: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1),
    session: auth.Session = Depends(get_session),
) -> JSONResponse:
    config = get_config(request)
    limit = min(limit, config.max_page_size)
    filt = _parse_filter(host, severity, facility, start, end, text)
    result = search_messages(config, filt, offset, limit)
    return JSONResponse({"rows": result.rows, "has_more": result.has_more, "offset": offset, "limit": limit})


@router.get("/messages", response_class=HTMLResponse)
def messages_page(
    request: Request,
    host: list[str] | None = Query(None),
    severity: int | None = None,
    facility: int | None = None,
    start: str | None = None,
    end: str | None = None,
    text: str | None = None,
    offset: int = Query(0, ge=0),
    session: auth.Session = Depends(get_session),
):
    config = get_config(request)
    filt = _parse_filter(host, severity, facility, start, end, text)
    result = search_messages(config, filt, offset, config.default_page_size)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "messages.html",
        {
            "session": session,
            "rows": result.rows,
            "has_more": result.has_more,
            "offset": offset,
            "limit": config.default_page_size,
            "filters": _filters_context(host, severity, facility, start, end, text),
            "devices": list_devices(config),
        },
    )


@router.get("/messages/results", response_class=HTMLResponse)
def messages_results(
    request: Request,
    host: list[str] | None = Query(None),
    severity: int | None = None,
    facility: int | None = None,
    start: str | None = None,
    end: str | None = None,
    text: str | None = None,
    offset: int = Query(0, ge=0),
    session: auth.Session = Depends(get_session),
):
    config = get_config(request)
    filt = _parse_filter(host, severity, facility, start, end, text)
    result = search_messages(config, filt, offset, config.default_page_size)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "_results.html",
        {
            "rows": result.rows,
            "has_more": result.has_more,
            "offset": offset,
            "limit": config.default_page_size,
            "filters": _filters_context(host, severity, facility, start, end, text),
        },
    )


def _sse_event(event: str, data: str) -> bytes:
    lines = data.splitlines() or [""]
    payload = "".join(f"data: {line}\n" for line in lines)
    return f"event: {event}\n{payload}\n".encode("utf-8")


def _poll_new_rows(db_path: Path, last_id: int | None) -> tuple[list[dict], int]:
    """last_id is None only for the very first poll of a given month --
    distinct from 0, which is a legitimate "seeded, table was empty at seed
    time" value. Conflating the two (e.g. both represented as 0) means the
    second poll can't tell "never seeded" from "seeded at zero," so it
    re-seeds and silently skips any row inserted in between the two polls.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if last_id is None:
            # First poll for this month: seed at the current max id so the
            # tail starts from "now", it doesn't replay history.
            row = conn.execute("SELECT MAX(id) AS max_id FROM messages").fetchone()
            return [], (row["max_id"] or 0)
        rows = conn.execute(
            "SELECT id, receipt_time, source_ip, facility, severity, host, tag, message, malformed "
            "FROM messages WHERE id > ? ORDER BY id ASC LIMIT 200",
            (last_id,),
        ).fetchall()
    finally:
        conn.close()
    new_last_id = rows[-1]["id"] if rows else last_id
    return [dict(r) for r in rows], new_last_id


async def _tail_generator(request: Request, config: WebConfig, templates):
    last_id_by_month: dict[str, int | None] = {}
    poll_interval = config.sse_poll_interval_seconds
    row_template = templates.get_template("_tail_row.html")
    try:
        while True:
            if await request.is_disconnected():
                break
            month_key = datetime.now(timezone.utc).strftime("%Y-%m")
            db_path = config.index_dir / f"{month_key}.sqlite3"
            if db_path.exists():
                last_id = last_id_by_month.get(month_key)
                rows, new_last_id = await run_in_threadpool(_poll_new_rows, db_path, last_id)
                last_id_by_month[month_key] = new_last_id
                for row in rows:
                    yield _sse_event("message", row_template.render(row=row))
            yield b": keep-alive\n\n"
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        return


@router.get("/messages/stream")
async def messages_stream(request: Request, session: auth.Session = Depends(get_session)):
    config = get_config(request)
    templates = request.app.state.templates
    return StreamingResponse(
        _tail_generator(request, config, templates),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
