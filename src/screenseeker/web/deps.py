"""
Request-scoped dependencies.

`require_user` is the auth seam: a no-op when no password is set, the CSRF
origin check on every mutation when one is.
"""

from typing import Iterator

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from .. import user_config
from ..database import session as db_session
from ..logger import get_logger
from . import auth

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


async def require_user(request: Request) -> None:
    """
    The mutation half of the auth seam.

    Authentication is enforced globally by the middleware; this dependency,
    declared by every mutating route, adds the CSRF origin check to exactly
    those routes. When no password is set it is the no-op it always was.

    Kept as a per-route dependency rather than folded into the middleware so
    that "every mutation declares require_user" stays a checkable invariant -
    a POST that forgets it is a POST the origin check does not cover.
    """
    if not auth.is_enabled():
        return None

    if not auth.origin_is_trusted(request):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")

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
