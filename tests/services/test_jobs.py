"""
Tests for the job ledger.

The one that matters is the single-flight guard. The rest is bookkeeping that
the UI depends on being written down.
"""

import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from screenseeker.database.models import Base, Job
from screenseeker.exceptions import JobAlreadyRunning
from screenseeker.services import jobs


@pytest.fixture
def sessions(tmp_path):
    """A file-backed database: the guard is an index, so schema fidelity matters."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
def session(sessions):
    s = sessions()
    try:
        yield s
    finally:
        s.close()


class TestSingleFlight:
    def test_second_job_of_the_same_kind_is_refused(self, session):
        first = jobs.claim(session, "refresh")

        with pytest.raises(JobAlreadyRunning) as caught:
            jobs.claim(session, "refresh")

        assert caught.value.job_id == first.id
        assert "already running" in str(caught.value)

    def test_a_different_kind_is_allowed_alongside(self, session):
        jobs.claim(session, "refresh")

        # Sync writes films and refresh writes offers; only same-kind
        # concurrency races get_or_create_film.
        assert jobs.claim(session, "sync").kind == "sync"

    def test_the_guard_is_a_constraint_not_a_check(self, sessions, session):
        """
        Two requests can both read "nothing is running" before either inserts.

        This bypasses claim() entirely and writes the row the way a racing
        second request would, to prove the database refuses it rather than the
        application.
        """
        jobs.claim(session, "refresh")

        other = sessions()
        try:
            other.add(
                Job(
                    kind="refresh",
                    status="queued",
                    progress_current=0,
                    progress_total=0,
                    created_at=datetime.now(UTC),
                )
            )
            with pytest.raises(Exception) as caught:
                other.commit()
        finally:
            other.rollback()
            other.close()

        assert isinstance(caught.value.orig, sqlite3.IntegrityError)

    def test_a_finished_job_releases_the_kind(self, session):
        first = jobs.claim(session, "refresh")
        jobs.finish(session, first.id, message="done")

        assert jobs.claim(session, "refresh").id != first.id

    def test_a_failed_job_releases_the_kind(self, session):
        first = jobs.claim(session, "sync")
        jobs.fail(session, first.id, "Letterboxd timed out")

        assert jobs.claim(session, "sync").id != first.id

    def test_unknown_kind_is_rejected(self, session):
        with pytest.raises(ValueError):
            jobs.claim(session, "vacuum")


class TestLifecycle:
    def test_progress_is_committed_so_a_reader_can_see_it(self, sessions, session):
        job = jobs.claim(session, "refresh")
        jobs.start(session, job.id, total=181)
        jobs.report_progress(session, job.id, 42, 181, "Fetching Heat")

        # A different session stands in for the polling request.
        reader = sessions()
        try:
            seen = jobs.get(reader, job.id)
        finally:
            reader.close()

        assert seen.progress_current == 42
        assert seen.percent == 23
        assert seen.message == "Fetching Heat"
        assert seen.is_active

    def test_percent_of_an_uncounted_job_is_zero_not_complete(self, session):
        job = jobs.claim(session, "sync")

        assert jobs.get(session, job.id).percent == 0

    def test_finish_records_partial_failures(self, session):
        """A run that mostly worked still has to surface what did not."""
        job = jobs.claim(session, "refresh")
        finished = jobs.finish(
            session, job.id, message="Refreshed 169, 12 failed.", error="Heat: 429 from TMDB"
        )

        assert finished.status == "succeeded"
        assert not finished.is_active
        assert "429" in finished.error

    def test_fail_records_the_reason(self, session):
        job = jobs.claim(session, "sync")
        failed = jobs.fail(session, job.id, "Letterboxd returned 503")

        assert failed.status == "failed"
        assert failed.finished_at is not None
        assert "503" in failed.error

    def test_latest_prefers_the_newest_job(self, session):
        first = jobs.claim(session, "sync")
        jobs.finish(session, first.id, message="done")
        second = jobs.claim(session, "refresh")

        assert jobs.latest(session).id == second.id
        assert jobs.latest(session, kind="sync").id == first.id

    def test_latest_of_an_empty_ledger_is_none(self, session):
        assert jobs.latest(session) is None


class TestReaping:
    def test_orphans_are_failed_so_the_guard_reopens(self, session):
        stranded = jobs.claim(session, "refresh")
        jobs.start(session, stranded.id, total=10)

        # The process dies here. Nothing marks the row finished.
        reaped = jobs.reap_orphans(session)

        assert reaped == 1
        assert jobs.get(session, stranded.id).status == "failed"
        assert "Interrupted" in jobs.get(session, stranded.id).error
        # And the kind is claimable again.
        assert jobs.claim(session, "refresh").id != stranded.id

    def test_finished_jobs_are_left_alone(self, session):
        job = jobs.claim(session, "sync")
        jobs.finish(session, job.id, message="Scraped 181 films.")

        assert jobs.reap_orphans(session) == 0
        assert jobs.get(session, job.id).status == "succeeded"
