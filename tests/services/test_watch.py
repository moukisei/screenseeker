"""
Tests for the watch use case.

It is a read: the TMDB enricher lives in the refresh job, so serving a page
cannot make an outbound request.
"""

from datetime import UTC, datetime

from screenseeker.database.models import Film, StreamingOffer
from screenseeker.services.watch import find_watch_options, watch_strategy_for

PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {"provider_names": ["Netflix"], "vpn_enabled": True, "available_countries": "all"}
    ],
    "vpn_country_priority": ["US", "GB"],
    "max_vpn_suggestions": 3,
}


def make_film(session, *, title="The Matrix", year=1999, tmdb_id=603, offers=()):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        tmdb_title=title,
        tmdb_year=year,
        poster_path="/poster.jpg",
        match_confidence="exact",
        date_added=datetime.now(UTC),
        last_checked=datetime.now(UTC),
    )
    session.add(film)
    session.flush()

    for provider, country, country_name, offer_type in offers:
        session.add(
            StreamingOffer(
                film_id=film.id,
                country_code=country,
                country_name=country_name,
                provider_id=1,
                provider_name=provider,
                monetization_type=offer_type,
                checked_at=datetime.now(UTC),
            )
        )
    session.flush()
    return film


class TestFindWatchOptions:
    def test_returns_detail_and_strategy(self, test_session):
        film = make_film(test_session, offers=[("Netflix", "FR", "France", "flatrate")])

        detail, strategy = find_watch_options(test_session, film.id, profile=PROFILE)

        assert detail.full_title == "The Matrix (1999)"
        assert strategy.best_option is not None
        assert strategy.best_option.provider == "Netflix"
        assert strategy.best_option.vpn_required is False

    def test_unknown_film_returns_none(self, test_session):
        assert find_watch_options(test_session, 999_999, profile=PROFILE) is None

    def test_survives_session_close(self, test_session):
        film = make_film(test_session, offers=[("Netflix", "FR", "France", "flatrate")])
        test_session.commit()

        detail, strategy = find_watch_options(test_session, film.id, profile=PROFILE)
        test_session.close()

        assert detail.full_title
        assert len(detail.offers) == 1
        assert strategy.best_option.provider == "Netflix"


class TestWatchStrategyFromCachedOffers:
    """The analyser must work from persisted offers, not just fresh TMDB ones."""

    def test_vpn_option_when_not_in_base_country(self, test_session):
        film = make_film(test_session, offers=[("Netflix", "US", "United States", "flatrate")])
        detail, strategy = find_watch_options(test_session, film.id, profile=PROFILE)

        assert strategy.best_option is None
        assert len(strategy.vpn_options) == 1
        assert strategy.vpn_options[0].vpn_required is True

    def test_rent_in_base_country_is_an_alternative(self, test_session):
        film = make_film(test_session, offers=[("Apple TV", "FR", "France", "rent")])
        _, strategy = find_watch_options(test_session, film.id, profile=PROFILE)

        assert strategy.best_option is None
        assert len(strategy.base_country_alternatives) == 1
        assert strategy.base_country_alternatives[0].offer_type == "rent"

    def test_unsubscribed_provider_is_not_owned(self, test_session):
        film = make_film(test_session, offers=[("Disney Plus", "FR", "France", "flatrate")])
        _, strategy = find_watch_options(test_session, film.id, profile=PROFILE)

        assert strategy.best_option is None
        assert len(strategy.not_owned_options) == 1

    def test_no_offers_yields_empty_strategy(self, test_session):
        film = make_film(test_session)
        _, strategy = find_watch_options(test_session, film.id, profile=PROFILE)

        assert strategy.has_any_option() is False

    def test_strategy_helper_takes_a_bare_offer_list(self, test_session):
        film = make_film(test_session, offers=[("Netflix", "FR", "France", "flatrate")])
        from screenseeker.services.library import get_detail

        detail = get_detail(test_session, film.id)
        strategy = watch_strategy_for(detail.offers, PROFILE)

        assert strategy.best_option.provider == "Netflix"
