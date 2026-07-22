"""
The FastAPI application factory.

`serve` runs this through uvicorn with `factory=True`; tests build their own
instance, override `get_db` and pass their own session factory.
"""

from contextlib import asynccontextmanager
from typing import Optional, cast

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from .. import settings
from ..logger import get_logger
from .rendering import STATIC_DIR, render
from .routes import router
from .runner import JobRunner, SessionFactory

logger = get_logger(__name__)


async def _http_exception_handler(request: Request, exc: Exception) -> Response:
    """
    Render errors as pages. This is a browser app; a JSON body is noise.

    The detail string is written by this codebase, never by a client, so
    rendering it leaks nothing. Server errors are not handled here - those
    reach the default handler, which shows a traceback only when DEBUG is on.

    Starlette types every handler against bare Exception but only routes the
    class it was registered for, hence the cast.
    """
    http_exc = cast(StarletteHTTPException, exc)
    return render(
        request,
        "error.html",
        {"status_code": http_exc.status_code, "detail": http_exc.detail},
        status_code=http_exc.status_code,
    )


def create_app(session_factory: Optional[SessionFactory] = None) -> FastAPI:
    """
    Build the app.

    The OpenAPI schema and its UIs are gated on SCREENSEEKER_DEBUG: they are a
    map of every route, and there is no authentication in front of them yet.

    `session_factory` is for the background runner, which outlives any request
    and so cannot use the `get_db` dependency. Left unset it resolves to the
    application's own factory at call time.
    """
    runner = JobRunner(session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A job row still marked running belongs to a process that no longer
        # exists - the runner is in-process, so nothing survives a restart.
        # Left alone these rows hold the single-flight guard shut forever.
        # Startup is the one moment where nothing of ours is running.
        try:
            reaped = runner.reap_orphans()
            if reaped:
                logger.warning(f"Failed {reaped} job(s) orphaned by a restart")
        except Exception:  # noqa: BLE001 - a broken ledger must not block serving
            logger.exception("Could not reap orphaned jobs")

        yield

        # Nothing to cancel: the workers are blocking threads, not coroutines.
        # A job in flight dies with the process and is reaped on next startup.

    docs = "/docs" if settings.DEBUG else None

    app = FastAPI(
        title="ScreenSeeker",
        description="What can I watch tonight, on what I already pay for.",
        version="0.1.0",
        docs_url=docs,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    app.state.job_runner = runner

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)

    logger.info(f"Web app created (debug={settings.DEBUG}, docs={'on' if docs else 'off'})")
    return app
