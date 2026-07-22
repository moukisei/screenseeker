"""
The Jinja environment, and the helpers templates are allowed to call.

Templates and static files are located relative to this module rather than
through `settings`. They are package data shipped inside the distribution, not
runtime state, so they do not vary between a laptop and a server - the rule
about `__file__` is about the database, the config and the output directory.
"""

from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _rating(value: Optional[float]) -> str:
    """TMDB vote average to one decimal, or an em dash."""
    return f"{value:.1f}" if value else "—"


def _days(value: Optional[int]) -> str:
    """Cache age in days, phrased for a badge."""
    if value is None:
        return "never checked"
    if value == 0:
        return "checked today"
    if value == 1:
        return "checked yesterday"
    return f"checked {value} days ago"


templates.env.filters["rating"] = _rating
templates.env.filters["days"] = _days


def is_htmx(request: Request) -> bool:
    """True when HTMX made the request and expects a fragment, not a page."""
    return request.headers.get("HX-Request") == "true"


def render(
    request: Request,
    template: str,
    context: Optional[dict[str, Any]] = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a template. Starlette builds the body here, while the session is open."""
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=context or {},
        status_code=status_code,
    )
