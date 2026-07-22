"""
Return types for the service layer.

These are the contract between the use cases and whatever renders them - the
CLI today, the web layer next. They hold no ORM instances so they stay valid
after the database session closes.
"""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..database.models import Film
from ..enrichers.enrichment_models import EnrichmentResult
from ..enrichers.watch_strategy import WatchStrategy


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

    @classmethod
    def from_film(cls, film: Film, *, offer_count: Optional[int] = None) -> "FilmSummary":
        """
        Build from an ORM row. Must be called while the session is open.

        Pass offer_count explicitly to avoid lazy-loading the relationship per
        row; omitting it reads film.streaming_offers.
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
