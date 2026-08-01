"""
Tests for the household: who the watchlists come from.

A member is a Letterboxd account to scrape, not a login - there is still one
password and one subscription profile for the whole app. What these cover is
the part that has teeth: the username is the sync key and must be unique and
well-formed, and removing someone must take their films with them without
touching anybody else's.
"""

import pytest

from screenseeker.database.models import Film, Member, WatchlistEntry
from screenseeker.exceptions import ConfigurationError
from screenseeker.services import members
from screenseeker.services.library import get_or_create_film, record_entry


class TestUsernames:
    def test_normalises_case_and_whitespace(self):
        assert members.normalise_username("  AliceB  ") == "aliceb"

    def test_accepts_a_pasted_profile_url(self):
        """What you get from the browser when you go looking for a watchlist."""
        assert members.normalise_username("https://letterboxd.com/aliceb/") == "aliceb"
        assert members.normalise_username("letterboxd.com/aliceb/watchlist/") == "aliceb"

    @pytest.mark.parametrize("bad", ["", "   ", "alice b", "alice!", "a" * 40])
    def test_rejects_what_the_scraper_would_404_on(self, bad):
        """
        Better a sentence now than a job that spends minutes on a dead URL.
        """
        with pytest.raises(ConfigurationError):
            members.normalise_username(bad)


class TestCreate:
    def test_adds_a_member_with_a_colour_and_a_default_name(self, test_session):
        member = members.create_member(test_session, "AliceB")

        assert member.letterboxd_username == "aliceb"
        assert member.display_name == "aliceb"
        assert member.color in members.PALETTE
        assert member.active is True

    def test_display_name_wins_when_given(self, test_session):
        member = members.create_member(test_session, "aliceb", display_name="Alice")
        assert member.display_name == "Alice"
        assert member.initials == "AL"

    def test_two_word_names_initial_to_two_letters(self, test_session):
        member = members.create_member(test_session, "aliceb", display_name="Alice Bernard")
        assert member.initials == "AB"

    def test_colours_do_not_repeat_until_the_palette_runs_out(self, test_session):
        seen = {
            members.create_member(test_session, f"user{i}").color
            for i in range(len(members.PALETTE))
        }
        assert len(seen) == len(members.PALETTE)

    def test_the_same_account_cannot_be_added_twice(self, test_session):
        """
        Two members on one account would write every entry twice and double
        the "wanted by" count, which is the number the whole feature is for.
        """
        members.create_member(test_session, "aliceb")

        with pytest.raises(ConfigurationError):
            members.create_member(test_session, "AliceB")


class TestListing:
    def test_counts_only_live_entries(self, test_session):
        alice = members.create_member(test_session, "alice")
        kept, _ = get_or_create_film(test_session, "Heat", 1995)
        dropped, _ = get_or_create_film(test_session, "Casino", 1995)

        record_entry(test_session, alice.id, kept)
        record_entry(test_session, alice.id, dropped)
        # As if a later scrape no longer found it.
        test_session.query(WatchlistEntry).filter(WatchlistEntry.film_id == dropped.id).update(
            {WatchlistEntry.removed_at: kept.date_added}
        )
        test_session.flush()

        [listed] = members.list_members(test_session)
        assert listed.film_count == 1

    def test_active_only_skips_paused_members(self, test_session):
        members.create_member(test_session, "alice")
        paused = members.create_member(test_session, "bob")
        members.update_member(test_session, paused.id, active=False)

        assert [m.letterboxd_username for m in members.list_members(test_session)] == [
            "alice",
            "bob",
        ]
        assert [
            m.letterboxd_username for m in members.list_members(test_session, active_only=True)
        ] == ["alice"]

    def test_count_matches_the_list(self, test_session):
        members.create_member(test_session, "alice")
        members.create_member(test_session, "bob")

        assert members.count_members(test_session) == 2


class TestUpdate:
    def test_renames_and_recolours(self, test_session):
        member = members.create_member(test_session, "alice")

        updated = members.update_member(
            test_session, member.id, display_name="Alice", color="#123456"
        )

        assert updated.display_name == "Alice"
        assert updated.chip_color == "#123456"

    def test_a_blank_name_is_ignored_rather_than_stored(self, test_session):
        """An empty display name would render as a nameless chip."""
        member = members.create_member(test_session, "alice", display_name="Alice")

        updated = members.update_member(test_session, member.id, display_name="   ")

        assert updated.display_name == "Alice"

    def test_missing_member_returns_none(self, test_session):
        assert members.update_member(test_session, 999, display_name="Nobody") is None


class TestDelete:
    def test_drops_films_nobody_else_wanted(self, test_session):
        """
        Leaving them would turn the library into a graveyard with no way to
        tell the orphans from the rest.
        """
        alice = members.create_member(test_session, "alice")
        only_hers, _ = get_or_create_film(test_session, "Solaris", 1972)
        record_entry(test_session, alice.id, only_hers)
        test_session.flush()

        report = members.delete_member(test_session, alice.id)

        assert report.entries_removed == 1
        assert report.films_removed == 1
        assert test_session.query(Film).count() == 0
        assert test_session.query(Member).count() == 0

    def test_keeps_films_someone_else_still_lists(self, test_session):
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        shared, _ = get_or_create_film(test_session, "Heat", 1995)
        record_entry(test_session, alice.id, shared)
        record_entry(test_session, bob.id, shared)
        test_session.flush()

        report = members.delete_member(test_session, alice.id)

        assert report.films_removed == 0
        assert test_session.query(Film).count() == 1
        # Bob's entry survives untouched, enrichment included.
        assert test_session.query(WatchlistEntry).count() == 1

    def test_a_film_someone_removed_is_still_theirs_to_restore(self, test_session):
        """
        A retired entry means "not right now", not "not mine". Deleting a
        different member must not take the film out from under them.
        """
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        film, _ = get_or_create_film(test_session, "Stalker", 1979)
        record_entry(test_session, alice.id, film)
        record_entry(test_session, bob.id, film)
        test_session.query(WatchlistEntry).filter(WatchlistEntry.member_id == bob.id).update(
            {WatchlistEntry.removed_at: film.date_added}
        )
        test_session.flush()

        report = members.delete_member(test_session, alice.id)

        assert report.films_removed == 0
        assert test_session.query(Film).count() == 1

    def test_missing_member_returns_none(self, test_session):
        assert members.delete_member(test_session, 999) is None
