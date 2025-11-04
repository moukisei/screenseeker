"""Abstract base class for all scrapers."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from models import ScrapingResult

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all Letterboxd scrapers."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        save_raw_data: bool = False
    ):
        """
        Initialize the base scraper.

        Args:
            output_dir: Directory to save outputs (defaults to ./output)
            save_raw_data: Whether to save raw data for analysis
        """
        self.output_dir = output_dir or Path("./output")
        self.save_raw_data = save_raw_data
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def scrape(self) -> ScrapingResult:
        """
        Scrape films from the source.

        Returns:
            ScrapingResult containing the scraped films and metadata
        """
        pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass
