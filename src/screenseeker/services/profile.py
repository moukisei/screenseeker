"""
Subscription profile editing.

Pure functions over the config dict - no prompting, no terminal output. The
CLI wizard and the web form are both thin wrappers around these.
"""

from typing import Optional, Union

from ..logger import get_logger
from ..user_config import DEFAULT_CONFIG, DEFAULT_VPN_PRIORITY, load_config, save_config

logger = get_logger(__name__)


class ProfileError(ValueError):
    """Raised when an edit would produce an invalid profile."""


def default_config() -> dict:
    """A fresh config skeleton, safe to mutate."""
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


def list_subscriptions(cfg: dict) -> list[dict]:
    """Every configured subscription."""
    return cfg.get("profile", {}).get("subscriptions", [])


def add_subscription(
    cfg: dict,
    provider_names: list[str],
    *,
    vpn_enabled: bool = False,
    available_countries: Union[str, list[str]] = "all",
    bundle_includes: Optional[list[str]] = None,
) -> dict:
    """
    Add a subscription. Returns the updated config; does not save it.

    Raises ProfileError on an empty name list or a duplicate primary name.
    """
    names = [n.strip() for n in provider_names if n and n.strip()]
    if not names:
        raise ProfileError("A subscription needs at least one provider name.")

    profile = cfg.setdefault("profile", {})
    subscriptions = profile.setdefault("subscriptions", [])

    existing = {n.lower() for s in subscriptions for n in s.get("provider_names", [])}
    if names[0].lower() in existing:
        raise ProfileError(f"'{names[0]}' is already configured.")

    entry = {
        "provider_names": names,
        "vpn_enabled": vpn_enabled,
        "available_countries": available_countries,
    }
    if bundle_includes:
        entry["bundle_includes"] = bundle_includes

    subscriptions.append(entry)
    return cfg


def remove_subscription(cfg: dict, provider: str) -> tuple[dict, bool]:
    """
    Remove the subscription matching `provider` on any of its names.

    Returns (config, removed). Matching is case-insensitive.
    """
    profile = cfg.setdefault("profile", {})
    subscriptions = profile.setdefault("subscriptions", [])
    target = provider.strip().lower()

    remaining = [
        s for s in subscriptions if target not in {n.lower() for n in s.get("provider_names", [])}
    ]

    removed = len(remaining) != len(subscriptions)
    profile["subscriptions"] = remaining
    return cfg, removed


def set_base_country(cfg: dict, country_code: str) -> dict:
    """Set the country that needs no VPN. Expects an ISO 3166-1 alpha-2 code."""
    code = country_code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ProfileError(f"'{country_code}' is not a two-letter country code.")

    cfg.setdefault("profile", {})["base_country"] = code
    return cfg


def set_vpn_priority(cfg: dict, country_codes: list[str]) -> dict:
    """Replace the VPN country preference order."""
    codes = [c.strip().upper() for c in country_codes if c and c.strip()]
    for code in codes:
        if len(code) != 2 or not code.isalpha():
            raise ProfileError(f"'{code}' is not a two-letter country code.")

    cfg.setdefault("profile", {})["vpn_country_priority"] = codes or list(DEFAULT_VPN_PRIORITY)
    return cfg


def update_profile(mutate) -> dict:
    """
    Load the config, apply `mutate`, save it back.

    `mutate` takes the config dict and returns it. Any exception propagates
    before the write, so a rejected edit leaves the file untouched.
    """
    cfg = load_config()
    cfg = mutate(cfg)
    save_config(cfg)
    return cfg
