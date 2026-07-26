"""
Reading and writing the user's profile.

The profile is the subscriptions, the VPN priority order, the base country and
the TMDB key. It drives every watch-strategy decision, so it earns its own
module here rather than being edited inline.

Two hard rules, both from the plan:

- The TMDB key is write-only. It is never rendered back; the form shows only
  whether one is set. A blank key field means "leave it unchanged", so saving
  the form never wipes a key you cannot see.
- Saving merges. `user_config.save_config` writes the whole file, so anything
  the form does not cover - the Letterboxd username, the TMDB rate limit - is
  read, preserved and written back untouched.
"""

from copy import deepcopy
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import settings, user_config
from ..logger import get_logger

logger = get_logger(__name__)

# A key may come from the environment instead of the file (a deployment secret).
# When it does, the file field cannot change it, and the form says so.
KEY_FROM_ENV = "environment"
KEY_FROM_FILE = "file"
KEY_UNSET = "unset"


class SubscriptionForm(BaseModel):
    """One subscription, as the form round-trips it."""

    model_config = ConfigDict(frozen=True)

    # The form edits one provider name per row; the stored shape is a list
    # because a subscription can span renamed services. Kept as a list on save.
    provider_name: str = ""
    vpn_enabled: bool = False
    # "all" or a comma-separated country list, exactly as typed.
    countries: str = ""
    bundles: str = ""

    @property
    def is_blank(self) -> bool:
        """An empty row the user added and left alone. Dropped on save."""
        return not self.provider_name.strip()


class ProfileForm(BaseModel):
    """The whole profile as the form shows and submits it."""

    model_config = ConfigDict(frozen=True)

    base_country: str = "FR"
    max_vpn_suggestions: int = Field(3, ge=0, le=20)
    # One country code per line, order preserved - order is priority.
    vpn_priority: str = ""
    subscriptions: list[SubscriptionForm] = Field(default_factory=list)

    # Never the key itself: only where it comes from, so the template can say
    # "set" without ever holding the secret.
    key_source: str = KEY_UNSET

    @property
    def key_is_locked(self) -> bool:
        """True when the key is supplied by the environment and the file cannot override it."""
        return self.key_source == KEY_FROM_ENV


def _countries_to_field(available) -> str:
    """Stored available_countries -> the text field."""
    if available == "all":
        return "all"
    if isinstance(available, list):
        return ", ".join(available)
    return ""


def load_form() -> ProfileForm:
    """Build the form model from the config on disk, or from defaults."""
    try:
        cfg = user_config.load_config()
    except Exception:
        cfg = {}

    prof = cfg.get("profile", {})

    subs = [
        SubscriptionForm(
            provider_name=(sub.get("provider_names") or [""])[0],
            vpn_enabled=bool(sub.get("vpn_enabled", False)),
            countries=_countries_to_field(sub.get("available_countries", [])),
            bundles=", ".join(sub.get("bundle_includes", [])),
        )
        for sub in prof.get("subscriptions", [])
    ]

    if settings.TMDB_API_KEY_ENV:
        key_source = KEY_FROM_ENV
    elif cfg.get("tmdb", {}).get("api_key"):
        key_source = KEY_FROM_FILE
    else:
        key_source = KEY_UNSET

    return ProfileForm(
        base_country=prof.get("base_country", "FR"),
        max_vpn_suggestions=prof.get("max_vpn_suggestions", 3),
        vpn_priority="\n".join(prof.get("vpn_country_priority", user_config.DEFAULT_VPN_PRIORITY)),
        subscriptions=subs,
        key_source=key_source,
    )


def _split(text: str, *, sep: str) -> list[str]:
    """Split a text field into a clean list, dropping blanks."""
    return [part.strip() for part in text.replace("\r", "").split(sep) if part.strip()]


def _countries_from_field(value: str) -> object:
    """Text field -> stored available_countries. "all" stays the string "all"."""
    if value.strip().lower() == "all":
        return "all"
    return [c.upper() for c in _split(value, sep=",")]


def _subscription_to_stored(sub: SubscriptionForm) -> dict:
    stored: dict = {
        "provider_names": [sub.provider_name.strip()],
        "vpn_enabled": sub.vpn_enabled,
        "available_countries": _countries_from_field(sub.countries),
    }
    bundles = _split(sub.bundles, sep=",")
    if bundles:
        stored["bundle_includes"] = bundles
    return stored


def save_form(form: ProfileForm, *, new_api_key: Optional[str] = None) -> None:
    """
    Write the submitted form back to config, merging with what is already there.

    `new_api_key` is the raw key field. None or empty leaves the stored key
    untouched - the field is write-only, so a blank submission must not wipe a
    key the user was never shown. When the key comes from the environment the
    field is ignored entirely.
    """
    # Read-modify-write: keep every section the form does not own.
    try:
        cfg = user_config.load_config()
    except Exception:
        cfg = deepcopy(user_config.DEFAULT_CONFIG)

    cfg.setdefault("profile", {})
    cfg["profile"]["base_country"] = form.base_country.strip().upper() or "FR"
    cfg["profile"]["max_vpn_suggestions"] = form.max_vpn_suggestions
    cfg["profile"]["vpn_country_priority"] = [
        c.upper() for c in _split(form.vpn_priority, sep="\n")
    ]
    cfg["profile"]["subscriptions"] = [
        _subscription_to_stored(sub) for sub in form.subscriptions if not sub.is_blank
    ]

    cfg.setdefault("tmdb", {})
    if new_api_key and not settings.TMDB_API_KEY_ENV:
        cfg["tmdb"]["api_key"] = new_api_key.strip()
    cfg["tmdb"].setdefault("api_key", "")
    cfg["tmdb"].setdefault("rate_limit", 5.0)
    cfg["tmdb"].setdefault("language", "en-US")

    cfg.setdefault("letterboxd", {"username": ""})

    user_config.save_config(cfg)
    logger.info("Profile saved: %d subscription(s)", len(cfg["profile"]["subscriptions"]))
