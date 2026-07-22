"""
Tests for all database functionality: models, queries, service, session, and init.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from screenseeker.database.models import Film
from screenseeker.database.queries import (
    delete_streaming_offers,
    get_database_stats,
    get_film_by_title_year,
    get_film_by_tmdb_id,
    get_films_by_country,
    get_films_by_provider,
    get_or_create_film,
    get_stale_films,
    get_streaming_offers,
    get_unwatched_films,
    mark_film_watched,
    save_streaming_offers,
    search_films_by_title,
)
from screenseeker.database.service import (
    convert_db_offers_to_pydantic,
    create_film_from_enrichment,
    enrich_and_save_film,
    get_film_with_offers,
    needs_refresh,
    update_film_from_enrichment,
)
from screenseeker.database.session import (
    DATABASE_DIR,
    DATABASE_PATH,
    DATABASE_URL,
    SessionLocal,
    engine,
    get_database_info,
    get_session,
    init_db,
    reset_database,
)
from screenseeker.enrichers.enrichment_models import (
    EnrichmentResult,
)
from screenseeker.enrichers.enrichment_models import StreamingOffer as StreamingOfferPydantic
from screenseeker.enrichers.enrichment_models import (
    TMDBMovieInfo,
)


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
        query_title=title,
    )


# =============================================================================
# Database Queries Tests
# =============================================================================


class TestGetOrCreateFilm:
    """Test get_or_create_film function."""

    def test_creates_new_film(self, test_session):
        """Test creating a new film."""
        film, created = get_or_create_film(test_session, "New Film", 2023)

        assert created is True
        assert film.letterboxd_title == "New Film"
        assert film.letterboxd_year == 2023

    def test_returns_existing_film(self, test_session):
        """Test returning an existing film."""
        film1, _ = get_or_create_film(test_session, "Existing Film", 2022)
        film2, created = get_or_create_film(test_session, "Existing Film", 2022)

        assert created is False
        assert film1.id == film2.id

    def test_handles_films_without_year(self, test_session):
        """Test handling films without a year."""
        film, created = get_or_create_film(test_session, "No Year Film", None)

        assert created is True
        assert film.letterboxd_title == "No Year Film"
        assert film.letterboxd_year is None


class TestGetFilmByTitleYear:
    """Test get_film_by_title_year function."""

    def test_finds_film_with_year(self, test_session):
        """Test finding a film with a year."""
        created_film, _ = get_or_create_film(test_session, "Test Film", 2021)

        found_film = get_film_by_title_year(test_session, "Test Film", 2021)

        assert found_film is not None
        assert found_film.id == created_film.id

    def test_returns_none_for_nonexistent_film(self, test_session):
        """Test returning None for nonexistent film."""
        found_film = get_film_by_title_year(test_session, "Nonexistent", 2021)

        assert found_film is None

    def test_finds_film_without_year(self, test_session):
        """Test finding a film without a year."""
        created_film, _ = get_or_create_film(test_session, "No Year", None)

        found_film = get_film_by_title_year(test_session, "No Year", None)

        assert found_film is not None
        assert found_film.id == created_film.id


class TestSearchFilmsByTitle:
    """Test search_films_by_title function."""

    def test_partial_match(self, test_session):
        """Test partial title matching."""
        get_or_create_film(test_session, "The Matrix", 1999)
        get_or_create_film(test_session, "The Matrix Reloaded", 2003)

        results = search_films_by_title(test_session, "Matrix")

        assert len(results) == 2

    def test_case_insensitive(self, test_session):
        """Test case-insensitive search."""
        get_or_create_film(test_session, "Inception", 2010)

        results = search_films_by_title(test_session, "INCEPTION")

        assert len(results) == 1

    def test_respects_limit(self, test_session):
        """Test that limit parameter is respected."""
        for i in range(5):
            get_or_create_film(test_session, f"Film {i}", 2020)

        results = search_films_by_title(test_session, "Film", limit=3)

        assert len(results) == 3


class TestGetUnwatchedFilms:
    """Test get_unwatched_films function."""

    def test_returns_only_unwatched(self, test_session):
        """Test that only unwatched films are returned."""
        film1, _ = get_or_create_film(test_session, "Unwatched", 2020)
        film2, _ = get_or_create_film(test_session, "Watched", 2020)

        film2.watched = True
        film2.watched_at = datetime.now(UTC)
        test_session.commit()

        unwatched = get_unwatched_films(test_session)

        assert film1 in unwatched
        assert film2 not in unwatched


class TestMarkFilmWatched:
    """Test mark_film_watched function."""

    def test_marks_film_as_watched(self, test_session):
        """Test marking a film as watched."""
        film, _ = get_or_create_film(test_session, "To Watch", 2020)
        test_session.commit()

        updated_film = mark_film_watched(test_session, film.id, watched=True)

        assert updated_film.watched is True
        assert updated_film.watched_at is not None

    def test_marks_film_as_unwatched(self, test_session):
        """Test marking a film as unwatched."""
        film, _ = get_or_create_film(test_session, "Watched", 2020)
        film.watched = True
        film.watched_at = datetime.now(UTC)
        test_session.commit()

        updated_film = mark_film_watched(test_session, film.id, watched=False)

        assert updated_film.watched is False
        assert updated_film.watched_at is None


class TestGetStaleFilms:
    """Test get_stale_films function."""

    def test_finds_stale_films(self, test_session):
        """Test finding stale films."""
        fresh_film, _ = get_or_create_film(test_session, "Fresh", 2020)
        stale_film, _ = get_or_create_film(test_session, "Stale", 2020)

        fresh_film.last_checked = datetime.now(UTC)
        stale_film.last_checked = datetime.now(UTC) - timedelta(days=10)
        test_session.commit()

        stale = get_stale_films(test_session, days=7)

        assert stale_film in stale
        assert fresh_film not in stale


class TestGetFilmsByProvider:
    """Test get_films_by_provider function."""

    def test_filters_by_provider(self, test_session):
        """Test filtering films by provider."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        save_streaming_offers(
            test_session,
            film.id,
            [
                {
                    "country_code": "US",
                    "country_name": "United States",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "monetization_type": "flatrate",
                }
            ],
            checked_at=datetime.now(UTC),
        )

        results = get_films_by_provider(test_session, "Netflix")
        assert len(results) >= 1
        assert film in results

    def test_filters_by_country(self, test_session):
        """Test filtering films by country."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        save_streaming_offers(
            test_session,
            film.id,
            [
                {
                    "country_code": "US",
                    "country_name": "United States",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "monetization_type": "flatrate",
                }
            ],
            checked_at=datetime.now(UTC),
        )

        results = get_films_by_provider(test_session, "Netflix", country_code="US")
        assert len(results) >= 1
        assert film in results


class TestGetDatabaseStats:
    """Test get_database_stats function."""

    def test_calculates_stats_correctly(self, test_session):
        """Test that stats are calculated correctly."""
        film1, _ = get_or_create_film(test_session, "Film1", 2020)
        film2, _ = get_or_create_film(test_session, "Film2", 2020)

        film1.tmdb_id = 123
        film1.last_checked = datetime.now(UTC) - timedelta(days=10)
        test_session.commit()

        stats = get_database_stats(test_session)

        assert stats["total_films"] == 2
        assert stats["films_with_tmdb"] == 1
        assert stats["stale_films"] >= 1


class TestGetFilmByTMDBId:
    """Test get_film_by_tmdb_id function."""

    def test_finds_film_by_tmdb_id(self, test_session):
        """Test finding a film by TMDB ID."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        film.tmdb_id = 999
        test_session.commit()

        found = get_film_by_tmdb_id(test_session, 999)

        assert found is not None
        assert found.id == film.id

    def test_returns_none_for_nonexistent_tmdb_id(self, test_session):
        """Test returning None for nonexistent TMDB ID."""
        found = get_film_by_tmdb_id(test_session, 99999)

        assert found is None


class TestGetFilmsByCountry:
    """Test get_films_by_country function."""

    def test_filters_by_country_code(self, test_session):
        """Test filtering films by country code."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        save_streaming_offers(
            test_session,
            film.id,
            [
                {
                    "country_code": "US",
                    "country_name": "United States",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "monetization_type": "flatrate",
                }
            ],
            checked_at=datetime.now(UTC),
        )

        results = get_films_by_country(test_session, "US")
        assert len(results) >= 1
        assert film in results


class TestGetStreamingOffers:
    """Test get_streaming_offers function."""

    def test_gets_offers_for_film(self, test_session):
        """Test getting streaming offers for a film."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        save_streaming_offers(
            test_session,
            film.id,
            [
                {
                    "country_code": "US",
                    "country_name": "United States",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "monetization_type": "flatrate",
                }
            ],
            checked_at=datetime.now(UTC),
        )

        offers = get_streaming_offers(test_session, film.id)
        assert len(offers) == 1
        assert offers[0].provider_name == "Netflix"


class TestDeleteStreamingOffers:
    """Test delete_streaming_offers function."""

    def test_deletes_offers(self, test_session):
        """Test deleting streaming offers for a film."""
        film, _ = get_or_create_film(test_session, "Test", 2020)
        test_session.commit()

        save_streaming_offers(
            test_session,
            film.id,
            [
                {
                    "country_code": "US",
                    "country_name": "United States",
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "monetization_type": "flatrate",
                }
            ],
            checked_at=datetime.now(UTC),
        )

        delete_streaming_offers(test_session, film.id)

        offers = get_streaming_offers(test_session, film.id)
        assert len(offers) == 0


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

        offers = get_streaming_offers(test_session, film.id)
        assert len(offers) == 2


# =============================================================================
# Database Service Tests
# =============================================================================


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


class TestGetFilmWithOffers:
    """Tests for get_film_with_offers function."""

    def test_get_film_with_offers_found(self, test_session):
        """Test getting film with streaming offers loaded."""
        film, _ = get_or_create_film(test_session, "Test Movie", 2020)
        test_session.commit()

        # Add streaming offers
        offers_data = [
            {
                "country_code": "US",
                "country_name": "United States",
                "provider_id": 8,
                "provider_name": "Netflix",
                "monetization_type": "flatrate",
            }
        ]
        save_streaming_offers(test_session, film.id, offers_data)
        test_session.commit()

        # Get film with offers
        result = get_film_with_offers(test_session, "Test Movie", 2020)

        assert result is not None
        assert result.letterboxd_title == "Test Movie"
        assert len(result.streaming_offers) == 1

    def test_get_film_with_offers_not_found(self, test_session):
        """Test getting non-existent film."""
        result = get_film_with_offers(test_session, "Nonexistent Movie", 2020)
        assert result is None

    def test_get_film_with_offers_without_year(self, test_session):
        """Test getting film without specifying year."""
        film, _ = get_or_create_film(test_session, "Test Movie", None)
        test_session.commit()

        result = get_film_with_offers(test_session, "Test Movie")

        assert result is not None
        assert result.letterboxd_title == "Test Movie"


class TestConvertDbOffersToPydantic:
    """Tests for convert_db_offers_to_pydantic function."""

    def test_convert_empty_offers(self, test_session):
        """Test converting film with no offers."""
        film, _ = get_or_create_film(test_session, "Test Movie", 2020)
        test_session.commit()

        offers = convert_db_offers_to_pydantic(film)

        assert isinstance(offers, list)
        assert len(offers) == 0

    def test_convert_offers_with_data(self, test_session):
        """Test converting film with streaming offers."""
        film, _ = get_or_create_film(test_session, "Test Movie", 2020)
        test_session.commit()

        # Add streaming offers
        offers_data = [
            {
                "country_code": "US",
                "country_name": "United States",
                "provider_id": 8,
                "provider_name": "Netflix",
                "monetization_type": "flatrate",
            },
            {
                "country_code": "FR",
                "country_name": "France",
                "provider_id": 119,
                "provider_name": "Canal+",
                "monetization_type": "flatrate",
            },
        ]
        save_streaming_offers(test_session, film.id, offers_data)
        test_session.commit()

        # Load offers and convert
        film_with_offers = get_film_with_offers(test_session, "Test Movie", 2020)
        offers = convert_db_offers_to_pydantic(film_with_offers)

        assert len(offers) == 2
        assert all(isinstance(offer, StreamingOfferPydantic) for offer in offers)
        assert offers[0].provider_name == "Netflix"
        assert offers[1].provider_name == "Canal+"


# =============================================================================
# Database Session Tests
# =============================================================================


class TestDatabaseConfiguration:
    """Test database configuration."""

    def test_database_url_configured(self):
        """Test that DATABASE_URL is configured."""
        assert DATABASE_URL is not None
        assert "sqlite:///" in DATABASE_URL

    def test_database_path_configured(self):
        """Test that DATABASE_PATH is configured."""
        assert DATABASE_PATH is not None
        assert DATABASE_PATH.suffix == ".db"

    def test_database_dir_configured(self):
        """Test that DATABASE_DIR is configured."""
        assert DATABASE_DIR is not None
        assert DATABASE_PATH.parent == DATABASE_DIR


class TestEngine:
    """Test database engine."""

    def test_engine_created(self):
        """Test that engine is created."""
        assert engine is not None

    def test_session_local_created(self):
        """Test that SessionLocal is created."""
        assert SessionLocal is not None


class TestGetSession:
    """Test get_session context manager."""

    def test_get_session_returns_session(self):
        """Test that get_session returns a session."""
        with get_session() as session:
            assert session is not None

    def test_get_session_error_handling(self):
        """Test that get_session handles errors properly."""
        # Deliberately cause an error and verify rollback
        with pytest.raises(ValueError):
            with get_session():
                raise ValueError("Test error")


class TestInitDB:
    """Test init_db function."""

    def test_init_db_callable(self):
        """Test that init_db is callable."""
        assert callable(init_db)

    def test_init_db_creates_database(self, tmp_path):
        """Test that init_db actually creates database."""
        # Call init_db - should not raise
        init_db()

        # Database should be accessible
        assert DATABASE_PATH.exists()

    def test_init_db_idempotent(self):
        """Test that init_db can be called multiple times."""
        # Call init_db twice - should not raise
        init_db()
        init_db()


class TestGetDatabaseInfo:
    """Test get_database_info function."""

    def test_get_database_info_returns_dict(self):
        """Test that get_database_info returns a dictionary."""
        info = get_database_info()
        assert isinstance(info, dict)
        assert "path" in info
        assert "exists" in info

    def test_database_info_has_path(self):
        """Test that database info includes path."""
        info = get_database_info()
        assert info["path"] is not None

    def test_database_info_has_exists_flag(self):
        """Test that database info includes exists flag."""
        info = get_database_info()
        assert isinstance(info["exists"], bool)

    def test_get_database_info_with_stats(self):
        """Test get_database_info with existing database."""
        # Ensure database exists
        init_db()

        info = get_database_info()

        # Should have file size info
        assert "size_bytes" in info
        assert "size_mb" in info
        assert info["size_mb"] > 0

        # Should have counts (even if 0)
        assert "film_count" in info
        assert "offer_count" in info
        assert info["film_count"] is not None
        assert info["offer_count"] is not None


class TestResetDatabase:
    """Test reset_database function."""

    def test_reset_database_callable(self):
        """Test that reset_database is callable."""
        assert callable(reset_database)

    def test_reset_database_executes(self):
        """Test that reset_database actually works."""
        # Call reset_database - should not raise
        reset_database()

        # Database should still be accessible after reset
        with get_session() as session:
            count = session.query(Film).count()
            assert count == 0  # Should be empty after reset


# =============================================================================
# Database Init Module Tests
# =============================================================================


class TestInitDBMain:
    """Test init_db.py main function."""

    @patch("screenseeker.database.init_db.init_db")
    @patch("screenseeker.database.init_db.get_database_info")
    def test_main_success(self, mock_get_info, mock_init_db):
        """Test successful database initialization."""
        from screenseeker.database.init_db import main

        mock_get_info.return_value = {
            "path": "/test/path/screenseeker.db",
            "exists": True,
            "size_mb": 1.5,
            "film_count": 10,
            "offer_count": 25,
        }

        result = main()

        assert result == 0
        mock_init_db.assert_called_once()
        mock_get_info.assert_called_once()

    @patch("screenseeker.database.init_db.init_db")
    @patch("screenseeker.database.init_db.get_database_info")
    def test_main_with_minimal_info(self, mock_get_info, mock_init_db):
        """Test main with minimal database info."""
        from screenseeker.database.init_db import main

        mock_get_info.return_value = {
            "path": "/test/path/screenseeker.db",
            "exists": False,
        }

        result = main()

        assert result == 0
        mock_init_db.assert_called_once()

    @patch("screenseeker.database.init_db.init_db")
    def test_main_failure(self, mock_init_db):
        """Test main function when init_db raises exception."""
        from screenseeker.database.init_db import main

        mock_init_db.side_effect = Exception("Database error")

        result = main()

        assert result == 1
        mock_init_db.assert_called_once()
