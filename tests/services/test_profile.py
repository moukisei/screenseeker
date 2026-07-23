"""
Tests for the profile service.

Two rules carry real risk if broken: saving must merge (never lose the
Letterboxd username or a key), and the API key is write-only (a blank field
must not wipe a key nobody was shown).
"""

import tomllib

import pytest

from screenseeker.services import profile
from screenseeker.services.profile import ProfileForm, SubscriptionForm


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Point the config at a throwaway file for both load and save."""
    path = tmp_path / "config.toml"
    monkeypatch.setattr("screenseeker.user_config.CONFIG_PATH", path)
    monkeypatch.setattr("screenseeker.user_config.CONFIG_DIR", tmp_path)
    # No environment key unless a test sets one.
    monkeypatch.setattr("screenseeker.settings.TMDB_API_KEY_ENV", None)
    return path


def write(path, text):
    path.write_text(text)


def read(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


class TestLoad:
    def test_loads_subscriptions_into_form_rows(self, config_path):
        write(
            config_path,
            """
[letterboxd]
username = "someone"
[tmdb]
api_key = "secret"
[profile]
base_country = "FR"
max_vpn_suggestions = 2
vpn_country_priority = ["US", "GB"]
[[profile.subscriptions]]
provider_names = ["Netflix"]
vpn_enabled = true
available_countries = "all"
[[profile.subscriptions]]
provider_names = ["Canal+"]
vpn_enabled = false
available_countries = ["FR"]
bundle_includes = ["Paramount+"]
""",
        )

        form = profile.load_form()

        assert form.base_country == "FR"
        assert form.max_vpn_suggestions == 2
        assert form.vpn_priority == "US\nGB"
        assert len(form.subscriptions) == 2
        assert form.subscriptions[0].provider_name == "Netflix"
        assert form.subscriptions[0].countries == "all"
        assert form.subscriptions[1].countries == "FR"
        assert form.subscriptions[1].bundles == "Paramount+"

    def test_reports_a_file_key_without_revealing_it(self, config_path):
        write(config_path, '[tmdb]\napi_key = "the-secret"\n[profile]\n')

        form = profile.load_form()

        assert form.key_source == profile.KEY_FROM_FILE
        # The secret is nowhere in the form.
        assert "the-secret" not in form.model_dump_json()

    def test_reports_an_environment_key_as_locked(self, config_path, monkeypatch):
        monkeypatch.setattr("screenseeker.settings.TMDB_API_KEY_ENV", "env-key")
        write(config_path, "[profile]\n")

        form = profile.load_form()

        assert form.key_source == profile.KEY_FROM_ENV
        assert form.key_is_locked

    def test_missing_config_yields_defaults(self, config_path):
        form = profile.load_form()

        assert form.base_country == "FR"
        assert form.subscriptions == []
        assert form.key_source == profile.KEY_UNSET


class TestSave:
    def base_form(self, **overrides):
        defaults = {
            "base_country": "FR",
            "max_vpn_suggestions": 3,
            "vpn_priority": "US\nGB",
            "subscriptions": [
                SubscriptionForm(provider_name="Netflix", vpn_enabled=True, countries="all")
            ],
        }
        defaults.update(overrides)
        return ProfileForm(**defaults)

    def test_round_trips_a_subscription(self, config_path):
        profile.save_form(
            self.base_form(
                subscriptions=[
                    SubscriptionForm(
                        provider_name="Canal+",
                        vpn_enabled=False,
                        countries="FR, BE",
                        bundles="Paramount+, HBO Max",
                    )
                ]
            )
        )

        stored = read(config_path)["profile"]["subscriptions"][0]
        assert stored["provider_names"] == ["Canal+"]
        assert stored["available_countries"] == ["FR", "BE"]
        assert stored["bundle_includes"] == ["Paramount+", "HBO Max"]
        assert stored["vpn_enabled"] is False

    def test_all_countries_stays_the_string_all(self, config_path):
        profile.save_form(self.base_form())

        stored = read(config_path)["profile"]["subscriptions"][0]
        assert stored["available_countries"] == "all"

    def test_vpn_priority_is_a_list_in_order(self, config_path):
        profile.save_form(self.base_form(vpn_priority="US\nGB\nDE\n"))

        assert read(config_path)["profile"]["vpn_country_priority"] == ["US", "GB", "DE"]

    def test_blank_subscription_rows_are_dropped(self, config_path):
        profile.save_form(
            self.base_form(
                subscriptions=[
                    SubscriptionForm(provider_name="Netflix"),
                    SubscriptionForm(provider_name="  "),  # blank
                    SubscriptionForm(provider_name=""),  # blank
                ]
            )
        )

        subs = read(config_path)["profile"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["provider_names"] == ["Netflix"]

    def test_saving_preserves_sections_the_form_does_not_own(self, config_path):
        write(
            config_path,
            '[letterboxd]\nusername = "keepme"\n[tmdb]\napi_key = "keepkey"\nrate_limit = 3.0\n[profile]\n',
        )

        profile.save_form(self.base_form())

        stored = read(config_path)
        assert stored["letterboxd"]["username"] == "keepme"
        assert stored["tmdb"]["rate_limit"] == 3.0

    def test_a_blank_key_field_keeps_the_existing_key(self, config_path):
        write(config_path, '[tmdb]\napi_key = "original"\n[profile]\n')

        # The write-only field submitted empty must not wipe the key.
        profile.save_form(self.base_form(), new_api_key="")

        assert read(config_path)["tmdb"]["api_key"] == "original"

    def test_a_new_key_replaces_the_old_one(self, config_path):
        write(config_path, '[tmdb]\napi_key = "original"\n[profile]\n')

        profile.save_form(self.base_form(), new_api_key="replacement")

        assert read(config_path)["tmdb"]["api_key"] == "replacement"

    def test_an_environment_key_ignores_the_field(self, config_path, monkeypatch):
        monkeypatch.setattr("screenseeker.settings.TMDB_API_KEY_ENV", "env-key")
        write(config_path, '[tmdb]\napi_key = ""\n[profile]\n')

        # Even a non-empty field must not write to the file when env wins.
        profile.save_form(self.base_form(), new_api_key="attempted")

        assert read(config_path)["tmdb"]["api_key"] == ""

    def test_saved_profile_is_readable_by_get_subscription_profile(self, config_path):
        """The written shape has to be exactly what the watch strategy consumes."""
        from screenseeker import user_config

        profile.save_form(
            self.base_form(
                subscriptions=[
                    SubscriptionForm(provider_name="Netflix", vpn_enabled=True, countries="all")
                ]
            )
        )

        resolved = user_config.get_subscription_profile(user_config.load_config())
        assert resolved["base_country"] == "FR"
        assert resolved["subscriptions"][0]["provider_names"] == ["Netflix"]
        assert resolved["vpn_country_priority"] == ["US", "GB"]
