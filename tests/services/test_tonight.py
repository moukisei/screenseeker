"""
Tests for watch.tonight.

The point that matters: Tonight is the watch strategy's best_option, not a SQL
provider filter. TMDB's "Paramount+ Amazon Channel" substring-matches an owned
"Paramount+" but is not it, and a film available only via a reseller name, or
only outside the base country, must not appear.
"""

from datetime import UTC, datetime

from screenseeker.database.models import Film, StreamingOffer
from screenseeker.services import watch


def make_film(session, title, *, tmdb_id, rating=5.0, watched=False, offers=()):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=2000,
        tmdb_id=tmdb_id,
        vote_average=rating,
        watched=watched,
        date_added=datetime.now(UTC),
        last_checked=datetime.now(UTC),
    )
    session.add(film)
    session.flush()
    for i, (country, provider, offer_type) in enumerate(offers):
        session.add(
            StreamingOffer(
                film_id=film.id,
                country_code=country,
                country_name=country,
                provider_id=100 + i,
                provider_name=provider,
                monetization_type=offer_type,
                streaming_url=f"https://example.test/{provider.lower()}/{film.id}",
                checked_at=datetime.now(UTC),
            )
        )
    session.flush()
    return film


PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {"provider_names": ["Netflix"], "vpn_enabled": True, "available_countries": "all"},
        {
            "provider_names": ["Canal+"],
            "vpn_enabled": False,
            "available_countries": ["FR"],
            "bundle_includes": ["Paramount+"],
        },
    ],
    "vpn_country_priority": ["US", "GB"],
    "max_vpn_suggestions": 3,
}


def picked_titles(session):
    return [p.film.title for p in watch.tonight(session, profile=PROFILE)]


class TestTonight:
    def test_owned_flatrate_in_base_country_is_a_pick(self, test_session):
        make_film(test_session, "Ready", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        test_session.commit()

        picks = watch.tonight(test_session, profile=PROFILE)

        assert [p.film.title for p in picks] == ["Ready"]
        assert picks[0].best_option.provider == "Netflix"
        assert picks[0].best_option.vpn_required is False

    def test_watched_films_are_excluded(self, test_session):
        make_film(
            test_session, "Seen", tmdb_id=1, watched=True, offers=[("FR", "Netflix", "flatrate")]
        )
        test_session.commit()

        assert picked_titles(test_session) == []

    def test_offer_outside_the_base_country_is_not_tonight(self, test_session):
        """It might be VPN-watchable, but Tonight is base-country, no VPN."""
        make_film(test_session, "Abroad", tmdb_id=1, offers=[("US", "Netflix", "flatrate")])
        test_session.commit()

        assert picked_titles(test_session) == []

    def test_rent_and_buy_do_not_count(self, test_session):
        make_film(test_session, "Rentable", tmdb_id=1, offers=[("FR", "Netflix", "rent")])
        test_session.commit()

        assert picked_titles(test_session) == []

    def test_a_provider_you_do_not_own_is_not_tonight(self, test_session):
        make_film(test_session, "Elsewhere", tmdb_id=1, offers=[("FR", "Disney Plus", "flatrate")])
        test_session.commit()

        assert picked_titles(test_session) == []

    def test_reseller_channel_name_does_not_count_as_owned(self, test_session):
        """
        The exact over-count a SQL substring filter would produce.

        "Paramount+ Amazon Channel" contains "Paramount+", but it is a reseller
        listing, not the bundle the profile holds. The strategy's fuzzy match
        rejects it; Tonight must too.
        """
        make_film(
            test_session,
            "Reseller only",
            tmdb_id=1,
            offers=[("FR", "Paramount+ Amazon Channel", "flatrate")],
        )
        test_session.commit()

        assert picked_titles(test_session) == []

    def test_a_bundled_provider_is_a_pick(self, test_session):
        """Canal+ bundles Paramount+, so a Paramount+ flatrate in FR is watchable."""
        make_film(test_session, "Bundled", tmdb_id=1, offers=[("FR", "Paramount+", "flatrate")])
        test_session.commit()

        picks = watch.tonight(test_session, profile=PROFILE)

        assert [p.film.title for p in picks] == ["Bundled"]

    def test_picks_are_ranked_best_first(self, test_session):
        make_film(
            test_session, "Mediocre", tmdb_id=1, rating=5.0, offers=[("FR", "Netflix", "flatrate")]
        )
        make_film(
            test_session, "Great", tmdb_id=2, rating=9.0, offers=[("FR", "Netflix", "flatrate")]
        )
        make_film(
            test_session, "Unrated", tmdb_id=3, rating=None, offers=[("FR", "Netflix", "flatrate")]
        )
        test_session.commit()

        assert picked_titles(test_session) == ["Great", "Mediocre", "Unrated"]

    def test_empty_when_no_subscriptions(self, test_session):
        make_film(test_session, "Ready", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        test_session.commit()

        bare = {**PROFILE, "subscriptions": []}
        assert watch.tonight(test_session, profile=bare) == []

    def test_marks_carry_the_deep_link_from_the_offer(self, test_session):
        make_film(test_session, "Ready", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        # A film with no owned base-country option gets no mark.
        make_film(test_session, "Nope", tmdb_id=2, offers=[("US", "Netflix", "flatrate")])
        test_session.commit()

        ready = test_session.query(Film).filter(Film.letterboxd_title == "Ready").one()
        nope = test_session.query(Film).filter(Film.letterboxd_title == "Nope").one()

        marks = watch.tonight_marks(test_session, [ready.id, nope.id], profile=PROFILE)

        assert nope.id not in marks
        assert marks[ready.id].provider == "Netflix"
        # make_film gives each offer a streaming_url; the mark surfaces it.
        assert marks[ready.id].url and str(ready.id) in marks[ready.id].url

    def test_marks_of_no_ids_is_empty(self, test_session):
        assert watch.tonight_marks(test_session, [], profile=PROFILE) == {}

    def test_constant_query_count(self, test_session):
        """Candidates are narrowed in SQL, then confirmed in memory - no per-film query."""
        from sqlalchemy import event

        for i in range(15):
            make_film(test_session, f"Film {i}", tmdb_id=i, offers=[("FR", "Netflix", "flatrate")])
        test_session.commit()

        statements = []
        engine = test_session.get_bind()

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            picks = watch.tonight(test_session, profile=PROFILE)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(picks) == 15
        # Candidate films, their offers, the offer counts, the member chips.
        # Not one per film.
        assert len(statements) <= 5, f"got {len(statements)} queries"
