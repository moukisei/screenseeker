"""Tests for src/screenseeker/user_config.py"""

from unittest.mock import patch

import pytest

from screenseeker.exceptions import ConfigurationError
from screenseeker.user_config import (
    DEFAULT_VPN_PRIORITY,
    get_letterboxd_username,
    get_subscription_profile,
    load_config,
    save_config,
)


@pytest.fixture
def tmp_config_path(tmp_path):
    """Patch CONFIG_PATH and CONFIG_DIR to use a temp directory."""
    config_file = tmp_path / "screenseeker" / "config.toml"
    with (
        patch("screenseeker.user_config.CONFIG_PATH", config_file),
        patch("screenseeker.user_config.CONFIG_DIR", config_file.parent),
    ):
        yield config_file


@pytest.fixture
def minimal_cfg():
    return {
        "letterboxd": {"username": "testuser"},
        "tmdb": {"api_key": "test123", "rate_limit": 5.0, "language": "en-US"},
        "profile": {
            "base_country": "FR",
            "max_vpn_suggestions": 3,
            "vpn_country_priority": ["US", "GB"],
            "subscriptions": [],
        },
    }


@pytest.fixture
def cfg_with_subscriptions():
    return {
        "tmdb": {"api_key": "test123", "rate_limit": 5.0, "language": "en-US"},
        "profile": {
            "base_country": "US",
            "max_vpn_suggestions": 2,
            "vpn_country_priority": ["US", "GB"],
            "subscriptions": [
                {
                    "provider_names": ["Netflix"],
                    "vpn_enabled": True,
                    "available_countries": "all",
                },
                {
                    "provider_names": ["Canal+", "Canal Plus"],
                    "vpn_enabled": False,
                    "available_countries": ["FR"],
                    "bundle_includes": ["HBO Max"],
                },
            ],
        },
    }


class TestSaveAndLoadConfig:
    def test_round_trip(self, tmp_config_path, minimal_cfg):
        save_config(minimal_cfg)
        loaded = load_config()
        assert loaded["tmdb"]["api_key"] == "test123"
        assert loaded["profile"]["base_country"] == "FR"

    def test_creates_parent_directory(self, tmp_config_path, minimal_cfg):
        assert not tmp_config_path.parent.exists()
        save_config(minimal_cfg)
        assert tmp_config_path.exists()

    def test_subscriptions_round_trip(self, tmp_config_path, cfg_with_subscriptions):
        save_config(cfg_with_subscriptions)
        loaded = load_config()
        subs = loaded["profile"]["subscriptions"]
        assert len(subs) == 2
        assert subs[0]["provider_names"] == ["Netflix"]
        assert subs[0]["available_countries"] == "all"
        assert subs[1]["bundle_includes"] == ["HBO Max"]

    def test_overwrite_existing_config(self, tmp_config_path, minimal_cfg):
        save_config(minimal_cfg)
        minimal_cfg["tmdb"]["api_key"] = "newkey"
        save_config(minimal_cfg)
        loaded = load_config()
        assert loaded["tmdb"]["api_key"] == "newkey"


class TestLoadConfigMissing:
    def test_raises_configuration_error_when_missing(self, tmp_config_path):
        assert not tmp_config_path.exists()
        with pytest.raises(ConfigurationError, match="config init"):
            load_config()

    def test_error_message_contains_path(self, tmp_config_path):
        with pytest.raises(ConfigurationError) as exc_info:
            load_config()
        assert str(tmp_config_path) in str(exc_info.value)


class TestGetSubscriptionProfile:
    def test_extracts_profile_fields(self, cfg_with_subscriptions):
        profile = get_subscription_profile(cfg_with_subscriptions)
        assert profile["base_country"] == "US"
        assert profile["max_vpn_suggestions"] == 2
        assert len(profile["subscriptions"]) == 2

    def test_defaults_when_profile_missing(self):
        profile = get_subscription_profile({})
        assert profile["base_country"] == "FR"
        assert profile["max_vpn_suggestions"] == 3
        assert profile["subscriptions"] == []
        assert profile["vpn_country_priority"] == DEFAULT_VPN_PRIORITY

    def test_subscriptions_match_watch_strategy_format(self, cfg_with_subscriptions):
        profile = get_subscription_profile(cfg_with_subscriptions)
        # WatchStrategyAnalyzer expects these exact keys
        assert "base_country" in profile
        assert "subscriptions" in profile
        assert "vpn_country_priority" in profile
        assert "max_vpn_suggestions" in profile

    def test_vpn_priority_uses_default_when_absent(self):
        cfg = {"profile": {"base_country": "GB", "subscriptions": []}}
        profile = get_subscription_profile(cfg)
        assert profile["vpn_country_priority"] == DEFAULT_VPN_PRIORITY


class TestGetLetterboxdUsername:
    def test_returns_username(self, minimal_cfg):
        assert get_letterboxd_username(minimal_cfg) == "testuser"

    def test_returns_empty_string_when_missing(self):
        assert get_letterboxd_username({}) == ""

    def test_round_trip(self, tmp_config_path, minimal_cfg):
        save_config(minimal_cfg)
        loaded = load_config()
        assert get_letterboxd_username(loaded) == "testuser"
