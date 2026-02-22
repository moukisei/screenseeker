"""
User configuration management.

Reads and writes ~/.config/screenseeker/config.toml.
"""

import tomllib
from pathlib import Path

import tomli_w

from .exceptions import ConfigurationError

CONFIG_DIR = Path.home() / ".config" / "screenseeker"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# Default VPN country priority (English-speaking first, then European, then other)
DEFAULT_VPN_PRIORITY = [
    "US",
    "GB",
    "CA",
    "AU",
    "NZ",
    "IE",
    "DE",
    "ES",
    "IT",
    "NL",
    "BE",
    "CH",
    "AT",
    "SE",
    "NO",
    "DK",
    "FI",
    "PT",
    "BR",
    "MX",
    "AR",
    "JP",
    "KR",
    "IN",
    "SG",
    "HK",
]

DEFAULT_CONFIG = {
    "letterboxd": {
        "username": "",
    },
    "tmdb": {
        "api_key": "",
        "rate_limit": 5.0,
        "language": "en-US",
    },
    "profile": {
        "base_country": "FR",
        "max_vpn_suggestions": 3,
        "vpn_country_priority": DEFAULT_VPN_PRIORITY,
        "subscriptions": [],
    },
}


def config_exists() -> bool:
    return CONFIG_PATH.exists()


def load_config() -> dict:
    """Load config from disk. Raises ConfigurationError if the file doesn't exist."""
    if not CONFIG_PATH.exists():
        raise ConfigurationError(
            f"No config file found at {CONFIG_PATH}.\n"
            "Run `screenseeker config init` to get started."
        )
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def save_config(cfg: dict) -> None:
    """Write config to disk, creating the directory if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(cfg, f)


def get_letterboxd_username(cfg: dict) -> str:
    """Return the configured Letterboxd username."""
    return cfg.get("letterboxd", {}).get("username", "")


def get_subscription_profile(cfg: dict) -> dict:
    """
    Extract the subscription profile dict that WatchStrategyAnalyzer expects.
    Keys: base_country, subscriptions, vpn_country_priority, max_vpn_suggestions.
    """
    profile = cfg.get("profile", {})
    return {
        "base_country": profile.get("base_country", "FR"),
        "subscriptions": profile.get("subscriptions", []),
        "vpn_country_priority": profile.get("vpn_country_priority", DEFAULT_VPN_PRIORITY),
        "max_vpn_suggestions": profile.get("max_vpn_suggestions", 3),
    }
