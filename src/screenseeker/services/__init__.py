"""
Use-case layer.

Everything in here takes a Session as its first argument, returns Pydantic
models rather than ORM instances, and never writes to a terminal. Both the CLI
and the web layer are thin callers of these functions.
"""

from . import enrichment, library, profile, sync
from .enrichment import EnrichmentReport, FilmError, enrich_films
from .models import FilmSummary, WatchResult
from .sync import SyncReport, ingest_watchlist
from .watch import find_watch_options, parse_query

__all__ = [
    "EnrichmentReport",
    "FilmError",
    "FilmSummary",
    "SyncReport",
    "WatchResult",
    "enrich_films",
    "enrichment",
    "find_watch_options",
    "ingest_watchlist",
    "library",
    "parse_query",
    "profile",
    "sync",
]
