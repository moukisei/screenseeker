"""
Use-case layer.

Everything in here takes a Session as its first argument, returns Pydantic
models rather than ORM instances, and never writes to a terminal. Both the CLI
and the web layer are thin callers of these functions.

This is the only service layer. database/ holds the models, the engine and the
session factory, and nothing else.
"""

from . import enrichment, jobs, library, sync, watch
from .enrichment import EnrichmentReport, FilmError, enrich_films
from .jobs import JobOut
from .library import Facets, LibraryFilter, list_films
from .models import FilmDetail, FilmSummary, OfferOut, logo_url, poster_url
from .sync import SyncReport, ingest_watchlist
from .watch import find_watch_options, reachable_countries, watch_strategy_for

__all__ = [
    "EnrichmentReport",
    "Facets",
    "FilmDetail",
    "FilmError",
    "FilmSummary",
    "JobOut",
    "LibraryFilter",
    "OfferOut",
    "SyncReport",
    "enrich_films",
    "enrichment",
    "find_watch_options",
    "ingest_watchlist",
    "jobs",
    "library",
    "list_films",
    "logo_url",
    "poster_url",
    "reachable_countries",
    "sync",
    "watch",
    "watch_strategy_for",
]
