"""Data models for Letterboxd scraper using Pydantic."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class Film(BaseModel):
    """Represents a film entry from Letterboxd."""

    film_id: str = Field(..., description="Unique film identifier (slug from URI)")
    film_full_title: str = Field(..., description="Full display name of the film with year")
    film_title: str = Field(..., description="Film title without year")
    year: Optional[int] = Field(None, description="Release year of the film")
    letterboxd_uri: Optional[str] = Field(None, description="Letterboxd URI")
    date_added: Optional[str] = Field(None, description="Date added to watchlist (CSV only)")

    @classmethod
    def from_html_data(cls, title: str, film_id: str) -> "Film":
        """
        Create a Film instance from HTML scraper data.

        Args:
            title: Full display name (e.g., "The Matrix (1999)")
            film_id: Letterboxd film identifier from HTML

        Returns:
            Film instance with parsed title and year
        """
        # Parse title and year using regex pattern: "Title (YYYY)"
        match = re.match(r"^(.+?)\s*\((\d{4})\)$", title.strip())

        if match:
            film_title = match.group(1).strip()
            year = int(match.group(2))
            film_full_title = title.strip()
        else:
            # If pattern doesn't match, use full title as film_title
            film_title = title.strip()
            film_full_title = title.strip()
            year = None
            logger.warning(f"Could not parse year from title: {title}")

        return cls(
            film_id=film_id.strip(),
            film_full_title=film_full_title,
            film_title=film_title,
            year=year,
            letterboxd_uri=None,
            date_added=None
        )

    @classmethod
    def from_csv_data(
        cls,
        name: str,
        year: Optional[str],
        letterboxd_uri: str,
        date_added: Optional[str] = None
    ) -> "Film":
        """
        Create a Film instance from CSV data.

        Args:
            name: Film title without year
            year: Release year as string
            letterboxd_uri: Letterboxd URI (e.g., "https://letterboxd.com/film/the-matrix/")
            date_added: Date added to watchlist

        Returns:
            Film instance with data from CSV
        """
        # Extract film_id (slug) from URI
        # URI format: https://letterboxd.com/film/the-matrix/
        film_id = cls._extract_slug_from_uri(letterboxd_uri)

        # Parse year
        year_int = None
        if year:
            try:
                year_int = int(year.strip())
            except ValueError:
                logger.warning(f"Could not parse year: {year}")

        # Build full title
        film_title = name.strip()
        film_full_title = f"{film_title} ({year_int})" if year_int else film_title

        return cls(
            film_id=film_id,
            film_full_title=film_full_title,
            film_title=film_title,
            year=year_int,
            letterboxd_uri=letterboxd_uri.strip(),
            date_added=date_added.strip() if date_added else None
        )

    @staticmethod
    def _extract_slug_from_uri(uri: str) -> str:
        """
        Extract the film slug from a Letterboxd URI.

        Args:
            uri: Letterboxd URI (e.g., "https://letterboxd.com/film/the-matrix/")

        Returns:
            Film slug (e.g., "the-matrix")
        """
        # Remove trailing slash and split
        uri = uri.rstrip("/")
        parts = uri.split("/")

        # The slug is the last part after /film/
        if len(parts) >= 2 and parts[-2] == "film":
            return parts[-1]
        elif "film/" in uri:
            # Try to extract after "film/"
            match = re.search(r"/film/([^/]+)", uri)
            if match:
                return match.group(1)

        # Fallback: use the whole URI as ID (not ideal but safe)
        logger.warning(f"Could not extract slug from URI: {uri}, using full URI as ID")
        return uri

    @field_validator("film_id", "film_full_title", "film_title")
    def validate_non_empty_strings(cls, v: str) -> str:
        """Ensure string fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    class Config:
        frozen = True  # Make instances immutable


class ScrapingResult(BaseModel):
    """Represents the result of a scraping operation."""

    films: list[Film] = Field(default_factory=list, description="List of scraped films")
    total_pages_scraped: int = Field(default=0, ge=0, description="Number of pages scraped")
    success: bool = Field(default=True, description="Whether scraping was successful")
    error_message: Optional[str] = Field(default=None, description="Error message if scraping failed")
    source: str = Field(default="unknown", description="Source of the data (html, csv, etc.)")

    @property
    def film_count(self) -> int:
        """Return the total number of films scraped."""
        return len(self.films)

    def to_dict(self) -> dict:
        """
        Convert the scraping result to a dictionary suitable for JSON export.

        Returns:
            Dictionary with metadata and film data
        """
        return {
            "scraped_at": datetime.now().isoformat(),
            "source": self.source,
            "total_films": self.film_count,
            "total_pages_scraped": self.total_pages_scraped,
            "success": self.success,
            "error_message": self.error_message,
            "films": [film.model_dump() for film in self.films]
        }
