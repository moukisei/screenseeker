"""
Pytest configuration and fixtures.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from screenseeker.database.models import Base

# Module namespaces that bind the session globals by value at import time and
# therefore need patching alongside the session module itself.
_REBIND_TARGETS = (
    "screenseeker.database",
    "screenseeker.database.session",
    "tests.database.test_database",
)


@pytest.fixture(autouse=True)
def isolate_database(tmp_path, monkeypatch):
    """
    Point the module-level engine at a throwaway database for every test.

    Several tests call init_db(), get_database_info() and reset_database(),
    which act on the global engine rather than on the fixtures below. Without
    this fixture they hit the real data/screenseeker.db, and reset_database()
    drops the user's watchlist on every test run.
    """
    import importlib
    import sys

    db_path = tmp_path / "screenseeker.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    replacements = {
        "DATABASE_DIR": tmp_path,
        "DATABASE_PATH": db_path,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "engine": engine,
        "SessionLocal": session_factory,
    }

    for mod_name in _REBIND_TARGETS:
        try:
            mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
        except ImportError:
            continue
        for attr, value in replacements.items():
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, value, raising=False)

    yield

    engine.dispose()


@pytest.fixture(scope="function")
def test_db_engine():
    """Create an in-memory SQLite database engine for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_db_engine):
    """Create a test database session."""
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
