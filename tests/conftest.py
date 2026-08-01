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


def own(session, film, owners=None):
    """
    Put a film on a watchlist so the library will actually return it.

    Films nobody lists are not in the library at all, so a test film with no
    entry is invisible to every query - almost never what a test means. The
    `make_film` helpers call this for you.

    `owners=None` attaches a single stand-in member, created once per database.
    `owners=()` attaches nobody, which is how a test asks for a film the
    household has dropped.
    """
    from datetime import UTC, datetime

    from screenseeker.database.models import WatchlistEntry

    if owners is None:
        owners = [_stand_in_member(session)]

    for member in owners:
        session.add(
            WatchlistEntry(member_id=member.id, film_id=film.id, date_added=datetime.now(UTC))
        )
    session.flush()
    return film


def _stand_in_member(session):
    """The one member test films belong to when a test does not care who."""
    from screenseeker.database.models import Member

    member = session.query(Member).filter(Member.letterboxd_username == "tester").first()
    if member is None:
        member = Member(letterboxd_username="tester", display_name="Tester", active=True)
        session.add(member)
        session.flush()
    return member
