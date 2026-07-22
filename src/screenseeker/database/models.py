"""
SQLAlchemy models for ScreenSeeker database.
"""

from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
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

    # TMDB presentation data (needed by the web UI, unused by the CLI)
    poster_path: Mapped[Optional[str]] = Column(String, nullable=True)  # TMDB path, not a full URL
    overview: Mapped[Optional[str]] = Column(Text, nullable=True)
    vote_average: Mapped[Optional[float]] = Column(Float, nullable=True)

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
    created_at: Mapped[datetime] = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[Optional[datetime]] = Column(
        DateTime, nullable=True, onupdate=lambda: datetime.now(UTC)
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
    created_at: Mapped[datetime] = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    film: Mapped["Film"] = relationship("Film", back_populates="streaming_offers")

    def __repr__(self) -> str:
        return (
            f"<StreamingOffer(id={self.id}, film_id={self.film_id}, "
            f"provider='{self.provider_name}', country='{self.country_code}', "
            f"type='{self.monetization_type}')>"
        )


class Job(Base):
    """
    One background run of sync or refresh.

    Both take minutes, so they cannot be a request. The row is the only thing
    the web layer and the worker share: the worker writes progress, the poll
    endpoint reads it.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)

    kind: Mapped[str] = Column(String, nullable=False)  # sync | refresh
    status: Mapped[str] = Column(String, nullable=False)  # queued/running/succeeded/failed

    progress_current: Mapped[int] = Column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = Column(Integer, nullable=False, default=0)

    # What the job is doing right now, then what it did. Safe to show.
    message: Mapped[Optional[str]] = Column(Text, nullable=True)
    # Populated whenever anything went wrong, including a run that otherwise
    # succeeded with some films failing - a failure that is not recorded here
    # vanishes, which is the thing this table exists to prevent.
    error: Mapped[Optional[str]] = Column(Text, nullable=True)

    # A queued job has no started_at, so ordering by it would put new jobs
    # last. created_at is what "most recent job" means.
    created_at: Mapped[datetime] = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[Optional[datetime]] = Column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, kind='{self.kind}', status='{self.status}')>"


# A job in one of these statuses owns its kind.
ACTIVE_JOB_STATUSES = ("queued", "running")


# Indexes for common query patterns
Index(
    "idx_offers_country_provider",
    StreamingOffer.country_code,
    StreamingOffer.provider_name,
)
Index("idx_offers_checked_at", StreamingOffer.checked_at)
Index("idx_films_title_year", Film.letterboxd_title, Film.letterboxd_year)

# The single-flight guard, as a constraint rather than an application check.
# Two requests can both read "nothing is running" before either inserts, and
# two concurrent syncs race get_or_create_film into duplicate films. The
# service still checks first so the user gets a sentence instead of an
# IntegrityError, but this is what makes the guarantee true.
Index(
    "idx_jobs_one_active_per_kind",
    Job.kind,
    unique=True,
    sqlite_where=text(f"status IN ({', '.join(repr(s) for s in ACTIVE_JOB_STATUSES)})"),
)
Index("idx_jobs_created_at", Job.created_at)
