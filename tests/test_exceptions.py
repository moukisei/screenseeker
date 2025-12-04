"""
Comprehensive tests for exception classes.
"""

import pytest

from screenseeker.exceptions import (
    ConfigurationError,
    DatabaseError,
    FilmNotFoundError,
    InvalidInputError,
    RateLimitError,
    ScraperError,
    ScreenSeekerError,
    TMDBAPIError,
    TMDBNotFoundError,
)


class TestScreenSeekerError:
    """Test base ScreenSeekerError."""

    def test_raise_with_message(self):
        """Test raising error with message."""
        with pytest.raises(ScreenSeekerError) as exc:
            raise ScreenSeekerError("Base error")
        assert "Base error" in str(exc.value)


class TestConfigurationError:
    """Test ConfigurationError."""

    def test_configuration_error(self):
        """Test raising configuration error."""
        with pytest.raises(ConfigurationError) as exc:
            raise ConfigurationError("Invalid config")
        assert "Invalid config" in str(exc.value)


class TestTMDBAPIError:
    """Test TMDB API errors."""

    def test_tmdb_api_error(self):
        """Test basic TMDB API error."""
        with pytest.raises(TMDBAPIError) as exc:
            raise TMDBAPIError("API failed")
        assert "API failed" in str(exc.value)

    def test_rate_limit_error(self):
        """Test rate limit error."""
        with pytest.raises(RateLimitError) as exc:
            raise RateLimitError("Rate limited")
        assert "Rate limited" in str(exc.value)

    def test_tmdb_not_found_error(self):
        """Test TMDB not found error."""
        with pytest.raises(TMDBNotFoundError) as exc:
            raise TMDBNotFoundError("Movie 'Test' not found")
        # Error has custom message formatting
        assert "not found" in str(exc.value).lower()


class TestDatabaseError:
    """Test database errors."""

    def test_database_error(self):
        """Test basic database error."""
        with pytest.raises(DatabaseError) as exc:
            raise DatabaseError("Database connection failed")
        assert "Database connection failed" in str(exc.value)

    def test_film_not_found_error(self):
        """Test film not found error."""
        with pytest.raises(FilmNotFoundError) as exc:
            raise FilmNotFoundError("Film 'The Matrix' not found")
        # Error has custom message formatting
        assert "not found" in str(exc.value).lower()


class TestScraperError:
    """Test scraper errors."""

    def test_scraper_error(self):
        """Test scraper error."""
        with pytest.raises(ScraperError) as exc:
            raise ScraperError("Failed to scrape")
        assert "Failed to scrape" in str(exc.value)


class TestInvalidInputError:
    """Test invalid input errors."""

    def test_invalid_input_error(self):
        """Test invalid input error."""
        with pytest.raises(InvalidInputError) as exc:
            raise InvalidInputError("Invalid year format")
        assert "Invalid year format" in str(exc.value)


class TestErrorInheritance:
    """Test error class inheritance."""

    def test_all_inherit_from_base(self):
        """Test that all errors inherit from ScreenSeekerError."""
        assert issubclass(ConfigurationError, ScreenSeekerError)
        assert issubclass(TMDBAPIError, ScreenSeekerError)
        assert issubclass(DatabaseError, ScreenSeekerError)
        assert issubclass(ScraperError, ScreenSeekerError)
        assert issubclass(InvalidInputError, ScreenSeekerError)

    def test_tmdb_errors_inherit(self):
        """Test TMDB error inheritance."""
        assert issubclass(RateLimitError, TMDBAPIError)
        assert issubclass(TMDBNotFoundError, TMDBAPIError)

    def test_database_errors_inherit(self):
        """Test database error inheritance."""
        assert issubclass(FilmNotFoundError, DatabaseError)


class TestErrorCatching:
    """Test catching errors with base class."""

    def test_catch_with_base_class(self):
        """Test that specific errors can be caught with base class."""
        with pytest.raises(ScreenSeekerError):
            raise ConfigurationError("Config error")

        with pytest.raises(ScreenSeekerError):
            raise TMDBAPIError("API error")

        with pytest.raises(ScreenSeekerError):
            raise DatabaseError("DB error")
