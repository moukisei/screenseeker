"""
Letterboxd watchlist ingestion.

The scraper is passed in rather than constructed here so the caller decides
between HTML and CSV, and so tests can supply a fake.
"""

from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import settings
from ..exceptions import ConfigurationError
from ..logger import get_logger
from ..models import ScrapingResult
from ..scrapers.base import BaseScraper
from ..scrapers.html_scraper import HTMLScraper
from ..user_config import get_letterboxd_username
from .library import get_or_create_film

logger = get_logger(__name__)

# Called with (completed, total).
ProgressCallback = Callable[[int, int], None]


class SyncReport(BaseModel):
    """Outcome of a watchlist sync."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scraped: int = Field(..., description="Films returned by the scraper")
    added: int = Field(default=0, description="Rows created")
    existing: int = Field(default=0, description="Rows already present")
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


def build_scraper(cfg: dict) -> HTMLScraper:
    """
    Construct a Letterboxd scraper from the user's config.

    ingest_watchlist still takes a scraper rather than building one, so tests
    can pass a fake; this is only the bridge from config to the real thing,
    shared by the CLI and the background runner.
    """
    username = get_letterboxd_username(cfg)
    if not username:
        raise ConfigurationError(
            "Letterboxd username not configured. Run `screenseeker config init`."
        )

    return HTMLScraper(
        base_url=f"https://letterboxd.com/{username}/watchlist/",
        delay_between_requests=settings.HTML_DELAY_BETWEEN_REQUESTS,
        timeout=settings.HTML_TIMEOUT,
        save_raw_data=False,
        output_dir=settings.OUTPUT_DIR,
    )


def ingest_watchlist(
    session: Session,
    scraper: BaseScraper,
    *,
    on_progress: Optional[ProgressCallback] = None,
) -> SyncReport:
    """
    Scrape a watchlist and upsert every film into the database.

    The scraper's own context manager is the caller's responsibility.
    """
    result = scraper.scrape()

    if not result.success:
        return SyncReport(
            scraped=0,
            source=result.source,
            success=False,
            error_message=result.error_message,
            scraping_result=result,
        )

    total = result.film_count
    added = 0
    existing = 0

    for index, film_data in enumerate(result.films, start=1):
        if on_progress:
            on_progress(index, total)

        _, created = get_or_create_film(session, film_data.film_title, film_data.year)
        if created:
            added += 1
        else:
            existing += 1

    logger.info(f"Sync complete: {added} added, {existing} already present")

    return SyncReport(
        scraped=total,
        added=added,
        existing=existing,
        films_with_year=sum(1 for f in result.films if f.year is not None),
        pages_scraped=result.total_pages_scraped,
        source=result.source,
        success=True,
        scraping_result=result,
    )
