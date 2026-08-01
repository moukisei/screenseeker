"""
Letterboxd watchlist ingestion, one member at a time.

Each member is scraped separately and reconciled against what they had last
time, so the household's list stays honest in both directions: films someone
adds appear, films someone drops stop counting towards "wanted by".

The scraper is passed in rather than constructed here so the caller decides
between HTML and CSV, and so tests can supply a fake.
"""

from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import settings
from ..logger import get_logger
from ..models import ScrapingResult
from ..scrapers.base import BaseScraper
from ..scrapers.html_scraper import HTMLScraper
from .library import get_or_create_film, record_entry, retire_missing_entries
from .members import mark_synced

logger = get_logger(__name__)

# Called with (completed, total).
ProgressCallback = Callable[[int, int], None]


class SyncReport(BaseModel):
    """Outcome of one member's watchlist sync."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    member: str = Field(default="", description="Display name of the member synced")

    scraped: int = Field(..., description="Films returned by the scraper")
    added: int = Field(default=0, description="Films new to this member's list")
    existing: int = Field(default=0, description="Films already on this member's list")
    restored: int = Field(default=0, description="Films they had removed and put back")
    removed: int = Field(default=0, description="Films no longer on their watchlist")
    new_films: int = Field(default=0, description="Films new to the household entirely")

    films_with_year: int = 0
    pages_scraped: int = 0
    source: str = "unknown"

    success: bool = True
    error_message: Optional[str] = None

    # Kept so the CLI can still export the raw scrape to JSON.
    scraping_result: Optional[ScrapingResult] = None

    @property
    def year_coverage(self) -> float:
        """Percentage of scraped films that carried a year."""
        return (self.films_with_year / self.scraped * 100) if self.scraped else 0.0


class HouseholdSyncReport(BaseModel):
    """Every member's sync in one run, as the job and the CLI summarise it."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    reports: list[SyncReport] = Field(default_factory=list)

    @property
    def scraped(self) -> int:
        return sum(r.scraped for r in self.reports)

    @property
    def added(self) -> int:
        return sum(r.added for r in self.reports)

    @property
    def new_films(self) -> int:
        return sum(r.new_films for r in self.reports)

    @property
    def removed(self) -> int:
        return sum(r.removed for r in self.reports)

    @property
    def failures(self) -> list[SyncReport]:
        return [r for r in self.reports if not r.success]

    @property
    def success(self) -> bool:
        """
        True when at least one member synced.

        Not "every member succeeded": one person's private or renamed profile
        must not throw away the three that scraped fine. The failures are
        carried on the report and surfaced separately.
        """
        return any(r.success for r in self.reports)


def watchlist_url(username: str) -> str:
    """The watchlist page for a Letterboxd account."""
    return f"https://letterboxd.com/{username}/watchlist/"


def build_scraper(username: str) -> HTMLScraper:
    """
    Construct a Letterboxd scraper for one member's watchlist.

    ingest_watchlist still takes a scraper rather than building one, so tests
    can pass a fake; this is only the bridge from a username to the real thing,
    shared by the CLI and the background runner.
    """
    return HTMLScraper(
        base_url=watchlist_url(username),
        delay_between_requests=settings.HTML_DELAY_BETWEEN_REQUESTS,
        timeout=settings.HTML_TIMEOUT,
        save_raw_data=False,
        output_dir=settings.OUTPUT_DIR,
    )


def ingest_watchlist(
    session: Session,
    scraper: BaseScraper,
    *,
    member_id: int,
    member_name: str = "",
    on_progress: Optional[ProgressCallback] = None,
) -> SyncReport:
    """
    Scrape one member's watchlist and reconcile it against what they had.

    Films are shared across the household - the same title on three watchlists
    is one Film row and three entries - so a film another member already added
    costs no TMDB lookup here.

    The scraper's own context manager is the caller's responsibility.
    """
    result = scraper.scrape()

    if not result.success:
        return SyncReport(
            member=member_name,
            scraped=0,
            source=result.source,
            success=False,
            error_message=result.error_message,
            scraping_result=result,
        )

    total = result.film_count
    counts = {"added": 0, "existing": 0, "restored": 0}
    new_films = 0
    seen: set[int] = set()

    for index, film_data in enumerate(result.films, start=1):
        if on_progress:
            on_progress(index, total)

        film, created = get_or_create_film(session, film_data.film_title, film_data.year)
        if created:
            new_films += 1

        counts[record_entry(session, member_id, film)] += 1
        seen.add(film.id)

    # A successful scrape that returned nothing is far more often a broken
    # scrape than an emptied watchlist - a rate limit, a login wall, a changed
    # page layout. Retiring on it would wipe this member's whole list, so the
    # reconcile pass is skipped and the entries stand until a scrape that
    # actually read something disagrees with them.
    removed = 0
    if total:
        removed = retire_missing_entries(session, member_id, seen)
        mark_synced(session, member_id)
    else:
        logger.warning(
            f"Scrape of '{member_name or member_id}' returned no films; "
            "keeping their existing entries rather than retiring them."
        )

    logger.info(
        f"Synced {member_name or member_id}: {counts['added']} added, "
        f"{counts['restored']} restored, {counts['existing']} unchanged, {removed} removed"
    )

    return SyncReport(
        member=member_name,
        scraped=total,
        added=counts["added"],
        existing=counts["existing"],
        restored=counts["restored"],
        removed=removed,
        new_films=new_films,
        films_with_year=sum(1 for f in result.films if f.year is not None),
        pages_scraped=result.total_pages_scraped,
        source=result.source,
        success=True,
        scraping_result=result,
    )
