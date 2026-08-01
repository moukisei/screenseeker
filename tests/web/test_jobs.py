"""
Background job routes and the runner.

These drive the real runner - a real thread, the real enrich_films, the real
job rows - with only the TMDB client faked. What the plan asks for is here: a
run that reports progress, a second run that is refused, and a mid-run TMDB
failure that ends up on screen instead of vanishing.
"""

import time

import pytest

from screenseeker.database.models import Film, Job, StreamingOffer, WatchlistEntry
from screenseeker.enrichers.enrichment_models import EnrichmentResult
from screenseeker.enrichers.enrichment_models import StreamingOffer as Offer
from screenseeker.enrichers.enrichment_models import TMDBMovieInfo
from screenseeker.services import jobs
from screenseeker.services.members import create_member, update_member
from screenseeker.web.app import create_app
from tests.web.conftest import make_film

HTMX = {"HX-Request": "true"}

FAKE_CFG = {
    "letterboxd": {"username": "someone"},
    "tmdb": {"api_key": "not-a-real-key", "rate_limit": 5.0, "language": "en-US"},
}


class FakeEnricher:
    """
    Stands in for TMDBEnricher.

    `fail_titles` raise, so a partial failure can be driven through the real
    enrich_films, which collects errors rather than propagating them.
    """

    def __init__(self, fail_titles=(), fail_all=False):
        self.fail_titles = set(fail_titles)
        self.fail_all = fail_all
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def enrich(self, title, year=None, fuzzy_year=True):
        self.calls.append(title)

        if self.fail_all or title in self.fail_titles:
            raise RuntimeError("429 from TMDB")

        return EnrichmentResult(
            query_title=title,
            query_year=year,
            tmdb_movie=TMDBMovieInfo(
                tmdb_id=abs(hash(title)) % 100000,
                title=title,
                year=year,
                release_date=f"{year}-01-01" if year else None,
                overview=f"{title} is a film.",
                poster_path="/poster.jpg",
                vote_average=7.5,
            ),
            match_confidence="exact",
            streaming_offers=[
                Offer(
                    country_code="FR",
                    country_name="France",
                    provider_id=8,
                    provider_name="Netflix",
                    offer_type="flatrate",
                    logo_path="/logo.jpg",
                )
            ],
            success=True,
        )


@pytest.fixture
def fake_tmdb(monkeypatch):
    """Swap the TMDB client and the config file out of the runner's path."""
    enricher = FakeEnricher()

    monkeypatch.setattr("screenseeker.user_config.load_config", lambda: FAKE_CFG)
    monkeypatch.setattr("screenseeker.web.runner.build_enricher", lambda cfg: enricher)

    return enricher


def wait_for_job(client, job_id, timeout=10.0):
    """Poll the status endpoint the way the page does, until terminal."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        body = client.get(f"/jobs/{job_id}").text
        if "job--succeeded" in body or "job--failed" in body:
            return body
        time.sleep(0.02)

    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def job_id_from(body):
    """Pull the id out of the panel's poll URL."""
    marker = 'hx-get="/jobs/'
    if marker in body:
        return int(body.split(marker)[1].split('"')[0])
    return None


class TestRefreshJob:
    def test_a_refresh_runs_and_records_what_it_did(self, client, db, sessions, fake_tmdb):
        for i in range(3):
            make_film(db, title=f"Film {i}", tmdb_id=None, checked_days_ago=None)

        response = client.post("/jobs/refresh", headers=HTMX)
        assert response.status_code == 200

        job_id = job_id_from(response.text)
        assert job_id is not None

        body = wait_for_job(client, job_id)

        assert "job--succeeded" in body
        assert "Refreshed 3 film(s)" in body
        assert sorted(fake_tmdb.calls) == ["Film 0", "Film 1", "Film 2"]

        # The films really were written, by the worker's own session.
        check = sessions()
        try:
            assert check.query(StreamingOffer).count() == 3
            assert check.query(Film).filter(Film.last_checked.isnot(None)).count() == 3
        finally:
            check.close()

    def test_progress_is_visible_while_it_runs(self, client, db, sessions, fake_tmdb):
        make_film(db, title="Solo", checked_days_ago=None)

        job_id = job_id_from(client.post("/jobs/refresh", headers=HTMX).text)
        wait_for_job(client, job_id)

        finished = jobs.get(db, job_id)
        assert finished.progress_total == 1
        assert finished.percent == 100
        # started_at proves the row went through running, not straight to done.
        assert finished.started_at is not None
        assert finished.finished_at >= finished.started_at

    def test_nothing_stale_is_a_success_not_an_error(self, client, db, fake_tmdb):
        make_film(db, title="Fresh", checked_days_ago=0)

        job_id = job_id_from(client.post("/jobs/refresh", headers=HTMX).text)
        body = wait_for_job(client, job_id)

        assert "job--succeeded" in body
        assert "Everything is fresh" in body
        assert fake_tmdb.calls == []


class TestFailuresSurface:
    def test_a_mid_run_tmdb_failure_is_shown_not_swallowed(self, client, db, monkeypatch):
        """
        enrich_films collects per-film errors and returns normally, so without
        the job carrying them a run where films failed reports plain success.
        """
        for i, title in enumerate(("Good", "Bad", "Also Good")):
            make_film(db, title=title, tmdb_id=700 + i, checked_days_ago=None)

        enricher = FakeEnricher(fail_titles=["Bad"])
        monkeypatch.setattr("screenseeker.user_config.load_config", lambda: FAKE_CFG)
        monkeypatch.setattr("screenseeker.web.runner.build_enricher", lambda cfg: enricher)

        job_id = job_id_from(client.post("/jobs/refresh", headers=HTMX).text)
        body = wait_for_job(client, job_id)

        assert "Refreshed 2 film(s), 1 failed" in body
        assert "Bad" in body
        assert "429 from TMDB" in body

    def test_a_run_where_everything_failed_is_a_failure(self, client, db, monkeypatch):
        make_film(db, title="Doomed", checked_days_ago=None)

        monkeypatch.setattr("screenseeker.user_config.load_config", lambda: FAKE_CFG)
        monkeypatch.setattr(
            "screenseeker.web.runner.build_enricher", lambda cfg: FakeEnricher(fail_all=True)
        )

        job_id = job_id_from(client.post("/jobs/refresh", headers=HTMX).text)
        body = wait_for_job(client, job_id)

        assert "job--failed" in body
        assert "429 from TMDB" in body

    def test_a_missing_api_key_fails_the_job_rather_than_the_request(self, client, db, monkeypatch):
        make_film(db, title="Whatever", checked_days_ago=None)

        monkeypatch.setattr("screenseeker.user_config.load_config", lambda: {"tmdb": {}})

        response = client.post("/jobs/refresh", headers=HTMX)
        assert response.status_code == 200

        body = wait_for_job(client, job_id_from(response.text))
        assert "job--failed" in body
        assert "TMDB API key" in body


class TestSingleFlight:
    def test_a_second_job_of_the_same_kind_is_refused(self, client, db, sessions):
        """
        Two concurrent syncs race get_or_create_film into duplicate films, so
        this is correctness rather than an abuse control.

        The first job is inserted directly, which is what a run already in
        flight looks like to the second request.
        """
        session = sessions()
        try:
            running = jobs.claim(session, "refresh")
            jobs.start(session, running.id, total=181, message="Fetching Heat")
        finally:
            session.close()

        response = client.post("/jobs/refresh", headers=HTMX)

        assert response.status_code == 409
        # The body is the running job's panel, so the page shows what is in
        # flight instead of a dead end.
        assert "already running" in response.text
        assert "Fetching Heat" in response.text

        check = sessions()
        try:
            assert check.query(Job).filter(Job.kind == "refresh").count() == 1
        finally:
            check.close()

    def test_a_different_kind_is_not_blocked(self, client, sessions, fake_tmdb):
        session = sessions()
        try:
            running = jobs.claim(session, "sync")
            jobs.start(session, running.id)
        finally:
            session.close()

        assert client.post("/jobs/refresh", headers=HTMX).status_code == 200


class TestStatusEndpoint:
    def test_an_active_job_asks_to_be_polled_again(self, client, sessions):
        session = sessions()
        try:
            job = jobs.claim(session, "sync")
            jobs.start(session, job.id, total=10)
        finally:
            session.close()

        body = client.get(f"/jobs/{job.id}").text

        assert f'hx-get="/jobs/{job.id}"' in body
        assert "hx-trigger" in body

    def test_a_finished_job_stops_the_polling(self, client, sessions):
        session = sessions()
        try:
            job = jobs.claim(session, "sync")
            jobs.finish(session, job.id, message="Scraped 181 film(s).")
        finally:
            session.close()

        body = client.get(f"/jobs/{job.id}").text

        assert "hx-trigger" not in body
        assert "Scraped 181" in body

    def test_unknown_job_is_404(self, client):
        assert client.get("/jobs/4242").status_code == 404

    def test_unknown_kind_cannot_be_started(self, client):
        assert client.post("/jobs/vacuum", headers=HTMX).status_code == 422


class TestOrphanReaping:
    def test_startup_fails_jobs_left_running_by_a_dead_process(self, sessions, profile):
        """
        The runner is in-process, so a `running` row after a restart belongs to
        nothing. Left alone it holds the single-flight guard shut forever.
        """
        from fastapi.testclient import TestClient

        from screenseeker.web.deps import get_db, get_profile

        session = sessions()
        try:
            stranded = jobs.claim(session, "refresh")
            jobs.start(session, stranded.id, total=181)
        finally:
            session.close()

        def override_db():
            request_session = sessions()
            try:
                yield request_session
            finally:
                request_session.close()

        app = create_app(session_factory=sessions)
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_profile] = lambda: profile

        with TestClient(app) as client:
            body = client.get(f"/jobs/{stranded.id}").text
            assert "job--failed" in body
            assert "Interrupted" in body

            # And a new one can start.
            session = sessions()
            try:
                assert jobs.claim(session, "refresh").id != stranded.id
            finally:
                session.close()


class TestSyncJob:
    """
    The sync job is one job for the whole household, not one per member.

    That is forced by the schema - the partial unique index allows a single
    active job per kind, so N member jobs would reject each other - and it is
    also the right granularity to report: the household syncs or it does not.
    """

    @pytest.fixture
    def fake_scrapers(self, monkeypatch):
        """Give each username a canned watchlist, or an exception."""
        from tests.services.test_household_sync import FakeScraper

        watchlists: dict[str, object] = {}

        def build(username):
            planned = watchlists.get(username)
            if isinstance(planned, Exception):
                raise planned
            return FakeScraper(planned or [])

        monkeypatch.setattr("screenseeker.web.runner.build_scraper", build)
        return watchlists

    def test_one_job_covers_every_active_member(self, client, db, fake_scrapers):
        alice = create_member(db, "alice", display_name="Alice")
        bob = create_member(db, "bob", display_name="Bob")
        db.commit()

        fake_scrapers["alice"] = [("Heat", 1995), ("Casino", 1995)]
        fake_scrapers["bob"] = [("Heat", 1995), ("Solaris", 1972)]

        body = wait_for_job(client, job_id_from(client.post("/jobs/sync", headers=HTMX).text))

        assert "job--succeeded" in body
        assert "2 watchlist(s)" in body
        # Heat is one row wanted by two people, not two rows.
        assert db.query(Film).count() == 3
        assert db.query(WatchlistEntry).count() == 4
        assert {m.id for m in (alice, bob)} == {e.member_id for e in db.query(WatchlistEntry).all()}

    def test_a_paused_member_is_not_scraped(self, client, db, fake_scrapers):
        create_member(db, "alice", display_name="Alice")
        paused = create_member(db, "bob", display_name="Bob")
        update_member(db, paused.id, active=False)
        db.commit()

        fake_scrapers["alice"] = [("Heat", 1995)]
        fake_scrapers["bob"] = [("Solaris", 1972)]

        wait_for_job(client, job_id_from(client.post("/jobs/sync", headers=HTMX).text))

        assert [f.letterboxd_title for f in db.query(Film).all()] == ["Heat"]

    def test_one_broken_account_does_not_sink_the_others(self, client, db, fake_scrapers):
        """A private or renamed profile costs that member, not the household."""
        create_member(db, "alice", display_name="Alice")
        create_member(db, "bob", display_name="Bob")
        db.commit()

        fake_scrapers["alice"] = RuntimeError("404 from Letterboxd")
        fake_scrapers["bob"] = [("Solaris", 1972)]

        body = wait_for_job(client, job_id_from(client.post("/jobs/sync", headers=HTMX).text))

        assert "job--succeeded" in body
        assert "1 member(s) failed" in body
        assert "404 from Letterboxd" in body
        assert db.query(Film).count() == 1

    def test_a_household_where_everything_failed_is_a_failure(self, client, db, fake_scrapers):
        create_member(db, "alice", display_name="Alice")
        db.commit()

        fake_scrapers["alice"] = RuntimeError("404 from Letterboxd")

        body = wait_for_job(client, job_id_from(client.post("/jobs/sync", headers=HTMX).text))

        assert "job--failed" in body

    def test_no_members_fails_the_job_with_an_instruction(self, client, db, fake_scrapers):
        """Nothing to scrape is a setup problem, and should say so."""
        body = wait_for_job(client, job_id_from(client.post("/jobs/sync", headers=HTMX).text))

        assert "job--failed" in body
        assert "Profile page" in body
