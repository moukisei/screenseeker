"""
TMDB enrichment: fetching availability and writing it down.

Both halves live here. They used to sit in database/service.py and
database/queries.py, one level below this package and doing the same job -
`database.service` next to `services.*` was a name collision waiting to be
imported wrongly.

Progress is reported through a callback rather than written to a terminal, so
the same code drives the CLI progress bar and the background job runner.
"""

from datetime import UTC, datetime, timedelta
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import settings
from ..database.models import Film, StreamingOffer
from ..enrichers.enrichment_models import EnrichmentResult
from ..enrichers.tmdb_enricher import TMDBEnricher
from ..exceptions import ConfigurationError
from ..logger import get_logger
from ..user_config import get_tmdb_api_key
from .library import IS_WANTED, get_or_create_film, merge_films, offer_counts
from .models import FilmSummary

logger = get_logger(__name__)

# Called with (completed, total, current_film_title).
ProgressCallback = Callable[[int, int, str], None]


class FilmError(BaseModel):
    """One film that failed to enrich."""

    model_config = ConfigDict(frozen=True)

    film_id: Optional[int] = None
    title: str
    error: str


class EnrichmentReport(BaseModel):
    """Outcome of a batch run."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(..., description="Films attempted")
    succeeded: int = 0
    failed: int = 0
    errors: list[FilmError] = Field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return self.failed == 0


def build_enricher(cfg: dict) -> TMDBEnricher:
    """
    Construct a TMDB client from the user's config.

    Lives here rather than in the CLI because the background runner needs the
    same object, and a second copy of this would be a second place for the key
    lookup to drift.
    """
    api_key = get_tmdb_api_key(cfg)
    if not api_key:
        raise ConfigurationError(
            "TMDB API key not configured. Run `screenseeker config init`, or set TMDB_API_KEY."
        )

    tmdb = cfg.get("tmdb", {})
    return TMDBEnricher(
        api_key=api_key,
        rate_limit_per_second=tmdb.get("rate_limit", 5.0),
        language=tmdb.get("language", "en-US"),
    )


def stale_films(session: Session, days: int = 7) -> list[Film]:
    """
    Film rows never checked, or checked longer than `days` ago.

    Restricted to films someone still has on their watchlist. A film the
    household has dropped is not shown anywhere, so fetching its availability
    spends the TMDB rate limit on an answer nobody will ever read - and the
    nightly refresh would keep paying for it forever.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return (
        session.query(Film)
        .filter(or_(Film.last_checked.is_(None), Film.last_checked < cutoff), IS_WANTED)
        .all()
    )


def needs_refresh(film: Film, days: int = settings.CACHE_TTL_DAYS) -> bool:
    """
    Whether one film's streaming data has aged out.

    A film that was never checked is stale, not fresh.
    """
    if film.last_checked is None:
        return True

    last_checked = film.last_checked
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=UTC)

    return last_checked < datetime.now(UTC) - timedelta(days=days)


def select_stale(
    session: Session, days: int = 7, limit: Optional[int] = None
) -> tuple[list[FilmSummary], int]:
    """
    Films that need a TMDB fetch.

    This covers both films never checked and films whose data has aged past
    `days` - a never-checked film is stale, which is why there is no separate
    "unenriched" selection.

    Returns (selection, total_found) so callers can say "doing N of M".
    """
    films = stale_films(session, days=days)
    total = len(films)
    if limit:
        films = films[:limit]
    counts = offer_counts(session, [f.id for f in films])
    return [FilmSummary.from_film(f, offer_count=counts.get(f.id, 0)) for f in films], total


def enrich_films(
    session: Session,
    enricher: TMDBEnricher,
    films: list[FilmSummary],
    *,
    force_refresh: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> EnrichmentReport:
    """
    Enrich each film in turn, collecting rather than raising per-film errors.

    One film failing must not abort the batch - a single bad TMDB response
    should not cost the caller the whole run.
    """
    total = len(films)
    succeeded = 0
    errors: list[FilmError] = []

    for index, film in enumerate(films, start=1):
        if on_progress:
            on_progress(index, total, film.full_title)

        try:
            enrich_and_save_film(
                session,
                enricher,
                film.title,
                film.year,
                force_refresh=force_refresh,
            )
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            logger.warning(f"Enrichment failed for '{film.full_title}': {exc}")
            errors.append(FilmError(film_id=film.id, title=film.full_title, error=str(exc)))

    return EnrichmentReport(
        total=total,
        succeeded=succeeded,
        failed=len(errors),
        errors=errors,
    )


# ==============================================================================
# Persistence
#
# Fetching one film and writing the result down. Moved here from
# database/service.py: it was a second service layer under this one.
# ==============================================================================


def _offer_to_row(offer) -> dict:
    """
    Map a Pydantic StreamingOffer to a `streaming_offers` row dict.

    The Pydantic model calls the field `offer_type`; the column is
    `monetization_type`. This function is the only place that translation
    happens - do not inline it at call sites.
    """
    return {
        "country_code": offer.country_code,
        "country_name": offer.country_name,
        "provider_id": offer.provider_id,
        "provider_name": offer.provider_name,
        "monetization_type": offer.offer_type,
        "streaming_url": offer.streaming_url,
        "logo_path": offer.logo_path,
        "display_priority": offer.display_priority,
    }


def _apply_tmdb_fields(film: Film, tmdb_movie) -> None:
    """
    Copy TMDB movie data onto a Film row.

    Shared by the create and update paths so a newly added TMDB field cannot
    be persisted on one path and silently dropped on the other.
    """
    film.tmdb_id = tmdb_movie.tmdb_id
    film.tmdb_title = tmdb_movie.title
    film.tmdb_year = tmdb_movie.year
    film.tmdb_release_date = tmdb_movie.release_date
    film.poster_path = tmdb_movie.poster_path
    film.overview = tmdb_movie.overview
    film.vote_average = tmdb_movie.vote_average
    film.runtime = tmdb_movie.runtime


def save_streaming_offers(
    session: Session,
    film_id: int,
    offers: list[dict],
    checked_at: Optional[datetime] = None,
) -> int:
    """Replace a film's offers wholesale. TMDB gives the full picture each time."""
    session.query(StreamingOffer).filter(StreamingOffer.film_id == film_id).delete()

    checked_at = checked_at or datetime.now(UTC)
    for offer_data in offers:
        session.add(StreamingOffer(film_id=film_id, checked_at=checked_at, **offer_data))

    session.flush()
    logger.debug(f"Saved {len(offers)} streaming offers for film ID {film_id}")

    return len(offers)


def create_film_from_enrichment(
    session: Session,
    letterboxd_title: str,
    letterboxd_year: Optional[int],
    enrichment: EnrichmentResult,
) -> Film:
    """Add a film that TMDB matched, with its offers."""
    tmdb_movie = enrichment.tmdb_movie
    year_mismatch = bool(letterboxd_year and tmdb_movie.year and letterboxd_year != tmdb_movie.year)

    now = datetime.now(UTC)
    film = Film(
        letterboxd_title=letterboxd_title,
        letterboxd_year=letterboxd_year,
        match_confidence=enrichment.match_confidence,
        year_mismatch=year_mismatch,
        date_added=now,
        last_checked=now,
    )
    _apply_tmdb_fields(film, tmdb_movie)

    session.add(film)
    session.flush()  # Assign the ID before the offers reference it.

    if enrichment.streaming_offers:
        save_streaming_offers(
            session, film.id, [_offer_to_row(o) for o in enrichment.streaming_offers]
        )

    if year_mismatch:
        logger.warning(f"Year mismatch: Letterboxd={letterboxd_year}, TMDB={tmdb_movie.year}")

    return film


def update_film_from_enrichment(session: Session, film: Film, enrichment: EnrichmentResult) -> Film:
    """Refresh an existing film's TMDB fields and replace its offers."""
    tmdb_movie = enrichment.tmdb_movie

    # tmdb_id is unique. Writing one that another row already holds would fail
    # the constraint mid-batch, so the collision is resolved before the write.
    #
    # Two rows resolving to one TMDB id means two members' watchlists spelled
    # the same film differently - a missing year, different punctuation - so
    # they are merged rather than flagged. Flagging was the old answer, and it
    # left the losing row permanently without offers, showing in the grid as
    # "nowhere to stream" while its twin streamed fine.
    if film.tmdb_id != tmdb_movie.tmdb_id:
        clash = session.query(Film).filter(Film.tmdb_id == tmdb_movie.tmdb_id).first()
        if clash and clash.id != film.id:
            logger.info(
                f"'{film.full_title}' (ID: {film.id}) is the same film as "
                f"'{clash.full_title}' (ID: {clash.id}) - TMDB ID {tmdb_movie.tmdb_id}. Merging."
            )
            # The enriched row survives: it already holds the TMDB id, the
            # poster and the offers, so keeping it means nothing is refetched.
            merge_films(session, keep=clash, drop=film)
            film = clash

    _apply_tmdb_fields(film, tmdb_movie)
    film.match_confidence = enrichment.match_confidence
    film.last_checked = datetime.now(UTC)

    if film.letterboxd_year and tmdb_movie.year:
        film.year_mismatch = film.letterboxd_year != tmdb_movie.year

    session.flush()

    if enrichment.streaming_offers:
        save_streaming_offers(
            session, film.id, [_offer_to_row(o) for o in enrichment.streaming_offers]
        )

    logger.info(f"Updated streaming offers for '{film.full_title}'")
    return film


def enrich_and_save_film(
    session: Session,
    enricher: TMDBEnricher,
    title: str,
    year: Optional[int] = None,
    force_refresh: bool = False,
) -> tuple[Film, EnrichmentResult]:
    """
    Fetch one film from TMDB and persist the result.

    Returns (film, enrichment) even when TMDB found nothing: the row is still
    recorded with confidence "none" so the next run does not retry it blind.
    """
    logger.info(f"Processing film: '{title}' ({year or 'no year'})")

    enrichment = enricher.enrich(title, year, fuzzy_year=True)

    if not enrichment.success or not enrichment.tmdb_movie:
        logger.warning(f"TMDB enrichment failed for '{title}'")
        film, _ = get_or_create_film(session, title, year)
        film.match_confidence = "none"
        session.flush()
        return film, enrichment

    # Title and year first: these films came from a Letterboxd sync, and
    # matching on TMDB ID alone would create a second row for one of them.
    by_title = session.query(Film).filter(Film.letterboxd_title == title)
    if year is not None:
        by_title = by_title.filter(Film.letterboxd_year == year)

    film = by_title.first()
    if not film:
        film = session.query(Film).filter(Film.tmdb_id == enrichment.tmdb_movie.tmdb_id).first()

    if not film:
        film = create_film_from_enrichment(session, title, year, enrichment)
        logger.info(f"Created new film: {film.full_title} (ID: {film.id})")
        return film, enrichment

    if force_refresh or needs_refresh(film):
        update_film_from_enrichment(session, film, enrichment)
    else:
        logger.info(f"Using cached streaming data for {film.full_title}")

    return film, enrichment
