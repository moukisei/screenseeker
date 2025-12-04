from abc import ABC, abstractmethod
from typing import Optional

from screenseeker.logger import get_logger

from ..enrichers.enrichment_models import EnrichmentResult


class BaseEnricher(ABC):
    """Abstract base class for all film enrichers."""

    def __init__(self):
        """Initialize the base enricher."""
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def enrich(self, title: str, year: Optional[int] = None) -> EnrichmentResult:
        """
        Enrich a film with streaming availability data.

        Args:
            title: Film title to search for
            year: Optional release year for better matching

        Returns:
            EnrichmentResult with streaming availability data
        """
        pass

    def __enter__(self):
        """Context manager entry."""
        return self

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass
