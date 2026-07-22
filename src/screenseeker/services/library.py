"""
Read and update the local film library.

This is the only module that queries films for display. The single-axis
helpers it replaced (`get_films_by_provider`, `get_films_by_country`) could not
be combined and applied their limit in Python; `list_films` pushes filtering,
sorting and slicing into one query.

Every function serialises to FilmSummary or FilmDetail while the session is
open, so callers never receive a detached ORM instance.
"""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import Session

from ..database.models import Film, StreamingOffer
from ..logger import get_logger
from .models import FilmDetail, FilmSummary

logger = get_logger(__name__)


# ==============================================================================
# Film row primitives
#
# These return ORM instances and exist for the write paths in sync.py and
# enrichment.py. Nothing above the service layer may call them.
# ==============================================================================


def get_or_create_film(
    session: Session, title: str, year: Optional[int] = None
) -> tuple[Film, bool]:
    """
    Find a film by Letterboxd title and year, or add it.

    Returns (film, created). Two callers running this concurrently produce
    duplicates, which is why sync and refresh are guarded by the single-flight
    index on the jobs table.
    """
    query = session.query(Film).filter(Film.letterboxd_title == title)
    if year is not None:
        query = query.filter(Film.letterboxd_year == year)

    film = query.first()
    if film:
        logger.debug(f"Found existing film: {film.full_title} (ID: {film.id})")
        return film, False

    film = Film(letterboxd_title=title, letterboxd_year=year, date_added=datetime.now(UTC))
    session.add(film)
    session.flush()  # Assign the ID without committing.

    logger.info(f"Created new film: {film.full_title} (ID: {film.id})")
    return film, True


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


# ==============================================================================
# Listing: one builder, one query
# ==============================================================================


class LibraryFilter(BaseModel):
    """
    What the grid is showing.

    Every field is optional and they compose. Combining them is what the CLI
    structurally could not do.
    """

    model_config = ConfigDict(frozen=True)

    provider: Optional[str] = None
    country: Optional[str] = None
    offer_type: Optional[str] = None
    watched: Optional[bool] = None

    @property
    def is_active(self) -> bool:
        """True when anything is being narrowed."""
        return any(v is not None and v != "" for v in self.model_dump().values())

    def as_params(self) -> dict:
        """
        The filter as URL query parameters, omitting what is not set.

        Views are bookmarkable, so the URL is the state; this is the one place
        that mapping is written down.
        """
        params: dict[str, str] = {}
        if self.provider:
            params["provider"] = self.provider
        if self.country:
            params["country"] = self.country
        if self.offer_type:
            params["offer_type"] = self.offer_type
        if self.watched is not None:
            params["watched"] = "true" if self.watched else "false"
        return params


# Sort keys the grid may ask for, mapped to SQL. This dict is the whitelist -
# a key that is not here falls back to the default rather than reaching the
# query builder. Title and year prefer the Letterboxd value, matching
# Film.display_title / Film.display_year.
_SORT_TITLE = func.coalesce(Film.letterboxd_title, Film.tmdb_title)
_SORT_YEAR = func.coalesce(Film.letterboxd_year, Film.tmdb_year)

# Confidence is an ordered scale stored as text, so alphabetical sorting would
# put "exact" after "duplicate" and "high" before "low". Rank it explicitly.
_SORT_CONFIDENCE = case(
    {"exact": 0, "high": 1, "medium": 2, "low": 3, "duplicate": 4, "none": 5},
    value=Film.match_confidence,
    else_=6,
)

# `col.is_(None)` sorts False before True, which puts unknown values last
# instead of at the top of a descending sort.
SORTS: dict[str, tuple] = {
    "added": (Film.date_added.desc(),),
    "title": (_SORT_TITLE.asc(),),
    "year": (_SORT_YEAR.is_(None), _SORT_YEAR.desc()),
    "rating": (Film.vote_average.is_(None), Film.vote_average.desc()),
    "confidence": (_SORT_CONFIDENCE.asc(),),
}
DEFAULT_SORT = "added"


def _offer_predicate(filters: LibraryFilter):
    """
    One correlated EXISTS over streaming_offers, covering every offer axis.

    All three conditions must hold for the *same* offer row. Three independent
    EXISTS clauses would match a film that streams on Netflix in the US and
    happens to be rentable in France on "unwatched, Netflix, FR" - which is
    the wrong answer to the only question this app asks.

    EXISTS rather than a JOIN because a join multiplies rows, and DISTINCT to
    undo that breaks LIMIT and ORDER BY.
    """
    conditions: list = []

    if filters.provider:
        # Substring match: TMDB names providers "Netflix basic with Ads",
        # "Amazon Prime Video", and so on.
        conditions.append(StreamingOffer.provider_name.ilike(f"%{filters.provider}%"))
    if filters.country:
        conditions.append(StreamingOffer.country_code == filters.country.upper())
    if filters.offer_type:
        conditions.append(StreamingOffer.monetization_type == filters.offer_type)

    if not conditions:
        return None

    return select(StreamingOffer.id).where(StreamingOffer.film_id == Film.id, *conditions).exists()


def _narrow(query, filters: LibraryFilter):
    """Apply every active filter. Shared by the count and the page."""
    if filters.watched is True:
        query = query.filter(Film.watched.is_(True))
    elif filters.watched is False:
        # Legacy rows could carry NULL rather than 0; both mean unwatched.
        query = query.filter(or_(Film.watched.is_(False), Film.watched.is_(None)))

    predicate = _offer_predicate(filters)
    if predicate is not None:
        query = query.filter(predicate)

    return query


def _summarise(session: Session, films: list[Film]) -> list[FilmSummary]:
    counts = offer_counts(session, [f.id for f in films])
    return [FilmSummary.from_film(f, offer_count=counts.get(f.id, 0)) for f in films]


def list_films(
    session: Session,
    *,
    filters: Optional[LibraryFilter] = None,
    sort: str = DEFAULT_SORT,
    page: int = 1,
    per_page: int = 48,
) -> tuple[list[FilmSummary], int]:
    """
    One page of the library, filtered, ordered and sliced in SQL.

    Returns (page, total_matching). "unwatched, on Netflix, available in FR"
    is one call and one query over films.
    """
    filters = filters or LibraryFilter()
    order = SORTS.get(sort, SORTS[DEFAULT_SORT])

    total = _narrow(session.query(func.count(Film.id)), filters).scalar() or 0

    films = (
        _narrow(session.query(Film), filters)
        # Films sharing a sort value would otherwise be free to swap places
        # between pages, so a row can appear twice or not at all.
        .order_by(*order, Film.id.asc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )

    return _summarise(session, films), total


class Facets(BaseModel):
    """The values a filter can usefully take, read from what is stored."""

    model_config = ConfigDict(frozen=True)

    providers: list[str] = []
    countries: list[str] = []
    offer_types: list[str] = []


def facets(session: Session) -> Facets:
    """
    Distinct providers, countries and offer types across every stored offer.

    Three cheap queries against indexed columns. Deliberately not filtered by
    the current selection: a dropdown that hides the option you need because
    of the option you already picked is worse than one that returns nothing.
    """
    return Facets(
        providers=sorted(r[0] for r in session.query(distinct(StreamingOffer.provider_name)).all()),
        countries=sorted(r[0] for r in session.query(distinct(StreamingOffer.country_code)).all()),
        offer_types=sorted(
            r[0] for r in session.query(distinct(StreamingOffer.monetization_type)).all()
        ),
    )


# ==============================================================================
# One film
# ==============================================================================


def get_detail(
    session: Session, film_id: int, *, countries: Optional[list[str]] = None
) -> Optional[FilmDetail]:
    """
    Single film with its offers, for the detail page.

    `countries` scopes which offers are loaded. TMDB returns availability for
    every country it knows - one film in this library has 668 offers, and the
    600-odd in countries the user can neither reach nor VPN into are weight on
    every render for no information. The unscoped total is still reported, so
    the page can say it is showing a subset.
    """
    film = session.query(Film).filter(Film.id == film_id).first()
    if not film:
        return None

    query = session.query(StreamingOffer).filter(StreamingOffer.film_id == film_id)
    if countries:
        query = query.filter(StreamingOffer.country_code.in_([c.upper() for c in countries]))

    total_offers = offer_counts(session, [film_id]).get(film_id, 0)

    return FilmDetail.from_film(film, offers=query.all(), offer_count=total_offers)


def set_watched_by_id(
    session: Session, film_id: int, watched: bool = True
) -> Optional[FilmSummary]:
    """Mark a film watched or unwatched by primary key."""
    film = session.query(Film).filter(Film.id == film_id).first()
    if not film:
        return None

    film.watched = watched
    film.watched_at = datetime.now(UTC) if watched else None
    session.flush()

    logger.info(f"Marked '{film.full_title}' as {'watched' if watched else 'unwatched'}")

    counts = offer_counts(session, [film.id])
    return FilmSummary.from_film(film, offer_count=counts.get(film.id, 0))


def stats(session: Session) -> dict:
    """Aggregate counts for the stats view."""
    total_films = session.query(func.count(Film.id)).scalar() or 0
    watched_films = session.query(func.count(Film.id)).filter(Film.watched.is_(True)).scalar() or 0
    films_with_tmdb = (
        session.query(func.count(Film.id)).filter(Film.tmdb_id.isnot(None)).scalar() or 0
    )

    return {
        "total_films": total_films,
        "watched_films": watched_films,
        "unwatched_films": total_films - watched_films,
        "films_with_tmdb": films_with_tmdb,
        "match_rate": round(films_with_tmdb / total_films * 100, 1) if total_films else 0,
        "total_offers": session.query(func.count(StreamingOffer.id)).scalar() or 0,
        "unique_providers": session.query(
            func.count(distinct(StreamingOffer.provider_name))
        ).scalar()
        or 0,
        "unique_countries": session.query(
            func.count(distinct(StreamingOffer.country_code))
        ).scalar()
        or 0,
    }
