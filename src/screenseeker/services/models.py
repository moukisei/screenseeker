"""
Return types for the service layer.

These are the contract between the use cases and whatever renders them - the
CLI today, the web layer next. They hold no ORM instances so they stay valid
after the database session closes.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..enrichers.enrichment_models import EnrichmentResult
from ..enrichers.watch_strategy import WatchStrategy


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
