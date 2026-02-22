"""
Integration tests for scrapers and base classes.
"""

from unittest.mock import Mock, patch

import pytest
import requests

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
        with pytest.raises(TypeError):

            class BadScraper(BaseScraper):
                pass

            BadScraper()  # type: ignore[abstract]

    def test_base_scraper_has_context_manager_methods(self):
        """Test that BaseScraper defines context manager methods."""
        assert hasattr(BaseScraper, "__enter__")
        assert hasattr(BaseScraper, "__exit__")


class TestCSVScraperIntegration:
    """Integration tests for CSV scraper."""

    @pytest.fixture
    def csv_dir(self, tmp_path):
        """Create temporary directory for CSV files."""
        return tmp_path

    def test_csv_scraper_basic_success(self, csv_dir):
        """Test CSV scraper with valid data."""
        csv_file = csv_dir / "movies.csv"
        csv_file.write_text(
            "Name,Year,Date\n"
            "The Matrix,1999,2024-01-01\n"
            "Inception,2010,2024-01-02\n"
            "Interstellar,2014,2024-01-03\n"
        )

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert result.film_count == 3
        assert result.source == "csv"
        assert len(result.films) == 3
        assert result.films[0].film_title == "The Matrix"
        assert result.films[0].year == 1999
        assert result.films[0].date_added == "2024-01-01"

    def test_csv_scraper_without_year(self, csv_dir):
        """Test CSV scraper with films without year."""
        csv_file = csv_dir / "no_year.csv"
        csv_file.write_text("Name\nThe Matrix\nInception\n")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert len(result.films) == 2
        assert result.films[0].year is None

    def test_csv_scraper_invalid_year(self, csv_dir):
        """Test CSV scraper handles invalid years."""
        csv_file = csv_dir / "invalid.csv"
        csv_file.write_text("Name,Year\nThe Matrix,invalid\nInception,2010\n")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert len(result.films) == 2
        assert result.films[0].year is None  # Invalid year
        assert result.films[1].year == 2010

    def test_csv_scraper_empty_names(self, csv_dir):
        """Test CSV scraper skips empty names."""
        csv_file = csv_dir / "empty.csv"
        csv_file.write_text("Name,Year\n,1999\nInception,2010\n")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert len(result.films) == 1
        assert result.films[0].film_title == "Inception"

    def test_csv_scraper_missing_columns(self, csv_dir):
        """Test CSV scraper with missing required columns."""
        csv_file = csv_dir / "missing.csv"
        csv_file.write_text("Title,Year\nThe Matrix,1999\n")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is False
        assert "Missing required columns" in result.error_message

    def test_csv_scraper_file_not_found(self):
        """Test CSV scraper with non-existent file."""
        with pytest.raises(FileNotFoundError):
            CSVScraper(csv_file_path="/non/existent.csv")

    def test_csv_scraper_malformed_csv(self, csv_dir):
        """Test CSV scraper with malformed CSV."""
        csv_file = csv_dir / "malformed.csv"
        csv_file.write_text('Name,Year\n"Unclosed,2010\n')

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        # CSV parser handles malformed data gracefully - logs error and continues
        assert result.success is True
        assert len(result.films) == 0  # Row was skipped due to error

    def test_csv_scraper_extra_columns(self, csv_dir):
        """Test CSV scraper ignores extra columns."""
        csv_file = csv_dir / "extra.csv"
        csv_file.write_text("Name,Year,Rating,Notes\nThe Matrix,1999,5,Great\n")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert len(result.films) == 1

    def test_csv_scraper_unicode(self, csv_dir):
        """Test CSV scraper with unicode characters."""
        csv_file = csv_dir / "unicode.csv"
        csv_file.write_text("Name,Year\nAmélie,2001\n", encoding="utf-8")

        scraper = CSVScraper(csv_file_path=str(csv_file))
        result = scraper.scrape()

        assert result.success is True
        assert result.films[0].film_title == "Amélie"


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
