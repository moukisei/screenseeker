"""
Tests for all model classes (Pydantic and SQLAlchemy).
"""

from datetime import date

import pytest
from pydantic import ValidationError

from screenseeker.models import Film, ScrapingResult


class TestFilmParseTitleAndYear:
    """Test Film.parse_title_and_year static method."""

    def test_parse_title_with_year(self):
        """Test parsing title with year."""
        full_title, title, year = Film.parse_title_and_year("The Matrix (1999)")

        assert full_title == "The Matrix (1999)"
        assert title == "The Matrix"
        assert year == 1999

    def test_parse_title_without_year(self):
        """Test parsing title without year."""
        full_title, title, year = Film.parse_title_and_year("The Matrix")

        assert full_title == "The Matrix"
        assert title == "The Matrix"
        assert year is None

    def test_parse_title_with_spaces(self):
        """Test parsing title with extra spaces."""
        full_title, title, year = Film.parse_title_and_year("  The Matrix (1999)  ")

        assert full_title == "The Matrix (1999)"
        assert title == "The Matrix"
        assert year == 1999


class TestFilmGenerateId:
    """Test Film.generate_film_id static method."""

    def test_generate_id_with_year(self):
        """Test generating ID with year."""
        id1 = Film.generate_film_id("The Matrix", 1999)
        id2 = Film.generate_film_id("The Matrix", 1999)

        # Same inputs should generate same ID
        assert id1 == id2
        assert len(id1) == 16

    def test_generate_id_without_year(self):
        """Test generating ID without year."""
        film_id = Film.generate_film_id("The Matrix", None)

        assert film_id is not None
        assert len(film_id) == 16

    def test_generate_id_case_insensitive(self):
        """Test that ID generation is case-insensitive."""
        id1 = Film.generate_film_id("The Matrix", 1999)
        id2 = Film.generate_film_id("the matrix", 1999)

        # Different case should generate same ID
        assert id1 == id2


class TestFilmValidation:
    """Test Film validation."""

    def test_film_id_auto_generated(self):
        """Test that film_id is auto-generated if missing."""
        film = Film(
            film_title="Test Movie",
            year=2020,
            film_full_title="Test Movie (2020)",
            date_added="2024-01-01",
        )

        # film_id should be auto-generated
        assert film.film_id is not None
        assert len(film.film_id) == 16

    def test_date_added_auto_set(self):
        """Test that date_added is auto-set if missing."""
        film = Film(
            film_title="Test Movie",
            year=2020,
            film_full_title="Test Movie (2020)",
        )

        # date_added should be set to today
        assert film.date_added == date.today().isoformat()

    def test_empty_title_validation(self):
        """Test that empty title raises ValidationError."""
        with pytest.raises(ValidationError):
            Film(
                film_title="",
                year=2020,
                film_full_title="Test (2020)",
                date_added="2024-01-01",
            )

    def test_empty_full_title_validation(self):
        """Test that empty full_title raises ValidationError."""
        with pytest.raises(ValidationError):
            Film(
                film_title="Test",
                year=2020,
                film_full_title="",
                date_added="2024-01-01",
            )

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from string fields."""
        film = Film(
            film_title="  Test Movie  ",
            year=2020,
            film_full_title="  Test Movie (2020)  ",
            date_added="  2024-01-01  ",
        )

        assert film.film_title == "Test Movie"
        assert film.film_full_title == "Test Movie (2020)"
        assert film.date_added == "2024-01-01"

    def test_film_without_year(self):
        """Test film model without year."""
        film = Film(
            film_title="Test Movie",
            year=None,
            film_full_title="Test Movie",
            date_added="2024-01-01",
        )

        assert film.film_title == "Test Movie"
        assert film.year is None


class TestScrapingResultModel:
    """Test ScrapingResult model."""

    def test_scraping_result_film_count_property(self):
        """Test film_count property."""
        films = [
            Film(
                film_title="Movie 1",
                year=2020,
                film_full_title="Movie 1 (2020)",
                date_added="2024-01-01",
            ),
            Film(
                film_title="Movie 2",
                year=2021,
                film_full_title="Movie 2 (2021)",
                date_added="2024-01-02",
            ),
        ]

        result = ScrapingResult(
            success=True,
            films=films,
            source="test",
        )

        assert result.film_count == 2

    def test_scraping_result_to_dict(self):
        """Test to_dict method."""
        result = ScrapingResult(
            success=True,
            films=[
                Film(
                    film_title="Test",
                    year=2020,
                    film_full_title="Test (2020)",
                    date_added="2024-01-01",
                )
            ],
            source="csv",
            total_pages_scraped=5,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["total_films"] == 1
        assert data["source"] == "csv"
        assert data["total_pages_scraped"] == 5
        assert len(data["films"]) == 1
        assert "scraped_at" in data

    def test_scraping_result_with_error(self):
        """Test ScrapingResult with error."""
        result = ScrapingResult(
            success=False,
            films=[],
            source="html",
            error_message="Failed to scrape",
        )

        assert result.success is False
        assert result.error_message == "Failed to scrape"
        assert result.film_count == 0
