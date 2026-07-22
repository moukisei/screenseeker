"""
Every route in the app.

One module until it earns splitting. Rules that hold throughout:

- Mutations are POST and declare `Depends(require_user)`.
- No route calls TMDB or Letterboxd. Fetching belongs to the refresh job, so a
  page view never makes an outbound request.
- Nothing here touches the ORM; `services` returns Pydantic models that stay
  valid after the session closes.
"""

from math import ceil
from typing import Annotated, Literal, NamedTuple, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ..enrichers.watch_strategy import WatchOption, WatchStrategy
from ..services import library
from ..services.models import FilmDetail, OfferOut
from ..services.watch import find_watch_options
from .deps import get_db, get_profile, require_user
from .rendering import is_htmx, render

router = APIRouter()

DEFAULT_PER_PAGE = 48
MAX_PER_PAGE = 96

# FastAPI rejects anything outside this set with a 422 before it reaches the
# query builder, so no user input ever selects an ORDER BY.
SortKey = Literal["added", "title", "year", "rating"]

SORT_LABELS: dict[str, str] = {
    "added": "Recently added",
    "title": "Title",
    "year": "Year",
    "rating": "Rating",
}

# Fails at import if the two drift apart, rather than silently sorting by date
# added because a key the UI offers is not one the service knows.
if set(SORT_LABELS) != set(library.SORTS):
    raise RuntimeError(
        f"sort keys disagree: UI offers {sorted(SORT_LABELS)}, "
        f"service knows {sorted(library.SORTS)}"
    )

DbSession = Annotated[Session, Depends(get_db)]
Profile = Annotated[dict, Depends(get_profile)]


class OptionView(NamedTuple):
    """
    A watch option with the presentation bits the strategy does not carry.

    WatchStrategy ranks options; logos and deep links live on the persisted
    offers. Pairing them here keeps the template free of lookup logic.
    """

    option: WatchOption
    logo: Optional[str]
    url: Optional[str]


def _offer_index(offers: list[OfferOut]) -> dict[tuple[str, str, str], OfferOut]:
    """Index offers by what identifies a WatchOption. First one wins."""
    index: dict[tuple[str, str, str], OfferOut] = {}
    for offer in offers:
        index.setdefault(
            (offer.provider_name.casefold(), offer.country_code, offer.offer_type), offer
        )
    return index


def _decorate(options: list[WatchOption], index) -> list[OptionView]:
    views = []
    for option in options:
        offer = index.get((option.provider.casefold(), option.country_code, option.offer_type))
        views.append(
            OptionView(
                option=option,
                logo=offer.logo if offer else None,
                url=offer.streaming_url if offer else None,
            )
        )
    return views


def _strategy_context(detail: FilmDetail, strategy: WatchStrategy) -> dict:
    index = _offer_index(detail.offers)
    best = _decorate([strategy.best_option], index)[0] if strategy.best_option else None

    return {
        "best": best,
        "vpn_options": _decorate(strategy.vpn_options, index),
        "alternatives": _decorate(strategy.base_country_alternatives, index),
        "not_owned": _decorate(strategy.not_owned_options, index),
        "has_any_option": strategy.has_any_option(),
    }


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
    sort: SortKey = "added",
) -> HTMLResponse:
    """
    The grid.

    Paginated and sorted in SQL, so the response cost does not grow with the
    library. HTMX asks for the grid alone; a plain request gets the page, which
    is why every control also carries a real href.
    """
    films, total = library.list_page(db, sort=sort, page=page, per_page=per_page)
    pages = max(1, ceil(total / per_page))

    context = {
        "films": films,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "sort": sort,
        "sort_labels": SORT_LABELS,
    }

    template = "partials/library.html" if is_htmx(request) else "index.html"
    return render(request, template, context)


@router.get("/film/{film_id}", response_class=HTMLResponse)
def film_detail(
    request: Request,
    film_id: int,
    db: DbSession,
    profile: Profile,
) -> HTMLResponse:
    """One film, and how to watch it. Reads cached offers; never calls TMDB."""
    found = find_watch_options(db, film_id, profile=profile)
    if found is None:
        raise HTTPException(status_code=404, detail="That film is not in your library.")

    detail, strategy = found
    context = {
        "film": detail,
        "base_country": profile["base_country"],
        **_strategy_context(detail, strategy),
    }
    return render(request, "film.html", context)


@router.post(
    "/film/{film_id}/watched",
    response_class=HTMLResponse,
    dependencies=[Depends(require_user)],
)
def toggle_watched(
    request: Request,
    film_id: int,
    db: DbSession,
    watched: bool = Form(...),
) -> Response:
    """
    Set the watched flag and return the updated card.

    POST rather than GET even though HTMX would happily fire `hx-get`: a GET
    that mutates is CSRF-exploitable the moment cookie auth exists.

    The desired state is submitted rather than inferred, so a double-submitted
    form lands on the same value instead of flipping twice. Without HTMX the
    response is a redirect, which keeps the detail page's form working.
    """
    updated = library.set_watched_by_id(db, film_id, watched=watched)
    if updated is None:
        raise HTTPException(status_code=404, detail="That film is not in your library.")

    db.commit()

    if is_htmx(request):
        return render(request, "partials/card.html", {"film": updated})

    return RedirectResponse(url=f"/film/{film_id}", status_code=303)
