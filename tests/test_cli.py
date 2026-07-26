"""
Tests for the CLI.

The CLI is plumbing: set up, keep the mirror fresh, start the server. Browsing
and filtering live in the web UI and are tested there.
"""

from unittest.mock import patch

from click.testing import CliRunner

from screenseeker.cli import cli
from screenseeker.services import FilmSummary
from screenseeker.services.enrichment import EnrichmentReport, FilmError
from screenseeker.services.sync import SyncReport

MOCK_CFG = {
    "letterboxd": {"username": "testuser"},
    "tmdb": {"api_key": "test_key", "rate_limit": 5.0, "language": "en-US"},
    "profile": {
        "base_country": "FR",
        "subscriptions": [],
        "vpn_country_priority": [],
        "max_vpn_suggestions": 3,
    },
}


def make_summary(title="Test Movie", year=2020, **overrides):
    fields = {
        "id": 1,
        "title": title,
        "year": year,
        "full_title": f"{title} ({year})" if year else title,
        "tmdb_id": 123,
    }
    fields.update(overrides)
    return FilmSummary(**fields)


class TestCommandSurface:
    """The CLI is deliberately small. Commands removed must stay removed."""

    def test_help(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ScreenSeeker" in result.output

    def test_version(self):
        assert CliRunner().invoke(cli, ["--version"]).exit_code == 0

    @classmethod
    def commands(cls):
        return {"config", "sync", "refresh", "serve"}

    def test_exposes_only_the_plumbing_commands(self):
        result = CliRunner().invoke(cli, ["--help"])
        for name in self.commands():
            assert name in result.output

    def test_browsing_commands_are_gone(self):
        """These moved to the web UI; a stub left behind would be a trap."""
        for removed in ("search", "providers", "country", "watchlist", "watched", "report"):
            result = CliRunner().invoke(cli, [removed, "--help"])
            assert result.exit_code != 0, f"{removed} should no longer exist"

    def test_enrich_is_gone(self):
        """A never-checked film is stale, so refresh already covers it."""
        assert CliRunner().invoke(cli, ["enrich", "--help"]).exit_code != 0

    def test_db_group_is_gone(self):
        """Schema is Alembic's job, and reset was what destroyed the database."""
        assert CliRunner().invoke(cli, ["db", "--help"]).exit_code != 0


class TestConfigCommands:
    def test_config_help(self):
        assert CliRunner().invoke(cli, ["config", "--help"]).exit_code == 0

    @patch("screenseeker.cli.user_config.config_exists", return_value=False)
    def test_edit_without_config_fails(self, mock_exists):
        result = CliRunner().invoke(cli, ["config", "edit"])
        assert result.exit_code == 1
        assert "config init" in result.output

    def test_path_reports_locations(self):
        result = CliRunner().invoke(cli, ["config", "path"])
        assert result.exit_code == 0
        assert "config:" in result.output
        assert "database:" in result.output


class TestSyncCommand:
    def test_help(self):
        assert CliRunner().invoke(cli, ["sync", "--help"]).exit_code == 0

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.build_scraper")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.ingest_watchlist")
    def test_reports_counts(self, mock_ingest, mock_session, mock_scraper, mock_init, mock_cfg):
        mock_ingest.return_value = SyncReport(
            scraped=10, added=3, existing=7, pages_scraped=2, source="html"
        )

        result = CliRunner().invoke(cli, ["sync"])

        assert result.exit_code == 0
        assert "Added: 3" in result.output
        assert "Already known: 7" in result.output

    @patch(
        "screenseeker.cli.user_config.load_config",
        return_value={"letterboxd": {"username": ""}, "tmdb": {}},
    )
    def test_requires_username(self, mock_cfg):
        result = CliRunner().invoke(cli, ["sync"])
        assert result.exit_code == 1
        assert "username not configured" in result.output

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.build_scraper")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.ingest_watchlist")
    def test_scrape_failure_exits_nonzero(
        self, mock_ingest, mock_session, mock_scraper, mock_init, mock_cfg
    ):
        mock_ingest.return_value = SyncReport(
            scraped=0, success=False, error_message="Letterboxd returned 503"
        )

        result = CliRunner().invoke(cli, ["sync"])

        assert result.exit_code == 1
        assert "503" in result.output


class TestRefreshCommand:
    def test_help(self):
        assert CliRunner().invoke(cli, ["refresh", "--help"]).exit_code == 0

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrichment.select_stale")
    def test_nothing_stale(self, mock_select, mock_session, mock_init, mock_cfg):
        mock_select.return_value = ([], 0)

        result = CliRunner().invoke(cli, ["refresh"])

        assert result.exit_code == 0
        assert "fresh" in result.output.lower()

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrichment.select_stale")
    def test_dry_run_makes_no_changes(self, mock_select, mock_session, mock_init, mock_cfg):
        mock_select.return_value = ([make_summary(cache_age_days=30)], 1)

        result = CliRunner().invoke(cli, ["refresh", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.output

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrichment.select_stale")
    def test_never_checked_is_labelled(self, mock_select, mock_session, mock_init, mock_cfg):
        mock_select.return_value = ([make_summary(cache_age_days=None)], 1)

        result = CliRunner().invoke(cli, ["refresh", "--dry-run"])

        assert "never checked" in result.output

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrichment.select_stale")
    @patch("screenseeker.cli.build_enricher")
    @patch("screenseeker.cli.enrich_films")
    def test_reports_failures(
        self, mock_enrich, mock_build, mock_select, mock_session, mock_init, mock_cfg
    ):
        mock_select.return_value = ([make_summary()], 1)
        mock_enrich.return_value = EnrichmentReport(
            total=2,
            succeeded=1,
            failed=1,
            errors=[FilmError(film_id=2, title="Broken (2020)", error="404 from TMDB")],
        )

        result = CliRunner().invoke(cli, ["refresh", "--yes"])

        assert result.exit_code == 0
        assert "Refreshed 1" in result.output
        assert "Broken (2020)" in result.output
        assert "404 from TMDB" in result.output

    @patch("screenseeker.cli.user_config.load_config", return_value=MOCK_CFG)
    @patch("screenseeker.cli.init_db")
    @patch("screenseeker.cli.get_session")
    @patch("screenseeker.cli.enrichment.select_stale")
    def test_declining_the_prompt_does_nothing(
        self, mock_select, mock_session, mock_init, mock_cfg
    ):
        mock_select.return_value = ([make_summary()], 1)

        result = CliRunner().invoke(cli, ["refresh"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestServeCommand:
    def test_help(self):
        result = CliRunner().invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "web" in result.output.lower()
