from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StreamingOffer(BaseModel):
    """Represents a streaming availability offer for a film in a specific country."""

    country_code: str = Field(..., description="ISO 3166-1 alpha-2 country code (e.g., 'US', 'FR')")
    country_name: str = Field(
        ..., description="Full country name (e.g., 'United States', 'France')"
    )
    provider_id: int = Field(..., description="TMDB provider ID")
    provider_name: str = Field(
        ..., description="Streaming provider name (e.g., 'Netflix', 'Disney Plus')"
    )
    offer_type: str = Field(
        ..., description="Type of offer: 'flatrate', 'rent', 'buy', 'free', 'ads'"
    )

    # Optional fields that may not always be available
    streaming_url: Optional[str] = Field(
        None, description="Deep link to the content on the provider"
    )
    logo_path: Optional[str] = Field(None, description="TMDB logo path for the provider")
    display_priority: Optional[int] = Field(None, description="Display priority for the provider")

    class Config:
        frozen = True


class TMDBMovieInfo(BaseModel):
    """Basic movie information from TMDB."""

    tmdb_id: int = Field(..., description="TMDB movie ID")
    title: str = Field(..., description="Movie title")
    original_title: str = Field(..., description="Original movie title")
    release_date: Optional[str] = Field(None, description="Release date (YYYY-MM-DD)")
    year: Optional[int] = Field(None, description="Release year")
    overview: Optional[str] = Field(None, description="Movie overview/description")
    original_language: str = Field(..., description="ISO 639-1 language code")
    poster_path: Optional[str] = Field(None, description="TMDB poster path")
    backdrop_path: Optional[str] = Field(None, description="TMDB backdrop path")
    vote_average: Optional[float] = Field(None, description="TMDB vote average")
    popularity: Optional[float] = Field(None, description="TMDB popularity score")


class EnrichmentResult(BaseModel):
    """Result of enriching a film with streaming availability data."""

    # Input information
    query_title: str = Field(..., description="Title used for search")
    query_year: Optional[int] = Field(None, description="Year used for search")

    # TMDB match information
    tmdb_movie: Optional[TMDBMovieInfo] = Field(None, description="Matched TMDB movie information")
    match_confidence: str = Field(
        ..., description="Confidence level: 'exact', 'high', 'medium', 'low', 'none'"
    )

    # Streaming availability
    streaming_offers: list[StreamingOffer] = Field(
        default_factory=list, description="List of streaming offers"
    )
    total_countries: int = Field(
        default=0, description="Number of countries where film is available"
    )
    total_providers: int = Field(
        default=0, description="Number of unique providers across all countries"
    )

    # Metadata
    enriched_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Timestamp of enrichment",
    )
    success: bool = Field(default=True, description="Whether enrichment was successful")
    error_message: Optional[str] = Field(None, description="Error message if enrichment failed")

    @property
    def available_countries(self) -> list[str]:
        """Get list of unique country codes where film is available."""
        return sorted({offer.country_code for offer in self.streaming_offers})

    @property
    def available_providers(self) -> list[str]:
        """Get list of unique provider names across all countries."""
        return sorted({offer.provider_name for offer in self.streaming_offers})

    def offers_by_country(self, country_code: str) -> list[StreamingOffer]:
        """Get all offers for a specific country."""
        return [offer for offer in self.streaming_offers if offer.country_code == country_code]

    def offers_by_provider(self, provider_name: str) -> list[StreamingOffer]:
        """Get all offers for a specific provider across all countries."""
        return [offer for offer in self.streaming_offers if offer.provider_name == provider_name]

    def offers_by_type(self, offer_type: str) -> list[StreamingOffer]:
        """Get all offers of a specific type (flatrate, rent, buy, etc.)."""
        return [offer for offer in self.streaming_offers if offer.offer_type == offer_type]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "query": {"title": self.query_title, "year": self.query_year},
            "tmdb_match": self.tmdb_movie.model_dump() if self.tmdb_movie else None,
            "match_confidence": self.match_confidence,
            "availability_summary": {
                "total_countries": self.total_countries,
                "total_providers": self.total_providers,
                "countries": self.available_countries,
                "providers": self.available_providers,
            },
            "streaming_offers": [offer.model_dump() for offer in self.streaming_offers],
            "metadata": {
                "enriched_at": self.enriched_at,
                "success": self.success,
                "error_message": self.error_message,
            },
        }
