"""
The "where can I watch this?" use case.

Owns the cache decision: a film whose streaming data is still fresh is answered
entirely from the database, with no TMDB request.
"""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..database.models import Film
from ..database.queries import get_film_by_title_year
from ..database.service import (
    convert_db_offers_to_pydantic,
    enrich_and_save_film,
    needs_refresh,
)
from ..enrichers.enrichment_models import EnrichmentResult, TMDBMovieInfo
from ..enrichers.tmdb_enricher import TMDBEnricher
from ..enrichers.watch_strategy import WatchStrategyAnalyzer
from ..exceptions import ConfigurationError
from ..logger import get_logger
from ..models import Film as FilmModel
from .models import WatchResult

logger = get_logger(__name__)

CACHE_TTL_DAYS = 7


def parse_query(title: str, year: Optional[int] = None) -> tuple[str, Optional[int]]:
    """
    Split a "Title (YYYY)" string into its parts.

    An explicitly supplied year always wins over one embedded in the title.
    """
    if year is not None:
        return title.strip(), year

    _, parsed_title, parsed_year = FilmModel.parse_title_and_year(title)
    return parsed_title, parsed_year


def build_enrichment_from_film(
    film: Film, query_title: str, query_year: Optional[int] = None
) -> EnrichmentResult:
    """
    Reconstruct an EnrichmentResult from persisted data.

    Only the fields the watch strategy and the UI actually read are restored.
    `original_title` and `original_language` are not stored and stay None.

    The caller must have loaded film.streaming_offers while the session is open.
    """
    offers = convert_db_offers_to_pydantic(film)

    return EnrichmentResult(
        query_title=query_title,
        query_year=query_year,
        tmdb_movie=TMDBMovieInfo(
            tmdb_id=film.tmdb_id,
            title=film.tmdb_title or film.letterboxd_title,
            release_date=film.tmdb_release_date,
            year=film.tmdb_year,
            overview=film.overview,
            poster_path=film.poster_path,
            vote_average=film.vote_average,
        ),
        match_confidence=film.match_confidence or "none",
        streaming_offers=offers,
        total_countries=len({o.country_code for o in offers}),
        total_providers=len({o.provider_name for o in offers}),
        enriched_at=(film.last_checked or datetime.now(UTC)).isoformat(),
        success=True,
    )


def _cache_age_seconds(film: Optional[Film]) -> Optional[float]:
    if film is None or film.last_checked is None:
        return None

    last_checked = film.last_checked
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=UTC)

    return (datetime.now(UTC) - last_checked).total_seconds()


def find_watch_options(
    session: Session,
    title: str,
    year: Optional[int] = None,
    *,
    profile: dict,
    enricher: Optional[TMDBEnricher] = None,
    force_refresh: bool = False,
    ttl_days: int = CACHE_TTL_DAYS,
) -> WatchResult:
    """
    Find where to watch a film, using cached data when it is still fresh.

    Args:
        session: Database session; the caller owns the transaction.
        title: Film title, with or without a trailing "(YYYY)".
        year: Release year. Overrides any year embedded in the title.
        profile: Subscription profile for WatchStrategyAnalyzer.
        enricher: Only required when the cache misses. Omit it to force a
            cache-only lookup, which raises ConfigurationError on a miss.
        force_refresh: Ignore the cache and refetch from TMDB.
        ttl_days: How long persisted streaming data stays fresh.

    Returns:
        WatchResult holding the enrichment, the ranked strategy and cache info.
    """
    title, year = parse_query(title, year)
    logger.info(f"Looking up '{title}' ({year or 'no year'})")

    film = get_film_by_title_year(session, title, year)
    serve_from_cache = (
        film is not None
        and film.tmdb_id is not None
        and not force_refresh
        and not needs_refresh(film, days=ttl_days)
    )

    if serve_from_cache:
        logger.info("Serving from cache, skipping TMDB")
        enrichment = build_enrichment_from_film(film, title, year)
        from_cache = True
    else:
        if enricher is None:
            raise ConfigurationError(
                f"No fresh data for '{title}' and no TMDB enricher was supplied."
            )
        film, enrichment = enrich_and_save_film(
            session, enricher, title, year, force_refresh=force_refresh
        )
        from_cache = False

    strategy = WatchStrategyAnalyzer(profile).analyze(enrichment)

    return WatchResult(
        film_id=film.id if film else None,
        query_title=title,
        query_year=year,
        enrichment=enrichment,
        strategy=strategy,
        from_cache=from_cache,
        cache_age_seconds=_cache_age_seconds(film),
        year_mismatch=bool(film.year_mismatch) if film else False,
        letterboxd_year=film.letterboxd_year if film else None,
        tmdb_year=film.tmdb_year if film else None,
    )
