"""
The web UI.

Server-rendered Jinja2 with HTMX for the two interactions that need it. Every
route is a thin caller of `services`; nothing here touches the ORM, TMDB or
Letterboxd directly.

Imports FastAPI, so it is only importable with the `web` extra installed.
"""

from .app import create_app

__all__ = ["create_app"]
