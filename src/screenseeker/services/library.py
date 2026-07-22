"""
Read and update the local film library.

Every function serialises to FilmSummary while the session is open, so callers
never receive a detached ORM instance.
"""

from typing import Optional

from sqlalchemy.orm import Session, selectinload

from ..database.models import Film
from ..database.queries import (
    get_database_stats,
    get_film_by_title_year,
    get_films_by_country,
    get_films_by_provider,
    get_stale_films,
    get_unwatched_films,
    mark_film_watched,
    search_films_by_title,
)
from ..logger import get_logger
from .models import FilmSummary

logger = get_logger(__name__)


def _summarise(films, limit: Optional[int] = None) -> list[FilmSummary]:
    if limit is not None:
        films = films[:limit]
    return [FilmSummary.from_film(f) for f in films]


def search(session: Session, query: str, limit: int = 10) -> list[FilmSummary]:
    """Partial, case-insensitive match on either the Letterboxd or TMDB title."""
    films = search_films_by_title(session, query, limit=limit)
    return _summarise(films)


def list_unwatched(session: Session, limit: Optional[int] = None) -> list[FilmSummary]:
    """Films not yet marked as watched."""
    return _summarise(get_unwatched_films(session), limit=limit)


def count_unwatched(session: Session) -> int:
    """Cheaper than len(list_unwatched) - counts in SQL."""
    return session.query(Film).filter(~Film.watched).count()


def list_by_provider(
    session: Session,
    provider: str,
    country: Optional[str] = None,
    offer_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> tuple[list[FilmSummary], int]:
    """
    Films with at least one offer from a provider, optionally narrowed.

    Returns (selection, total_matched). The limit is applied in Python, not
    SQL - the underlying query has no LIMIT. Step 6 replaces this with a
    composable builder that pushes both down to the database.
    """
    films = get_films_by_provider(
        session, provider, country_code=country, monetization_type=offer_type
    )
    return _summarise(films, limit=limit), len(films)


def list_by_country(
    session: Session,
    country: str,
    offer_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> tuple[list[FilmSummary], int]:
    """Films with at least one offer in a country. Returns (selection, total)."""
    films = get_films_by_country(session, country, monetization_type=offer_type)
    return _summarise(films, limit=limit), len(films)


def list_stale(session: Session, days: int = 7, limit: Optional[int] = None) -> list[FilmSummary]:
    """Films whose streaming data is older than `days`."""
    return _summarise(get_stale_films(session, days=days), limit=limit)


def get_by_id(session: Session, film_id: int) -> Optional[FilmSummary]:
    """Single film by primary key, with offers eager-loaded for the count."""
    film = (
        session.query(Film)
        .options(selectinload(Film.streaming_offers))
        .filter(Film.id == film_id)
        .first()
    )
    return FilmSummary.from_film(film) if film else None


def set_watched(
    session: Session, title: str, year: Optional[int] = None, watched: bool = True
) -> Optional[FilmSummary]:
    """
    Mark a film watched or unwatched by title.

    Returns None when no film matches. The web layer should prefer
    set_watched_by_id - a title is not a stable identifier.
    """
    film = get_film_by_title_year(session, title, year)
    if not film:
        return None

    updated = mark_film_watched(session, film.id, watched=watched)
    return FilmSummary.from_film(updated) if updated else None


def set_watched_by_id(
    session: Session, film_id: int, watched: bool = True
) -> Optional[FilmSummary]:
    """Mark a film watched or unwatched by primary key."""
    film = mark_film_watched(session, film_id, watched=watched)
    return FilmSummary.from_film(film) if film else None


def stats(session: Session) -> dict:
    """Aggregate counts for the stats view."""
    return get_database_stats(session)
