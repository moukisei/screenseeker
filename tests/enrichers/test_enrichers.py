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

    def test_tmdb_enricher_empty_api_key_raises_error(self):
        """Test that empty API key raises ValueError."""
        with pytest.raises(ValueError, match="TMDB API key is required"):
            TMDBEnricher(api_key="")

    def test_tmdb_enricher_init_sets_defaults(self):
        """Test that TMDBEnricher sets default values."""
        enricher = TMDBEnricher(api_key="test_key")
        assert enricher.api_key == "test_key"
        assert enricher.base_url == "https://api.themoviedb.org/3"
        assert enricher.language == "en-US"
        assert enricher.session is not None

    def test_tmdb_enricher_custom_rate_limit(self):
        """Test TMDBEnricher with custom rate limit."""
        enricher = TMDBEnricher(api_key="test_key", rate_limit_per_second=10.0)
        assert enricher.rate_limit_delay == 0.1  # 1.0 / 10.0

    def test_tmdb_enricher_custom_language(self):
        """Test TMDBEnricher with custom language."""
        enricher = TMDBEnricher(api_key="test_key", language="fr-FR")
        assert enricher.language == "fr-FR"

    def test_tmdb_enricher_country_names_mapping(self):
        """Test that country names mapping is available."""
        assert TMDBEnricher.COUNTRY_NAMES["US"] == "United States"
        assert TMDBEnricher.COUNTRY_NAMES["FR"] == "France"
        assert TMDBEnricher.COUNTRY_NAMES["GB"] == "United Kingdom"

    def test_tmdb_enricher_offer_type_names(self):
        """Test that offer type names mapping is available."""
        assert TMDBEnricher.OFFER_TYPE_NAMES["flatrate"] == "Streaming (Subscription)"
        assert TMDBEnricher.OFFER_TYPE_NAMES["rent"] == "Rent"
        assert TMDBEnricher.OFFER_TYPE_NAMES["buy"] == "Buy"

    def test_tmdb_enricher_calculate_match_confidence_exact(self):
        """Test exact match confidence calculation."""
        enricher = TMDBEnricher(api_key="test_key")
        confidence = enricher._calculate_match_confidence("The Matrix", 1999, "The Matrix", 1999)
        assert confidence == "exact"

    def test_tmdb_enricher_calculate_match_confidence_high(self):
        """Test high match confidence calculation."""
        enricher = TMDBEnricher(api_key="test_key")
        # Same title, different year
        confidence = enricher._calculate_match_confidence("The Matrix", 1999, "The Matrix", 2000)
        assert confidence == "high"

    def test_tmdb_enricher_calculate_match_confidence_medium(self):
        """Test medium match confidence calculation."""
        enricher = TMDBEnricher(api_key="test_key")
        # Partial title match
        confidence = enricher._calculate_match_confidence("Matrix", 1999, "The Matrix", 2000)
        assert confidence == "medium"

    def test_tmdb_enricher_calculate_match_confidence_low(self):
        """Test low match confidence calculation."""
        enricher = TMDBEnricher(api_key="test_key")
        # Different titles
        confidence = enricher._calculate_match_confidence("The Matrix", 1999, "Inception", 2010)
        assert confidence == "low"

    def test_tmdb_enricher_calculate_match_confidence_no_year(self):
        """Test match confidence with no query year."""
        enricher = TMDBEnricher(api_key="test_key")
        confidence = enricher._calculate_match_confidence("The Matrix", None, "The Matrix", 1999)
        assert confidence == "exact"

    def test_tmdb_enricher_parse_tmdb_movie(self):
        """Test parsing TMDB movie data."""
        enricher = TMDBEnricher(api_key="test_key")
        movie_data = {
            "id": 603,
            "title": "The Matrix",
            "original_title": "The Matrix",
            "release_date": "1999-03-31",
            "overview": "A computer hacker learns...",
            "original_language": "en",
            "poster_path": "/test.jpg",
            "backdrop_path": "/backdrop.jpg",
            "vote_average": 8.7,
            "popularity": 100.0,
        }

        movie_info = enricher._parse_tmdb_movie(movie_data)

        assert movie_info.tmdb_id == 603
        assert movie_info.title == "The Matrix"
        assert movie_info.year == 1999
        assert movie_info.vote_average == 8.7

    def test_tmdb_enricher_parse_tmdb_movie_reads_runtime(self):
        """Runtime rides in on the details endpoint, absent from search."""
        enricher = TMDBEnricher(api_key="test_key")

        with_runtime = enricher._parse_tmdb_movie({"id": 603, "title": "X", "runtime": 136})
        assert with_runtime.runtime == 136

        # A search result carries no runtime; the field stays None.
        from_search = enricher._parse_tmdb_movie({"id": 603, "title": "X"})
        assert from_search.runtime is None

    def test_tmdb_enricher_enrich_folds_runtime_and_providers_into_one_call(self, monkeypatch):
        """
        enrich() takes runtime and providers from a single details request
        (append_to_response), not a separate providers call.
        """
        enricher = TMDBEnricher(api_key="test_key")
        calls = []

        def fake_request(endpoint, params=None):
            calls.append((endpoint, params))
            if endpoint == "/search/movie":
                return {
                    "results": [{"id": 603, "title": "The Matrix", "release_date": "1999-03-31"}]
                }
            if endpoint == "/movie/603":
                return {
                    "id": 603,
                    "title": "The Matrix",
                    "release_date": "1999-03-31",
                    "runtime": 136,
                    "watch/providers": {"results": {}},
                }
            raise AssertionError(f"unexpected endpoint {endpoint}")

        monkeypatch.setattr(enricher, "_make_request", fake_request)

        result = enricher.enrich("The Matrix", 1999, fuzzy_year=False)

        assert result.success
        assert result.tmdb_movie.runtime == 136
        # The details call asks for providers to be appended - no separate fetch.
        detail_call = next(c for c in calls if c[0] == "/movie/603")
        assert detail_call[1] == {"append_to_response": "watch/providers"}
        assert not any(c[0].endswith("/watch/providers") for c in calls)

    def test_tmdb_enricher_parse_tmdb_movie_no_release_date(self):
        """Test parsing TMDB movie data without release date."""
        enricher = TMDBEnricher(api_key="test_key")
        movie_data = {
            "id": 603,
            "title": "The Matrix",
            "original_title": "The Matrix",
        }

        movie_info = enricher._parse_tmdb_movie(movie_data)

        assert movie_info.tmdb_id == 603
        assert movie_info.year is None
        assert movie_info.release_date is None

    def test_tmdb_enricher_parse_streaming_offers(self):
        """Test parsing streaming offers."""
        enricher = TMDBEnricher(api_key="test_key")
        providers_data = {
            "US": {
                "link": "https://www.themoviedb.org/movie/603/watch?locale=US",
                "flatrate": [
                    {
                        "provider_id": 8,
                        "provider_name": "Netflix",
                        "logo_path": "/test.jpg",
                        "display_priority": 1,
                    }
                ],
                "rent": [
                    {
                        "provider_id": 3,
                        "provider_name": "Amazon Video",
                        "logo_path": "/amazon.jpg",
                        "display_priority": 2,
                    }
                ],
            },
            "FR": {
                "flatrate": [
                    {
                        "provider_id": 119,
                        "provider_name": "Canal+",
                        "logo_path": "/canal.jpg",
                        "display_priority": 1,
                    }
                ],
            },
        }

        offers = enricher._parse_streaming_offers(providers_data)

        assert len(offers) == 3
        assert any(o.provider_name == "Netflix" and o.country_code == "US" for o in offers)
        assert any(o.provider_name == "Canal+" and o.country_code == "FR" for o in offers)
        assert any(o.offer_type == "rent" for o in offers)

        # The country link rides along on every offer in that country, and a
        # country without one leaves it null rather than borrowing another's.
        us = next(o for o in offers if o.country_code == "US")
        fr = next(o for o in offers if o.country_code == "FR")
        assert us.streaming_url == "https://www.themoviedb.org/movie/603/watch?locale=US"
        assert fr.streaming_url is None

    def test_tmdb_enricher_parse_streaming_offers_empty(self):
        """Test parsing empty streaming offers."""
        enricher = TMDBEnricher(api_key="test_key")
        offers = enricher._parse_streaming_offers({})
        assert len(offers) == 0

    def test_tmdb_enricher_context_manager(self):
        """Test TMDBEnricher works as context manager."""
        with TMDBEnricher(api_key="test_key") as enricher:
            assert enricher.api_key == "test_key"
            assert enricher.session is not None

    @pytest.mark.parametrize(
        "country_code,expected_name",
        [
            ("US", "United States"),
            ("FR", "France"),
            ("GB", "United Kingdom"),
            ("JP", "Japan"),
            ("XX", "XX"),  # Unknown country should return code
        ],
    )
    def test_tmdb_enricher_country_name_lookup(self, country_code, expected_name):
        """Test country name lookup."""
        enricher = TMDBEnricher(api_key="test_key")
        country_name = enricher.COUNTRY_NAMES.get(country_code, country_code)
        assert country_name == expected_name


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
