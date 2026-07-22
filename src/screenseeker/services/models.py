"""
Return types for the service layer.

These are the contract between the use cases and whatever renders them - the
CLI today, the web layer next. They hold no ORM instances so they stay valid
after the database session closes.
"""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import settings
from ..database.models import Film
from ..database.models import StreamingOffer as OfferRow
from ..enrichers.enrichment_models import EnrichmentResult
from ..enrichers.watch_strategy import WatchStrategy


def poster_url(poster_path: Optional[str], size: str = settings.TMDB_POSTER_SIZE) -> Optional[str]:
    """Turn a stored TMDB path into a full image URL."""
    if not poster_path:
        return None
    return f"{settings.TMDB_IMAGE_BASE}/{size}{poster_path}"


def logo_url(logo_path: Optional[str], size: str = settings.TMDB_LOGO_SIZE) -> Optional[str]:
    """Turn a stored TMDB provider logo path into a full image URL."""
    if not logo_path:
        return None
    return f"{settings.TMDB_IMAGE_BASE}/{size}{logo_path}"


class OfferOut(BaseModel):
    """
    A streaming offer as the UI consumes it.

    This is the only place the `monetization_type` column is translated to the
    `offer_type` name used everywhere above the database. Do not map it at a
    call site.
    """

    model_config = ConfigDict(frozen=True)

    country_code: str
    country_name: str
    provider_id: int
    provider_name: str
    offer_type: str = Field(..., description="flatrate / rent / buy / free / ads")

    streaming_url: Optional[str] = None
    logo_path: Optional[str] = Field(None, description="TMDB path, not a full URL")
    display_priority: Optional[int] = None

    @property
    def logo(self) -> Optional[str]:
        """Full URL for the provider logo."""
        return logo_url(self.logo_path)

    @classmethod
    def from_row(cls, offer: OfferRow) -> "OfferOut":
        """Build from an ORM row. Must be called while the session is open."""
        return cls(
            country_code=offer.country_code,
            country_name=offer.country_name,
            provider_id=offer.provider_id,
            provider_name=offer.provider_name,
            offer_type=offer.monetization_type,
            streaming_url=offer.streaming_url,
            logo_path=offer.logo_path,
            display_priority=offer.display_priority,
        )


class FilmSummary(BaseModel):
    """A film as it appears in a list. Holds no ORM state."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str = Field(..., description="Best display title")
    year: Optional[int] = None
    full_title: str = Field(..., description="Title with year when known")

    tmdb_id: Optional[int] = None
    poster_path: Optional[str] = Field(None, description="TMDB path, not a full URL")
    vote_average: Optional[float] = None
    match_confidence: Optional[str] = None

    # Both years are kept so a mismatch can be shown, not just flagged.
    letterboxd_year: Optional[int] = None
    tmdb_year: Optional[int] = None
    year_mismatch: bool = False

    watched: bool = False
    watched_at: Optional[datetime] = None

    offer_count: int = Field(default=0, description="Persisted offers; 0 if not loaded")
    last_checked: Optional[datetime] = None
    cache_age_days: Optional[int] = None

    @property
    def poster(self) -> Optional[str]:
        """Full URL for the poster image."""
        return poster_url(self.poster_path)

    @property
    def is_stale(self) -> bool:
        """True when the streaming data has aged past the cache TTL."""
        return self.cache_age_days is None or self.cache_age_days > settings.CACHE_TTL_DAYS

    @classmethod
    def from_film(cls, film: Film, *, offer_count: Optional[int] = None) -> "FilmSummary":
        """
        Build from an ORM row. Must be called while the session is open.

        Always pass offer_count in a list context. Omitting it reads
        film.streaming_offers, which lazy-loads once per row - 182 queries for
        a 181-film library.
        """
        last_checked = film.last_checked
        age_days = None
        if last_checked is not None:
            aware = last_checked if last_checked.tzinfo else last_checked.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - aware).days

        return cls(
            id=film.id,
            title=film.display_title,
            year=film.display_year,
            full_title=film.full_title,
            tmdb_id=film.tmdb_id,
            poster_path=film.poster_path,
            vote_average=film.vote_average,
            match_confidence=film.match_confidence,
            letterboxd_year=film.letterboxd_year,
            tmdb_year=film.tmdb_year,
            year_mismatch=bool(film.year_mismatch),
            watched=bool(film.watched),
            watched_at=film.watched_at,
            offer_count=offer_count if offer_count is not None else len(film.streaming_offers),
            last_checked=last_checked,
            cache_age_days=age_days,
        )


class FilmDetail(FilmSummary):
    """A single film with its streaming offers, for the detail page."""

    overview: Optional[str] = None
    tmdb_release_date: Optional[str] = None
    date_added: Optional[datetime] = None
    notes: Optional[str] = None

    offers: list[OfferOut] = Field(default_factory=list)

    @property
    def countries(self) -> list[str]:
        """Distinct country codes, sorted."""
        return sorted({o.country_code for o in self.offers})

    @property
    def providers(self) -> list[str]:
        """Distinct provider names, sorted."""
        return sorted({o.provider_name for o in self.offers})

    def offers_in(self, country_code: str) -> list[OfferOut]:
        """Offers for one country."""
        return [o for o in self.offers if o.country_code == country_code]

    @classmethod
    def from_film(cls, film: Film, *, offer_count: Optional[int] = None) -> "FilmDetail":
        """
        Build from an ORM row with its offers loaded.

        The caller is responsible for eager-loading film.streaming_offers;
        this reads the relationship.
        """
        offers = [OfferOut.from_row(row) for row in film.streaming_offers]
        summary = FilmSummary.from_film(film, offer_count=len(offers))

        return cls(
            **summary.model_dump(),
            overview=film.overview,
            tmdb_release_date=film.tmdb_release_date,
            date_added=film.date_added,
            notes=film.notes,
            offers=offers,
        )


class WatchResult(BaseModel):
    """Everything needed to answer "where can I watch this?"."""

    model_config = ConfigDict(frozen=True)

    film_id: Optional[int] = Field(None, description="Database id, None if nothing was persisted")
    query_title: str = Field(..., description="Title the caller asked for")
    query_year: Optional[int] = Field(None, description="Year the caller asked for")

    enrichment: EnrichmentResult = Field(..., description="TMDB data, live or from cache")
    strategy: WatchStrategy = Field(..., description="Personalised ranking of the offers")

    from_cache: bool = Field(..., description="True when no TMDB request was made")
    cache_age_seconds: Optional[float] = Field(
        None, description="Age of the persisted data, None if never checked"
    )

    year_mismatch: bool = Field(default=False, description="Letterboxd year differs from TMDB")
    letterboxd_year: Optional[int] = Field(None, description="Year as recorded by Letterboxd")
    tmdb_year: Optional[int] = Field(None, description="Year according to TMDB")

    @property
    def found(self) -> bool:
        """Whether TMDB matched the query to a film at all."""
        return self.enrichment.success and self.enrichment.tmdb_movie is not None
