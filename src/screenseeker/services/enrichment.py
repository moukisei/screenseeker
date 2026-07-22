"""
Batch TMDB enrichment.

Progress is reported through a callback rather than written to a terminal, so
the same code drives the CLI progress bar and, later, a background job that
persists progress for the web UI.
"""

from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database.models import Film
from ..database.queries import get_stale_films
from ..database.service import enrich_and_save_film
from ..enrichers.tmdb_enricher import TMDBEnricher
from ..logger import get_logger
from .models import FilmSummary

logger = get_logger(__name__)

# Called with (completed, total, current_film_title).
ProgressCallback = Callable[[int, int, str], None]


class FilmError(BaseModel):
    """One film that failed to enrich."""

    model_config = ConfigDict(frozen=True)

    film_id: Optional[int] = None
    title: str
    error: str


class EnrichmentReport(BaseModel):
    """Outcome of a batch run."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(..., description="Films attempted")
    succeeded: int = 0
    failed: int = 0
    errors: list[FilmError] = Field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return self.failed == 0


def select_unenriched(
    session: Session, limit: Optional[int] = None
) -> tuple[list[FilmSummary], int]:
    """
    Films with no TMDB match yet.

    Returns (selection, total_found) so callers can say "limiting to N of M".
    """
    films = session.query(Film).filter(Film.tmdb_id.is_(None)).all()
    total = len(films)
    if limit:
        films = films[:limit]
    return [FilmSummary.from_film(f, offer_count=0) for f in films], total


def select_all(session: Session, limit: Optional[int] = None) -> tuple[list[FilmSummary], int]:
    """Every film, for a forced re-enrichment."""
    films = session.query(Film).all()
    total = len(films)
    if limit:
        films = films[:limit]
    return [FilmSummary.from_film(f) for f in films], total


def select_stale(
    session: Session, days: int = 7, limit: Optional[int] = None
) -> tuple[list[FilmSummary], int]:
    """Films whose streaming data has aged past `days`."""
    films = get_stale_films(session, days=days)
    total = len(films)
    if limit:
        films = films[:limit]
    return [FilmSummary.from_film(f) for f in films], total


def enrich_films(
    session: Session,
    enricher: TMDBEnricher,
    films: list[FilmSummary],
    *,
    force_refresh: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> EnrichmentReport:
    """
    Enrich each film in turn, collecting rather than raising per-film errors.

    One film failing must not abort the batch - a single bad TMDB response
    should not cost the caller the whole run.
    """
    total = len(films)
    succeeded = 0
    errors: list[FilmError] = []

    for index, film in enumerate(films, start=1):
        if on_progress:
            on_progress(index, total, film.full_title)

        try:
            enrich_and_save_film(
                session,
                enricher,
                film.title,
                film.year,
                force_refresh=force_refresh,
            )
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            logger.warning(f"Enrichment failed for '{film.full_title}': {exc}")
            errors.append(FilmError(film_id=film.id, title=film.full_title, error=str(exc)))

    return EnrichmentReport(
        total=total,
        succeeded=succeeded,
        failed=len(errors),
        errors=errors,
    )
