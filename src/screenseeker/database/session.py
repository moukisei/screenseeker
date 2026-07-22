"""
Database session management and engine setup.
"""

import sqlite3
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .. import settings
from ..logger import get_logger
from .models import Base

logger = get_logger(__name__)

# Resolved in settings.py from the environment, with a fallback to the legacy
# in-checkout location so an existing database is not orphaned.
DATABASE_DIR = settings.DB_DIR
DATABASE_PATH = settings.DB_PATH
DATABASE_URL = settings.DATABASE_URL


@event.listens_for(Engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record):
    """
    Apply the pragmas SQLite needs to behave under a server.

    Registered against the Engine class rather than one instance so every
    engine gets them - the app's, the test fixtures', and the web layer's.

    - WAL lets readers run alongside a single writer instead of blocking.
    - busy_timeout makes a blocked writer wait instead of failing instantly
      with "database is locked".
    - foreign_keys is OFF by default in SQLite, which means the ON DELETE
      CASCADE declared on streaming_offers.film_id was never enforced.
      Deleting a film orphaned its offers.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_db_engine(url: str = DATABASE_URL, echo: bool = False):
    """Build an engine with the connection arguments SQLite needs."""
    return create_engine(
        url,
        echo=echo,
        # Allow SQLite to be used from more than one thread.
        connect_args={"check_same_thread": False},
    )


engine = create_db_engine(DATABASE_URL)

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
        # In WAL mode recent writes live in the -wal sidecar until a
        # checkpoint, so the main file alone understates the real size - a
        # freshly created database reports 0 bytes.
        size_bytes = sum(
            path.stat().st_size
            for path in (
                DATABASE_PATH,
                DATABASE_PATH.with_name(DATABASE_PATH.name + "-wal"),
                DATABASE_PATH.with_name(DATABASE_PATH.name + "-shm"),
            )
            if path.exists()
        )
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
