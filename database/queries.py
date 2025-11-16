"""
Database query helper functions.

Provides convenient functions for common database operations.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from database.models import Film, StreamingOffer
from logger import get_logger

logger = get_logger(__name__)


def get_film_by_id(session: Session, film_id: int) -> Optional[Film]:
    """
    Get a film by its database ID.

    Args:
        session: Database session
        film_id: Film database ID

    Returns:
        Film object or None
    """
    return session.query(Film).filter(Film.id == film_id).first()


def get_film_by_tmdb_id(session: Session, tmdb_id: int) -> Optional[Film]:
    """
    Get a film by its TMDB ID.

    Args:
        session: Database session
        tmdb_id: TMDB movie ID

    Returns:
        Film object or None
    """
    return session.query(Film).filter(Film.tmdb_id == tmdb_id).first()


def get_film_by_title_year(
    session: Session, title: str, year: Optional[int] = None
) -> Optional[Film]:
    """
    Get a film by Letterboxd title and year.

    Args:
        session: Database session
        title: Film title
        year: Release year (optional)

    Returns:
        Film object or None
    """
    query = session.query(Film).filter(Film.letterboxd_title == title)

    if year is not None:
        query = query.filter(Film.letterboxd_year == year)

    return query.first()


def search_films_by_title(session: Session, title: str, limit: int = 10) -> List[Film]:
    """
    Search films by title (case-insensitive partial match).

    Args:
        session: Database session
        title: Search term
        limit: Maximum results to return

    Returns:
        List of matching films
    """
    search_term = f"%{title}%"
    return (
        session.query(Film)
        .filter(
            or_(
                Film.letterboxd_title.ilike(search_term),
                Film.tmdb_title.ilike(search_term),
            )
        )
        .limit(limit)
        .all()
    )


def get_or_create_film(
    session: Session, title: str, year: Optional[int] = None
) -> tuple[Film, bool]:
    """
    Get existing film or create a new one.

    Args:
        session: Database session
        title: Film title
        year: Release year

    Returns:
        Tuple of (Film object, created boolean)
    """
    # Try to find existing film
    film = get_film_by_title_year(session, title, year)

    if film:
        logger.debug(f"Found existing film: {film.full_title} (ID: {film.id})")
        return film, False

    # Create new film
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        date_added=datetime.utcnow(),
    )
    session.add(film)
    session.flush()  # Get the ID without committing

    logger.info(f"Created new film: {film.full_title} (ID: {film.id})")
    return film, True


def get_stale_films(session: Session, days: int = 7) -> List[Film]:
    """
    Get films that haven't been checked in the specified number of days.

    Args:
        session: Database session
        days: Number of days to consider stale

    Returns:
        List of stale films
    """
    stale_date = datetime.utcnow() - timedelta(days=days)

    return (
        session.query(Film)
        .filter(or_(Film.last_checked.is_(None), Film.last_checked < stale_date))
        .all()
    )


def get_unwatched_films(session: Session) -> List[Film]:
    """
    Get all unwatched films from the watchlist.

    Args:
        session: Database session

    Returns:
        List of unwatched films
    """
    return session.query(Film).filter(Film.watched == False).all()


def mark_film_watched(
    session: Session, film_id: int, watched: bool = True
) -> Optional[Film]:
    """
    Mark a film as watched or unwatched.

    Args:
        session: Database session
        film_id: Film database ID
        watched: Whether the film is watched

    Returns:
        Updated Film object or None
    """
    film = get_film_by_id(session, film_id)

    if film:
        film.watched = watched
        film.watched_at = datetime.utcnow() if watched else None
        session.flush()
        logger.info(f"Marked film '{film.full_title}' as {'watched' if watched else 'unwatched'}")

    return film


def get_films_by_provider(
    session: Session,
    provider_name: str,
    country_code: Optional[str] = None,
    monetization_type: Optional[str] = None,
) -> List[Film]:
    """
    Get all films available on a specific provider.

    Args:
        session: Database session
        provider_name: Provider name (e.g., "Netflix")
        country_code: Optional country filter (e.g., "US")
        monetization_type: Optional type filter (e.g., "flatrate")

    Returns:
        List of films
    """
    query = (
        session.query(Film)
        .join(StreamingOffer)
        .filter(StreamingOffer.provider_name.ilike(f"%{provider_name}%"))
    )

    if country_code:
        query = query.filter(StreamingOffer.country_code == country_code)

    if monetization_type:
        query = query.filter(StreamingOffer.monetization_type == monetization_type)

    return query.distinct().all()


def get_films_by_country(
    session: Session, country_code: str, monetization_type: Optional[str] = None
) -> List[Film]:
    """
    Get all films available in a specific country.

    Args:
        session: Database session
        country_code: Country code (e.g., "US", "FR")
        monetization_type: Optional type filter (e.g., "flatrate")

    Returns:
        List of films
    """
    query = (
        session.query(Film)
        .join(StreamingOffer)
        .filter(StreamingOffer.country_code == country_code)
    )

    if monetization_type:
        query = query.filter(StreamingOffer.monetization_type == monetization_type)

    return query.distinct().all()


def get_streaming_offers(
    session: Session, film_id: int, eager_load: bool = False
) -> List[StreamingOffer]:
    """
    Get all streaming offers for a film.

    Args:
        session: Database session
        film_id: Film database ID
        eager_load: Whether to eager load the film relationship

    Returns:
        List of streaming offers
    """
    query = session.query(StreamingOffer).filter(StreamingOffer.film_id == film_id)

    if eager_load:
        query = query.options(joinedload(StreamingOffer.film))

    return query.all()


def delete_streaming_offers(session: Session, film_id: int) -> int:
    """
    Delete all streaming offers for a film.

    Args:
        session: Database session
        film_id: Film database ID

    Returns:
        Number of offers deleted
    """
    count = (
        session.query(StreamingOffer)
        .filter(StreamingOffer.film_id == film_id)
        .delete()
    )

    logger.debug(f"Deleted {count} streaming offers for film ID {film_id}")
    return count


def save_streaming_offers(
    session: Session, film_id: int, offers: List[dict], checked_at: Optional[datetime] = None
) -> int:
    """
    Save streaming offers for a film.

    Deletes existing offers and creates new ones.

    Args:
        session: Database session
        film_id: Film database ID
        offers: List of offer dictionaries
        checked_at: Timestamp for when offers were checked (defaults to now)

    Returns:
        Number of offers saved
    """
    # Delete existing offers
    delete_streaming_offers(session, film_id)

    # Create new offers
    if checked_at is None:
        checked_at = datetime.utcnow()

    for offer_data in offers:
        offer = StreamingOffer(
            film_id=film_id,
            country_code=offer_data["country_code"],
            country_name=offer_data.get("country_name", ""),
            provider_id=offer_data["provider_id"],
            provider_name=offer_data["provider_name"],
            monetization_type=offer_data["monetization_type"],
            streaming_url=offer_data.get("streaming_url"),
            logo_path=offer_data.get("logo_path"),
            display_priority=offer_data.get("display_priority"),
            checked_at=checked_at,
        )
        session.add(offer)

    session.flush()
    logger.debug(f"Saved {len(offers)} streaming offers for film ID {film_id}")

    return len(offers)


def get_database_stats(session: Session) -> dict:
    """
    Get statistics about the database.

    Args:
        session: Database session

    Returns:
        Dictionary with statistics
    """
    total_films = session.query(Film).count()
    watched_films = session.query(Film).filter(Film.watched == True).count()
    unwatched_films = total_films - watched_films

    films_with_tmdb = session.query(Film).filter(Film.tmdb_id.isnot(None)).count()
    total_offers = session.query(StreamingOffer).count()

    # Get unique providers and countries
    unique_providers = (
        session.query(func.count(func.distinct(StreamingOffer.provider_name)))
        .scalar()
        or 0
    )
    unique_countries = (
        session.query(func.count(func.distinct(StreamingOffer.country_code)))
        .scalar()
        or 0
    )

    # Get films that need refresh (stale)
    stale_films = len(get_stale_films(session, days=7))

    return {
        "total_films": total_films,
        "watched_films": watched_films,
        "unwatched_films": unwatched_films,
        "films_with_tmdb": films_with_tmdb,
        "match_rate": round(films_with_tmdb / total_films * 100, 1) if total_films > 0 else 0,
        "total_offers": total_offers,
        "unique_providers": unique_providers,
        "unique_countries": unique_countries,
        "stale_films": stale_films,
    }
