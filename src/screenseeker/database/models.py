"""
SQLAlchemy models for ScreenSeeker database.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class Film(Base):
    """
    Represents a film from Letterboxd watchlist with TMDB enrichment data.

    Stores both Letterboxd metadata (as scraped) and TMDB metadata (after matching)
    to handle year mismatches and provide canonical film identification.
    """

    __tablename__ = "films"

    # Primary key
    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)

    # Letterboxd data (as scraped from user's watchlist)
    letterboxd_title: Mapped[str] = Column(String, nullable=False, index=True)
    letterboxd_year: Mapped[Optional[int]] = Column(Integer, nullable=True)

    # TMDB data (after enrichment) - canonical source of truth
    tmdb_id: Mapped[Optional[int]] = Column(Integer, nullable=True, unique=True, index=True)
    tmdb_title: Mapped[Optional[str]] = Column(String, nullable=True)
    tmdb_year: Mapped[Optional[int]] = Column(Integer, nullable=True)
    tmdb_release_date: Mapped[Optional[str]] = Column(
        String, nullable=True
    )  # Full date: YYYY-MM-DD

    # Match metadata
    match_confidence: Mapped[Optional[str]] = Column(
        String, nullable=True
    )  # exact/high/medium/low/none
    year_mismatch: Mapped[bool] = Column(Boolean, default=False)  # Flag for year discrepancies

    # Watchlist metadata
    date_added: Mapped[datetime] = Column(DateTime, nullable=False)  # When added to watchlist
    watched: Mapped[bool] = Column(Boolean, default=False)  # Track if watched
    watched_at: Mapped[Optional[datetime]] = Column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = Column(Text, nullable=True)  # Personal notes

    # Cache metadata
    last_checked: Mapped[Optional[datetime]] = Column(
        DateTime, nullable=True, index=True
    )  # When streaming data was last fetched

    # Timestamps
    created_at: Mapped[datetime] = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = Column(
        DateTime, nullable=True, onupdate=datetime.utcnow
    )

    # Relationships
    streaming_offers: Mapped[List["StreamingOffer"]] = relationship(
        "StreamingOffer", back_populates="film", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        year = self.letterboxd_year or self.tmdb_year or "Unknown"
        title = self.letterboxd_title or self.tmdb_title
        return f"<Film(id={self.id}, title='{title}', year={year}, tmdb_id={self.tmdb_id})>"

    @property
    def display_title(self) -> str:
        """Get the best title for display (prefer Letterboxd)."""
        return self.letterboxd_title or self.tmdb_title or "Unknown"

    @property
    def display_year(self) -> Optional[int]:
        """Get the best year for display (prefer Letterboxd)."""
        return self.letterboxd_year or self.tmdb_year

    @property
    def full_title(self) -> str:
        """Get full title with year."""
        year = self.display_year
        if year:
            return f"{self.display_title} ({year})"
        return self.display_title


class StreamingOffer(Base):
    """
    Represents a streaming availability offer for a film.

    Caches TMDB streaming provider data to reduce API calls.
    """

    __tablename__ = "streaming_offers"

    # Primary key
    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to film
    film_id: Mapped[int] = Column(
        Integer, ForeignKey("films.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Streaming offer details
    country_code: Mapped[str] = Column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    country_name: Mapped[str] = Column(String, nullable=False)
    provider_id: Mapped[int] = Column(Integer, nullable=False)  # TMDB provider ID
    provider_name: Mapped[str] = Column(String, nullable=False, index=True)
    monetization_type: Mapped[str] = Column(String, nullable=False)  # flatrate/rent/buy/free/ads

    # Optional fields
    streaming_url: Mapped[Optional[str]] = Column(Text, nullable=True)
    logo_path: Mapped[Optional[str]] = Column(String, nullable=True)
    display_priority: Mapped[Optional[int]] = Column(Integer, nullable=True)

    # Cache metadata
    checked_at: Mapped[datetime] = Column(DateTime, nullable=False)  # When this offer was verified

    # Timestamps
    created_at: Mapped[datetime] = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    film: Mapped["Film"] = relationship("Film", back_populates="streaming_offers")

    def __repr__(self) -> str:
        return (
            f"<StreamingOffer(id={self.id}, film_id={self.film_id}, "
            f"provider='{self.provider_name}', country='{self.country_code}', "
            f"type='{self.monetization_type}')>"
        )


# Indexes for common query patterns
Index(
    "idx_offers_country_provider",
    StreamingOffer.country_code,
    StreamingOffer.provider_name,
)
Index("idx_offers_checked_at", StreamingOffer.checked_at)
Index("idx_films_title_year", Film.letterboxd_title, Film.letterboxd_year)
