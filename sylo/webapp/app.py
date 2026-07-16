from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import appdb, auth
from .config import WebConfig
from .deps import NotAuthenticated
from .receiver_health import read_receiver_health
from .routes import auth as auth_routes
from .routes import devices as devices_routes
from .routes import health as health_routes
from .routes import help as help_routes
from .routes import messages as messages_routes
from .routes import settings as settings_routes
from .routes import users as users_routes

logger = logging.getLogger("sylo.webapp")

_HERE = Path(__file__).parent


def _wants_json(request: Request) -> bool:
    path = request.url.path
    return path.startswith("/api/") or path == "/messages/stream"


def create_app(config: WebConfig, initial_admin_password: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        appdb.init_db(config.app_db_path)
        generated = auth.ensure_default_admin(config, initial_admin_password)
        if generated:
            logger.warning(
                "created default admin user 'admin' with generated password: %s "
                "-- this is shown once, log in and note it down",
                generated,
            )
        yield

    app = FastAPI(title="sylo", lifespan=lifespan)
    app.state.config = config
    app.state.templates = Jinja2Templates(directory=str(_HERE / "templates"))
    # A plain Jinja global rather than per-route context (plan section 11) --
    # every route would otherwise need to remember to pass this, and the
    # banner in base.html applies uniformly across all of them. The read
    # itself is one small file stat+parse, cheap enough to redo per request.
    app.state.templates.env.globals["receiver_health"] = lambda: read_receiver_health(config.index_dir)
    app.state.rate_limiter = auth.LoginRateLimiter(
        config.login_rate_limit_attempts,
        config.login_rate_limit_window_seconds,
        config.login_rate_limit_lockout_seconds,
    )
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    @app.exception_handler(NotAuthenticated)
    def _handle_not_authenticated(request: Request, exc: NotAuthenticated):
        if _wants_json(request):
            return PlainTextResponse("not authenticated", status_code=401)
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)

    app.include_router(auth_routes.router)
    app.include_router(health_routes.router)
    app.include_router(messages_routes.router)
    app.include_router(devices_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(users_routes.router)
    app.include_router(help_routes.router)

    @app.get("/")
    def root():
        return RedirectResponse(url="/messages", status_code=303)

    return app
