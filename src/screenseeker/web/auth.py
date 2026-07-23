"""
The authentication seam, made real.

One shared password, one signed session cookie, gated entirely on
`settings.PASSWORD`. When it is empty this module's `is_enabled()` is False and
every check short-circuits to "allowed" - the app runs exactly as it did on
localhost and behind a tailnet, and none of this is in the request path.

No new dependency: the token is signed with stdlib HMAC-SHA256. Possession of a
validly signed cookie proves the holder knew the secret, and the secret is
derived from the password, so there is no per-user identity to store.
"""

import base64
import hashlib
import hmac
import time
from urllib.parse import urlparse

from starlette.requests import Request

from .. import settings
from ..logger import get_logger

logger = get_logger(__name__)

COOKIE_NAME = "screenseeker_session"

# Paths reachable without a session: the login form, logging out, and the
# static assets the login page itself needs.
EXEMPT_PREFIXES = ("/login", "/logout", "/static/")

# Methods that change state and therefore get the CSRF origin check.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_enabled() -> bool:
    """True when a password is configured. The whole module hinges on this."""
    return bool(settings.PASSWORD)


def _secret() -> bytes:
    """
    The HMAC key.

    An explicit SECRET_KEY wins; otherwise it is derived from the password, so
    a single env var is enough to run and changing the password invalidates
    every existing session - a feature, not a bug.
    """
    if settings.SECRET_KEY:
        return settings.SECRET_KEY.encode()
    return hashlib.sha256(f"screenseeker-session:{settings.PASSWORD}".encode()).digest()


def _sign(message: str) -> str:
    digest = hmac.new(_secret(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_token(*, now: int | None = None) -> str:
    """A fresh signed session token. The payload is just its issue time."""
    issued = str(int(now if now is not None else time.time()))
    return f"{issued}.{_sign(issued)}"


def token_is_valid(token: str, *, now: int | None = None) -> bool:
    """
    Verify signature and age in constant time.

    A tampered or expired token is indistinguishable from an absent one: the
    caller treats False as "not logged in".
    """
    if not token or "." not in token:
        return False

    issued_str, provided = token.split(".", 1)
    if not hmac.compare_digest(provided, _sign(issued_str)):
        return False

    try:
        issued = int(issued_str)
    except ValueError:
        return False

    age = int(now if now is not None else time.time()) - issued
    max_age = settings.SESSION_MAX_AGE_DAYS * 86400
    # Reject the future too: a clock-skewed or forged-forward stamp is not ours.
    return -300 <= age <= max_age


def password_matches(candidate: str) -> bool:
    """Constant-time comparison against the configured password."""
    if not settings.PASSWORD:
        return False
    return hmac.compare_digest(candidate, settings.PASSWORD)


def request_is_authenticated(request: Request) -> bool:
    """True when the request carries a valid session cookie."""
    return token_is_valid(request.cookies.get(COOKIE_NAME, ""))


def is_exempt(path: str) -> bool:
    return path.startswith(EXEMPT_PREFIXES)


def cookie_params() -> dict:
    """
    The flags every session cookie is set and cleared with.

    HttpOnly keeps it out of JavaScript. SameSite=Lax stops a cross-site POST
    from carrying it, which is the first half of the CSRF defence. Secure is
    configurable only so auth can be exercised over http on localhost.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.COOKIE_SECURE,
        "path": "/",
    }


def origin_is_trusted(request: Request) -> bool:
    """
    The second half of the CSRF defence: the request must come from us.

    Compares the Origin (or Referer) host against the Host the browser sent.
    Browsers attach Origin to state-changing requests, so a form POST forged by
    another site fails this even if SameSite were somehow bypassed. Behind a
    proxy the Host header is the public name, which is what Origin carries, so
    they still match.
    """
    host = request.headers.get("host")
    if not host:
        return False

    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if value:
            return urlparse(value).netloc == host

    # Neither present. A browser sends at least one on a real cross-document
    # POST; their joint absence is not something to wave through under auth.
    return False


def safe_next(target: str | None) -> str:
    """
    A post-login redirect target that cannot leave the site.

    Only a path beginning with a single slash is allowed, so `next` cannot be
    turned into an open redirect to `//evil.example`.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"
