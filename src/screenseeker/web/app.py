"""
The FastAPI application factory.

`serve` runs this through uvicorn with `factory=True`; tests build their own
instance and override `get_db`.
"""

from typing import cast

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from .. import settings
from ..logger import get_logger
from .rendering import STATIC_DIR, render
from .routes import router

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


def create_app() -> FastAPI:
    """
    Build the app.

    The OpenAPI schema and its UIs are gated on SCREENSEEKER_DEBUG: they are a
    map of every route, and there is no authentication in front of them yet.
    """
    docs = "/docs" if settings.DEBUG else None

    app = FastAPI(
        title="ScreenSeeker",
        description="What can I watch tonight, on what I already pay for.",
        version="0.1.0",
        docs_url=docs,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)

    logger.info(f"Web app created (debug={settings.DEBUG}, docs={'on' if docs else 'off'})")
    return app
