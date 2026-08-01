"""
The Jinja environment, and the helpers templates are allowed to call.

Templates and static files are located relative to this module rather than
through `settings`. They are package data shipped inside the distribution, not
runtime state, so they do not vary between a laptop and a server - the rule
about `__file__` is about the database, the config and the output directory.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from . import auth

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


def _ago(value: Optional[datetime]) -> str:
    """A past datetime as a coarse relative phrase, e.g. a member's last sync."""
    if value is None:
        return ""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - aware).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    # Past a month the exact day matters less than the date itself.
    return f"on {aware.date().isoformat()}"


def _runtime(value: Optional[int]) -> str:
    """Runtime in minutes as a compact 2h 5m, or an em dash when unknown."""
    if not value or value <= 0:
        return "—"
    hours, minutes = divmod(value, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


templates.env.filters["rating"] = _rating
templates.env.filters["days"] = _days
templates.env.filters["ago"] = _ago
templates.env.filters["runtime"] = _runtime

# Read at render time, not import: tests toggle the password via monkeypatch.
# The template uses it only to decide whether to show a Sign out control.
templates.env.globals["auth_enabled"] = auth.is_enabled


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
