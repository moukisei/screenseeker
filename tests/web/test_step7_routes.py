"""
Route tests for Tonight, Stale and the profile form.

These check the wiring the service tests cannot: that Tonight renders the
strategy's picks, that the key is never sent to the browser, and that the
subscription form survives a full POST round trip including a checkbox that
submits nothing.
"""

import tomllib

import pytest
from fastapi.testclient import TestClient

from screenseeker.web.app import create_app
from screenseeker.web.deps import get_db, get_profile
from tests.web.conftest import make_film


class TestTonightRoute:
    def test_lists_only_base_country_no_vpn_picks(self, client, db):
        make_film(db, title="Ready", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        make_film(db, title="Abroad", tmdb_id=2, offers=[("US", "Netflix", "flatrate")])
        make_film(db, title="Rental", tmdb_id=3, offers=[("FR", "Netflix", "rent")])
        make_film(db, title="Dropped", tmdb_id=4, owners=(), offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/tonight").text

        assert "Ready" in body
        assert "badge--best" in body
        assert "Netflix" in body
        assert "Abroad" not in body
        assert "Rental" not in body
        assert "Dropped" not in body
        assert "1 film ready" in body

    def test_says_so_when_nothing_is_watchable(self, client, db):
        make_film(db, title="Abroad", tmdb_id=1, offers=[("US", "Netflix", "flatrate")])

        body = client.get("/tonight").text

        assert "Nothing to watch tonight" in body


class TestStaleRoute:
    def test_lists_never_checked_and_old_films(self, client, db):
        make_film(db, title="Never", tmdb_id=1, checked_days_ago=None)
        make_film(db, title="Old", tmdb_id=2, checked_days_ago=30)
        make_film(db, title="Fresh", tmdb_id=3, checked_days_ago=0)

        body = client.get("/stale").text

        assert "Never" in body
        assert "Old" in body
        assert "Fresh" not in body
        assert "2 stale films" in body

    def test_offers_the_refresh_action(self, client, db):
        make_film(db, title="Old", tmdb_id=1, checked_days_ago=30)

        body = client.get("/stale").text

        assert 'action="/jobs/refresh"' in body
        assert 'id="job-panel"' in body

    def test_empty_when_all_fresh(self, client, db):
        make_film(db, title="Fresh", tmdb_id=1, checked_days_ago=0)

        assert "Nothing is stale" in client.get("/stale").text


class TestProfileForm:
    """
    A dedicated app whose config points at a temp file, so a POST cannot touch
    the real profile.
    """

    @pytest.fixture
    def profile_config(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        path.write_text(
            '[letterboxd]\nusername = "someone"\n'
            '[tmdb]\napi_key = "the-real-key"\n'
            '[profile]\nbase_country = "FR"\nvpn_country_priority = ["US"]\n'
        )
        monkeypatch.setattr("screenseeker.user_config.CONFIG_PATH", path)
        monkeypatch.setattr("screenseeker.user_config.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("screenseeker.settings.TMDB_API_KEY_ENV", None)
        return path

    @pytest.fixture
    def profile_client(self, sessions, profile, profile_config):
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

    def read(self, path):
        with open(path, "rb") as f:
            return tomllib.load(f)

    def test_get_never_sends_the_key(self, profile_client, profile_config):
        body = profile_client.get("/profile").text

        assert "the-real-key" not in body
        assert "leave blank to keep" in body
        assert 'type="password"' in body

    def test_add_subscription_returns_a_blank_row(self, profile_client):
        body = profile_client.get("/profile/subscription").text

        assert "-provider_name" in body
        assert "Remove" in body

    def test_saving_writes_the_subscriptions(self, profile_client, profile_config):
        response = profile_client.post(
            "/profile",
            data={
                "base_country": "GB",
                "max_vpn_suggestions": "2",
                "vpn_priority": "US\nGB",
                "sub-a-provider_name": "Netflix",
                "sub-a-vpn_enabled": "on",
                "sub-a-countries": "all",
                "sub-b-provider_name": "Canal+",
                # sub-b has no vpn_enabled key - the unchecked box.
                "sub-b-countries": "FR",
                "sub-b-bundles": "Paramount+",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/profile?saved=1"

        stored = self.read(profile_config)
        subs = stored["profile"]["subscriptions"]
        assert stored["profile"]["base_country"] == "GB"
        assert len(subs) == 2

        netflix = next(s for s in subs if s["provider_names"] == ["Netflix"])
        canal = next(s for s in subs if s["provider_names"] == ["Canal+"])
        # The checkbox that submitted a value is True; the one that submitted
        # nothing is False - and they did not slide onto each other.
        assert netflix["vpn_enabled"] is True
        assert canal["vpn_enabled"] is False
        assert canal["available_countries"] == ["FR"]
        assert canal["bundle_includes"] == ["Paramount+"]

    def test_saving_a_blank_key_preserves_the_existing_one(self, profile_client, profile_config):
        profile_client.post(
            "/profile",
            data={
                "base_country": "FR",
                "max_vpn_suggestions": "3",
                "vpn_priority": "US",
                "api_key": "",
            },
            follow_redirects=False,
        )

        assert self.read(profile_config)["tmdb"]["api_key"] == "the-real-key"

    def test_saving_preserves_the_letterboxd_username(self, profile_client, profile_config):
        profile_client.post(
            "/profile",
            data={"base_country": "FR", "max_vpn_suggestions": "3", "vpn_priority": "US"},
            follow_redirects=False,
        )

        assert self.read(profile_config)["letterboxd"]["username"] == "someone"
