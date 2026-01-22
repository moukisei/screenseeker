"""
Tests for enrich.py module functions.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from screenseeker import config
from screenseeker.enrich import (
    display_watch_strategy,
    main,
    parse_title_year,
    save_result_to_json,
)
from screenseeker.enrichers.enrichment_models import EnrichmentResult, TMDBMovieInfo
from screenseeker.enrichers.watch_strategy import WatchOption, WatchStrategy


class TestParseTitleYear:
    """Test parse_title_year function."""

    def test_parse_with_year(self):
        """Test parsing title with year in parentheses."""
        title, year = parse_title_year("The Matrix (1999)")
        assert title == "The Matrix"
        assert year == 1999

    def test_parse_without_year(self):
        """Test parsing title without year."""
        title, year = parse_title_year("The Matrix")
        assert title == "The Matrix"
        assert year is None

    def test_parse_with_extra_spaces(self):
        """Test parsing title with extra spaces."""
        title, year = parse_title_year("  The Matrix  (1999)  ")
        assert title == "The Matrix"
        assert year == 1999

    def test_parse_complex_title(self):
        """Test parsing complex title with special characters."""
        title, year = parse_title_year("The Lord of the Rings: The Fellowship of the Ring (2001)")
        assert title == "The Lord of the Rings: The Fellowship of the Ring"
        assert year == 2001

    def test_parse_title_with_parentheses_not_year(self):
        """Test parsing title with parentheses that don't contain year."""
        title, year = parse_title_year("Some Movie (Director's Cut)")
        assert title == "Some Movie (Director's Cut)"
        assert year is None


class TestDisplayWatchStrategy:
    """Test display_watch_strategy function."""

    @pytest.fixture
    def mock_logger(self):
        """Mock logger for testing."""
        with patch("screenseeker.enrich.logger") as mock:
            yield mock

    @pytest.fixture
    def sample_movie(self):
        """Create sample movie info."""
        return TMDBMovieInfo(
            tmdb_id=603,
            title="The Matrix",
            original_title="The Matrix",
            year=1999,
            release_date="1999-03-31",
            overview="A computer hacker learns...",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.7,
            popularity=100.0,
            query_title="The Matrix",
        )

    def test_display_failed_result(self, mock_logger, sample_movie):
        """Test displaying failed enrichment result."""
        result = EnrichmentResult(
            success=False,
            tmdb_movie=None,
            streaming_offers=[],
            match_confidence="none",
            error_message="API Error",
            query_title="The Matrix",
            query_year=1999,
        )
        strategy = WatchStrategy()

        display_watch_strategy(result, strategy)

        # Verify error was logged
        mock_logger.error.assert_called()
        assert any("failed" in str(call).lower() for call in mock_logger.error.call_args_list)

    def test_display_no_match(self, mock_logger, sample_movie):
        """Test displaying result with no TMDB match."""
        result = EnrichmentResult(
            success=True,
            tmdb_movie=None,
            streaming_offers=[],
            match_confidence="none",
            error_message=None,
            query_title="Unknown Movie",
        )
        strategy = WatchStrategy()

        display_watch_strategy(result, strategy)

        # Verify warning was logged
        mock_logger.warning.assert_called()
        assert any("No match" in str(call) for call in mock_logger.warning.call_args_list)

    def test_display_no_options_available(self, mock_logger, sample_movie):
        """Test displaying result when movie is not available."""
        result = EnrichmentResult(
            success=True,
            tmdb_movie=sample_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
            total_countries=50,
            total_providers=10,
        )
        strategy = WatchStrategy()

        display_watch_strategy(result, strategy)

        # Verify not available message
        assert any("NOT AVAILABLE" in str(call) for call in mock_logger.warning.call_args_list)

    def test_display_with_best_option(self, mock_logger, sample_movie):
        """Test displaying result with best watch option."""
        result = EnrichmentResult(
            success=True,
            tmdb_movie=sample_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

        best_option = WatchOption(
            country_code="FR",
            country_name="France",
            provider="Netflix",
            offer_type="flatrate",
            via_bundle=None,
            vpn_required=False,
            priority_score=1,
        )

        strategy = WatchStrategy(best_option=best_option)

        display_watch_strategy(result, strategy)

        # Verify watch now message
        assert any("WATCH NOW" in str(call) for call in mock_logger.info.call_args_list)

    def test_display_with_vpn_options(self, mock_logger, sample_movie):
        """Test displaying result with VPN options."""
        result = EnrichmentResult(
            success=True,
            tmdb_movie=sample_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

        vpn_option = WatchOption(
            country_code="US",
            country_name="United States",
            provider="Netflix",
            offer_type="flatrate",
            via_bundle=None,
            vpn_required=True,
            priority_score=2,
        )

        strategy = WatchStrategy(vpn_options=[vpn_option])

        display_watch_strategy(result, strategy)

        # Verify VPN options message
        assert any("VPN OPTIONS" in str(call) for call in mock_logger.info.call_args_list)

    def test_display_with_rent_buy_options(self, mock_logger, sample_movie):
        """Test displaying result with rent/buy options."""
        result = EnrichmentResult(
            success=True,
            tmdb_movie=sample_movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

        rent_option = WatchOption(
            country_code="FR",
            country_name="France",
            provider="Amazon Video",
            offer_type="rent",
            via_bundle=None,
            vpn_required=False,
            priority_score=3,
        )
        buy_option = WatchOption(
            country_code="FR",
            country_name="France",
            provider="iTunes",
            offer_type="buy",
            via_bundle=None,
            vpn_required=False,
            priority_score=4,
        )

        strategy = WatchStrategy(base_country_alternatives=[rent_option, buy_option])

        display_watch_strategy(result, strategy)

        # Verify rent/buy message
        assert any("RENT/BUY" in str(call) for call in mock_logger.info.call_args_list)


class TestSaveResultToJson:
    """Test save_result_to_json function."""

    @pytest.fixture
    def sample_result(self):
        """Create sample enrichment result."""
        movie = TMDBMovieInfo(
            tmdb_id=603,
            title="The Matrix",
            original_title="The Matrix",
            year=1999,
            release_date="1999-03-31",
            overview="A computer hacker learns...",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.7,
            popularity=100.0,
            query_title="The Matrix",
        )

        return EnrichmentResult(
            success=True,
            tmdb_movie=movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

    def test_save_result_creates_file(self, sample_result, tmp_path):
        """Test that save_result_to_json creates JSON file."""
        with patch.object(config, "OUTPUT_DIR", tmp_path):
            with patch("screenseeker.enrich.logger"):
                save_result_to_json(sample_result, "test_output.json")

                output_file = tmp_path / "test_output.json"
                assert output_file.exists()

                # Verify JSON content
                with open(output_file) as f:
                    data = json.load(f)
                    assert data["query"]["title"] == "The Matrix"
                    assert data["match_confidence"] == "exact"

    def test_save_result_creates_parent_dirs(self, sample_result, tmp_path):
        """Test that save_result_to_json creates parent directories."""
        with patch.object(config, "OUTPUT_DIR", tmp_path):
            with patch("screenseeker.enrich.logger"):
                save_result_to_json(sample_result, "subdir/test_output.json")

                output_file = tmp_path / "subdir" / "test_output.json"
                assert output_file.exists()


class TestMain:
    """Test main function."""

    @patch("screenseeker.enrich.sys.argv", ["enrich.py"])
    @patch("screenseeker.enrich.input")
    @patch("screenseeker.enrich.TMDBEnricher")
    @patch("screenseeker.enrich.WatchStrategyAnalyzer")
    def test_main_interactive_mode(self, mock_analyzer, mock_enricher, mock_input):
        """Test main function in interactive mode."""
        # Mock user input
        mock_input.return_value = "The Matrix (1999)"

        # Mock enricher
        mock_enricher_instance = MagicMock()
        mock_enricher.return_value.__enter__.return_value = mock_enricher_instance

        movie = TMDBMovieInfo(
            tmdb_id=603,
            title="The Matrix",
            original_title="The Matrix",
            year=1999,
            release_date="1999-03-31",
            overview="A computer hacker learns...",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.7,
            popularity=100.0,
            query_title="The Matrix",
        )

        result = EnrichmentResult(
            success=True,
            tmdb_movie=movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

        mock_enricher_instance.enrich.return_value = result

        # Mock analyzer
        mock_analyzer_instance = MagicMock()
        mock_analyzer.return_value = mock_analyzer_instance
        mock_analyzer_instance.analyze.return_value = WatchStrategy()

        with patch("screenseeker.enrich.display_watch_strategy"):
            with patch("screenseeker.enrich.save_result_to_json"):
                exit_code = main()

        assert exit_code == 0
        mock_enricher_instance.enrich.assert_called_once_with("The Matrix", 1999)

    @patch("screenseeker.enrich.sys.argv", ["enrich.py", "The Matrix", "(1999)"])
    @patch("screenseeker.enrich.TMDBEnricher")
    @patch("screenseeker.enrich.WatchStrategyAnalyzer")
    def test_main_with_args(self, mock_analyzer, mock_enricher):
        """Test main function with command line arguments."""
        # Mock enricher
        mock_enricher_instance = MagicMock()
        mock_enricher.return_value.__enter__.return_value = mock_enricher_instance

        movie = TMDBMovieInfo(
            tmdb_id=603,
            title="The Matrix",
            original_title="The Matrix",
            year=1999,
            release_date="1999-03-31",
            overview="A computer hacker learns...",
            original_language="en",
            poster_path="/test.jpg",
            backdrop_path=None,
            vote_average=8.7,
            popularity=100.0,
            query_title="The Matrix",
        )

        result = EnrichmentResult(
            success=True,
            tmdb_movie=movie,
            streaming_offers=[],
            match_confidence="exact",
            error_message=None,
            query_title="The Matrix",
            query_year=1999,
        )

        mock_enricher_instance.enrich.return_value = result

        # Mock analyzer
        mock_analyzer_instance = MagicMock()
        mock_analyzer.return_value = mock_analyzer_instance
        mock_analyzer_instance.analyze.return_value = WatchStrategy()

        with patch("screenseeker.enrich.display_watch_strategy"):
            with patch("screenseeker.enrich.save_result_to_json"):
                exit_code = main()

        assert exit_code == 0

    @patch("screenseeker.enrich.sys.argv", ["enrich.py"])
    @patch("screenseeker.enrich.input")
    def test_main_empty_input(self, mock_input):
        """Test main function with empty input."""
        mock_input.return_value = ""

        exit_code = main()

        assert exit_code == 1

    @patch("screenseeker.enrich.sys.argv", ["enrich.py"])
    @patch("screenseeker.enrich.input")
    def test_main_keyboard_interrupt(self, mock_input):
        """Test main function handles keyboard interrupt."""
        mock_input.side_effect = KeyboardInterrupt()

        exit_code = main()

        assert exit_code == 0

    @patch.object(config, "TMDB_API_KEY", "your_tmdb_api_key_here")
    def test_main_no_api_key(self):
        """Test main function with missing API key."""
        exit_code = main()
        assert exit_code == 1

    @patch("screenseeker.enrich.sys.argv", ["enrich.py", "The Matrix"])
    @patch("screenseeker.enrich.TMDBEnricher")
    def test_main_enricher_error(self, mock_enricher):
        """Test main function handles enricher errors."""
        mock_enricher.return_value.__enter__.side_effect = ValueError("Invalid API key")

        exit_code = main()

        assert exit_code == 1

    @patch("screenseeker.enrich.sys.argv", ["enrich.py", "The Matrix"])
    @patch("screenseeker.enrich.TMDBEnricher")
    @patch("screenseeker.enrich.WatchStrategyAnalyzer")
    def test_main_failed_enrichment(self, mock_analyzer, mock_enricher):
        """Test main function with failed enrichment."""
        # Mock enricher
        mock_enricher_instance = MagicMock()
        mock_enricher.return_value.__enter__.return_value = mock_enricher_instance

        result = EnrichmentResult(
            success=False,
            tmdb_movie=None,
            streaming_offers=[],
            match_confidence="none",
            error_message="Not found",
            query_title="The Matrix",
        )

        mock_enricher_instance.enrich.return_value = result

        # Mock analyzer
        mock_analyzer_instance = MagicMock()
        mock_analyzer.return_value = mock_analyzer_instance
        mock_analyzer_instance.analyze.return_value = WatchStrategy()

        with patch("screenseeker.enrich.display_watch_strategy"):
            exit_code = main()

        assert exit_code == 1
