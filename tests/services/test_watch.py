"""
Tests for the watch use case.

The cache assertions here are the point: before this service existed the
`watch` path called TMDB on every invocation regardless of freshness.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from screenseeker.database.models import Film, StreamingOffer
from screenseeker.enrichers.enrichment_models import EnrichmentResult
from screenseeker.enrichers.enrichment_models import StreamingOffer as PydanticOffer
from screenseeker.enrichers.enrichment_models import TMDBMovieInfo
from screenseeker.exceptions import ConfigurationError
from screenseeker.services.watch import (
    build_enrichment_from_film,
    find_watch_options,
    parse_query,
)

PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {"provider_names": ["Netflix"], "vpn_enabled": True, "available_countries": "all"}
    ],
    "vpn_country_priority": ["US", "GB"],
    "max_vpn_suggestions": 3,
}


def make_film(session, *, last_checked, title="The Matrix", year=1999, tmdb_id=603):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        tmdb_title=title,
        tmdb_year=year,
        tmdb_release_date="1999-03-31",
        poster_path="/poster.jpg",
        overview="A hacker learns the truth.",
        vote_average=8.7,
        match_confidence="exact",
        year_mismatch=False,
        date_added=datetime.now(UTC),
        last_checked=last_checked,
    )
    session.add(film)
    session.flush()

    session.add(
        StreamingOffer(
            film_id=film.id,
            country_code="FR",
            country_name="France",
            provider_id=8,
            provider_name="Netflix",
            monetization_type="flatrate",
            logo_path="/netflix.jpg",
            checked_at=datetime.now(UTC),
        )
    )
    session.flush()
    return film


def make_enricher(tmdb_id=603, title="The Matrix", year=1999):
    """An enricher whose enrich() records that it was called."""
    enricher = MagicMock()
    enricher.enrich.return_value = EnrichmentResult(
        query_title=title,
        query_year=year,
        tmdb_movie=TMDBMovieInfo(
            tmdb_id=tmdb_id,
            title=title,
            original_title=title,
            release_date="1999-03-31",
            year=year,
            original_language="en",
            poster_path="/poster.jpg",
            vote_average=8.7,
        ),
        match_confidence="exact",
        streaming_offers=[
            PydanticOffer(
                country_code="FR",
                country_name="France",
                provider_id=8,
                provider_name="Netflix",
                offer_type="flatrate",
            )
        ],
    )
    return enricher


class TestParseQuery:
    def test_extracts_year_from_title(self):
        assert parse_query("The Matrix (1999)") == ("The Matrix", 1999)

    def test_title_without_year(self):
        assert parse_query("The Matrix") == ("The Matrix", None)

    def test_explicit_year_wins(self):
        assert parse_query("The Matrix (1999)", 2003) == ("The Matrix (1999)", 2003)


class TestCacheBehaviour:
    def test_fresh_film_does_not_call_tmdb(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC))
        enricher = make_enricher()

        result = find_watch_options(
            test_session, "The Matrix", 1999, profile=PROFILE, enricher=enricher
        )

        enricher.enrich.assert_not_called()
        assert result.from_cache is True
        assert result.enrichment.tmdb_movie.tmdb_id == 603

    def test_stale_film_calls_tmdb(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC) - timedelta(days=30))
        enricher = make_enricher()

        result = find_watch_options(
            test_session, "The Matrix", 1999, profile=PROFILE, enricher=enricher
        )

        enricher.enrich.assert_called_once()
        assert result.from_cache is False

    def test_force_refresh_bypasses_fresh_cache(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC))
        enricher = make_enricher()

        result = find_watch_options(
            test_session,
            "The Matrix",
            1999,
            profile=PROFILE,
            enricher=enricher,
            force_refresh=True,
        )

        enricher.enrich.assert_called_once()
        assert result.from_cache is False

    def test_never_checked_film_calls_tmdb(self, test_session):
        make_film(test_session, last_checked=None)
        enricher = make_enricher()

        find_watch_options(test_session, "The Matrix", 1999, profile=PROFILE, enricher=enricher)

        enricher.enrich.assert_called_once()

    def test_unknown_film_calls_tmdb(self, test_session):
        enricher = make_enricher()

        find_watch_options(test_session, "Arrival", 2016, profile=PROFILE, enricher=enricher)

        enricher.enrich.assert_called_once()

    def test_ttl_is_configurable(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC) - timedelta(days=3))
        enricher = make_enricher()

        find_watch_options(
            test_session, "The Matrix", 1999, profile=PROFILE, enricher=enricher, ttl_days=1
        )

        enricher.enrich.assert_called_once()

    def test_cache_miss_without_enricher_raises(self, test_session):
        with pytest.raises(ConfigurationError):
            find_watch_options(test_session, "Arrival", 2016, profile=PROFILE)


class TestWatchResult:
    def test_strategy_is_analysed_from_cached_offers(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC))

        result = find_watch_options(test_session, "The Matrix", 1999, profile=PROFILE)

        assert result.from_cache is True
        assert result.strategy.best_option is not None
        assert result.strategy.best_option.provider == "Netflix"
        assert result.strategy.best_option.vpn_required is False

    def test_survives_session_close(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC))
        result = find_watch_options(test_session, "The Matrix", 1999, profile=PROFILE)

        test_session.close()

        # Nothing below may touch a detached ORM instance.
        assert result.query_title == "The Matrix"
        assert result.enrichment.tmdb_movie.title == "The Matrix"
        assert len(result.enrichment.streaming_offers) == 1
        assert result.found is True

    def test_cache_age_reported(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC) - timedelta(days=2))
        enricher = make_enricher()

        result = find_watch_options(
            test_session, "The Matrix", 1999, profile=PROFILE, enricher=enricher, ttl_days=30
        )

        assert result.cache_age_seconds == pytest.approx(2 * 86400, rel=0.01)

    def test_parses_year_from_title_argument(self, test_session):
        make_film(test_session, last_checked=datetime.now(UTC))

        result = find_watch_options(test_session, "The Matrix (1999)", profile=PROFILE)

        assert result.query_year == 1999
        assert result.from_cache is True


class TestBuildEnrichmentFromFilm:
    def test_restores_offers_and_counts(self, test_session):
        film = make_film(test_session, last_checked=datetime.now(UTC))

        enrichment = build_enrichment_from_film(film, "The Matrix", 1999)

        assert enrichment.success is True
        assert enrichment.match_confidence == "exact"
        assert enrichment.total_countries == 1
        assert enrichment.total_providers == 1
        assert enrichment.streaming_offers[0].offer_type == "flatrate"

    def test_restores_presentation_fields(self, test_session):
        film = make_film(test_session, last_checked=datetime.now(UTC))

        movie = build_enrichment_from_film(film, "The Matrix").tmdb_movie

        assert movie.poster_path == "/poster.jpg"
        assert movie.overview == "A hacker learns the truth."
        assert movie.vote_average == 8.7
        # Not persisted, so not invented.
        assert movie.original_title is None
        assert movie.original_language is None
