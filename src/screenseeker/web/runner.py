"""
The background job runner.

An in-process asyncio task per job. One user and one process, so Celery and
Redis would buy nothing; the thing they would buy - surviving a restart - is
handled by failing orphaned rows at startup instead.

The work itself is blocking `requests` code, hardened with retries and rate
limiting. It runs through `asyncio.to_thread` rather than being rewritten as
async.
"""

import asyncio
from contextlib import closing
from typing import Callable, Optional

from sqlalchemy.orm import Session

from .. import settings, user_config
from ..database import session as db_session
from ..logger import get_logger
from ..services import enrichment, jobs, members, sync
from ..services.enrichment import build_enricher, enrich_films
from ..services.jobs import JobOut
from ..services.sync import build_scraper, ingest_watchlist

logger = get_logger(__name__)

SessionFactory = Callable[[], Session]

# Failures listed in full on the job before it collapses into a count.
MAX_LISTED_ERRORS = 5


def _error_summary(report: enrichment.EnrichmentReport) -> str:
    """
    The per-film failures, as text the job row can carry.

    enrich_films collects failures rather than raising, so without this a
    refresh where 12 films failed reports plain success and the 12 vanish.
    """
    lines = [f"{e.title}: {e.error}" for e in report.errors[:MAX_LISTED_ERRORS]]
    remaining = report.failed - len(lines)
    if remaining > 0:
        lines.append(f"... and {remaining} more")
    return "\n".join(lines)


class JobRunner:
    """Runs sync and refresh in the background. One of each at a time."""

    def __init__(self, session_factory: Optional[SessionFactory] = None):
        # Read off the module when not supplied, so a test fixture that swaps
        # the engine is honoured and production still gets the real factory.
        self._session_factory = session_factory
        # Strong references: asyncio only holds weak ones, and a task that is
        # garbage collected mid-run disappears without a trace.
        self._tasks: set[asyncio.Task] = set()

    def _session(self) -> Session:
        factory = self._session_factory or db_session.SessionLocal
        return factory()

    def reap_orphans(self) -> int:
        """Fail jobs left active by a process that died. Called at startup."""
        with closing(self._session()) as session:
            return jobs.reap_orphans(session)

    async def submit(self, kind: str) -> JobOut:
        """
        Claim a job and start it, or raise JobAlreadyRunning.

        The claim happens before the task is spawned, so the guard is decided
        by the time this returns and the caller can report the refusal.
        """
        with closing(self._session()) as session:
            job = jobs.claim(session, kind)

        task = asyncio.create_task(asyncio.to_thread(self._work, job.id, kind))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return job

    # --- Worker side. Everything below runs in a thread, not on the loop. ---

    def _work(self, job_id: int, kind: str) -> None:
        """Entry point for the worker thread. Never raises."""
        handlers = {"sync": self._run_sync, "refresh": self._run_refresh}

        with closing(self._session()) as job_session:
            try:
                # Tolerated rather than required: the household lives in the
                # database, so a sync needs no config file at all. Refresh
                # still does, and says so through build_enricher.
                try:
                    cfg = user_config.load_config()
                except Exception as exc:  # noqa: BLE001 - the handler reports what it needs
                    logger.warning(f"No usable config for job {job_id} ({kind}): {exc}")
                    cfg = {}

                handlers[kind](job_id, job_session, cfg)
            except Exception as exc:  # noqa: BLE001 - recorded on the job row
                logger.exception(f"Job {job_id} ({kind}) failed")
                try:
                    jobs.fail(job_session, job_id, f"{type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001 - nothing left to report through
                    logger.exception(f"Could not record the failure of job {job_id}")

    def _progress_reporter(self, job_session: Session, job_id: int, work: Session):
        """
        Build a progress callback that commits both sessions, work first.

        SQLite allows one writer. The work session holds an open write
        transaction from the first film it saves, so committing the job row
        while that is open would block until busy_timeout expires and then
        fail. Committing the work first releases the lock, and also means an
        interrupted run keeps the films it already fetched.
        """

        def report(current: int, total: int, message: str = "") -> None:
            work.commit()
            jobs.report_progress(job_session, job_id, current, total, message)

        return report

    def _run_refresh(self, job_id: int, job_session: Session, cfg: dict) -> None:
        jobs.start(job_session, job_id, message="Looking for films that need a refresh…")
        enricher = build_enricher(cfg)

        with closing(self._session()) as work:
            films, _ = enrichment.select_stale(work, days=settings.CACHE_TTL_DAYS)

            if not films:
                jobs.finish(
                    job_session,
                    job_id,
                    message=f"Everything is fresh (checked within {settings.CACHE_TTL_DAYS} days).",
                )
                return

            report_progress = self._progress_reporter(job_session, job_id, work)
            report_progress(0, len(films), f"Refreshing {len(films)} film(s)…")

            with enricher:
                report = enrich_films(
                    work,
                    enricher,
                    films,
                    force_refresh=True,
                    on_progress=lambda done, total, title: report_progress(
                        done, total, f"Fetching {title}"
                    ),
                )

            work.commit()

        errors = _error_summary(report) if report.failed else ""

        if report.failed and not report.succeeded:
            jobs.fail(
                job_session,
                job_id,
                error=errors,
                message=f"All {report.total} film(s) failed.",
            )
            return

        summary = f"Refreshed {report.succeeded} film(s)"
        if report.failed:
            summary += f", {report.failed} failed"
        jobs.finish(job_session, job_id, message=summary + ".", error=errors)

    def _run_sync(self, job_id: int, job_session: Session, cfg: dict) -> None:
        """
        Scrape every active member's watchlist, in one job.

        One job rather than one per member: the partial unique index on `jobs`
        allows a single active row per kind, so N member jobs would simply
        reject each other. It is also the right granularity to report - the
        household syncs or it does not.
        """
        jobs.start(job_session, job_id, message="Reading the household…")

        with closing(self._session()) as work:
            household = members.list_members(work, active_only=True)

        if not household:
            jobs.fail(
                job_session,
                job_id,
                error="No active members.",
                message="Add someone on the Profile page, then sync again.",
            )
            return

        # Progress counts members, not films: the film total is unknown until
        # each scrape finishes, and a bar that jumps backwards when the second
        # person's larger watchlist lands is worse than a coarse one. The
        # per-film detail rides on the message instead.
        total_members = len(household)
        reports: list[sync.SyncReport] = []

        for index, member in enumerate(household, start=1):
            jobs.report_progress(
                job_session,
                job_id,
                index - 1,
                total_members,
                f"Scraping {member.display_name}'s watchlist…",
            )
            reports.append(self._sync_member(job_session, job_id, member, index, total_members))

        jobs.report_progress(job_session, job_id, total_members, total_members, "Finishing up…")
        self._finish_sync(job_session, job_id, sync.HouseholdSyncReport(reports=reports))

    def _sync_member(
        self,
        job_session: Session,
        job_id: int,
        member: members.MemberOut,
        index: int,
        total_members: int,
    ) -> sync.SyncReport:
        """
        One member's scrape. Never raises.

        A private profile, a renamed account or a network failure belongs to
        that member alone; the other three watchlists still sync, and the
        failure is reported on the job rather than thrown away.
        """
        try:
            scraper = build_scraper(member.letterboxd_username)

            with closing(self._session()) as work:
                report_progress = self._progress_reporter(job_session, job_id, work)

                with scraper:
                    report = ingest_watchlist(
                        work,
                        scraper,
                        member_id=member.id,
                        member_name=member.display_name,
                        on_progress=lambda done, total: report_progress(
                            index - 1,
                            total_members,
                            f"{member.display_name}: film {done} of {total}",
                        ),
                    )

                work.commit()

            return report
        except Exception as exc:  # noqa: BLE001 - recorded on the report, not raised
            logger.exception(f"Sync failed for member {member.letterboxd_username}")
            return sync.SyncReport(
                member=member.display_name,
                scraped=0,
                success=False,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    def _finish_sync(
        self, job_session: Session, job_id: int, household: sync.HouseholdSyncReport
    ) -> None:
        """Turn the per-member reports into one job outcome."""
        failures = household.failures
        errors = "\n".join(f"{r.member}: {r.error_message}" for r in failures)

        if not household.success:
            jobs.fail(
                job_session,
                job_id,
                error=errors or "Scraping failed.",
                message=f"Could not read any of the {len(household.reports)} watchlist(s).",
            )
            return

        summary = (
            f"Synced {len(household.reports) - len(failures)} watchlist(s): "
            f"{household.scraped} film(s) seen, {household.new_films} new to the library"
        )
        if household.removed:
            summary += f", {household.removed} no longer wanted"
        if failures:
            summary += f". {len(failures)} member(s) failed"

        jobs.finish(job_session, job_id, message=summary + ".", error=errors)
