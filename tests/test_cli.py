"""
Tests for CLI commands and functionality.
"""

from unittest.mock import Mock, patch

from click.testing import CliRunner

from screenseeker.cli import cli
from screenseeker.database.models import Film
from screenseeker.enrichers.enrichment_models import EnrichmentResult, TMDBMovieInfo


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self):
        """Test main CLI help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ScreenSeeker" in result.output

    def test_cli_version(self):
        """Test version command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_db_help(self):
        """Test db command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0

    def test_search_help(self):
        """Test search command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0

    def test_watch_help(self):
        """Test watch command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0

    def test_sync_help(self):
        """Test sync command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0

    def test_enrich_help(self):
        """Test enrich command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["enrich", "--help"])
        assert result.exit_code == 0

    def test_watchlist_help(self):
        """Test watchlist command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watchlist", "--help"])
        assert result.exit_code == 0

    def test_watched_help(self):
        """Test watched command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watched", "--help"])
        assert result.exit_code == 0

    def test_providers_help(self):
        """Test providers command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["providers", "--help"])
        assert result.exit_code == 0

    def test_country_help(self):
        """Test country command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["country", "--help"])
        assert result.exit_code == 0

    def test_refresh_help(self):
        """Test refresh command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["refresh", "--help"])
        assert result.exit_code == 0

    def test_report_help(self):
        """Test report command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0


class TestWatchCommand:
    """Test watch command."""

    @patch("screenseeker.cli.TMDBEnricher")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrich_and_save_film")
    @patch("screenseeker.cli.WatchStrategyAnalyzer")
    @patch("screenseeker.cli._display_watch_strategy")
    def test_watch_with_title_and_year(
        self, mock_display, mock_analyzer, mock_enrich, mock_session, mock_enricher
    ):
        """Test watch command with title and year."""
        # Setup mocks
        mock_film = Mock()
        mock_film.last_checked = None
        mock_film.year_mismatch = False

        mock_result = EnrichmentResult(
            query_title="Test Movie",
            success=True,
            tmdb_movie=TMDBMovieInfo(
                tmdb_id=123,
                title="Test Movie",
                original_title="Test Movie",
                year=2020,
                release_date="2020-01-01",
                overview="Test",
                original_language="en",
                poster_path="/test.jpg",
                backdrop_path=None,
                vote_average=8.0,
                popularity=100.0,
                query_title="Test Movie",
            ),
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
        )

        mock_enrich.return_value = (mock_film, mock_result)
        mock_analyzer.return_value.analyze.return_value = Mock()

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "Test Movie", "--year", "2020"])

        assert result.exit_code == 0
        assert "Searching for" in result.output

    @patch("screenseeker.cli.config")
    def test_watch_without_api_key(self, mock_config):
        """Test watch command without TMDB API key."""
        mock_config.TMDB_API_KEY = None

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "Test Movie"])

        assert result.exit_code == 1
        assert "TMDB API key not configured" in result.output

    def test_watch_with_title_containing_year(self):
        """Test watch command with title containing year."""
        runner = CliRunner()
        # This will fail without API key, but tests the parsing logic
        result = runner.invoke(cli, ["watch", "The Matrix (1999)"])

        # Should parse the year from title
        assert "1999" in result.output or "Matrix" in result.output


class TestSearchCommand:
    """Test search command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.search_films_by_title")
    def test_search_with_query(self, mock_search, mock_session):
        """Test search command with query."""
        mock_film = Film(
            letterboxd_title="Test Movie",
            letterboxd_year=2020,
        )
        mock_search.return_value = [mock_film]

        runner = CliRunner()
        result = runner.invoke(cli, ["search", "Test"])

        assert result.exit_code == 0
        mock_search.assert_called_once()

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.search_films_by_title")
    def test_search_no_results(self, mock_search, mock_session):
        """Test search command with no results."""
        mock_search.return_value = []

        runner = CliRunner()
        result = runner.invoke(cli, ["search", "NonexistentMovie"])

        assert result.exit_code == 0
        assert "No films found" in result.output


class TestWatchlistCommand:
    """Test watchlist command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_unwatched_films")
    def test_watchlist_default(self, mock_get_films, mock_session):
        """Test watchlist command."""
        mock_film = Film(
            letterboxd_title="Test Movie",
            letterboxd_year=2020,
        )
        mock_get_films.return_value = [mock_film]

        runner = CliRunner()
        result = runner.invoke(cli, ["watchlist"])

        assert result.exit_code == 0


class TestWatchedCommand:
    """Test watched command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_film_by_title_year")
    @patch("screenseeker.cli.mark_film_watched")
    def test_mark_film_watched(self, mock_mark, mock_get_film, mock_session):
        """Test marking a film as watched."""
        mock_film = Film(
            letterboxd_title="Test Movie",
            letterboxd_year=2020,
        )
        mock_get_film.return_value = mock_film

        runner = CliRunner()
        result = runner.invoke(cli, ["watched", "Test Movie", "--year", "2020"])

        assert result.exit_code == 0
        mock_mark.assert_called_once()
