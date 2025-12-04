"""
Database session management and engine setup.
"""

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..logger import get_logger
from .models import Base

logger = get_logger(__name__)

# Database configuration
# Go up from src/screenseeker/database/ to project root, then into data/
DATABASE_DIR = Path(__file__).parent.parent.parent.parent / "data"
DATABASE_PATH = DATABASE_DIR / "screenseeker.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create engine
# echo=False for production, set to True for SQL debugging
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # Allow SQLite to be used in multiple threads
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """
    Initialize database by creating all tables if they don't exist.

    This function is idempotent - safe to call multiple times.
    Creates the data/ directory if it doesn't exist.
    """
    # Ensure data directory exists
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    # Check if database exists
    db_exists = DATABASE_PATH.exists()

    if not db_exists:
        logger.info(f"Creating new database at {DATABASE_PATH}")
    else:
        logger.debug(f"Database already exists at {DATABASE_PATH}")

    # Create all tables (idempotent)
    Base.metadata.create_all(bind=engine)

    if not db_exists:
        logger.info("Database initialized successfully")
        logger.info("Tables created: films, streaming_offers")
    else:
        logger.debug("Database tables verified")


@contextmanager
def get_session() -> Session:
    """
    Context manager for database sessions.

    Usage:
        with get_session() as session:
            film = session.query(Film).first()
            # ... do work ...
            session.commit()

    Automatically handles:
    - Session creation
    - Commit on success
    - Rollback on error
    - Session cleanup
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        session.close()


def get_database_info() -> dict:
    """
    Get information about the database.

    Returns:
        Dictionary with database metadata
    """
    db_exists = DATABASE_PATH.exists()

    info = {
        "path": str(DATABASE_PATH),
        "exists": db_exists,
        "url": DATABASE_URL,
    }

    if db_exists:
        # Get file size
        size_bytes = DATABASE_PATH.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        info["size_bytes"] = size_bytes
        info["size_mb"] = round(size_mb, 2)

        # Get table counts
        try:
            with get_session() as session:
                from .models import Film, StreamingOffer

                film_count = session.query(Film).count()
                offer_count = session.query(StreamingOffer).count()

                info["film_count"] = film_count
                info["offer_count"] = offer_count
        except Exception as e:
            logger.warning(f"Could not fetch database stats: {e}")
            info["film_count"] = None
            info["offer_count"] = None

    return info


def reset_database() -> None:
    """
    Drop all tables and recreate them.

    WARNING: This will delete all data!
    Use only for development/testing.
    """
    logger.warning("Resetting database - all data will be lost!")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logger.info("Database reset complete")
