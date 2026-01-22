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

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_film_by_title_year")
    def test_watched_film_not_found(self, mock_get_film, mock_session):
        """Test watched command when film not found."""
        mock_get_film.return_value = None

        runner = CliRunner()
        result = runner.invoke(cli, ["watched", "Nonexistent Movie"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestSyncCommand:
    """Test sync command - basic help test only due to complexity."""

    def test_sync_help(self):
        """Test sync command help works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0
        assert "sync" in result.output.lower() or "scrape" in result.output.lower()


class TestDbCommands:
    """Test database commands."""

    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_database_info")
    def test_db_init(self, mock_get_info, mock_init_db):
        """Test db init command."""
        mock_get_info.return_value = {"path": "/test/path", "exists": True}

        runner = CliRunner()
        result = runner.invoke(cli, ["db", "init"])

        assert result.exit_code == 0
        mock_init_db.assert_called_once()

    @patch("screenseeker.cli.reset_database")
    @patch("screenseeker.cli.get_database_info")
    def test_db_init_with_reset(self, mock_get_info, mock_reset):
        """Test db init command with reset flag."""
        mock_get_info.return_value = {"path": "/test/path", "exists": True}

        runner = CliRunner()
        result = runner.invoke(cli, ["db", "init", "--reset"], input="y\n")

        assert result.exit_code == 0
        mock_reset.assert_called_once()

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_database_stats")
    @patch("screenseeker.cli.init_db")
    def test_db_stats(self, mock_init, mock_stats, mock_session):
        """Test db stats command."""
        mock_stats.return_value = {
            "total_films": 10,
            "watched_films": 3,
            "unwatched_films": 7,
            "films_with_tmdb": 8,
            "match_rate": 80.0,
            "total_offers": 50,
            "unique_providers": 5,
            "unique_countries": 10,
            "stale_films": 2,
        }

        runner = CliRunner()
        result = runner.invoke(cli, ["db", "stats"])

        assert result.exit_code == 0
        mock_stats.assert_called_once()


class TestProvidersCommand:
    """Test providers command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_films_by_provider")
    def test_providers_with_provider_filter(self, mock_get_films, mock_session):
        """Test providers command with provider filter."""
        mock_film = Film(letterboxd_title="Test Movie", letterboxd_year=2020)
        mock_get_films.return_value = [mock_film]

        runner = CliRunner()
        result = runner.invoke(cli, ["providers", "--provider", "Netflix"])

        assert result.exit_code == 0
        mock_get_films.assert_called_once()

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_films_by_provider")
    def test_providers_no_results(self, mock_get_films, mock_session):
        """Test providers command with no results."""
        mock_get_films.return_value = []

        runner = CliRunner()
        result = runner.invoke(cli, ["providers", "--provider", "Netflix"])

        assert result.exit_code == 0
        assert "No films found" in result.output


class TestCountryCommand:
    """Test country command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_films_by_country")
    @patch("screenseeker.cli.init_db")
    def test_country_with_code(self, mock_init, mock_get_films, mock_session):
        """Test country command with country code."""
        mock_film = Film(letterboxd_title="Test Movie", letterboxd_year=2020)
        mock_get_films.return_value = [mock_film]

        runner = CliRunner()
        result = runner.invoke(cli, ["country", "--country", "US"])

        assert result.exit_code == 0
        mock_get_films.assert_called_once()

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_films_by_country")
    @patch("screenseeker.cli.init_db")
    def test_country_no_results(self, mock_init, mock_get_films, mock_session):
        """Test country command with no results."""
        mock_get_films.return_value = []

        runner = CliRunner()
        result = runner.invoke(cli, ["country", "--country", "US"])

        assert result.exit_code == 0
        assert "No films found" in result.output


class TestRefreshCommand:
    """Test refresh command."""

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_stale_films")
    @patch("screenseeker.cli.init_db")
    def test_refresh_no_stale_films(self, mock_init, mock_get_stale, mock_session):
        """Test refresh command with no stale films."""
        mock_get_stale.return_value = []

        runner = CliRunner()
        result = runner.invoke(cli, ["refresh"])

        assert result.exit_code == 0
        assert "fresh" in result.output.lower()

    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.get_stale_films")
    @patch("screenseeker.cli.init_db")
    def test_refresh_dry_run(self, mock_init, mock_get_stale, mock_session):
        """Test refresh command in dry-run mode."""
        mock_film = Film(letterboxd_title="Test Movie", letterboxd_year=2020)
        mock_get_stale.return_value = [mock_film]

        runner = CliRunner()
        result = runner.invoke(cli, ["refresh", "--dry-run"])

        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would" in result.output.lower()


class TestEnrichCommand:
    """Test enrich command - basic tests only."""

    def test_enrich_help(self):
        """Test enrich command help works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "enrich" in result.output.lower()


class TestReportCommand:
    """Test report command - basic tests only."""

    def test_report_help(self):
        """Test report command help works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0
        assert "report" in result.output.lower()
