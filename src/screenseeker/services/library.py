"""
Read and update the local film library.

This is the only module that queries films for display. The single-axis
helpers it replaced (`get_films_by_provider`, `get_films_by_country`) could not
be combined and applied their limit in Python; `list_films` pushes filtering,
sorting and slicing into one query.

Every function serialises to FilmSummary or FilmDetail while the session is
open, so callers never receive a detached ORM instance.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from .. import settings
from ..database.models import Film, Member, StreamingOffer, WatchlistEntry
from ..logger import get_logger
from .models import FilmDetail, FilmSummary, MemberRef, OfferOut

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

    A year is matched exactly when given, then falls back to a row stored
    without one. That fallback is what keeps a household from splitting one
    film in two: Letterboxd omits the year on some entries, so one member's
    scrape can store "Heat" with no year and another's "Heat (1995)". Without
    it the second scrape misses the first row and creates a duplicate, which
    then needs enriching separately and appears twice in the grid.
    """
    query = session.query(Film).filter(Film.letterboxd_title == title)

    if year is None:
        # Nothing to match on: prefer the row that also has no year, then the
        # oldest, so repeated scrapes keep landing on the same film.
        film = query.order_by(Film.letterboxd_year.is_(None).desc(), Film.id.asc()).first()
    else:
        film = query.filter(Film.letterboxd_year == year).first()
        if film is None:
            film = query.filter(Film.letterboxd_year.is_(None)).order_by(Film.id.asc()).first()
            if film is not None:
                # Fill in what the earlier scrape could not see.
                film.letterboxd_year = year
                session.flush()
                logger.info(f"Backfilled year {year} onto '{title}' (ID: {film.id})")

    if film:
        logger.debug(f"Found existing film: {film.full_title} (ID: {film.id})")
        return film, False

    film = Film(letterboxd_title=title, letterboxd_year=year, date_added=datetime.now(UTC))
    session.add(film)
    session.flush()  # Assign the ID without committing.

    logger.info(f"Created new film: {film.full_title} (ID: {film.id})")
    return film, True


def record_entry(session: Session, member_id: int, film: Film) -> str:
    """
    Note that a member wants a film. Returns "added", "restored" or "existing".

    The unique constraint on (member_id, film_id) makes this an upsert rather
    than an insert: a film put back on a watchlist reuses its old row, instead
    of stacking a second entry that would double the member's count.
    """
    entry = (
        session.query(WatchlistEntry)
        .filter(WatchlistEntry.member_id == member_id, WatchlistEntry.film_id == film.id)
        .first()
    )

    now = datetime.now(UTC)

    if entry is None:
        session.add(WatchlistEntry(member_id=member_id, film_id=film.id, date_added=now))
        session.flush()
        _pull_back_date_added(film, now)
        return "added"

    if entry.removed_at is not None:
        entry.removed_at = None
        session.flush()
        return "restored"

    return "existing"


def _pull_back_date_added(film: Film, when: datetime) -> None:
    """
    Keep Film.date_added at the earliest date any member added the film.

    The column is denormalised so the "recently added" sort stays a plain
    column rather than a correlated MIN() per row; this is what keeps it
    honest when a second member adds a film the first already had.
    """
    current = film.date_added
    if current is None:
        film.date_added = when
        return

    # SQLite hands back naive datetimes whatever went in, so both sides are
    # normalised before comparing; mixing the two raises TypeError.
    stored = current if current.tzinfo else current.replace(tzinfo=UTC)
    candidate = when if when.tzinfo else when.replace(tzinfo=UTC)

    if candidate < stored:
        film.date_added = when


def merge_films(session: Session, keep: Film, drop: Film) -> int:
    """
    Fold one film row into another and delete the loser. Returns entries moved.

    Two rows can describe one film - Letterboxd omitting a year on one member's
    entry, a title punctuated differently on another's - and enrichment only
    finds out when both resolve to the same TMDB id. Before the household
    existed the collision was flagged and left alone, which meant the losing
    row never got streaming data and sat in the grid as "nowhere to stream"
    forever. Now the two rows are the same film wanted by different people, so
    merging them is both possible and the only correct answer.

    The caller decides which row survives; this moves the entries, keeps the
    earliest added date, and lets the ORM cascade take the loser's offers.
    """
    if keep.id == drop.id:
        return 0

    existing = {
        entry.member_id: entry
        for entry in session.query(WatchlistEntry).filter(WatchlistEntry.film_id == keep.id).all()
    }

    moved = 0
    for entry in session.query(WatchlistEntry).filter(WatchlistEntry.film_id == drop.id).all():
        twin = existing.get(entry.member_id)
        if twin is None:
            entry.film_id = keep.id
            existing[entry.member_id] = entry
            moved += 1
            continue

        # The member listed both rows. Keep one entry holding the earlier date,
        # and treat it as live if either side was - they still want the film.
        if entry.date_added and (not twin.date_added or entry.date_added < twin.date_added):
            twin.date_added = entry.date_added
        if entry.removed_at is None:
            twin.removed_at = None
        session.delete(entry)

    if drop.date_added:
        _pull_back_date_added(keep, drop.date_added)

    session.delete(drop)
    session.flush()

    logger.info(
        f"Merged film {drop.id} ('{drop.letterboxd_title}') into {keep.id} "
        f"('{keep.letterboxd_title}'): {moved} entries moved"
    )
    return moved


def retire_missing_entries(session: Session, member_id: int, seen_film_ids: set[int]) -> int:
    """
    Mark this member's live entries that the latest scrape did not return.

    Soft, and never called on an empty scrape (see `sync.ingest_watchlist`): a
    partial or failed scrape reading as "your watchlist is empty" would
    otherwise retire the household's whole list in one run.
    """
    query = session.query(WatchlistEntry).filter(
        WatchlistEntry.member_id == member_id,
        WatchlistEntry.removed_at.is_(None),
    )
    if seen_film_ids:
        query = query.filter(WatchlistEntry.film_id.notin_(seen_film_ids))

    retired = query.update(
        {WatchlistEntry.removed_at: datetime.now(UTC)}, synchronize_session=False
    )
    return int(retired or 0)


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

    `extra="forbid"` so a filter that no longer exists fails loudly. Pydantic's
    default is to ignore unknown keys, which meant a caller still passing the
    removed `watched=` kept working and quietly filtered nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A free-text title search. Matches either the Letterboxd or the TMDB
    # title, so a film renamed on match is still found by either name.
    query: Optional[str] = None
    provider: Optional[str] = None
    country: Optional[str] = None
    offer_type: Optional[str] = None

    # Whose watchlists to draw from. A tuple because the model is frozen and
    # a list would make it unhashable. Empty means everyone.
    members: tuple[int, ...] = ()
    # "any" is the union - what at least one of these people wants. "all" is
    # the intersection, which is the question a household actually asks on a
    # Friday night: what do we *all* want to see?
    member_match: Literal["any", "all"] = "any"

    @property
    def is_active(self) -> bool:
        """True when anything is being narrowed."""
        if self.members:
            return True
        # member_match alone narrows nothing, so an untouched dropdown does not
        # light up the Clear link.
        ignored = {"members", "member_match"}
        return any(
            value is not None and value != ""
            for key, value in self.model_dump().items()
            if key not in ignored
        )

    def as_params(self) -> dict:
        """
        The filter as URL query parameters, omitting what is not set.

        Views are bookmarkable, so the URL is the state; this is the one place
        that mapping is written down.

        Every value is a string, including the member selection, which is
        comma-joined rather than repeated. Pager links are built by merging
        this dict and running it through Jinja's `urlencode`, which stringifies
        a list value instead of expanding it - `members=%5B1%2C2%5D`, silently
        dropping the filter on page two. The route parses both spellings, so
        the form can still submit `members=1&members=2` the way HTML does.
        """
        params: dict[str, str] = {}
        if self.query:
            params["query"] = self.query
        if self.provider:
            params["provider"] = self.provider
        if self.country:
            params["country"] = self.country
        if self.offer_type:
            params["offer_type"] = self.offer_type
        if self.members:
            params["members"] = ",".join(str(m) for m in self.members)
            # Only meaningful alongside a selection, and "any" is the default.
            if self.member_match == "all":
                params["member_match"] = "all"
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

# How many people currently want this film. A correlated scalar subquery
# rather than a JOIN + GROUP BY: joining multiplies rows, and the GROUP BY
# needed to undo that breaks LIMIT and OFFSET the same way DISTINCT does.
_WANTED_BY = (
    select(func.count(WatchlistEntry.id))
    .where(WatchlistEntry.film_id == Film.id, WatchlistEntry.removed_at.is_(None))
    .scalar_subquery()
)

# `col.is_(None)` sorts False before True, which puts unknown values last
# instead of at the top of a descending sort.
SORTS: dict[str, tuple] = {
    "added": (Film.date_added.desc(),),
    "title": (_SORT_TITLE.asc(),),
    "year": (_SORT_YEAR.is_(None), _SORT_YEAR.desc()),
    "rating": (Film.vote_average.is_(None), Film.vote_average.desc()),
    "confidence": (_SORT_CONFIDENCE.asc(),),
    # Consensus first, then rating inside a tie: the point of a shared
    # watchlist is that what several people want outranks what one does.
    "wanted": (_WANTED_BY.desc(), Film.vote_average.is_(None), Film.vote_average.desc()),
}
DEFAULT_SORT = "added"


def _offer_predicate(filters: LibraryFilter):
    """
    One correlated EXISTS over streaming_offers, covering every offer axis.

    All three conditions must hold for the *same* offer row. Three independent
    EXISTS clauses would match a film that streams on Netflix in the US and
    happens to be rentable in France on "Netflix, FR, flatrate" - which is
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


def _member_predicate(filters: LibraryFilter):
    """
    Restrict the grid to the selected members' watchlists.

    "any" is an EXISTS over the selection - the union of those people's lists.
    "all" counts the distinct members among them who list the film and demands
    the full set, which is the intersection. Counting distinct member_ids
    rather than rows matters even with the unique constraint in place: it makes
    a duplicated selection ("2,2") mean the same thing as "2" instead of
    matching nothing.
    """
    if not filters.members:
        return None

    ids = set(filters.members)
    live = (WatchlistEntry.film_id == Film.id, WatchlistEntry.removed_at.is_(None))

    if filters.member_match == "all":
        return (
            select(func.count(distinct(WatchlistEntry.member_id)))
            .where(*live, WatchlistEntry.member_id.in_(ids))
            .scalar_subquery()
        ) == len(ids)

    return select(WatchlistEntry.id).where(*live, WatchlistEntry.member_id.in_(ids)).exists()


# Somebody, right now, has this film on their watchlist.
#
# This is the library's definition of membership, not a filter the user picks:
# a film everyone has dropped is not in the library any more. Logging a film on
# Letterboxd takes it off the watchlist, which is what makes this the only
# "watched" signal the app needs - there is no flag here to keep in sync with
# the diary, and nothing to click twice.
#
# The row is kept rather than deleted (see WatchlistEntry.removed_at), so a
# half-read scrape is recoverable and a re-added film comes back with its
# original date. It is simply invisible until someone wants it again.
IS_WANTED = (
    select(WatchlistEntry.id)
    .where(WatchlistEntry.film_id == Film.id, WatchlistEntry.removed_at.is_(None))
    .exists()
)


def _narrow(query, filters: LibraryFilter):
    """Apply every active filter. Shared by the count and the page."""
    # Unconditional: films nobody lists are not part of the library.
    query = query.filter(IS_WANTED)

    if filters.query:
        # Case-insensitive substring on either title. `\`, `_` and `%` in the
        # input are escaped so a search for them is literal, not a wildcard.
        term = filters.query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{term}%"
        query = query.filter(
            or_(
                Film.letterboxd_title.ilike(like, escape="\\"),
                Film.tmdb_title.ilike(like, escape="\\"),
            )
        )

    predicate = _offer_predicate(filters)
    if predicate is not None:
        query = query.filter(predicate)

    members = _member_predicate(filters)
    if members is not None:
        query = query.filter(members)

    return query


def wanted_by(session: Session, film_ids: list[int]) -> dict[int, list[MemberRef]]:
    """
    Who currently wants each of these films, in one query.

    The grid draws a chip per member on every card, so this has to be a single
    join over the page's films rather than a relationship read per row - the
    same reason `offer_counts` exists. Members are ordered by name so a film's
    chips do not reshuffle between renders.
    """
    if not film_ids:
        return {}

    rows = (
        session.query(WatchlistEntry.film_id, Member)
        .join(Member, Member.id == WatchlistEntry.member_id)
        .filter(
            WatchlistEntry.film_id.in_(film_ids),
            WatchlistEntry.removed_at.is_(None),
        )
        .order_by(func.lower(Member.display_name).asc(), Member.id.asc())
        .all()
    )

    grouped: dict[int, list[MemberRef]] = {fid: [] for fid in film_ids}
    for film_id, member in rows:
        grouped[film_id].append(MemberRef.from_row(member))
    return grouped


def _summarise(session: Session, films: list[Film]) -> list[FilmSummary]:
    ids = [f.id for f in films]
    counts = offer_counts(session, ids)
    members = wanted_by(session, ids)
    return [
        FilmSummary.from_film(f, offer_count=counts.get(f.id, 0), members=members.get(f.id, []))
        for f in films
    ]


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

    Returns (page, total_matching). "on Netflix, available in FR, wanted by
    Alice"
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


def _facet_values(session: Session, column: InstrumentedAttribute[str]) -> list[str]:
    """
    Distinct values of one offer column, across films someone still wants.

    Scoped to wanted films because the alternative is a dropdown offering a
    provider that only ever appears on films nobody has listed for months -
    pick it and the grid comes back empty with no way to tell why.

    `column` is annotated rather than left bare: with an implicit Any, mypy
    cannot solve the type variable on `distinct()` and gives up on the row
    type, which surfaces as "Need type annotation" on the comprehension.
    """
    wanted = select(Film.id).where(Film.id == StreamingOffer.film_id, IS_WANTED).exists()
    rows = session.query(distinct(column)).filter(wanted).all()
    return sorted(row[0] for row in rows)


def facets(session: Session) -> Facets:
    """
    The values a filter can usefully take.

    Three cheap queries against indexed columns. Deliberately not filtered by
    the current *selection*: a dropdown that hides the option you need because
    of the option you already picked is worse than one that returns nothing.
    """
    return Facets(
        providers=_facet_values(session, StreamingOffer.provider_name),
        countries=_facet_values(session, StreamingOffer.country_code),
        offer_types=_facet_values(session, StreamingOffer.monetization_type),
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
    # IS_WANTED here too, so a bookmark to a film the household has since
    # dropped 404s rather than rendering a page unreachable from anywhere else.
    film = session.query(Film).filter(Film.id == film_id, IS_WANTED).first()
    if not film:
        return None

    query = session.query(StreamingOffer).filter(StreamingOffer.film_id == film_id)
    if countries:
        query = query.filter(StreamingOffer.country_code.in_([c.upper() for c in countries]))

    total_offers = offer_counts(session, [film_id]).get(film_id, 0)

    return FilmDetail.from_film(
        film,
        offers=query.all(),
        offer_count=total_offers,
        members=wanted_by(session, [film_id]).get(film_id, []),
    )


def offers_for_films(
    session: Session, film_ids: list[int], *, countries: Optional[list[str]] = None
) -> dict[int, list[OfferOut]]:
    """
    Load offers for many films in one query, grouped by film.

    The Tonight view needs each candidate's offers to run the watch strategy;
    calling get_detail per film would be one query each. `countries` scopes
    the rows the same way get_detail does.
    """
    if not film_ids:
        return {}

    query = session.query(StreamingOffer).filter(StreamingOffer.film_id.in_(film_ids))
    if countries:
        query = query.filter(StreamingOffer.country_code.in_([c.upper() for c in countries]))

    grouped: dict[int, list[OfferOut]] = {fid: [] for fid in film_ids}
    for row in query.all():
        grouped[row.film_id].append(OfferOut.from_row(row))
    return grouped


def list_stale(
    session: Session, *, days: int = settings.CACHE_TTL_DAYS, page: int = 1, per_page: int = 48
) -> tuple[list[FilmSummary], int]:
    """
    Films whose streaming data has aged past the TTL, oldest first.

    A never-checked film is stale, not fresh, so it sorts before everything
    with a date. Ordered so the refresh queue reads worst-first.

    Films nobody lists are excluded: refreshing them spends the TMDB rate limit
    on availability for films the household will never be shown.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stale = or_(Film.last_checked.is_(None), Film.last_checked < cutoff)

    total = session.query(func.count(Film.id)).filter(stale, IS_WANTED).scalar() or 0

    films = (
        session.query(Film)
        .filter(stale, IS_WANTED)
        # NULLs first: never-checked is the most stale. Then oldest check.
        .order_by(Film.last_checked.is_(None).desc(), Film.last_checked.asc(), Film.id.asc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )

    return _summarise(session, films), total
