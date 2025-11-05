import hashlib
import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from logger import get_logger

logger = get_logger(__name__)


class Film(BaseModel):
    """Represents a film entry from Letterboxd."""

    film_id: str = Field(default="", description="Unique auto-generated identifier")
    film_full_title: str = Field(
        ..., description="Full display name of the film with year"
    )
    film_title: str = Field(..., description="Film title without year")
    year: Optional[int] = Field(None, description="Release year of the film")
    date_added: str = Field(..., description="Date added to watchlist")

    @staticmethod
    def parse_title_and_year(title: str) -> tuple[str, str, Optional[int]]:
        """
        Parse a full title into components.

        Args:
            title: Full title (e.g., "The Matrix (1999)" or "The Matrix")

        Returns:
            Tuple of (film_full_title, film_title, year)
        """
        # Try to parse "Title (YYYY)" format
        match = re.match(r"^(.+?)\s*\((\d{4})\)$", title.strip())

        if match:
            film_title = match.group(1).strip()
            year = int(match.group(2))
            film_full_title = f"{film_title} ({year})"
            return film_full_title, film_title, year
        else:
            # No year in title
            film_title = title.strip()
            return film_title, film_title, None

    @staticmethod
    def generate_film_id(title: str, year: Optional[int]) -> str:
        """
        Generate a deterministic unique ID for a film based on title and year.

        Args:
            title: Film title (without year)
            year: Release year

        Returns:
            Unique film ID (hash-based)
        """
        # Create a string to hash: lowercase title + year
        key = f"{title.lower().strip()}_{year or 'unknown'}"
        # Generate SHA256 hash and take first 16 characters
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    @model_validator(mode="before")
    @classmethod
    def generate_id_if_missing(cls, values):
        """Automatically generate film_id if not provided or empty."""
        if isinstance(values, dict):
            # Get film_id, film_title, and year from values
            film_id = values.get("film_id", "")
            film_title = values.get("film_title", "")
            year = values.get("year")

            # Generate ID if missing or empty
            if not film_id and film_title:
                values["film_id"] = cls.generate_film_id(film_title, year)

            # Set date_added to today if not provided
            if not values.get("date_added"):
                values["date_added"] = date.today().isoformat()

        return values

    @field_validator("film_full_title", "film_title", "date_added")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        """Ensure string fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("film_id")
    @classmethod
    def validate_film_id(cls, v: str) -> str:
        """Ensure film_id is not empty."""
        if not v:
            raise ValueError("film_id cannot be empty")
        return v

    class Config:
        frozen = True  # Make instances immutable


class ScrapingResult(BaseModel):
    """Represents the result of a scraping operation."""

    films: list[Film] = Field(default_factory=list, description="List of scraped films")
    total_pages_scraped: int = Field(
        default=0, ge=0, description="Number of pages scraped"
    )
    success: bool = Field(default=True, description="Whether scraping was successful")
    error_message: Optional[str] = Field(
        default=None, description="Error message if scraping failed"
    )
    source: str = Field(
        default="unknown", description="Source of the data (html, csv, etc.)"
    )

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
            "films": [film.model_dump() for film in self.films],
        }
