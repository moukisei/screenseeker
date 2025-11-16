"""
Database package for ScreenSeeker.

Provides SQLAlchemy models and database management for persistent storage.
"""

from database.models import Base, Film, StreamingOffer
from database.session import SessionLocal, engine, get_session, init_db

__all__ = [
    "Base",
    "Film",
    "StreamingOffer",
    "SessionLocal",
    "engine",
    "get_session",
    "init_db",
]
