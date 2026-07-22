"""
Tests for library.list_page.

The grid depends on LIMIT and ORDER BY being in SQL rather than applied to a
fully loaded list, and on the ordering being total - otherwise a row can appear
on two pages or on none.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from screenseeker.database.models import Film
from screenseeker.services import library


def make_film(session, title, *, year=2000, rating=5.0, added_days_ago=0, tmdb_id=None):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        vote_average=rating,
        date_added=datetime.now(UTC) - timedelta(days=added_days_ago),
    )
    session.add(film)
    session.flush()
    return film


def titles(page):
    return [f.title for f in page]


class TestPaging:
    def test_pages_partition_the_library(self, test_session):
        for i in range(5):
            make_film(test_session, f"Film {i}", added_days_ago=i)
        test_session.commit()

        seen = []
        for page in (1, 2, 3):
            films, total = library.list_page(test_session, page=page, per_page=2)
            assert total == 5
            seen.extend(titles(films))

        assert seen == ["Film 0", "Film 1", "Film 2", "Film 3", "Film 4"]

    def test_page_past_the_end_is_empty_not_an_error(self, test_session):
        make_film(test_session, "Only")
        test_session.commit()

        films, total = library.list_page(test_session, page=99, per_page=10)

        assert films == []
        assert total == 1

    def test_ties_are_broken_so_pages_do_not_overlap(self, test_session):
        added = datetime.now(UTC)
        for i in range(6):
            film = make_film(test_session, f"Same {i}")
            film.date_added = added  # every row shares the sort key
        test_session.commit()

        first, _ = library.list_page(test_session, page=1, per_page=3)
        second, _ = library.list_page(test_session, page=2, per_page=3)

        assert set(titles(first)).isdisjoint(titles(second))
        assert len(set(titles(first) + titles(second))) == 6


class TestSorting:
    def test_unknown_key_falls_back_to_the_default(self, test_session):
        make_film(test_session, "Older", added_days_ago=5)
        make_film(test_session, "Newer", added_days_ago=1)
        test_session.commit()

        films, _ = library.list_page(test_session, sort="nonsense")

        assert titles(films) == ["Newer", "Older"]

    def test_title_sorts_alphabetically(self, test_session):
        for title in ("Zodiac", "Amélie", "Memento"):
            make_film(test_session, title)
        test_session.commit()

        films, _ = library.list_page(test_session, sort="title")

        assert titles(films) == ["Amélie", "Memento", "Zodiac"]

    def test_unknown_years_sort_last_not_first(self, test_session):
        make_film(test_session, "Undated", year=None)
        make_film(test_session, "Recent", year=2020)
        make_film(test_session, "Ancient", year=1950)
        test_session.commit()

        films, _ = library.list_page(test_session, sort="year")

        assert titles(films) == ["Recent", "Ancient", "Undated"]

    def test_unrated_films_sort_last(self, test_session):
        make_film(test_session, "Unrated", rating=None)
        make_film(test_session, "Great", rating=9.0)
        make_film(test_session, "Poor", rating=2.0)
        test_session.commit()

        films, _ = library.list_page(test_session, sort="rating")

        assert titles(films) == ["Great", "Poor", "Unrated"]


class TestQueryCost:
    def test_a_page_costs_a_constant_number_of_queries(self, test_session):
        for i in range(30):
            make_film(test_session, f"Film {i}")
        test_session.commit()

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        engine = test_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            films, total = library.list_page(test_session, page=1, per_page=10)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(films) == 10
        assert total == 30
        # Count, page, offer counts. Not one per film.
        assert len(statements) <= 3, f"got {len(statements)} queries"

    def test_the_page_query_carries_its_own_limit(self, test_session):
        for i in range(10):
            make_film(test_session, f"Film {i}")
        test_session.commit()

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        engine = test_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            library.list_page(test_session, page=2, per_page=3)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        # The slicing must happen in SQL; loading every row and cutting it in
        # Python is what list_by_provider does and what this replaces.
        assert any("LIMIT" in s and "OFFSET" in s for s in statements)
