"""
Tests for database query functions.
"""

from datetime import datetime, timedelta

import pytest

from database.models import StreamingOffer
from database.queries import (
    get_database_stats,
    get_film_by_title_year,
    get_film_by_tmdb_id,
    get_films_by_provider,
    get_or_create_film,
    get_stale_films,
    get_unwatched_films,
    mark_film_watched,
    search_films_by_title,
)


class TestGetOrCreateFilm:
    """Tests for get_or_create_film function."""

    def test_creates_new_film(self, test_session):
        """Test that a new film is created when it doesn't exist."""
        film, created = get_or_create_film(test_session, "The Matrix", 1999)

        assert created is True
        assert film.letterboxd_title == "The Matrix"
        assert film.letterboxd_year == 1999
        assert film.id is not None

    def test_returns_existing_film(self, test_session):
        """Test that existing film is returned without creating duplicate."""
        # Create first time
        film1, created1 = get_or_create_film(test_session, "The Matrix", 1999)
        test_session.commit()

        # Try to create again
        film2, created2 = get_or_create_film(test_session, "The Matrix", 1999)

        assert created1 is True
        assert created2 is False
        assert film1.id == film2.id

    def test_handles_films_without_year(self, test_session):
        """Test that films without year are handled correctly."""
        film, created = get_or_create_film(test_session, "Some Film", None)

        assert created is True
        assert film.letterboxd_title == "Some Film"
        assert film.letterboxd_year is None


class TestGetFilmByTitleYear:
    """Tests for get_film_by_title_year function."""

    def test_finds_film_with_year(self, test_session):
        """Test finding a film by exact title and year."""
        # Create film
        film, _ = get_or_create_film(test_session, "Inception", 2010)
        test_session.commit()

        # Find it
        found = get_film_by_title_year(test_session, "Inception", 2010)

        assert found is not None
        assert found.id == film.id

    def test_returns_none_for_nonexistent_film(self, test_session):
        """Test that None is returned when film doesn't exist."""
        found = get_film_by_title_year(test_session, "Nonexistent Film", 2020)

        assert found is None

    def test_finds_film_without_year(self, test_session):
        """Test finding a film by title only."""
        film, _ = get_or_create_film(test_session, "Arrival", None)
        test_session.commit()

        found = get_film_by_title_year(test_session, "Arrival", None)

        assert found is not None
        assert found.id == film.id


class TestSearchFilmsByTitle:
    """Tests for search_films_by_title function."""

    def test_partial_match(self, test_session):
        """Test that partial title matching works."""
        # Create films
        get_or_create_film(test_session, "The Matrix", 1999)
        get_or_create_film(test_session, "The Matrix Reloaded", 2003)
        get_or_create_film(test_session, "Inception", 2010)
        test_session.commit()

        # Search
        results = search_films_by_title(test_session, "matrix")

        assert len(results) == 2
        titles = [f.letterboxd_title for f in results]
        assert "The Matrix" in titles
        assert "The Matrix Reloaded" in titles

    def test_case_insensitive(self, test_session):
        """Test that search is case-insensitive."""
        get_or_create_film(test_session, "The Matrix", 1999)
        test_session.commit()

        results = search_films_by_title(test_session, "MATRIX")

        assert len(results) == 1
        assert results[0].letterboxd_title == "The Matrix"

    def test_respects_limit(self, test_session):
        """Test that limit parameter works."""
        for i in range(5):
            get_or_create_film(test_session, f"Film {i}", 2020 + i)
        test_session.commit()

        results = search_films_by_title(test_session, "Film", limit=3)

        assert len(results) == 3


class TestGetUnwatchedFilms:
    """Tests for get_unwatched_films function."""

    def test_returns_only_unwatched(self, test_session):
        """Test that only unwatched films are returned."""
        # Create films
        film1, _ = get_or_create_film(test_session, "Film 1", 2020)
        film2, _ = get_or_create_film(test_session, "Film 2", 2021)
        film3, _ = get_or_create_film(test_session, "Film 3", 2022)

        # Mark one as watched
        film2.watched = True
        film2.watched_at = datetime.utcnow()
        test_session.commit()

        # Get unwatched
        unwatched = get_unwatched_films(test_session)

        assert len(unwatched) == 2
        unwatched_ids = [f.id for f in unwatched]
        assert film1.id in unwatched_ids
        assert film3.id in unwatched_ids
        assert film2.id not in unwatched_ids


class TestMarkFilmWatched:
    """Tests for mark_film_watched function."""

    def test_marks_film_as_watched(self, test_session):
        """Test marking a film as watched."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        test_session.commit()

        mark_film_watched(test_session, film.id, watched=True)
        test_session.commit()

        # Refresh from database
        test_session.expire(film)
        assert film.watched is True
        assert film.watched_at is not None

    def test_marks_film_as_unwatched(self, test_session):
        """Test marking a film as unwatched."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        film.watched = True
        film.watched_at = datetime.utcnow()
        test_session.commit()

        mark_film_watched(test_session, film.id, watched=False)
        test_session.commit()

        test_session.expire(film)
        assert film.watched is False
        assert film.watched_at is None


class TestGetStaleFilms:
    """Tests for get_stale_films function."""

    def test_finds_stale_films(self, test_session):
        """Test that films with old last_checked are found."""
        # Create films
        fresh_film, _ = get_or_create_film(test_session, "Fresh Film", 2020)
        fresh_film.last_checked = datetime.utcnow()

        stale_film, _ = get_or_create_film(test_session, "Stale Film", 2021)
        stale_film.last_checked = datetime.utcnow() - timedelta(days=10)

        unchecked_film, _ = get_or_create_film(test_session, "Unchecked Film", 2022)
        unchecked_film.last_checked = None

        test_session.commit()

        # Get stale films (>7 days)
        stale = get_stale_films(test_session, days=7)

        stale_ids = [f.id for f in stale]
        assert stale_film.id in stale_ids
        assert unchecked_film.id in stale_ids
        assert fresh_film.id not in stale_ids


class TestGetFilmsByProvider:
    """Tests for get_films_by_provider function."""

    def test_filters_by_provider(self, test_session):
        """Test filtering films by provider."""
        # Create films with offers
        film1, _ = get_or_create_film(test_session, "Film 1", 2020)
        film1.tmdb_id = 1
        film2, _ = get_or_create_film(test_session, "Film 2", 2021)
        film2.tmdb_id = 2

        # Add streaming offers
        offer1 = StreamingOffer(
            film_id=film1.id,
            country_code="US",
            country_name="United States",
            provider_id=8,
            provider_name="Netflix",
            monetization_type="flatrate",
            checked_at=datetime.utcnow(),
        )
        offer2 = StreamingOffer(
            film_id=film2.id,
            country_code="US",
            country_name="United States",
            provider_id=9,
            provider_name="Prime Video",
            monetization_type="flatrate",
            checked_at=datetime.utcnow(),
        )

        test_session.add(offer1)
        test_session.add(offer2)
        test_session.commit()

        # Query by provider
        netflix_films = get_films_by_provider(test_session, "Netflix")

        assert len(netflix_films) == 1
        assert netflix_films[0].id == film1.id

    def test_filters_by_country(self, test_session):
        """Test filtering by country."""
        film, _ = get_or_create_film(test_session, "Film", 2020)
        film.tmdb_id = 1

        # Add offers in different countries
        offer_us = StreamingOffer(
            film_id=film.id,
            country_code="US",
            country_name="United States",
            provider_id=8,
            provider_name="Netflix",
            monetization_type="flatrate",
            checked_at=datetime.utcnow(),
        )
        offer_fr = StreamingOffer(
            film_id=film.id,
            country_code="FR",
            country_name="France",
            provider_id=8,
            provider_name="Netflix",
            monetization_type="flatrate",
            checked_at=datetime.utcnow(),
        )

        test_session.add_all([offer_us, offer_fr])
        test_session.commit()

        # Query with country filter
        us_films = get_films_by_provider(test_session, "Netflix", country_code="US")
        fr_films = get_films_by_provider(test_session, "Netflix", country_code="FR")

        assert len(us_films) == 1
        assert len(fr_films) == 1


class TestGetDatabaseStats:
    """Tests for get_database_stats function."""

    def test_calculates_stats_correctly(self, test_session):
        """Test that database statistics are calculated correctly."""
        # Create test data
        film1, _ = get_or_create_film(test_session, "Film 1", 2020)
        film1.tmdb_id = 1
        film1.watched = True

        film2, _ = get_or_create_film(test_session, "Film 2", 2021)
        film2.tmdb_id = 2

        film3, _ = get_or_create_film(test_session, "Film 3", 2022)
        # No TMDB ID

        test_session.commit()

        # Get stats
        stats = get_database_stats(test_session)

        assert stats["total_films"] == 3
        assert stats["watched_films"] == 1
        assert stats["unwatched_films"] == 2
        assert stats["films_with_tmdb"] == 2
        assert stats["match_rate"] == pytest.approx(66.7, rel=0.1)


class TestGetFilmByTMDBId:
    """Tests for get_film_by_tmdb_id function."""

    def test_finds_film_by_tmdb_id(self, test_session):
        """Test finding a film by TMDB ID."""
        film, _ = get_or_create_film(test_session, "Test Film", 2020)
        film.tmdb_id = 12345
        test_session.commit()

        found = get_film_by_tmdb_id(test_session, 12345)

        assert found is not None
        assert found.id == film.id
        assert found.tmdb_id == 12345

    def test_returns_none_for_nonexistent_tmdb_id(self, test_session):
        """Test that None is returned when TMDB ID doesn't exist."""
        found = get_film_by_tmdb_id(test_session, 99999)

        assert found is None
