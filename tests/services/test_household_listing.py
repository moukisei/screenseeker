"""
Tests for the household half of the grid query.

Three things earn their place here: filtering by whose watchlist a film is on
(and combining that selection as a union or an intersection), ranking by how
many people want a film, and loading the card chips without a query per row.
"""

from datetime import UTC, datetime

from sqlalchemy import event

from screenseeker.database.models import WatchlistEntry
from screenseeker.services import library
from screenseeker.services.library import LibraryFilter
from screenseeker.services.members import create_member

from .test_listing import make_film, titles


def want(session, member, film, *, removed=False):
    """
    Put a film on a member's watchlist, optionally already retired.

    The retirement is written directly rather than through
    `retire_missing_entries`, which works on everything a member has and would
    take the other films in the test with it.
    """
    library.record_entry(session, member.id, film)
    if removed:
        session.query(WatchlistEntry).filter(
            WatchlistEntry.member_id == member.id, WatchlistEntry.film_id == film.id
        ).update({WatchlistEntry.removed_at: datetime.now(UTC)})
    session.flush()


def listed(session, **filter_kwargs):
    films, total = library.list_films(session, filters=LibraryFilter(**filter_kwargs))
    return titles(films), total


class TestMemberFilter:
    def test_any_is_the_union_of_those_watchlists(self, test_session):
        alice = create_member(test_session, "alice")
        bob = create_member(test_session, "bob")

        hers = make_film(test_session, "Solaris")
        his = make_film(test_session, "Heat")
        theirs = make_film(test_session, "Casino")
        nobodys = make_film(test_session, "Orphan")

        want(test_session, alice, hers)
        want(test_session, bob, his)
        want(test_session, alice, theirs)
        want(test_session, bob, theirs)
        test_session.commit()

        found, total = listed(test_session, members=(alice.id, bob.id))

        assert sorted(found) == ["Casino", "Heat", "Solaris"]
        assert total == 3
        assert nobodys.letterboxd_title not in found

    def test_all_is_the_intersection(self, test_session):
        """The Friday-night question: what do we *all* want to see?"""
        alice = create_member(test_session, "alice")
        bob = create_member(test_session, "bob")

        shared = make_film(test_session, "Casino")
        hers = make_film(test_session, "Solaris")

        want(test_session, alice, shared)
        want(test_session, bob, shared)
        want(test_session, alice, hers)
        test_session.commit()

        found, total = listed(test_session, members=(alice.id, bob.id), member_match="all")

        assert found == ["Casino"]
        assert total == 1

    def test_a_repeated_selection_means_the_same_as_one(self, test_session):
        """
        Counting distinct members rather than rows is what makes "2,2" behave
        like "2" instead of matching nothing.
        """
        alice = create_member(test_session, "alice")
        film = make_film(test_session, "Solaris")
        want(test_session, alice, film)
        test_session.commit()

        found, _ = listed(test_session, members=(alice.id, alice.id), member_match="all")

        assert found == ["Solaris"]

    def test_a_retired_entry_no_longer_matches(self, test_session):
        alice = create_member(test_session, "alice")
        dropped = make_film(test_session, "Solaris")
        want(test_session, alice, dropped, removed=True)
        test_session.commit()

        found, total = listed(test_session, members=(alice.id,))

        assert found == []
        assert total == 0

    def test_no_selection_shows_everyone(self, test_session):
        alice = create_member(test_session, "alice")
        want(test_session, alice, make_film(test_session, "Solaris"))
        make_film(test_session, "Orphan")
        test_session.commit()

        found, total = listed(test_session)

        assert total == 2
        assert sorted(found) == ["Orphan", "Solaris"]

    def test_composes_with_the_offer_filters(self, test_session):
        alice = create_member(test_session, "alice")

        wanted = make_film(test_session, "Right", offers=[("FR", "Netflix", "flatrate")])
        wrong_country = make_film(test_session, "Wrong", offers=[("US", "Netflix", "flatrate")])
        want(test_session, alice, wanted)
        want(test_session, alice, wrong_country)
        test_session.commit()

        found, _ = listed(test_session, members=(alice.id,), provider="Netflix", country="FR")

        assert found == ["Right"]


class TestMostWantedSort:
    def test_ranks_by_how_many_people_want_it(self, test_session):
        alice = create_member(test_session, "alice")
        bob = create_member(test_session, "bob")
        carol = create_member(test_session, "carol")

        one = make_film(test_session, "One", rating=9.0)
        two = make_film(test_session, "Two", rating=1.0)
        three = make_film(test_session, "Three", rating=1.0)

        want(test_session, alice, one)
        for member in (alice, bob):
            want(test_session, member, two)
        for member in (alice, bob, carol):
            want(test_session, member, three)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="wanted")

        assert titles(films) == ["Three", "Two", "One"]

    def test_rating_breaks_a_tie(self, test_session):
        """Consensus first, then the better film."""
        alice = create_member(test_session, "alice")

        worse = make_film(test_session, "Worse", rating=3.0)
        better = make_film(test_session, "Better", rating=8.0)
        want(test_session, alice, worse)
        want(test_session, alice, better)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="wanted")

        assert titles(films) == ["Better", "Worse"]

    def test_a_film_nobody_lists_sorts_last(self, test_session):
        alice = create_member(test_session, "alice")
        wanted = make_film(test_session, "Wanted", rating=1.0)
        want(test_session, alice, wanted)
        make_film(test_session, "Orphan", rating=9.0)
        test_session.commit()

        films, _ = library.list_films(test_session, sort="wanted")

        assert titles(films) == ["Wanted", "Orphan"]


class TestChips:
    def test_a_summary_carries_who_wants_it(self, test_session):
        alice = create_member(test_session, "alice", display_name="Alice")
        bob = create_member(test_session, "bob", display_name="Bob Smith")

        film = make_film(test_session, "Casino")
        want(test_session, alice, film)
        want(test_session, bob, film)
        test_session.commit()

        [summary], _ = library.list_films(test_session)

        assert [m.display_name for m in summary.members] == ["Alice", "Bob Smith"]
        assert [m.initials for m in summary.members] == ["AL", "BS"]
        assert summary.wanted_by == 2

    def test_chips_do_not_reshuffle_between_renders(self, test_session):
        """Ordered by name, so a card is stable across page loads."""
        zoe = create_member(test_session, "zoe", display_name="Zoe")
        adam = create_member(test_session, "adam", display_name="Adam")

        film = make_film(test_session, "Casino")
        want(test_session, zoe, film)
        want(test_session, adam, film)
        test_session.commit()

        [summary], _ = library.list_films(test_session)

        assert [m.display_name for m in summary.members] == ["Adam", "Zoe"]

    def test_a_retired_entry_leaves_no_chip(self, test_session):
        alice = create_member(test_session, "alice")
        film = make_film(test_session, "Casino")
        want(test_session, alice, film, removed=True)
        test_session.commit()

        [summary], _ = library.list_films(test_session)

        assert summary.members == []

    def test_chips_cost_one_query_for_a_whole_page(self, test_session):
        """
        The reason `wanted_by` exists at all: reading the relationship per row
        is one query per card, which is what offer_counts already avoided.
        """
        alice = create_member(test_session, "alice")
        for i in range(20):
            want(test_session, alice, make_film(test_session, f"Film {i}"))
        test_session.commit()

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            if "watchlist_entries" in statement:
                statements.append(statement)

        engine = test_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            films, _ = library.list_films(test_session, per_page=20)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(films) == 20
        assert len(statements) == 1, f"got {len(statements)} entry queries"

    def test_the_watched_toggle_keeps_the_chips(self, test_session):
        """
        The response replaces the whole card, so dropping them here would look
        like marking a film watched had lost its owners.
        """
        alice = create_member(test_session, "alice", display_name="Alice")
        film = make_film(test_session, "Casino")
        want(test_session, alice, film)
        test_session.commit()

        updated = library.set_watched_by_id(test_session, film.id, watched=True)

        assert [m.display_name for m in updated.members] == ["Alice"]


class TestDetail:
    def test_the_detail_page_knows_who_wants_the_film(self, test_session):
        alice = create_member(test_session, "alice", display_name="Alice")
        film = make_film(test_session, "Casino", offers=[("FR", "Netflix", "flatrate")])
        want(test_session, alice, film)
        test_session.commit()

        detail = library.get_detail(test_session, film.id)

        assert [m.display_name for m in detail.members] == ["Alice"]


class TestFilterParams:
    def test_members_round_trip_through_the_url(self):
        """
        Comma-joined, not repeated: Jinja's urlencode stringifies a list value
        instead of expanding it, which silently drops the filter on page two.
        """
        params = LibraryFilter(members=(1, 2), member_match="all").as_params()

        assert params["members"] == "1,2"
        assert params["member_match"] == "all"

    def test_the_default_match_is_left_out(self):
        params = LibraryFilter(members=(1,)).as_params()

        assert params["members"] == "1"
        assert "member_match" not in params

    def test_match_alone_does_not_count_as_a_filter(self):
        """Otherwise an untouched dropdown lights up the Clear link."""
        assert LibraryFilter(member_match="all").is_active is False
        assert LibraryFilter(members=(1,)).is_active is True
