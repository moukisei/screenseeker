"""
The job ledger.

Sync and refresh take minutes, so they run in the background and report here.
Every function commits: the worker and the poll endpoint are different
sessions, and progress nobody can read is not progress.
"""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database.models import ACTIVE_JOB_STATUSES, Job
from ..exceptions import JobAlreadyRunning
from ..logger import get_logger

logger = get_logger(__name__)

KINDS = ("sync", "refresh")

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

TERMINAL_STATUSES = (SUCCEEDED, FAILED)

# How the two kinds read in a sentence.
KIND_LABELS = {"sync": "Watchlist sync", "refresh": "Availability refresh"}


class JobOut(BaseModel):
    """A job as the UI consumes it. Holds no ORM state."""

    model_config = ConfigDict(frozen=True)

    id: int
    kind: str
    status: str

    progress_current: int = 0
    progress_total: int = 0

    message: Optional[str] = None
    error: Optional[str] = Field(None, description="Set whenever anything went wrong")

    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def is_active(self) -> bool:
        """True while the UI should keep polling."""
        return self.status not in TERMINAL_STATUSES

    @property
    def percent(self) -> int:
        """Completion 0-100. Zero total means "not counted yet", not "done"."""
        if self.progress_total <= 0:
            return 0
        return min(100, round(self.progress_current / self.progress_total * 100))

    @classmethod
    def from_row(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            kind=job.kind,
            status=job.status,
            progress_current=job.progress_current or 0,
            progress_total=job.progress_total or 0,
            message=job.message,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


def _row(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(f"No job {job_id}")
    return job


def claim(session: Session, kind: str) -> JobOut:
    """
    Reserve the right to run `kind`, or refuse.

    The check below is for the error message. The guarantee comes from the
    partial unique index on jobs.kind, which is why the IntegrityError is
    translated rather than left to surface as a 500: two requests can both
    read "nothing is running" before either inserts.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown job kind: {kind!r}")

    active = (
        session.query(Job).filter(Job.kind == kind, Job.status.in_(ACTIVE_JOB_STATUSES)).first()
    )
    if active is not None:
        raise JobAlreadyRunning(kind, active.id)

    job = Job(kind=kind, status=QUEUED, progress_current=0, progress_total=0)
    session.add(job)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        active = (
            session.query(Job).filter(Job.kind == kind, Job.status.in_(ACTIVE_JOB_STATUSES)).first()
        )
        raise JobAlreadyRunning(kind, active.id if active else 0) from None

    logger.info(f"Claimed {kind} job {job.id}")
    return JobOut.from_row(job)


def get(session: Session, job_id: int) -> Optional[JobOut]:
    job = session.get(Job, job_id)
    return JobOut.from_row(job) if job else None


def latest(session: Session, kind: Optional[str] = None) -> Optional[JobOut]:
    """The most recently created job, for showing state on a fresh page load."""
    query = session.query(Job)
    if kind:
        query = query.filter(Job.kind == kind)

    job = query.order_by(Job.created_at.desc(), Job.id.desc()).first()
    return JobOut.from_row(job) if job else None


def start(session: Session, job_id: int, *, total: int = 0, message: str = "") -> JobOut:
    """Mark a claimed job as running."""
    job = _row(session, job_id)
    job.status = RUNNING
    job.started_at = datetime.now(UTC)
    job.progress_total = total
    job.message = message or None
    session.commit()
    return JobOut.from_row(job)


def report_progress(
    session: Session, job_id: int, current: int, total: int, message: str = ""
) -> None:
    """
    Record how far along the job is.

    Committed immediately - the polling request reads through a different
    session and would otherwise see nothing until the run ended.
    """
    job = _row(session, job_id)
    job.progress_current = current
    job.progress_total = total
    if message:
        job.message = message
    session.commit()


def finish(session: Session, job_id: int, *, message: str, error: str = "") -> JobOut:
    """
    Close a job that ran to completion.

    `error` is separate from status on purpose: a refresh where 12 of 181 films
    failed did finish, and hiding those 12 is exactly the vanishing this table
    exists to stop.
    """
    job = _row(session, job_id)
    job.status = SUCCEEDED
    job.message = message
    job.error = error or None
    job.progress_current = job.progress_total
    job.finished_at = datetime.now(UTC)
    session.commit()
    return JobOut.from_row(job)


def fail(session: Session, job_id: int, error: str, *, message: str = "") -> JobOut:
    """Close a job that could not run at all."""
    job = _row(session, job_id)
    job.status = FAILED
    job.error = error
    if message:
        job.message = message
    job.finished_at = datetime.now(UTC)
    session.commit()
    logger.warning(f"Job {job_id} failed: {error}")
    return JobOut.from_row(job)


def reap_orphans(session: Session) -> int:
    """
    Fail jobs left active by a process that died.

    An in-process runner loses its tasks on restart, and the rows they left
    behind would hold the single-flight guard shut forever. Called at startup,
    which is the only moment nothing of ours is running.
    """
    orphans = session.query(Job).filter(Job.status.in_(ACTIVE_JOB_STATUSES)).all()

    for job in orphans:
        job.status = FAILED
        job.error = "Interrupted: the server stopped while this job was running."
        job.finished_at = datetime.now(UTC)

    if orphans:
        session.commit()
        logger.warning(f"Reaped {len(orphans)} job(s) orphaned by a restart")

    return len(orphans)
