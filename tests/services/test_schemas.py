"""
Tests for the service-layer response schemas.

Two things matter here: nothing may hold an ORM instance past the session, and
listing a library must not issue a query per film.
"""

from datetime import UTC, datetime

from sqlalchemy import event

from screenseeker.database.models import Film, StreamingOffer
from screenseeker.services import library
from screenseeker.services.library import LibraryFilter
from screenseeker.services.models import FilmDetail, FilmSummary, OfferOut


def make_film(session, title="The Matrix", year=1999, tmdb_id=603, offers=2, watched=False):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        tmdb_title=title,
        tmdb_year=year,
        tmdb_release_date="1999-03-31",
        poster_path="/poster.jpg",
        overview="An overview.",
        vote_average=8.7,
        match_confidence="exact",
        date_added=datetime.now(UTC),
        last_checked=datetime.now(UTC),
        watched=watched,
    )
    session.add(film)
    session.flush()

    for i in range(offers):
        session.add(
            StreamingOffer(
                film_id=film.id,
                country_code="FR" if i % 2 == 0 else "US",
                country_name="France" if i % 2 == 0 else "United States",
                provider_id=i,
                provider_name=f"Provider {i}",
                monetization_type="flatrate" if i % 2 == 0 else "rent",
                logo_path=f"/logo{i}.jpg",
                streaming_url=f"https://example.test/{i}",
                checked_at=datetime.now(UTC),
            )
        )
    session.flush()
    return film


class TestOfferOut:
    def test_maps_monetization_type_to_offer_type(self, test_session):
        """The column is monetization_type; everything above it says offer_type."""
        film = make_film(test_session, offers=1)
        offer = OfferOut.from_row(film.streaming_offers[0])

        assert offer.offer_type == "flatrate"
        assert not hasattr(offer, "monetization_type")

    def test_builds_logo_url_from_path(self, test_session):
        film = make_film(test_session, offers=1)
        offer = OfferOut.from_row(film.streaming_offers[0])

        assert offer.logo_path == "/logo0.jpg"
        assert offer.logo.startswith("https://image.tmdb.org/t/p/")
        assert offer.logo.endswith("/logo0.jpg")

    def test_missing_logo_yields_none(self, test_session):
        film = make_film(test_session, offers=1)
        film.streaming_offers[0].logo_path = None
        test_session.flush()

        assert OfferOut.from_row(film.streaming_offers[0]).logo is None


class TestFilmSummary:
    def test_poster_url_built_from_path(self, test_session):
        summary = FilmSummary.from_film(make_film(test_session), offer_count=0)

        assert summary.poster.startswith("https://image.tmdb.org/t/p/")
        assert summary.poster.endswith("/poster.jpg")

    def test_missing_poster_yields_none(self, test_session):
        film = make_film(test_session)
        film.poster_path = None
        test_session.flush()

        assert FilmSummary.from_film(film, offer_count=0).poster is None

    def test_never_checked_counts_as_stale(self, test_session):
        film = make_film(test_session)
        film.last_checked = None
        test_session.flush()

        assert FilmSummary.from_film(film, offer_count=0).is_stale is True

    def test_fresh_film_is_not_stale(self, test_session):
        assert FilmSummary.from_film(make_film(test_session), offer_count=0).is_stale is False


class TestFilmDetail:
    def test_includes_offers(self, test_session):
        film = make_film(test_session, offers=4)
        detail = FilmDetail.from_film(film)

        assert len(detail.offers) == 4
        assert detail.offer_count == 4
        assert detail.overview == "An overview."

    def test_groups_countries_and_providers(self, test_session):
        detail = FilmDetail.from_film(make_film(test_session, offers=4))

        assert detail.countries == ["FR", "US"]
        assert len(detail.providers) == 4
        assert len(detail.offers_in("FR")) == 2

    def test_is_a_film_summary(self, test_session):
        """The detail page reuses every summary field rather than redefining it."""
        detail = FilmDetail.from_film(make_film(test_session))
        assert isinstance(detail, FilmSummary)


class TestDetachedInstanceSafety:
    """
    The bug class that never shows up in a test with an open session and
    always shows up in a template.
    """

    def test_summary_survives_session_close(self, test_session):
        make_film(test_session)
        test_session.commit()

        summaries = library.list_films(test_session, filters=LibraryFilter(watched=False))[0]
        test_session.close()

        for s in summaries:
            assert s.full_title
            assert s.offer_count == 2
            assert s.poster is not None
            assert s.is_stale is False
            _ = s.model_dump()

    def test_detail_survives_session_close(self, test_session):
        film = make_film(test_session, offers=3)
        test_session.commit()
        film_id = film.id

        detail = library.get_detail(test_session, film_id)
        test_session.close()

        assert detail.full_title
        assert len(detail.offers) == 3
        assert detail.countries
        assert detail.providers
        for offer in detail.offers:
            assert offer.provider_name
            assert offer.offer_type
            assert offer.logo is not None
        _ = detail.model_dump()

    def test_watched_toggle_survives_session_close(self, test_session):
        film = make_film(test_session)
        test_session.commit()

        updated = library.set_watched_by_id(test_session, film.id, watched=True)
        test_session.close()

        assert updated.watched is True
        assert updated.full_title


class TestQueryCounts:
    """Listing must not issue a query per film."""

    def count_queries(self, session, fn):
        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            result = fn()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return result, statements

    def test_listing_is_constant_query_count(self, test_session):
        for i in range(12):
            make_film(test_session, title=f"Film {i}", tmdb_id=1000 + i, offers=2)
        test_session.commit()

        summaries, statements = self.count_queries(
            test_session,
            lambda: library.list_films(test_session, filters=LibraryFilter(watched=False))[0],
        )

        assert len(summaries) == 12
        assert all(s.offer_count == 2 for s in summaries)
        # One SELECT for the films, one grouped count for the offers, one
        # join for the member chips.
        assert len(statements) <= 4, f"expected a constant number of queries, got {len(statements)}"

    def test_empty_listing_skips_the_offer_count_query(self, test_session):
        summaries, statements = self.count_queries(
            test_session,
            lambda: library.list_films(test_session, filters=LibraryFilter(watched=False))[0],
        )

        assert summaries == []
        # The total and the page. No grouped offer count, because there are no
        # film ids to count offers for.
        assert len(statements) == 2
