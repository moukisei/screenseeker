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
from typing import Annotated, Literal, NamedTuple, Optional, get_args
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .. import settings
from ..enrichers.watch_strategy import WatchOption, WatchStrategy
from ..exceptions import JobAlreadyRunning
from ..services import jobs, library
from ..services import profile as profile_service
from ..services import watch
from ..services.models import FilmDetail, OfferOut
from ..services.watch import find_watch_options
from .deps import get_db, get_profile, require_user
from .rendering import is_htmx, render

router = APIRouter()

DEFAULT_PER_PAGE = 48
MAX_PER_PAGE = 96

# FastAPI rejects anything outside this set with a 422 before it reaches the
# query builder, so no user input ever selects an ORDER BY.
SortKey = Literal["added", "title", "year", "rating", "confidence"]

# The five monetization types TMDB uses. Anything else is a typo, not a filter.
OfferType = Literal["flatrate", "rent", "buy", "free", "ads"]

# Same idea for job kinds: /jobs/sync and /jobs/refresh exist, nothing else.
JobKind = Literal["sync", "refresh"]

if set(get_args(JobKind)) != set(jobs.KINDS):
    raise RuntimeError(f"job kinds disagree: routes {get_args(JobKind)}, service {jobs.KINDS}")

SORT_LABELS: dict[str, str] = {
    "added": "Recently added",
    "title": "Title",
    "year": "Year",
    "rating": "Rating",
    "confidence": "Match confidence",
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
    provider: Optional[str] = Query(None, max_length=100),
    country: Optional[str] = Query(None, min_length=2, max_length=2),
    offer_type: Optional[OfferType] = None,
    watched: Optional[bool] = None,
) -> HTMLResponse:
    """
    The grid: filtered, sorted, paginated, all in one query.

    Every filter is a query parameter, so "unwatched, on Netflix, available in
    FR" is a URL you can bookmark and share. HTMX asks for the library block
    alone; a plain request gets the page, which is why every control also
    carries a real href.
    """
    filters = library.LibraryFilter(
        # Blank form fields arrive as "" and must not narrow anything.
        provider=provider or None,
        country=country.upper() if country else None,
        offer_type=offer_type,
        watched=watched,
    )

    films, total = library.list_films(db, filters=filters, sort=sort, page=page, per_page=per_page)
    pages = max(1, ceil(total / per_page))

    # Everything that identifies this view, for building links that keep it.
    params = {**filters.as_params(), "sort": sort, "per_page": str(per_page)}

    context = {
        "films": films,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "sort": sort,
        "sort_labels": SORT_LABELS,
        "filters": filters,
        "params": params,
        "facets": library.facets(db),
    }

    if is_htmx(request):
        # Filtering, sorting and paging swap the library alone; the jobs bar
        # sits outside it precisely so a running job's panel survives.
        return render(request, "partials/library.html", context)

    context["latest_job"] = jobs.latest(db)
    return render(request, "index.html", context)


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


@router.get("/tonight", response_class=HTMLResponse)
def tonight_view(request: Request, db: DbSession, profile: Profile) -> HTMLResponse:
    """
    What to watch tonight: unwatched, in the base country, no VPN.

    The actual product. Computed through the watch strategy rather than a SQL
    filter, because best_option depends on fuzzy, bundle-aware provider
    matching that SQL cannot reproduce.
    """
    picks = watch.tonight(db, profile=profile)
    return render(
        request,
        "tonight.html",
        {"picks": picks, "base_country": profile["base_country"]},
    )


@router.get("/stale", response_class=HTMLResponse)
def stale_view(
    request: Request,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
) -> HTMLResponse:
    """
    Films whose availability has aged past the TTL, worst first.

    The refresh button triggers the same background job the grid does; it
    refreshes every stale film, which is all of these.
    """
    films, total = library.list_stale(db, page=page, per_page=per_page)
    pages = max(1, ceil(total / per_page))

    return render(
        request,
        "stale.html",
        {
            "films": films,
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": per_page,
            "ttl_days": settings.CACHE_TTL_DAYS,
            "latest_job": jobs.latest(db, kind="refresh"),
        },
    )


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


# ==============================================================================
# Background jobs
# ==============================================================================


@router.post(
    "/jobs/{kind}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_user)],
)
async def start_job(request: Request, kind: JobKind, db: DbSession) -> Response:
    """
    Enqueue a sync or refresh, or refuse because one is already running.

    A refusal is a 409 carrying the running job's panel as its body, so the
    page shows what is already in flight rather than a dead-end error. The
    htmx-config meta in base.html is what makes that body swap.

    Refusing is correctness, not politeness: two concurrent syncs race
    get_or_create_film and produce duplicate films.
    """
    runner = request.app.state.job_runner

    try:
        job = await runner.submit(kind)
    except JobAlreadyRunning as refusal:
        running = jobs.get(db, refusal.job_id)
        return render(
            request,
            "partials/job.html",
            {"job": running, "refused": str(refusal)},
            status_code=409,
        )

    if is_htmx(request):
        return render(request, "partials/job.html", {"job": job})

    return RedirectResponse(url="/", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status(request: Request, job_id: int, db: DbSession) -> HTMLResponse:
    """
    The status panel, polled by HTMX while the job is active.

    The fragment stops asking for itself once the job reaches a terminal
    state, so nothing needs to cancel the poll.
    """
    job = jobs.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")

    return render(request, "partials/job.html", {"job": job})


# ==============================================================================
# Profile
# ==============================================================================


@router.get("/profile", response_class=HTMLResponse)
def profile_form(request: Request) -> HTMLResponse:
    """
    The profile editor.

    Reads config from disk, not the request-scoped `get_profile`: this edits
    the raw stored shape (available_countries can be "all"), which the resolved
    profile flattens.
    """
    return render(request, "profile.html", {"form": profile_service.load_form()})


@router.get("/profile/subscription", response_class=HTMLResponse)
def profile_add_subscription(request: Request) -> HTMLResponse:
    """A blank subscription row, for the form's Add button. HTMX appends it."""
    return render(
        request,
        "partials/subscription_row.html",
        {"sub": profile_service.SubscriptionForm(), "token": _fresh_token()},
    )


@router.post(
    "/profile",
    response_class=HTMLResponse,
    dependencies=[Depends(require_user)],
)
async def save_profile(request: Request) -> Response:
    """
    Persist the profile.

    Subscriptions are a variable-length list, so the form is read raw and
    parsed by row token rather than declared as fixed parameters. The key field
    is write-only: an empty submission leaves the stored key untouched, which
    is why it is not simply overwritten.
    """
    data = await request.form()
    form = _parse_profile_form(data)

    profile_service.save_form(form, new_api_key=str(data.get("api_key") or ""))

    # Redirect so a reload does not repost, and so the page re-reads the saved
    # state (masked key included) rather than echoing the submission back.
    return RedirectResponse(url="/profile?saved=1", status_code=303)


def _fresh_token() -> str:
    """A short unique token to namespace one subscription row's field names."""
    return uuid4().hex[:8]


def _parse_profile_form(data) -> profile_service.ProfileForm:
    """
    Turn the raw multipart form into a ProfileForm.

    Rows are keyed `sub-<token>-<field>` so an unchecked checkbox - which
    submits nothing - cannot slide a row's values onto the next row's, the way
    parallel same-named lists would.
    """
    tokens = [
        key[len("sub-") : -len("-provider_name")]
        for key in data.keys()
        if key.startswith("sub-") and key.endswith("-provider_name")
    ]

    subscriptions = [
        profile_service.SubscriptionForm(
            provider_name=str(data.get(f"sub-{token}-provider_name") or ""),
            vpn_enabled=f"sub-{token}-vpn_enabled" in data,
            countries=str(data.get(f"sub-{token}-countries") or ""),
            bundles=str(data.get(f"sub-{token}-bundles") or ""),
        )
        for token in tokens
    ]

    # Clamp rather than validate-and-500: a browser number field can still
    # submit an out-of-range or empty value, and this form has one user.
    try:
        max_vpn = int(data.get("max_vpn_suggestions") or 3)
    except ValueError:
        max_vpn = 3
    max_vpn = max(0, min(20, max_vpn))

    return profile_service.ProfileForm(
        base_country=str(data.get("base_country") or "FR"),
        max_vpn_suggestions=max_vpn,
        vpn_priority=str(data.get("vpn_priority") or ""),
        subscriptions=subscriptions,
    )
