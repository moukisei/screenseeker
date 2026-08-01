"""
Tests for library.list_films - the one query behind the grid.

It replaced get_films_by_provider and get_films_by_country, which were
single-axis and could not be combined, and which applied their limit in Python
after loading every matching row.

What matters here: filters compose and land on the same offer row, filtering
and slicing happen in SQL, and the ordering is total so a film cannot appear on
two pages or on none.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from screenseeker.database.models import Film, StreamingOffer
from screenseeker.services import library
from screenseeker.services.library import LibraryFilter
from tests.conftest import own


def make_film(
    session,
    title,
    *,
    year=2000,
    rating=5.0,
    added_days_ago=0,
    tmdb_id=None,
    confidence=None,
    offers=(),
    owners=None,
):
    """
    `offers` is a list of (country, provider, offer_type).

    `owners` defaults to a stand-in member, because a film nobody lists is not
    in the library and no query returns it. Pass `owners=()` for that case.
    """
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        vote_average=rating,
        match_confidence=confidence,
        date_added=datetime.now(UTC) - timedelta(days=added_days_ago),
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
                checked_at=datetime.now(UTC),
            )
        )
    session.flush()
    return own(session, film, owners)


def titles(page):
    return [f.title for f in page]


def listed(session, **filter_kwargs):
    films, total = library.list_films(session, filters=LibraryFilter(**filter_kwargs))
    return titles(films), total


class TestFiltering:
    """Composability is the whole point: the CLI structurally could not do it."""

    def test_the_plans_worked_example_is_one_call(self, test_session):
        """ "on Netflix, available in FR, flatrate" - the step 6 acceptance test."""
        make_film(test_session, "Wanted", offers=[("FR", "Netflix", "flatrate")])
        make_film(test_session, "Wrong country", offers=[("US", "Netflix", "flatrate")])
        make_film(test_session, "Wrong provider", offers=[("FR", "Disney Plus", "flatrate")])
        make_film(test_session, "Nowhere")
        test_session.commit()

        found, total = listed(test_session, provider="Netflix", country="FR", offer_type="flatrate")

        assert found == ["Wanted"]
        assert total == 1

    def test_offer_conditions_must_hold_on_the_same_row(self, test_session):
        """
        The failure three independent EXISTS clauses would produce.

        This film streams on Netflix in the US and is rentable from Apple in
        France. It satisfies "Netflix" and "FR" and "flatrate" separately, and
        satisfies none of the combinations that matter.
        """
        make_film(
            test_session,
            "Split",
            offers=[("US", "Netflix", "flatrate"), ("FR", "Apple TV", "rent")],
        )
        test_session.commit()

        assert listed(test_session, provider="Netflix", country="FR")[0] == []
        assert listed(test_session, country="FR", offer_type="flatrate")[0] == []
        assert listed(test_session, provider="Netflix", offer_type="rent")[0] == []
        # Each axis alone still matches.
        assert listed(test_session, provider="Netflix")[0] == ["Split"]
        assert listed(test_session, country="FR")[0] == ["Split"]

    def test_provider_matches_on_a_substring(self, test_session):
        """TMDB names providers "Netflix basic with Ads", not "Netflix"."""
        make_film(test_session, "Ad tier", offers=[("FR", "Netflix basic with Ads", "flatrate")])
        test_session.commit()

        assert listed(test_session, provider="netflix")[0] == ["Ad tier"]

    def test_a_film_is_not_duplicated_by_matching_offers(self, test_session):
        """A JOIN would return this film four times; EXISTS returns it once."""
        make_film(
            test_session,
            "Everywhere",
            offers=[
                ("FR", "Netflix", "flatrate"),
                ("FR", "Netflix", "rent"),
                ("FR", "Netflix", "buy"),
                ("FR", "Netflix basic with Ads", "flatrate"),
            ],
        )
        test_session.commit()

        found, total = listed(test_session, provider="Netflix", country="FR")

        assert found == ["Everywhere"]
        assert total == 1

    def test_a_film_nobody_lists_is_not_in_the_library(self, test_session):
        """
        The rule the whole grid rests on. Logging a film on Letterboxd takes it
        off the watchlist; the next sync retires the entry, and the film has to
        disappear here rather than linger as sediment nobody can clear.
        """
        make_film(test_session, "Still Wanted")
        make_film(test_session, "Dropped", owners=())
        test_session.commit()

        found, total = listed(test_session)

        assert found == ["Still Wanted"]
        assert total == 1

    def test_country_is_matched_case_insensitively(self, test_session):
        make_film(test_session, "French", offers=[("FR", "Canal+", "flatrate")])
        test_session.commit()

        assert listed(test_session, country="fr")[0] == ["French"]

    def test_the_total_counts_matches_not_the_library(self, test_session):
        for i in range(5):
            make_film(test_session, f"Film {i}", offers=[("FR", "Netflix", "flatrate")])
        make_film(test_session, "Elsewhere", offers=[("US", "Netflix", "flatrate")])
        test_session.commit()

        films, total = library.list_films(
            test_session, filters=LibraryFilter(country="FR"), per_page=1
        )

        assert len(films) == 1
        assert total == 5

    def test_an_empty_string_does_not_narrow(self, test_session):
        """Blank form fields arrive as "" and must behave like "no filter"."""
        make_film(test_session, "Anything")
        test_session.commit()

        assert not LibraryFilter().is_active
        assert listed(test_session, provider=None, country=None)[0] == ["Anything"]

    def test_filters_round_trip_through_url_parameters(self):
        """Views are bookmarkable, so the filter has to survive the URL."""
        original = LibraryFilter(
            query="matrix", provider="Netflix", country="FR", offer_type="flatrate"
        )
        params = original.as_params()

        assert params == {
            "query": "matrix",
            "provider": "Netflix",
            "country": "FR",
            "offer_type": "flatrate",
        }
        assert LibraryFilter().as_params() == {}


class TestSearch:
    def test_matches_a_title_substring_case_insensitively(self, test_session):
        make_film(test_session, "The Matrix")
        make_film(test_session, "Matrix Reloaded")
        make_film(test_session, "Casino")
        test_session.commit()

        assert sorted(listed(test_session, query="matrix")[0]) == ["Matrix Reloaded", "The Matrix"]

    def test_matches_the_tmdb_title_when_it_differs(self, test_session):
        """A film renamed on match is still found by the TMDB name."""
        film = make_film(test_session, "Amelie")
        film.tmdb_title = "Le Fabuleux Destin d'Amélie Poulain"
        test_session.commit()

        assert listed(test_session, query="fabuleux")[0] == ["Amelie"]

    def test_no_match_is_empty(self, test_session):
        make_film(test_session, "Heat")
        test_session.commit()

        assert listed(test_session, query="nonesuch")[0] == []

    def test_search_composes_with_other_filters(self, test_session):
        make_film(test_session, "The Matrix", offers=[("FR", "Netflix", "flatrate")])
        make_film(test_session, "The Matrix Revisited")
        test_session.commit()

        # "matrix" AND on Netflix -> only the first.
        assert listed(test_session, query="matrix", provider="Netflix")[0] == ["The Matrix"]

    def test_wildcards_in_the_term_are_literal(self, test_session):
        """A stray % must not turn into "match everything"."""
        make_film(test_session, "Heat")
        make_film(test_session, "50%% Off")
        test_session.commit()

        # Without escaping, "%" would match every film.
        assert listed(test_session, query="%")[0] == ["50%% Off"]

    def test_no_query_does_not_narrow(self, test_session):
        make_film(test_session, "Heat")
        test_session.commit()

        assert listed(test_session, query=None)[0] == ["Heat"]


class TestPaging:
    def test_pages_partition_the_library(self, test_session):
        for i in range(5):
            make_film(test_session, f"Film {i}", added_days_ago=i)
        test_session.commit()

        seen = []
        for page in (1, 2, 3):
            films, total = library.list_films(test_session, page=page, per_page=2)
            assert total == 5
            seen.extend(titles(films))

        assert seen == ["Film 0", "Film 1", "Film 2", "Film 3", "Film 4"]

    def test_page_past_the_end_is_empty_not_an_error(self, test_session):
        make_film(test_session, "Only")
        test_session.commit()

        films, total = library.list_films(test_session, page=99, per_page=10)

        assert films == []
        assert total == 1

    def test_ties_are_broken_so_pages_do_not_overlap(self, test_session):
        added = datetime.now(UTC)
        for i in range(6):
            film = make_film(test_session, f"Same {i}")
            film.date_added = added  # every row shares the sort key
        test_session.commit()

        first, _ = library.list_films(test_session, page=1, per_page=3)
        second, _ = library.list_films(test_session, page=2, per_page=3)

        assert set(titles(first)).isdisjoint(titles(second))
        assert len(set(titles(first) + titles(second))) == 6


class TestSorting:
    def test_unknown_key_falls_back_to_the_default(self, test_session):
        make_film(test_session, "Older", added_days_ago=5)
        make_film(test_session, "Newer", added_days_ago=1)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="nonsense")

        assert titles(films) == ["Newer", "Older"]

    def test_title_sorts_alphabetically(self, test_session):
        for title in ("Zodiac", "Amélie", "Memento"):
            make_film(test_session, title)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="title")

        assert titles(films) == ["Amélie", "Memento", "Zodiac"]

    def test_unknown_years_sort_last_not_first(self, test_session):
        make_film(test_session, "Undated", year=None)
        make_film(test_session, "Recent", year=2020)
        make_film(test_session, "Ancient", year=1950)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="year")

        assert titles(films) == ["Recent", "Ancient", "Undated"]

    def test_confidence_sorts_by_rank_not_alphabetically(self, test_session):
        """
        The values are an ordered scale stored as text.

        Alphabetically "duplicate" precedes "exact" and "high" precedes "low",
        which is exactly backwards for a column you sort to find bad matches.
        """
        for title, confidence in (
            ("Low", "low"),
            ("Exact", "exact"),
            ("Duplicate", "duplicate"),
            ("High", "high"),
            ("Unmatched", None),
        ):
            make_film(test_session, title, confidence=confidence)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="confidence")

        assert titles(films) == ["Exact", "High", "Low", "Duplicate", "Unmatched"]

    def test_unrated_films_sort_last(self, test_session):
        make_film(test_session, "Unrated", rating=None)
        make_film(test_session, "Great", rating=9.0)
        make_film(test_session, "Poor", rating=2.0)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="rating")

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
            films, total = library.list_films(test_session, page=1, per_page=10)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(films) == 10
        assert total == 30
        # Count, page, offer counts, member chips. Not one per film.
        assert len(statements) <= 4, f"got {len(statements)} queries"

    def test_a_filtered_page_is_still_a_constant_number_of_queries(self, test_session):
        for i in range(20):
            make_film(test_session, f"Film {i}", offers=[("FR", "Netflix", "flatrate")])
        test_session.commit()

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        engine = test_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            films, total = library.list_films(
                test_session,
                filters=LibraryFilter(provider="Netflix", country="FR", offer_type="flatrate"),
                per_page=5,
            )
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(films) == 5
        assert total == 20
        # Filtering does not add a query per axis; the offer counts and the
        # member chips stay one grouped SELECT each.
        assert len(statements) <= 4, f"got {len(statements)} queries"

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
            library.list_films(test_session, page=2, per_page=3)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        # The slicing must happen in SQL; loading every row and cutting it in
        # Python is what get_films_by_provider did and what this replaces.
        assert any("LIMIT" in s and "OFFSET" in s for s in statements)
