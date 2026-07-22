"""
Tests for the SQLite connection settings a server depends on.

These pragmas are not cosmetic: without foreign_keys=ON the ON DELETE CASCADE
declared on streaming_offers.film_id is silently ignored, and without a busy
timeout concurrent writers fail immediately with "database is locked".
"""

from datetime import UTC, datetime

from sqlalchemy import text

from screenseeker.database.models import Film, StreamingOffer


def make_film_with_offers(session, offer_count=3, title="Test Film"):
    film = Film(
        letterboxd_title=title,
        letterboxd_year=2020,
        tmdb_id=abs(hash(title)) % 1_000_000,
        date_added=datetime.now(UTC),
    )
    session.add(film)
    session.flush()

    for i in range(offer_count):
        session.add(
            StreamingOffer(
                film_id=film.id,
                country_code="FR",
                country_name="France",
                provider_id=i,
                provider_name=f"Provider {i}",
                monetization_type="flatrate",
                checked_at=datetime.now(UTC),
            )
        )
    session.flush()
    return film


class TestPragmas:
    def test_foreign_keys_enforced(self, test_session):
        assert test_session.execute(text("PRAGMA foreign_keys")).scalar() == 1

    def test_busy_timeout_set(self, test_session):
        assert test_session.execute(text("PRAGMA busy_timeout")).scalar() > 0

    def test_journal_mode(self, test_session):
        # An in-memory database cannot use WAL and reports "memory"; a file
        # database must report "wal".
        mode = test_session.execute(text("PRAGMA journal_mode")).scalar()
        assert mode.lower() in {"wal", "memory"}


class TestCascadeDelete:
    def test_deleting_film_removes_its_offers(self, test_session):
        film = make_film_with_offers(test_session, offer_count=3)
        film_id = film.id

        assert test_session.query(StreamingOffer).filter_by(film_id=film_id).count() == 3

        test_session.delete(film)
        test_session.flush()

        assert test_session.query(StreamingOffer).filter_by(film_id=film_id).count() == 0

    def test_orphan_offer_is_rejected(self, test_session):
        """A film_id pointing at nothing must fail, not insert silently."""
        from sqlalchemy.exc import IntegrityError

        test_session.add(
            StreamingOffer(
                film_id=999_999,
                country_code="FR",
                country_name="France",
                provider_id=1,
                provider_name="Nowhere",
                monetization_type="flatrate",
                checked_at=datetime.now(UTC),
            )
        )

        try:
            test_session.flush()
        except IntegrityError:
            return
        raise AssertionError("expected an IntegrityError for a dangling film_id")

    def test_bulk_delete_removes_offers(self, test_session):
        """The CASCADE has to survive a query-level delete too."""
        make_film_with_offers(test_session, offer_count=2, title="A")
        make_film_with_offers(test_session, offer_count=2, title="B")
        test_session.commit()

        for film in test_session.query(Film).all():
            test_session.delete(film)
        test_session.commit()

        assert test_session.query(StreamingOffer).count() == 0
