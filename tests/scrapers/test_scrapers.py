"""
Integration tests for scrapers and base classes.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from screenseeker.scrapers.base import BaseScraper
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
        with pytest.raises(TypeError):

            class BadScraper(BaseScraper):
                pass

            BadScraper()  # type: ignore[abstract]

    def test_base_scraper_has_context_manager_methods(self):
        """Test that BaseScraper defines context manager methods."""
        assert hasattr(BaseScraper, "__enter__")
        assert hasattr(BaseScraper, "__exit__")


class TestHTMLScraperIntegration:
    """Integration tests for HTML scraper with mocked HTTP."""

    @pytest.fixture
    def sample_html(self):
        """Sample Letterboxd HTML."""
        return """
        <html><body><ul class="poster-list">
            <li class="griditem poster-container">
                <div class="react-component" data-item-full-display-name="The Matrix (1999)"></div>
            </li>
            <li class="griditem poster-container">
                <div class="react-component" data-item-full-display-name="Inception (2010)"></div>
            </li>
        </ul></body></html>
        """

    def test_html_scraper_success(self, sample_html):
        """Test HTML scraper with successful response."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session

            # First page has films, second page is empty (stops pagination)
            mock_response_1 = Mock()
            mock_response_1.status_code = 200
            mock_response_1.text = sample_html

            mock_response_2 = Mock()
            mock_response_2.status_code = 200
            mock_response_2.text = "<html><body></body></html>"

            mock_session.get.side_effect = [mock_response_1, mock_response_2]

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            )
            result = scraper.scrape()

            assert result.success is True
            assert len(result.films) == 2
            assert result.films[0].film_title == "The Matrix"
            assert result.films[0].year == 1999

    def test_html_scraper_empty_page(self):
        """Test HTML scraper with empty page."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "<html><body></body></html>"
            mock_session.get.return_value = mock_response

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            )
            result = scraper.scrape()

            assert result.success is True
            assert len(result.films) == 0

    def test_html_scraper_404_error(self):
        """Test HTML scraper with 404 error."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session

            mock_response = Mock()
            mock_response.status_code = 404
            mock_session.get.return_value = mock_response

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            )
            result = scraper.scrape()

            assert result.success is True
            assert len(result.films) == 0

    def test_html_scraper_network_error(self):
        """Test HTML scraper with network error."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session
            mock_session.get.side_effect = requests.RequestException("Network error")

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            )
            result = scraper.scrape()

            assert result.success is False
            assert "Request error" in result.error_message

    def test_html_scraper_film_without_year(self):
        """Test HTML scraper with film without year."""
        html = """
        <html><body><ul class="poster-list">
            <li class="griditem poster-container">
                <div class="react-component" data-item-full-display-name="Unknown Film"></div>
            </li>
        </ul></body></html>
        """

        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session

            mock_response_1 = Mock()
            mock_response_1.status_code = 200
            mock_response_1.text = html

            mock_response_2 = Mock()
            mock_response_2.status_code = 200
            mock_response_2.text = "<html><body></body></html>"

            mock_session.get.side_effect = [mock_response_1, mock_response_2]

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            )
            result = scraper.scrape()

            assert result.success is True
            assert len(result.films) == 1
            assert result.films[0].year is None

    def test_html_scraper_context_manager(self, sample_html):
        """Test HTML scraper as context manager."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session
            mock_session.close = Mock()

            mock_response_1 = Mock()
            mock_response_1.status_code = 200
            mock_response_1.text = sample_html

            mock_response_2 = Mock()
            mock_response_2.status_code = 200
            mock_response_2.text = "<html><body></body></html>"

            mock_session.get.side_effect = [mock_response_1, mock_response_2]

            with HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist", delay_between_requests=0
            ) as scraper:
                result = scraper.scrape()
                assert result.success is True

            mock_session.close.assert_called_once()

    def test_html_scraper_save_raw_data(self, sample_html, tmp_path):
        """Test HTML scraper saves raw data."""
        with patch("screenseeker.scrapers.html_scraper.requests.Session") as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session

            mock_response_1 = Mock()
            mock_response_1.status_code = 200
            mock_response_1.text = sample_html

            mock_response_2 = Mock()
            mock_response_2.status_code = 200
            mock_response_2.text = "<html><body></body></html>"

            mock_session.get.side_effect = [mock_response_1, mock_response_2]

            scraper = HTMLScraper(
                base_url="https://letterboxd.com/user/watchlist",
                delay_between_requests=0,
                save_raw_data=True,
                output_dir=tmp_path,
            )
            result = scraper.scrape()

            assert result.success is True
            html_files = list(tmp_path.rglob("*.html"))
            assert len(html_files) > 0
