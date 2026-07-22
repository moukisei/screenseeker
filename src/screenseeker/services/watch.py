"""
"Where can I watch this?" for a film already in the library.

Reads only. Fetching from TMDB happens in the refresh job, never while
serving a page, so a page view cannot make an outbound request or block on
one. Films arrive in the library through sync; there is no on-demand lookup.
"""

from typing import Optional

from sqlalchemy.orm import Session

from ..enrichers.watch_strategy import WatchStrategy, WatchStrategyAnalyzer
from ..logger import get_logger
from .library import get_detail
from .models import FilmDetail, OfferOut

logger = get_logger(__name__)


def reachable_countries(profile: dict) -> list[str]:
    """
    Every country this user could plausibly watch from.

    Their base country, the countries their VPN offers, and any country a
    subscription is explicitly limited to. TMDB reports availability for 139
    countries; the rest are unreachable and only make the page heavier.

    A subscription marked available in "all" countries still only reaches the
    VPN's country list, so it adds nothing here.
    """
    countries = {profile["base_country"].upper()}
    countries.update(c.upper() for c in profile.get("vpn_country_priority", []))

    for sub in profile.get("subscriptions", []):
        available = sub.get("available_countries", [])
        if available != "all":
            countries.update(c.upper() for c in available)

    return sorted(countries)


def watch_strategy_for(offers: list[OfferOut], profile: dict) -> WatchStrategy:
    """Rank cached offers against the user's subscriptions."""
    return WatchStrategyAnalyzer(profile).analyze_offers(offers)


def find_watch_options(
    session: Session, film_id: int, *, profile: dict
) -> Optional[tuple[FilmDetail, WatchStrategy]]:
    """
    The detail page: a film and how to watch it.

    Only offers in reachable countries are loaded. FilmDetail still reports
    the unscoped total, so the page can say it is showing a subset rather than
    imply the film is unavailable everywhere else.

    Returns None when the film is not in the library.
    """
    detail = get_detail(session, film_id, countries=reachable_countries(profile))
    if detail is None:
        return None

    return detail, watch_strategy_for(detail.offers, profile)
