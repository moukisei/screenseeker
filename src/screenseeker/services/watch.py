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


def watch_strategy_for(offers: list[OfferOut], profile: dict) -> WatchStrategy:
    """Rank cached offers against the user's subscriptions."""
    return WatchStrategyAnalyzer(profile).analyze_offers(offers)


def find_watch_options(
    session: Session, film_id: int, *, profile: dict
) -> Optional[tuple[FilmDetail, WatchStrategy]]:
    """
    The detail page: a film and how to watch it.

    Returns None when the film is not in the library.
    """
    detail = get_detail(session, film_id)
    if detail is None:
        return None

    return detail, watch_strategy_for(detail.offers, profile)
