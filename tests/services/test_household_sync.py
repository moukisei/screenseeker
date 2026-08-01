"""
Tests for syncing a household's watchlists.

The behaviour that matters once there is more than one watchlist: films are
shared rather than duplicated, a film someone drops stops counting without
being deleted, and a scrape that read nothing is not allowed to erase anybody.
"""

from datetime import UTC, datetime

from screenseeker.database.models import Film, WatchlistEntry
from screenseeker.models import Film as ScrapedFilm
from screenseeker.models import ScrapingResult
from screenseeker.scrapers.base import BaseScraper
from screenseeker.services import members
from screenseeker.services.library import get_or_create_film
from screenseeker.services.sync import ingest_watchlist


class FakeScraper(BaseScraper):
    """
    Returns a canned watchlist. `titles` is a list of (title, year).

    ingest_watchlist takes a scraper rather than building one precisely so this
    can stand in for the HTML one.
    """

    def __init__(self, titles=(), *, success=True, error=None):
        super().__init__()
        self.titles = list(titles)
        self.success = success
        self.error = error

    def scrape(self) -> ScrapingResult:
        return ScrapingResult(
            films=[
                ScrapedFilm(
                    film_full_title=f"{title} ({year})" if year else title,
                    film_title=title,
                    year=year,
                    date_added="2026-01-01",
                )
                for title, year in self.titles
            ],
            total_pages_scraped=1,
            success=self.success,
            error_message=self.error,
            source="fake",
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def live_entries(session, member_id):
    return (
        session.query(WatchlistEntry)
        .filter(WatchlistEntry.member_id == member_id, WatchlistEntry.removed_at.is_(None))
        .all()
    )


class TestSharedFilms:
    def test_two_members_wanting_one_film_share_a_row(self, test_session):
        """
        The whole point of the join table: TMDB enrichment is the expensive
        part and is paid once, however many people list the film.
        """
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)
        report = ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=bob.id)

        assert test_session.query(Film).count() == 1
        # New to Bob's list, not new to the library.
        assert report.added == 1
        assert report.new_films == 0
        assert test_session.query(WatchlistEntry).count() == 2

    def test_a_missing_year_does_not_split_a_film_in_two(self, test_session):
        """
        Letterboxd omits the year on some entries, so one member's scrape can
        store "Heat" and another's "Heat (1995)". Two rows would mean two TMDB
        lookups and two cards for one film.
        """
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        ingest_watchlist(test_session, FakeScraper([("Heat", None)]), member_id=alice.id)
        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=bob.id)

        films = test_session.query(Film).all()
        assert len(films) == 1
        # The year the second scrape carried is filled in on the shared row.
        assert films[0].letterboxd_year == 1995

    def test_date_added_holds_the_earliest_of_the_two(self, test_session):
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)
        film = test_session.query(Film).one()
        first_seen = film.date_added

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=bob.id)
        test_session.refresh(film)

        assert film.date_added == first_seen


class TestReconcile:
    def test_a_film_dropped_from_a_watchlist_stops_counting(self, test_session):
        alice = members.create_member(test_session, "alice")

        ingest_watchlist(
            test_session,
            FakeScraper([("Heat", 1995), ("Casino", 1995)]),
            member_id=alice.id,
        )
        report = ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)

        assert report.removed == 1
        assert [e.film_id for e in live_entries(test_session, alice.id)] == [
            test_session.query(Film).filter(Film.letterboxd_title == "Heat").one().id
        ]

    def test_the_film_itself_survives_being_dropped(self, test_session):
        """Enrichment is expensive and the film usually comes back."""
        alice = members.create_member(test_session, "alice")

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)
        ingest_watchlist(test_session, FakeScraper([]), member_id=alice.id)

        assert test_session.query(Film).count() == 1

    def test_putting_a_film_back_reuses_its_entry(self, test_session):
        """
        A second entry would double this member's count and their chip on the
        card. The original date survives too.
        """
        alice = members.create_member(test_session, "alice")

        ingest_watchlist(
            test_session,
            FakeScraper([("Heat", 1995), ("Casino", 1995)]),
            member_id=alice.id,
        )
        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)
        report = ingest_watchlist(
            test_session,
            FakeScraper([("Heat", 1995), ("Casino", 1995)]),
            member_id=alice.id,
        )

        assert report.restored == 1
        assert report.added == 0
        assert test_session.query(WatchlistEntry).count() == 2

    def test_one_member_dropping_a_film_leaves_the_others_alone(self, test_session):
        alice = members.create_member(test_session, "alice")
        bob = members.create_member(test_session, "bob")

        both = [("Heat", 1995), ("Casino", 1995)]
        ingest_watchlist(test_session, FakeScraper(both), member_id=alice.id)
        ingest_watchlist(test_session, FakeScraper(both), member_id=bob.id)

        # Alice drops Casino; Bob still wants it.
        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)

        casino = test_session.query(Film).filter(Film.letterboxd_title == "Casino").one()
        assert casino.id not in {e.film_id for e in live_entries(test_session, alice.id)}
        assert casino.id in {e.film_id for e in live_entries(test_session, bob.id)}

    def test_a_successful_but_empty_scrape_retires_nothing(self, test_session):
        """
        A rate limit, a login wall or a changed page layout all read as "your
        watchlist is empty". Acting on that wipes the household's list in one
        run, so the entries stand until a scrape that read something disagrees.
        """
        alice = members.create_member(test_session, "alice")
        ingest_watchlist(
            test_session,
            FakeScraper([("Heat", 1995), ("Casino", 1995)]),
            member_id=alice.id,
        )

        report = ingest_watchlist(test_session, FakeScraper([]), member_id=alice.id)

        assert report.removed == 0
        assert len(live_entries(test_session, alice.id)) == 2

    def test_a_failed_scrape_writes_nothing(self, test_session):
        alice = members.create_member(test_session, "alice")
        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)

        report = ingest_watchlist(
            test_session,
            FakeScraper(success=False, error="Letterboxd returned 503"),
            member_id=alice.id,
        )

        assert report.success is False
        assert "503" in report.error_message
        assert len(live_entries(test_session, alice.id)) == 1


class TestSyncStamp:
    def test_records_when_a_member_was_last_scraped(self, test_session):
        alice = members.create_member(test_session, "alice")
        assert alice.last_synced_at is None

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)

        [synced] = members.list_members(test_session)
        assert synced.last_synced_at is not None

    def test_an_empty_scrape_does_not_claim_a_successful_sync(self, test_session):
        """It read nothing; saying otherwise hides a broken account."""
        alice = members.create_member(test_session, "alice")

        ingest_watchlist(test_session, FakeScraper([]), member_id=alice.id)

        [synced] = members.list_members(test_session)
        assert synced.last_synced_at is None


class TestProgress:
    def test_reports_progress_per_film(self, test_session):
        alice = members.create_member(test_session, "alice")
        seen = []

        ingest_watchlist(
            test_session,
            FakeScraper([("Heat", 1995), ("Casino", 1995), ("Solaris", 1972)]),
            member_id=alice.id,
            on_progress=lambda done, total: seen.append((done, total)),
        )

        assert seen == [(1, 3), (2, 3), (3, 3)]


class TestExistingFilmsWithoutEntries:
    def test_a_film_from_before_the_household_gains_an_entry(self, test_session):
        """
        The migration backfills entries for existing films, but a row created
        by an enrichment run has none. Syncing must adopt it rather than
        duplicate it.
        """
        alice = members.create_member(test_session, "alice")
        orphan, _ = get_or_create_film(test_session, "Heat", 1995)
        orphan.date_added = datetime(2020, 1, 1, tzinfo=UTC)
        test_session.flush()

        ingest_watchlist(test_session, FakeScraper([("Heat", 1995)]), member_id=alice.id)

        assert test_session.query(Film).count() == 1
        assert len(live_entries(test_session, alice.id)) == 1
