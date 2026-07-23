"""
Tests for the password-gated auth seam.

Two worlds to keep honest: with no password the app is exactly as open as
before, and with one every page needs a session and every mutation needs a
same-origin header. The unit-level token and origin checks are here too, since
a subtle bug in either is a silent lock-out or a silent hole.
"""

import time

import pytest
from fastapi.testclient import TestClient

from screenseeker.web import auth
from screenseeker.web.app import create_app
from screenseeker.web.deps import get_db, get_profile
from tests.web.conftest import make_film

PASSWORD = "correct horse"
ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def enable_auth(monkeypatch):
    """Turn auth on with a known password and http-friendly cookies."""
    monkeypatch.setattr("screenseeker.settings.PASSWORD", PASSWORD)
    monkeypatch.setattr("screenseeker.settings.SECRET_KEY", "")
    monkeypatch.setattr("screenseeker.settings.COOKIE_SECURE", False)
    monkeypatch.setattr("screenseeker.settings.SESSION_MAX_AGE_DAYS", 14)


@pytest.fixture
def auth_client(sessions, profile, enable_auth):
    app = create_app(session_factory=sessions)

    def override_db():
        s = sessions()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_profile] = lambda: profile
    with TestClient(app) as c:
        yield c


def log_in(client):
    """Post the right password; the TestClient keeps the returned cookie."""
    response = client.post(
        "/login",
        data={"password": PASSWORD},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


# ---------------------------------------------------------------------------
# The token, in isolation
# ---------------------------------------------------------------------------


class TestToken:
    def test_a_fresh_token_verifies(self, enable_auth):
        assert auth.token_is_valid(auth.issue_token())

    def test_a_tampered_token_fails(self, enable_auth):
        token = auth.issue_token()
        issued, _, sig = token.partition(".")
        # Same age, forged signature.
        assert not auth.token_is_valid(f"{issued}.{sig}x")

    def test_an_expired_token_fails(self, enable_auth):
        old = auth.issue_token(now=int(time.time()) - 15 * 86400)
        assert not auth.token_is_valid(old)

    def test_a_future_token_fails(self, enable_auth):
        ahead = auth.issue_token(now=int(time.time()) + 3600)
        assert not auth.token_is_valid(ahead)

    def test_rotating_the_password_invalidates_old_tokens(self, monkeypatch, enable_auth):
        token = auth.issue_token()
        assert auth.token_is_valid(token)

        monkeypatch.setattr("screenseeker.settings.PASSWORD", "a different password")
        # The signing secret is derived from the password, so the old cookie
        # no longer verifies.
        assert not auth.token_is_valid(token)

    def test_garbage_is_not_valid(self, enable_auth):
        for junk in ("", "nodot", "abc.def", "123.", ".sig"):
            assert not auth.token_is_valid(junk)


class TestPasswordCheck:
    def test_matches_the_configured_password(self, enable_auth):
        assert auth.password_matches(PASSWORD)

    def test_rejects_the_wrong_password(self, enable_auth):
        assert not auth.password_matches("wrong")

    def test_rejects_everything_when_no_password_is_set(self, monkeypatch):
        monkeypatch.setattr("screenseeker.settings.PASSWORD", "")
        assert not auth.password_matches("")
        assert not auth.password_matches("anything")


# ---------------------------------------------------------------------------
# Disabled: the app must behave exactly as before
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_pages_are_open_without_a_password(self, client, db):
        make_film(db, title="Open", tmdb_id=1)
        # `client` is the default fixture: no password configured.
        assert client.get("/").status_code == 200
        assert "Open" in client.get("/").text

    def test_login_page_bounces_out_when_auth_is_off(self, client):
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_mutations_need_no_origin_when_auth_is_off(self, client, db):
        film = make_film(db, title="Toggle", tmdb_id=1)
        # No Origin header, no session - still fine, because auth is off.
        response = client.post(
            f"/film/{film.id}/watched",
            data={"watched": "true"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Enabled: authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_an_anonymous_page_redirects_to_login(self, auth_client):
        response = auth_client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login?next=%2F"

    def test_an_anonymous_htmx_request_gets_a_redirect_header(self, auth_client):
        response = auth_client.get("/", headers={"HX-Request": "true"})
        assert response.status_code == 401
        assert response.headers["HX-Redirect"] == "/login"

    def test_the_login_page_itself_is_reachable(self, auth_client):
        response = auth_client.get("/login")
        assert response.status_code == 200
        assert "Password" in response.text

    def test_static_assets_stay_public(self, auth_client):
        # The login page needs its stylesheet before anyone is logged in.
        assert auth_client.get("/static/app.css").status_code == 200

    def test_the_right_password_logs_in_and_unlocks_pages(self, auth_client, db):
        make_film(db, title="Secret", tmdb_id=1)
        log_in(auth_client)

        response = auth_client.get("/")
        assert response.status_code == 200
        assert "Secret" in response.text

    def test_the_wrong_password_is_rejected(self, auth_client):
        response = auth_client.post(
            "/login", data={"password": "nope"}, headers=ORIGIN, follow_redirects=False
        )
        assert response.status_code == 401
        assert "not right" in response.text
        # And no session was handed out.
        assert auth.COOKIE_NAME not in response.cookies

    def test_login_honours_a_safe_next(self, auth_client):
        response = auth_client.post(
            "/login",
            data={"password": PASSWORD, "next": "/stale"},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.headers["location"] == "/stale"

    def test_login_refuses_an_off_site_next(self, auth_client):
        response = auth_client.post(
            "/login",
            data={"password": PASSWORD, "next": "//evil.example/phish"},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.headers["location"] == "/"

    def test_logout_clears_the_session(self, auth_client):
        log_in(auth_client)
        assert auth_client.get("/").status_code == 200

        auth_client.post("/logout", headers=ORIGIN, follow_redirects=False)

        # Cookie gone: back to being bounced.
        assert auth_client.get("/", follow_redirects=False).status_code == 303


# ---------------------------------------------------------------------------
# Enabled: CSRF via the origin check
# ---------------------------------------------------------------------------


class TestCsrf:
    def test_origin_check_accepts_our_own_host(self, enable_auth):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"host", b"seek.example"), (b"origin", b"https://seek.example")],
        }
        assert auth.origin_is_trusted(Request(scope))

    def test_origin_check_rejects_another_host(self, enable_auth):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"host", b"seek.example"), (b"origin", b"https://evil.example")],
        }
        assert not auth.origin_is_trusted(Request(scope))

    def test_a_mutation_without_an_origin_is_refused(self, auth_client, db):
        film = make_film(db, title="Guarded", tmdb_id=1)
        log_in(auth_client)

        # Logged in, valid session cookie, but no Origin header: the forged
        # cross-site POST shape.
        response = auth_client.post(
            f"/film/{film.id}/watched",
            data={"watched": "true"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 403

    def test_a_cross_origin_mutation_is_refused(self, auth_client, db):
        film = make_film(db, title="Guarded", tmdb_id=1)
        log_in(auth_client)

        response = auth_client.post(
            f"/film/{film.id}/watched",
            data={"watched": "true"},
            headers={"HX-Request": "true", "origin": "http://evil.example"},
        )
        assert response.status_code == 403

    def test_a_same_origin_mutation_succeeds(self, auth_client, db):
        film = make_film(db, title="Guarded", tmdb_id=1)
        log_in(auth_client)

        response = auth_client.post(
            f"/film/{film.id}/watched",
            data={"watched": "true"},
            headers={"HX-Request": "true", **ORIGIN},
        )
        assert response.status_code == 200

        db.expire_all()
        assert db.get(type(film), film.id).watched is True
