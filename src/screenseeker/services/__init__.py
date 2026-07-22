"""
Use-case layer.

Everything in here takes a Session as its first argument, returns Pydantic
models rather than ORM instances, and never writes to a terminal. Both the CLI
and the web layer are thin callers of these functions.
"""

from . import enrichment, library, sync
from .enrichment import EnrichmentReport, FilmError, enrich_films
from .models import FilmDetail, FilmSummary, OfferOut, logo_url, poster_url
from .sync import SyncReport, ingest_watchlist
from .watch import find_watch_options, watch_strategy_for

__all__ = [
    "EnrichmentReport",
    "FilmDetail",
    "FilmError",
    "FilmSummary",
    "OfferOut",
    "SyncReport",
    "enrich_films",
    "enrichment",
    "find_watch_options",
    "ingest_watchlist",
    "library",
    "logo_url",
    "poster_url",
    "sync",
    "watch_strategy_for",
]
