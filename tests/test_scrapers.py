"""
Tests for scrapers and base classes.
"""

import pytest

from screenseeker.scrapers.base import BaseScraper
from screenseeker.scrapers.csv_scraper import CSVScraper
from screenseeker.scrapers.html_scraper import HTMLScraper


class TestBaseScraper:
    """Test BaseScraper class."""

    def test_base_scraper_has_abstract_method(self):
        """Test that BaseScraper defines abstract scrape method."""
        assert hasattr(BaseScraper, "scrape")

    def test_cannot_instantiate_base_scraper(self):
        """Test that BaseScraper cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseScraper()  # type: ignore[abstract]

    def test_concrete_scraper_must_implement_scrape(self):
        """Test that concrete scraper must implement scrape method."""
        # Try to create a concrete class without implementing scrape
        with pytest.raises(TypeError):

            class BadScraper(BaseScraper):
                pass

            BadScraper()  # type: ignore[abstract]

    def test_base_scraper_has_context_manager_methods(self):
        """Test that BaseScraper defines context manager methods."""
        assert hasattr(BaseScraper, "__enter__")
        assert hasattr(BaseScraper, "__exit__")


class TestCSVScraper:
    """Test CSV scraper."""

    def test_csv_scraper_can_be_imported(self):
        """Test that CSVScraper can be imported."""
        assert CSVScraper is not None


class TestHTMLScraper:
    """Test HTML scraper."""

    def test_html_scraper_can_be_imported(self):
        """Test that HTMLScraper can be imported."""
        assert HTMLScraper is not None
