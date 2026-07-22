"""
Request-scoped dependencies.

`require_user` is the auth seam: a no-op today, the one function that changes
when the app leaves localhost.
"""

from typing import Iterator

from sqlalchemy.orm import Session

from .. import user_config
from ..database import session as db_session
from ..logger import get_logger

logger = get_logger(__name__)


def get_db() -> Iterator[Session]:
    """
    A session for the life of one request.

    Deliberately does not commit on exit. A GET should not open a write
    transaction, and a mutation that commits explicitly fails inside the route
    - where the error can still be turned into a response - rather than during
    dependency teardown after the body has been rendered.

    SessionLocal is read off the module at call time, not bound at import, so
    test fixtures that swap the engine take effect.
    """
    session = db_session.SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def require_user() -> None:
    """
    No-op today. Later this validates a session cookie and raises 401.

    Every mutating route already depends on it, so adding authentication is a
    change to this function rather than to each route.
    """
    return None


def get_profile() -> dict:
    """
    The subscription profile the watch strategy is ranked against.

    Re-read per request: the file is a kilobyte, and caching it would mean the
    profile form in Step 7 needs a cache-invalidation path it does not
    otherwise need. A missing or unreadable config yields defaults with no
    subscriptions, so the page renders "not on anything you pay for" instead
    of a 500.
    """
    try:
        cfg = user_config.load_config()
    except Exception as e:
        logger.warning(f"Falling back to a default profile: {e}")
        cfg = {}

    return user_config.get_subscription_profile(cfg)
