"""
Read and update the local film library.

Every function serialises to FilmSummary while the session is open, so callers
never receive a detached ORM instance.
"""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..database.models import Film, StreamingOffer
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
from .models import FilmDetail, FilmSummary

logger = get_logger(__name__)


def offer_counts(session: Session, film_ids: list[int]) -> dict[int, int]:
    """
    Count offers for many films in one query.

    Reading film.streaming_offers per row costs one query each - 182 queries
    for a 181-film library - and loads every offer row just to length them.
    """
    if not film_ids:
        return {}

    rows = (
        session.query(StreamingOffer.film_id, func.count(StreamingOffer.id))
        .filter(StreamingOffer.film_id.in_(film_ids))
        .group_by(StreamingOffer.film_id)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def _summarise(session: Session, films, limit: Optional[int] = None) -> list[FilmSummary]:
    if limit is not None:
        films = films[:limit]

    counts = offer_counts(session, [f.id for f in films])
    return [FilmSummary.from_film(f, offer_count=counts.get(f.id, 0)) for f in films]


# Sort keys the grid may ask for, mapped to SQL. This dict is the whitelist -
# a key that is not here falls back to the default rather than reaching the
# query builder. Both title and year prefer the Letterboxd value, matching
# Film.display_title / Film.display_year.
_SORT_TITLE = func.coalesce(Film.letterboxd_title, Film.tmdb_title)
_SORT_YEAR = func.coalesce(Film.letterboxd_year, Film.tmdb_year)

# `col.is_(None)` sorts False before True, which puts unknown values last
# instead of at the top of a descending sort.
SORTS: dict[str, tuple] = {
    "added": (Film.date_added.desc(),),
    "title": (_SORT_TITLE.asc(),),
    "year": (_SORT_YEAR.is_(None), _SORT_YEAR.desc()),
    "rating": (Film.vote_average.is_(None), Film.vote_average.desc()),
}
DEFAULT_SORT = "added"


def list_page(
    session: Session,
    *,
    sort: str = DEFAULT_SORT,
    page: int = 1,
    per_page: int = 48,
) -> tuple[list[FilmSummary], int]:
    """
    One page of the library, ordered and sliced in SQL.

    Returns (page, total_films). Unlike list_by_provider, LIMIT and OFFSET are
    pushed into the query rather than applied to a fully loaded list. Filtering
    is deliberately absent - it arrives in Step 6 with the query builder that
    replaces the single-axis helpers below.
    """
    order = SORTS.get(sort, SORTS[DEFAULT_SORT])

    total = session.query(func.count(Film.id)).scalar() or 0

    films = (
        session.query(Film)
        # Films sharing a sort value would otherwise be free to swap places
        # between pages, so a row can appear twice or not at all.
        .order_by(*order, Film.id.asc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )

    return _summarise(session, films), total


def search(session: Session, query: str, limit: int = 10) -> list[FilmSummary]:
    """Partial, case-insensitive match on either the Letterboxd or TMDB title."""
    films = search_films_by_title(session, query, limit=limit)
    return _summarise(session, films)


def list_unwatched(session: Session, limit: Optional[int] = None) -> list[FilmSummary]:
    """Films not yet marked as watched."""
    return _summarise(session, get_unwatched_films(session), limit=limit)


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
    return _summarise(session, films, limit=limit), len(films)


def list_by_country(
    session: Session,
    country: str,
    offer_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> tuple[list[FilmSummary], int]:
    """Films with at least one offer in a country. Returns (selection, total)."""
    films = get_films_by_country(session, country, monetization_type=offer_type)
    return _summarise(session, films, limit=limit), len(films)


def list_stale(session: Session, days: int = 7, limit: Optional[int] = None) -> list[FilmSummary]:
    """Films whose streaming data is older than `days`."""
    return _summarise(session, get_stale_films(session, days=days), limit=limit)


def get_by_id(session: Session, film_id: int) -> Optional[FilmSummary]:
    """Single film by primary key. Counts offers without loading them."""
    film = session.query(Film).filter(Film.id == film_id).first()
    if not film:
        return None

    counts = offer_counts(session, [film.id])
    return FilmSummary.from_film(film, offer_count=counts.get(film.id, 0))


def get_detail(session: Session, film_id: int) -> Optional[FilmDetail]:
    """
    Single film with every offer, for the detail page.

    Offers are eager-loaded here because the page renders them all; the grid
    only needs a count and must not use this.
    """
    film = (
        session.query(Film)
        .options(selectinload(Film.streaming_offers))
        .filter(Film.id == film_id)
        .first()
    )
    return FilmDetail.from_film(film) if film else None


def _summarise_one(session: Session, film: Optional[Film]) -> Optional[FilmSummary]:
    if not film:
        return None
    counts = offer_counts(session, [film.id])
    return FilmSummary.from_film(film, offer_count=counts.get(film.id, 0))


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

    return _summarise_one(session, mark_film_watched(session, film.id, watched=watched))


def set_watched_by_id(
    session: Session, film_id: int, watched: bool = True
) -> Optional[FilmSummary]:
    """Mark a film watched or unwatched by primary key."""
    return _summarise_one(session, mark_film_watched(session, film_id, watched=watched))


def stats(session: Session) -> dict:
    """Aggregate counts for the stats view."""
    return get_database_stats(session)
