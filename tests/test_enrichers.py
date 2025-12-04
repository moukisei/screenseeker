"""
Tests for enrichers and related functionality.
"""

import pytest

from screenseeker.enrichers.base import BaseEnricher
from screenseeker.enrichers.enrichment_models import (
    EnrichmentResult,
    StreamingOffer,
    TMDBMovieInfo,
)
from screenseeker.enrichers.tmdb_enricher import TMDBEnricher


class TestBaseEnricher:
    """Test BaseEnricher class."""

    def test_base_enricher_has_abstract_method(self):
        """Test that BaseEnricher defines abstract enrich method."""
        assert hasattr(BaseEnricher, "enrich")

    def test_cannot_instantiate_base_enricher(self):
        """Test that BaseEnricher cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseEnricher()  # type: ignore[abstract]

    def test_concrete_enricher_must_implement_enrich(self):
        """Test that concrete enricher must implement enrich method."""
        # Try to create a concrete class without implementing enrich
        with pytest.raises(TypeError):

            class BadEnricher(BaseEnricher):
                pass

            BadEnricher()  # type: ignore[abstract]

    def test_base_enricher_has_context_manager_methods(self):
        """Test that BaseEnricher defines context manager methods."""
        assert hasattr(BaseEnricher, "__enter__")
        assert hasattr(BaseEnricher, "__exit__")


class TestTMDBEnricher:
    """Test TMDB enricher."""

    def test_tmdb_enricher_can_be_imported(self):
        """Test that TMDBEnricher can be imported."""
        assert TMDBEnricher is not None

    def test_tmdb_enricher_requires_api_key(self):
        """Test that TMDBEnricher requires API key."""
        # Should be able to instantiate with api_key
        enricher = TMDBEnricher(api_key="test_key")
        assert enricher.api_key == "test_key"


class TestEnrichmentModels:
    """Test enrichment result models."""

    def test_streaming_offer_model(self):
        """Test creating a StreamingOffer model."""
        offer = StreamingOffer(
            country_code="US",
            country_name="United States",
            provider_id=8,
            provider_name="Netflix",
            offer_type="flatrate",
        )

        assert offer.country_code == "US"
        assert offer.provider_name == "Netflix"

    def test_tmdb_movie_info(self):
        """Test creating TMDBMovieInfo model."""
        movie = TMDBMovieInfo(
            tmdb_id=123,
            title="Test",
            original_title="Test",
            year=2020,
            release_date="2020-01-01",
            overview="Overview",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.0,
            popularity=100.0,
            query_title="Test",
        )

        assert movie.tmdb_id == 123
        assert movie.title == "Test"

    def test_enrichment_result(self):
        """Test creating EnrichmentResult."""
        movie = TMDBMovieInfo(
            tmdb_id=123,
            title="Test",
            original_title="Test",
            year=2020,
            release_date="2020-01-01",
            overview="Overview",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.0,
            popularity=100.0,
            query_title="Test",
        )

        result = EnrichmentResult(
            success=True,
            tmdb_movie=movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="Test",
        )

        assert result.success is True
        assert result.tmdb_movie.tmdb_id == 123

    def test_enrichment_result_failure(self):
        """Test creating failed enrichment result."""
        result = EnrichmentResult(
            success=False,
            tmdb_movie=None,
            streaming_offers=[],
            match_confidence="none",
            error_message="Not found",
            query_title="Unknown Movie",
        )

        assert result.success is False
        assert result.error_message == "Not found"
        assert result.tmdb_movie is None


class TestEnricherInit:
    """Test enricher package initialization."""

    def test_enricher_imports(self):
        """Test that enricher classes can be imported from package."""
        from screenseeker.enrichers import BaseEnricher, TMDBEnricher, WatchStrategyAnalyzer

        assert BaseEnricher is not None
        assert TMDBEnricher is not None
        assert WatchStrategyAnalyzer is not None
