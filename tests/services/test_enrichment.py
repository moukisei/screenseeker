"""
Tests for TMDB enrichment and the write path behind it.

These moved here with the code, from tests/database/test_database.py: fetching
a film and persisting the result was a second service layer under services/,
and the database package now holds only models, engine and session.
"""

from datetime import UTC, datetime, timedelta

from screenseeker.database.models import StreamingOffer
from screenseeker.enrichers.enrichment_models import EnrichmentResult
from screenseeker.enrichers.enrichment_models import StreamingOffer as StreamingOfferPydantic
from screenseeker.enrichers.enrichment_models import TMDBMovieInfo
from screenseeker.services.enrichment import (
    create_film_from_enrichment,
    enrich_and_save_film,
    needs_refresh,
    save_streaming_offers,
    update_film_from_enrichment,
)
from screenseeker.services.library import get_or_create_film


def create_test_tmdb_movie(tmdb_id=123, title="Test Movie", year=2020):
    """Helper to create a valid TMDBMovieInfo for testing."""
    return TMDBMovieInfo(
        tmdb_id=tmdb_id,
        title=title,
        original_title=title,
        year=year,
        release_date=f"{year}-01-15",
        overview="Test overview",
        original_language="en",
        poster_path="/test.jpg",
        backdrop_path=None,
        vote_average=8.5,
        popularity=100.0,
    )


def offers_for(session, film_id):
    return session.query(StreamingOffer).filter(StreamingOffer.film_id == film_id).all()


class TestNeedsRefresh:
    """Tests for needs_refresh function."""

    def test_needs_refresh_when_never_checked(self, test_session):
        """Test that film needs refresh when never checked."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        film.last_checked = None
        test_session.commit()

        assert needs_refresh(film) is True

    def test_needs_refresh_when_stale(self, test_session):
        """Test that film needs refresh when data is old."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        film.last_checked = datetime.now(UTC) - timedelta(days=10)
        test_session.commit()

        assert needs_refresh(film, days=7) is True

    def test_no_refresh_when_fresh(self, test_session):
        """Test that film doesn't need refresh when data is fresh."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        film.last_checked = datetime.now(UTC)
        test_session.commit()

        assert needs_refresh(film, days=7) is False


class TestCreateFilmFromEnrichment:
    """Tests for create_film_from_enrichment function."""

    def test_creates_film_with_tmdb_data(self, test_session):
        """Test creating a new film from enrichment data."""
        tmdb_movie = create_test_tmdb_movie()
        offers = [
            StreamingOfferPydantic(
                country_code="US",
                country_name="United States",
                provider_id=8,
                provider_name="Netflix",
                offer_type="flatrate",
            )
        ]

        enrichment = EnrichmentResult(
            query_title="Test Movie",
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=offers,
            match_confidence="exact",
            error_message=None,
        )

        film = create_film_from_enrichment(test_session, "Test Movie", 2020, enrichment)

        assert film.letterboxd_title == "Test Movie"
        assert film.letterboxd_year == 2020
        assert film.tmdb_id == 123
        assert film.match_confidence == "exact"

    def test_creates_film_with_year_mismatch(self, test_session):
        """Test creating film when years don't match."""
        tmdb_movie = create_test_tmdb_movie(year=2021)

        enrichment = EnrichmentResult(
            query_title="Test Movie",
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=[],
            match_confidence="fuzzy",
            error_message=None,
        )

        film = create_film_from_enrichment(test_session, "Test Movie", 2020, enrichment)

        assert film.letterboxd_year == 2020
        assert film.tmdb_year == 2021
        assert film.year_mismatch is True


class TestUpdateFilmFromEnrichment:
    """Tests for update_film_from_enrichment function."""

    def test_updates_existing_film(self, test_session):
        """Test updating an existing film with new enrichment data."""
        film, _ = get_or_create_film(test_session, "Old Title", 2020)
        test_session.commit()

        tmdb_movie = create_test_tmdb_movie(tmdb_id=456, title="New Title")
        enrichment = EnrichmentResult(
            query_title="Test Movie",
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
        )

        updated_film = update_film_from_enrichment(test_session, film, enrichment)

        assert updated_film.tmdb_id == 456
        assert updated_film.tmdb_title == "New Title"
        assert updated_film.match_confidence == "exact"

    def test_detects_duplicate_tmdb_id(self, test_session):
        """Test that duplicate TMDB IDs are detected and handled."""
        film1, _ = get_or_create_film(test_session, "Film 1", 2020)
        film1.tmdb_id = 999
        test_session.commit()

        film2, _ = get_or_create_film(test_session, "Film 2", 2020)
        test_session.commit()

        tmdb_movie = create_test_tmdb_movie(tmdb_id=999)
        enrichment = EnrichmentResult(
            query_title="Test Movie",
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
        )

        updated_film = update_film_from_enrichment(test_session, film2, enrichment)

        assert updated_film.tmdb_id is None
        assert updated_film.match_confidence == "duplicate"


class TestEnrichAndSaveFilm:
    """Tests for enrich_and_save_film function."""

    def test_enrich_and_save_new_film(self, test_session):
        """Test enriching and saving a new film."""
        from unittest.mock import MagicMock

        # Create mock enricher
        mock_enricher = MagicMock()
        tmdb_movie = create_test_tmdb_movie(tmdb_id=123, title="The Matrix")
        enrichment = EnrichmentResult(
            query_title="The Matrix",
            query_year=1999,
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
        )
        mock_enricher.enrich.return_value = enrichment

        film, result = enrich_and_save_film(test_session, mock_enricher, "The Matrix", 1999)

        assert film is not None
        assert film.tmdb_id == 123
        assert result.success is True
        mock_enricher.enrich.assert_called_once_with("The Matrix", 1999, fuzzy_year=True)

    def test_enrich_and_save_existing_film_no_refresh(self, test_session):
        """Test enriching existing film without refresh."""
        from unittest.mock import MagicMock

        # Create existing film
        existing_film, _ = get_or_create_film(test_session, "The Matrix", 1999)
        existing_film.tmdb_id = 123
        existing_film.last_checked = datetime.now(UTC)
        test_session.commit()

        # Create mock enricher
        mock_enricher = MagicMock()
        tmdb_movie = create_test_tmdb_movie(tmdb_id=123, title="The Matrix")
        enrichment = EnrichmentResult(
            query_title="The Matrix",
            query_year=1999,
            success=True,
            tmdb_movie=tmdb_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
        )
        mock_enricher.enrich.return_value = enrichment

        film, result = enrich_and_save_film(
            test_session, mock_enricher, "The Matrix", 1999, force_refresh=False
        )

        assert film.id == existing_film.id

    def test_enrich_and_save_failed_enrichment(self, test_session):
        """Test enriching when TMDB enrichment fails."""
        from unittest.mock import MagicMock

        # Create mock enricher that returns failed enrichment
        mock_enricher = MagicMock()
        enrichment = EnrichmentResult(
            query_title="Unknown Movie",
            query_year=None,
            success=False,
            tmdb_movie=None,
            streaming_offers=[],
            match_confidence="none",
            error_message="Not found",
        )
        mock_enricher.enrich.return_value = enrichment

        film, result = enrich_and_save_film(test_session, mock_enricher, "Unknown Movie", None)

        assert film is not None
        assert film.match_confidence == "none"
        assert result.success is False


class TestSaveStreamingOffers:
    """Test save_streaming_offers function."""

    def test_saves_multiple_offers(self, test_session):
        """Test saving multiple streaming offers."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        offers_data = [
            {
                "country_code": "US",
                "country_name": "United States",
                "provider_id": 8,
                "provider_name": "Netflix",
                "monetization_type": "flatrate",
            },
            {
                "country_code": "US",
                "country_name": "United States",
                "provider_id": 9,
                "provider_name": "Amazon",
                "monetization_type": "flatrate",
            },
        ]

        save_streaming_offers(test_session, film.id, offers_data, checked_at=datetime.now(UTC))

        offers = offers_for(test_session, film.id)
        assert len(offers) == 2
