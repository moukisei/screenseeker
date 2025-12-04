"""
Database service layer for enrichment workflow.

Handles the integration between TMDB enrichment and database persistence.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from screenseeker.logger import get_logger

from ..enrichers.enrichment_models import EnrichmentResult
from ..enrichers.tmdb_enricher import TMDBEnricher
from .models import Film
from .queries import (
    get_film_by_title_year,
    get_film_by_tmdb_id,
    get_or_create_film,
    save_streaming_offers,
)

logger = get_logger(__name__)


def enrich_and_save_film(
    session: Session,
    enricher: TMDBEnricher,
    title: str,
    year: Optional[int] = None,
    force_refresh: bool = False,
) -> tuple[Film, EnrichmentResult]:
    """
    Enrich a film with TMDB data and save to database.

    Handles the complete workflow:
    1. Check if film exists in database
    2. Check if cached data is fresh
    3. Call TMDB API if needed
    4. Save/update film and streaming offers
    5. Return film and enrichment result

    Args:
        session: Database session
        enricher: TMDBEnricher instance
        title: Film title
        year: Optional release year
        force_refresh: Force API call even if cached data exists

    Returns:
        Tuple of (Film object, EnrichmentResult)
    """
    logger.info(f"Processing film: '{title}' ({year or 'no year'})")

    # Call TMDB API with fuzzy year matching
    enrichment = enricher.enrich(title, year, fuzzy_year=True)

    if not enrichment.success or not enrichment.tmdb_movie:
        logger.warning(f"TMDB enrichment failed for '{title}'")

        # Still create/update film record (mark as failed enrichment)
        film, created = get_or_create_film(session, title, year)
        film.match_confidence = "none"
        session.flush()

        return film, enrichment

    # Check if film already exists - prioritize matching by title/year first
    # This prevents duplicates when enriching films that were synced from Letterboxd
    film = get_film_by_title_year(session, title, year)

    # If not found by title/year, check by TMDB ID (for films from other sources)
    if not film:
        film = get_film_by_tmdb_id(session, enrichment.tmdb_movie.tmdb_id)

    if film:
        logger.info(f"Film already exists in database: {film.full_title} (ID: {film.id})")

        # Check if we need to refresh streaming offers
        if force_refresh or needs_refresh(film):
            logger.info("Refreshing streaming offers...")
            update_film_from_enrichment(session, film, enrichment)
        else:
            logger.info("Using cached streaming data")

    else:
        # Create new film
        film = create_film_from_enrichment(session, title, year, enrichment)
        logger.info(f"Created new film: {film.full_title} (ID: {film.id})")

    return film, enrichment


def create_film_from_enrichment(
    session: Session,
    letterboxd_title: str,
    letterboxd_year: Optional[int],
    enrichment: EnrichmentResult,
) -> Film:
    """
    Create a new film record from enrichment result.

    Args:
        session: Database session
        letterboxd_title: Original title from Letterboxd
        letterboxd_year: Original year from Letterboxd
        enrichment: TMDB enrichment result

    Returns:
        Created Film object
    """
    tmdb_movie = enrichment.tmdb_movie
    year_mismatch = False

    if letterboxd_year and tmdb_movie.year:
        year_mismatch = letterboxd_year != tmdb_movie.year

    film = Film(
        letterboxd_title=letterboxd_title,
        letterboxd_year=letterboxd_year,
        tmdb_id=tmdb_movie.tmdb_id,
        tmdb_title=tmdb_movie.title,
        tmdb_year=tmdb_movie.year,
        tmdb_release_date=tmdb_movie.release_date,
        match_confidence=enrichment.match_confidence,
        year_mismatch=year_mismatch,
        date_added=datetime.utcnow(),
        last_checked=datetime.utcnow(),
    )

    session.add(film)
    session.flush()  # Get the ID

    # Save streaming offers
    if enrichment.streaming_offers:
        offers_data = [
            {
                "country_code": offer.country_code,
                "country_name": offer.country_name,
                "provider_id": offer.provider_id,
                "provider_name": offer.provider_name,
                "monetization_type": offer.offer_type,
                "streaming_url": offer.streaming_url,
                "logo_path": offer.logo_path,
                "display_priority": offer.display_priority,
            }
            for offer in enrichment.streaming_offers
        ]

        save_streaming_offers(session, film.id, offers_data)

    logger.info(
        f"Saved {len(enrichment.streaming_offers)} streaming offers for '{film.full_title}'"
    )

    if year_mismatch:
        logger.warning(f"Year mismatch: Letterboxd={letterboxd_year}, TMDB={tmdb_movie.year}")

    return film


def update_film_from_enrichment(session: Session, film: Film, enrichment: EnrichmentResult) -> Film:
    """
    Update existing film with fresh enrichment data.

    Args:
        session: Database session
        film: Existing film record
        enrichment: Fresh TMDB enrichment result

    Returns:
        Updated Film object
    """
    tmdb_movie = enrichment.tmdb_movie

    # Check if another film already has this TMDB ID
    if film.tmdb_id != tmdb_movie.tmdb_id:
        existing_film_with_tmdb_id = get_film_by_tmdb_id(session, tmdb_movie.tmdb_id)
        if existing_film_with_tmdb_id and existing_film_with_tmdb_id.id != film.id:
            logger.warning(
                f"Duplicate film detected: '{film.full_title}' (ID: {film.id}) "
                f"matches TMDB ID {tmdb_movie.tmdb_id} already used by "
                f"'{existing_film_with_tmdb_id.full_title}' (ID: {existing_film_with_tmdb_id.id}). "
                f"Skipping TMDB update to preserve database integrity."
            )
            # Mark as low confidence to indicate potential duplicate
            film.match_confidence = "duplicate"
            film.last_checked = datetime.utcnow()
            session.flush()
            return film

    # Update TMDB data (might have changed or be newly added)
    film.tmdb_id = tmdb_movie.tmdb_id
    film.tmdb_title = tmdb_movie.title
    film.tmdb_year = tmdb_movie.year
    film.tmdb_release_date = tmdb_movie.release_date
    film.match_confidence = enrichment.match_confidence
    film.last_checked = datetime.utcnow()

    # Check for year mismatch
    if film.letterboxd_year and tmdb_movie.year:
        film.year_mismatch = film.letterboxd_year != tmdb_movie.year

    session.flush()

    # Update streaming offers (delete old, insert new)
    if enrichment.streaming_offers:
        offers_data = [
            {
                "country_code": offer.country_code,
                "country_name": offer.country_name,
                "provider_id": offer.provider_id,
                "provider_name": offer.provider_name,
                "monetization_type": offer.offer_type,
                "streaming_url": offer.streaming_url,
                "logo_path": offer.logo_path,
                "display_priority": offer.display_priority,
            }
            for offer in enrichment.streaming_offers
        ]

        save_streaming_offers(session, film.id, offers_data)

    logger.info(f"Updated streaming offers for '{film.full_title}'")

    return film


def needs_refresh(film: Film, days: int = 7) -> bool:
    """
    Check if film's streaming data needs refresh.

    Args:
        film: Film object
        days: Number of days before data is considered stale

    Returns:
        True if needs refresh, False otherwise
    """
    if film.last_checked is None:
        return True

    from datetime import timedelta

    stale_date = datetime.utcnow() - timedelta(days=days)
    return film.last_checked < stale_date


def get_film_with_offers(
    session: Session, title: str, year: Optional[int] = None
) -> Optional[Film]:
    """
    Get a film with its streaming offers loaded.

    Args:
        session: Database session
        title: Film title
        year: Optional release year

    Returns:
        Film object with streaming_offers loaded, or None
    """
    from sqlalchemy.orm import joinedload

    film = (
        session.query(Film)
        .filter(Film.letterboxd_title == title)
        .options(joinedload(Film.streaming_offers))
    )

    if year is not None:
        film = film.filter(Film.letterboxd_year == year)

    return film.first()


def convert_db_offers_to_pydantic(film: Film) -> list:
    """
    Convert database StreamingOffer objects to Pydantic models.

    Args:
        film: Film object with streaming_offers relationship loaded

    Returns:
        List of Pydantic StreamingOffer objects
    """
    from ..enrichers.enrichment_models import StreamingOffer as PydanticStreamingOffer

    return [
        PydanticStreamingOffer(
            country_code=offer.country_code,
            country_name=offer.country_name,
            provider_id=offer.provider_id,
            provider_name=offer.provider_name,
            offer_type=offer.monetization_type,
            streaming_url=offer.streaming_url,
            logo_path=offer.logo_path,
            display_priority=offer.display_priority,
        )
        for offer in film.streaming_offers
    ]
