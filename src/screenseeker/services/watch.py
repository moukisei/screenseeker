"""
"Where can I watch this?" for a film already in the library.

Reads only. Fetching from TMDB happens in the refresh job, never while
serving a page, so a page view cannot make an outbound request or block on
one. Films arrive in the library through sync; there is no on-demand lookup.
"""

from typing import NamedTuple, Optional

from sqlalchemy.orm import Session

from ..enrichers.watch_strategy import WatchOption, WatchStrategy, WatchStrategyAnalyzer
from ..logger import get_logger
from . import library
from .library import LibraryFilter, get_detail
from .models import FilmDetail, FilmSummary, OfferOut

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


class TonightPick(NamedTuple):
    """A film you could start tonight, and the option to do it on."""

    film: FilmSummary
    best_option: WatchOption


class CardMark(NamedTuple):
    """
    The "watchable tonight" badge for one card: a provider and a way to reach it.

    `url` and `logo` are the deep link and logo from the persisted offer the
    best option came from; either can be missing, as TMDB does not supply a
    link for every provider.
    """

    provider: str
    url: Optional[str]
    logo: Optional[str]


def _mark_from(offers: list[OfferOut], best: WatchOption) -> CardMark:
    """Pair a ranked best option with the offer row it came from, for its link."""
    match = next(
        (
            o
            for o in offers
            if o.provider_name.casefold() == best.provider.casefold()
            and o.country_code == best.country_code
            and o.offer_type == best.offer_type
        ),
        None,
    )
    return CardMark(
        provider=best.provider,
        url=match.streaming_url if match else None,
        logo=match.logo if match else None,
    )


def tonight_marks(session: Session, film_ids: list[int], *, profile: dict) -> dict[int, CardMark]:
    """
    The best base-country, no-VPN option per film, for the grid and Tonight.

    Same computation as `tonight`, but keyed by film id and decorated with the
    deep link, so a card can show "watchable on Netflix" and link straight to
    it. Offers load in one query; the strategy runs in memory. Films with no
    such option are simply absent from the result.
    """
    if not film_ids:
        return {}

    offers_by_film = library.offers_for_films(
        session, film_ids, countries=reachable_countries(profile)
    )

    marks: dict[int, CardMark] = {}
    for film_id in film_ids:
        offers = offers_by_film.get(film_id, [])
        best = watch_strategy_for(offers, profile).best_option
        if best:
            marks[film_id] = _mark_from(offers, best)
    return marks


def tonight(session: Session, *, profile: dict) -> list[TonightPick]:
    """
    Films with a best option in the base country, no VPN, most wanted first.

    The product the CLI never exposed directly. best_option is a watch-strategy
    concept - it means a flatrate offer, in the base country, on a subscription
    the profile actually holds - and the strategy's provider matching is fuzzy
    and bundle-aware, which SQL cannot reproduce. TMDB's "Paramount+ Amazon
    Channel"-style reseller names substring-match an owned provider but are not
    it, so a pure-SQL filter over-counts by roughly half on this library.

    So candidates are narrowed in SQL to what could possibly qualify - films
    with a flatrate offer in the base country - and best_option is then
    confirmed per film against batch-loaded offers. Constant query count, no
    per-film round trip.

    There is no "unwatched" filter because there is no watched flag: a film
    logged on Letterboxd leaves the watchlist, and `list_films` only returns
    films somebody still lists.
    """
    base = profile["base_country"].upper()

    candidates, _ = library.list_films(
        session,
        filters=LibraryFilter(country=base, offer_type="flatrate"),
        # A shortlist by nature; load them all and rank in memory.
        per_page=100_000,
    )
    if not candidates:
        return []

    offers_by_film = library.offers_for_films(
        session, [c.id for c in candidates], countries=reachable_countries(profile)
    )

    picks = []
    for film in candidates:
        strategy = watch_strategy_for(offers_by_film.get(film.id, []), profile)
        if strategy.best_option:
            picks.append(TonightPick(film=film, best_option=strategy.best_option))

    # Consensus first, then the better film. What three of you want beats what
    # one of you wants and IMDb likes more - that is the whole reason to pool
    # the watchlists. Rating breaks the tie; unrated films sort last rather
    # than as zero. Sorted in Python because wanted_by is already loaded with
    # the chips, so ranking here costs nothing and a SQL sort would not survive
    # the best_option filter above anyway.
    picks.sort(
        key=lambda p: (
            -p.film.wanted_by,
            -(p.film.vote_average or -1),
            p.film.title.casefold(),
        )
    )
    return picks


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
