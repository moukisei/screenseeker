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
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from pydantic import BeforeValidator
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .. import settings, user_config
from ..enrichers.tmdb_enricher import TMDBEnricher
from ..enrichers.watch_strategy import WatchOption, WatchStrategy
from ..exceptions import ConfigurationError, JobAlreadyRunning, TMDBNotFoundError
from ..services import jobs, library
from ..services import members as member_service
from ..services import profile as profile_service
from ..services import watch
from ..services.enrichment import build_enricher, rematch_film_by_id, search_tmdb_candidates
from ..services.models import FilmDetail, OfferOut, poster_url
from ..services.watch import find_watch_options
from . import auth
from .deps import get_db, get_profile, require_user
from .rendering import is_htmx, render

router = APIRouter()

DEFAULT_PER_PAGE = 48
MAX_PER_PAGE = 96

# FastAPI rejects anything outside this set with a 422 before it reaches the
# query builder, so no user input ever selects an ORDER BY.
SortKey = Literal["added", "wanted", "title", "year", "rating", "duration", "confidence"]

# Optional, so "not specified" (an unbookmarked / pre-existing URL) can fall
# back to whatever `sort` reads naturally in, rather than always meaning
# "desc" - see library.sort_default_direction.
SortDirection = Literal["asc", "desc"]

# How a member selection combines: the union of those watchlists, or their
# intersection.
MemberMatch = Literal["any", "all"]

# The five monetization types TMDB uses. Anything else is a typo, not a filter.
OfferType = Literal["flatrate", "rent", "buy", "free", "ads"]

# Same idea for job kinds: /jobs/sync and /jobs/refresh exist, nothing else.
JobKind = Literal["sync", "refresh"]


def _blank_to_none(value: object) -> object:
    """
    A form select's "Any" option submits as an empty string, not an absent
    field, so the grid form always sends `country=&offer_type=&member_match=`.
    An empty string fails min_length and the enums, so without this the whole
    form 422s before the handler runs. Coercing blank to None before typed
    validation makes an unset dropdown mean "no filter".
    """
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


# A blank query parameter reads as absent, not as an invalid value.
BlankAsNone = BeforeValidator(_blank_to_none)


def _country_code(value: object) -> object:
    """
    Blank means no filter; any other value must be a two-letter code.

    The plain min_length/max_length guard cannot ride alongside BlankAsNone -
    pydantic would apply it to the coerced None - so the length is enforced
    here, still raising (a 422) on a malformed code like "FRANCE".
    """
    if not isinstance(value, str):
        return value
    code = value.strip().upper()
    if code == "":
        return None
    if len(code) != 2:
        raise ValueError("country must be a two-letter ISO code")
    return code


# Blank -> no filter; a present code is normalised and length-checked.
CountryCode = BeforeValidator(_country_code)


def _member_ids(values: Optional[list[str]]) -> tuple[int, ...]:
    """
    Parse the member selection from either spelling, preserving order.

    A checkbox group submits `members=1&members=2`; pager and bookmark links
    carry `members=1,2`, because Jinja's urlencode stringifies a list value
    instead of expanding it. Both are accepted so the form and the links agree.

    Anything unparseable is dropped rather than raising: a stale bookmark
    naming a member who has left the household should show the library, not a
    422.
    """
    if not values:
        return ()

    ids: list[int] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                parsed = int(part)
            except ValueError:
                continue
            if parsed > 0 and parsed not in ids:
                ids.append(parsed)

    return tuple(ids)


def _owned_providers(profile: dict) -> set[str]:
    """Every provider name configured on any subscription, case-folded for matching."""
    return {
        name.casefold()
        for sub in profile.get("subscriptions", [])
        for name in sub.get("provider_names", [])
    }


def _split_providers_by_ownership(
    all_providers: list[str], profile: dict
) -> tuple[list[str], list[str]]:
    """
    The Provider filter's suggestions, split into what the household owns
    and everything else - so the picker can show "yours" as its own group
    instead of one long alphabetical list a two-provider household has to
    hunt through.

    `all_providers` already comes back alphabetical (facets() sorts it), so
    each returned list stays alphabetical too. A provider matches "owned" on
    a case-insensitive substring either way, the same fuzziness the watch
    strategy itself uses for reseller names (e.g. a config listing "Netflix"
    still marks a facet value of "Netflix Standard with Ads" as owned).
    """
    owned = _owned_providers(profile)
    if not owned:
        return [], all_providers

    def is_owned(provider: str) -> bool:
        folded = provider.casefold()
        return any(o in folded or folded in o for o in owned)

    owned_providers = [p for p in all_providers if is_owned(p)]
    other_providers = [p for p in all_providers if not is_owned(p)]
    return owned_providers, other_providers


if set(get_args(JobKind)) != set(jobs.KINDS):
    raise RuntimeError(f"job kinds disagree: routes {get_args(JobKind)}, service {jobs.KINDS}")

SORT_LABELS: dict[str, str] = {
    "added": "Recently added",
    "wanted": "Most wanted",
    "title": "Title",
    "year": "Year",
    "rating": "Rating",
    "duration": "Duration",
    "confidence": "Match confidence",
}

# Fails at import if the two drift apart, rather than silently sorting by date
# added because a key the UI offers is not one the service knows.
if set(SORT_LABELS) != set(library.SORTS_META):
    raise RuntimeError(
        f"sort keys disagree: UI offers {sorted(SORT_LABELS)}, "
        f"service knows {sorted(library.SORTS_META)}"
    )

# A third place a sort key has to be spelled right: SortKey is what FastAPI
# validates the `sort` query param against, ahead of ever reaching either of
# the two dicts above - a key missing here 422s instead of misrouting.
if set(get_args(SortKey)) != set(SORT_LABELS):
    raise RuntimeError(
        f"sort keys disagree: SortKey allows {sorted(get_args(SortKey))}, "
        f"UI offers {sorted(SORT_LABELS)}"
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
    profile: Profile,
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
    sort: SortKey = "added",
    # Unset (rather than defaulting to "desc" here) is what lets an
    # unbookmarked URL fall back to whatever `sort` reads naturally in - see
    # library.sort_default_direction.
    direction: Optional[SortDirection] = None,
    # A blank string passes max_length, so these two never needed the coercion.
    query: Optional[str] = Query(None, max_length=100),
    provider: Optional[str] = Query(None, max_length=100),
    # These two reject a blank string (the length, the enum), so an empty
    # select value 422s the whole form without a blank->None coerce.
    country: Annotated[Optional[str], CountryCode] = None,
    offer_type: Annotated[Optional[OfferType], BlankAsNone] = None,
    # Repeatable, so it is declared through Annotated rather than as a default
    # `Query(...)` call - a list default is what B008 exists to catch.
    members: Annotated[Optional[list[str]], Query()] = None,
    member_match: Annotated[Optional[MemberMatch], BlankAsNone] = None,
) -> HTMLResponse:
    """
    The grid: filtered, sorted, paginated, all in one query.

    Every filter is a query parameter, so "on Netflix, available in FR, wanted
    by Alice and Bob" is a URL you can bookmark and share. HTMX asks
    for the library block alone; a plain request gets the page, which is why
    every control also carries a real href.
    """
    filters = library.LibraryFilter(
        # Blank form fields arrive as "" and must not narrow anything.
        query=(query or "").strip() or None,
        provider=provider or None,
        country=country,
        offer_type=offer_type,
        members=_member_ids(members),
        member_match=member_match or "any",
    )

    films, total = library.list_films(
        db, filters=filters, sort=sort, direction=direction, page=page, per_page=per_page
    )
    pages = max(1, ceil(total / per_page))
    household = member_service.list_members(db)

    # The direction actually applied, resolved even when the request left it
    # unset - so the "Order" select shows the right choice and pager/clear
    # links carry an explicit value rather than silently losing it.
    resolved_direction = direction or library.sort_default_direction(sort)

    # Everything that identifies this view, for building links that keep it.
    params = {
        **filters.as_params(),
        "sort": sort,
        "direction": resolved_direction,
        "per_page": str(per_page),
    }

    facets = library.facets(db)
    owned_providers, other_providers = _split_providers_by_ownership(facets.providers, profile)

    context = {
        "films": films,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "sort": sort,
        "direction": resolved_direction,
        "sort_labels": SORT_LABELS,
        "filters": filters,
        "params": params,
        "facets": facets,
        # The Provider picker's two groups: what the household actually pays
        # for, and everything else the library has ever seen an offer for.
        "owned_providers": owned_providers,
        "other_providers": other_providers,
        # Everyone, not just the active members: a paused member's films are
        # still in the library, so hiding them from the filter would make those
        # rows unreachable.
        "household": household,
        "household_size": len(household),
        # The "watchable tonight" badge per card, for this page's films only.
        "card_marks": watch.tonight_marks(db, [f.id for f in films], profile=profile),
    }

    if is_htmx(request):
        # Filter/sort/page requests swap the results region only, leaving the
        # filter form (and the search box's focus) untouched. The jobs bar sits
        # outside #library entirely, so a running job's panel also survives.
        return render(request, "partials/results.html", context)

    context["latest_job"] = jobs.latest(db)
    return render(request, "index.html", context)


@router.get("/film/{film_id}", response_class=HTMLResponse)
def film_detail(
    request: Request,
    film_id: int,
    db: DbSession,
    profile: Profile,
    rematched: Optional[str] = None,
    rematch_error: Optional[str] = None,
) -> HTMLResponse:
    """One film, and how to watch it. Reads cached offers; never calls TMDB."""
    found = find_watch_options(db, film_id, profile=profile)
    if found is None:
        raise HTTPException(status_code=404, detail="That film is not in your library.")

    detail, strategy = found
    context = {
        "film": detail,
        "base_country": profile["base_country"],
        "rematched": bool(rematched),
        "rematch_error": rematch_error,
        **_strategy_context(detail, strategy),
    }
    return render(request, "film.html", context)


def _build_enricher_or_none() -> Optional[TMDBEnricher]:
    """`build_enricher`, tolerating a missing API key rather than raising."""
    try:
        cfg = user_config.load_config()
    except Exception:
        cfg = {}
    try:
        return build_enricher(cfg)
    except ConfigurationError:
        return None


@router.get("/film/{film_id}/rematch", response_class=HTMLResponse)
def rematch_search(
    request: Request,
    film_id: int,
    query: str = Query(..., min_length=1),
    year: Optional[int] = Query(None),
) -> HTMLResponse:
    """
    Candidate TMDB matches for a manual correction, when the automatic one
    picked the wrong film.

    A deliberate, narrow exception to "no route calls TMDB" above: this is
    one fast lookup a person is actively waiting on having just typed a
    search, not an implicit page-load fetch. Sync and refresh stay
    background jobs because they are bulk and can run for minutes; this is
    neither.
    """
    enricher = _build_enricher_or_none()
    if enricher is None:
        return render(
            request,
            "partials/rematch_candidates.html",
            {"film_id": film_id, "candidates": [], "error": "TMDB is not configured."},
        )

    with enricher:
        results = search_tmdb_candidates(enricher, query, year)

    candidates = [
        {
            "tmdb_id": r.tmdb_id,
            "title": r.title,
            "year": r.year,
            "poster": poster_url(r.poster_path),
            "overview": r.overview,
        }
        for r in results
    ]
    return render(
        request,
        "partials/rematch_candidates.html",
        {
            "film_id": film_id,
            "candidates": candidates,
            "error": None if candidates else "No matches.",
        },
    )


@router.post("/film/{film_id}/rematch", dependencies=[Depends(require_user)])
def rematch_apply(
    film_id: int,
    db: DbSession,
    tmdb_id: int = Form(...),
) -> Response:
    """Point this film at a different TMDB id and refresh it from there."""
    enricher = _build_enricher_or_none()
    if enricher is None:
        return RedirectResponse(
            url=f"/film/{film_id}?rematch_error={quote('TMDB is not configured.')}", status_code=303
        )

    try:
        with enricher:
            film = rematch_film_by_id(db, enricher, film_id, tmdb_id)
    except TMDBNotFoundError as bad:
        db.rollback()
        return RedirectResponse(
            url=f"/film/{film_id}?rematch_error={quote(str(bad))}", status_code=303
        )

    if film is None:
        raise HTTPException(status_code=404, detail="That film is not in your library.")

    db.commit()
    return RedirectResponse(url=f"/film/{film_id}?rematched=1", status_code=303)


@router.get("/tonight", response_class=HTMLResponse)
def tonight_view(request: Request, db: DbSession, profile: Profile) -> HTMLResponse:
    """
    What to watch tonight: in the base country, no VPN, most wanted first.

    The actual product. Computed through the watch strategy rather than a SQL
    filter, because best_option depends on fuzzy, bundle-aware provider
    matching that SQL cannot reproduce.
    """
    picks = watch.tonight(db, profile=profile)
    marks = watch.tonight_marks(db, [p.film.id for p in picks], profile=profile)
    return render(
        request,
        "tonight.html",
        {
            "picks": picks,
            "marks": marks,
            "base_country": profile["base_country"],
            "household_size": member_service.count_members(db),
        },
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
            "household_size": member_service.count_members(db),
        },
    )


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
def profile_form(request: Request, db: DbSession, error: Optional[str] = None) -> HTMLResponse:
    """
    The profile editor: the household, and the subscriptions it shares.

    Reads config from disk, not the request-scoped `get_profile`: this edits
    the raw stored shape (available_countries can be "all"), which the resolved
    profile flattens. Members are not in that file - they are rows - so they
    are read separately.
    """
    return render(
        request,
        "profile.html",
        {
            "form": profile_service.load_form(),
            "household": member_service.list_members(db),
            "member_error": error,
        },
    )


# ==============================================================================
# The household
#
# Members are watchlist sources, not logins: there is still one password and
# one subscription profile for the whole house. Every route here mutates, so
# every one is a POST behind require_user.
# ==============================================================================


@router.post("/members", dependencies=[Depends(require_user)])
def add_member(
    db: DbSession,
    username: str = Form(...),
    display_name: str = Form(""),
    color: str = Form(""),
) -> Response:
    """Add a Letterboxd account to the household."""
    try:
        member_service.create_member(db, username, display_name=display_name, color=color or None)
    except ConfigurationError as bad:
        # Redirect rather than render: the profile page is a plain form post,
        # and re-rendering here would leave a URL that reposts on reload.
        db.rollback()
        return RedirectResponse(url=f"/profile?error={quote(str(bad))}", status_code=303)

    db.commit()
    return RedirectResponse(url="/profile?saved=1", status_code=303)


@router.post("/members/{member_id}", dependencies=[Depends(require_user)])
def edit_member(
    db: DbSession,
    member_id: int,
    display_name: str = Form(""),
    color: str = Form(""),
    active: str = Form(""),
) -> Response:
    """
    Rename a member, recolour their chip, or pause their syncing.

    `active` is read as presence, not as a parsed bool: an unchecked checkbox
    submits nothing at all, so an absent field means paused. Each member has
    their own form carrying every field, which is what makes that safe.
    """
    updated = member_service.update_member(
        db, member_id, display_name=display_name, color=color, active=bool(active)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="No such member.")

    db.commit()
    return RedirectResponse(url="/profile?saved=1", status_code=303)


@router.post("/members/{member_id}/delete", dependencies=[Depends(require_user)])
def remove_member(db: DbSession, member_id: int) -> Response:
    """
    Remove a member, their entries, and any film nobody else listed.

    Dropping those films is deliberate: a film only this person wanted is not
    the household's any more, and keeping it would leave the library a
    graveyard with no way to tell the orphans apart.
    """
    if member_service.delete_member(db, member_id) is None:
        raise HTTPException(status_code=404, detail="No such member.")

    db.commit()
    return RedirectResponse(url="/profile?saved=1", status_code=303)


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


# ==============================================================================
# Authentication
#
# These routes exist whether or not a password is set; when none is, the login
# page just reports that the app is open and every redirect lands back on it.
# The middleware in app.py is what actually enforces the session - see auth.py.
# ==============================================================================


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/") -> Response:
    """The login page. Redirects straight in if auth is off or already valid."""
    if not auth.is_enabled() or auth.request_is_authenticated(request):
        return RedirectResponse(url=auth.safe_next(next), status_code=303)

    return render(request, "login.html", {"next": auth.safe_next(next), "error": False})


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    password: str = Form(...),
    next: str = Form("/"),
) -> Response:
    """
    Check the password and, on success, set the session cookie.

    Not behind require_user: you cannot be asked to be logged in to log in.
    SameSite=Lax on the cookie it sets is what defends the session afterwards.
    """
    if not auth.is_enabled():
        return RedirectResponse(url="/", status_code=303)

    if not auth.password_matches(password):
        # Same response whether the password was wrong or empty; nothing here
        # distinguishes them for a guesser.
        return render(
            request,
            "login.html",
            {"next": auth.safe_next(next), "error": True},
            status_code=401,
        )

    response = RedirectResponse(url=auth.safe_next(next), status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_token(),
        max_age=settings.SESSION_MAX_AGE_DAYS * 86400,
        **auth.cookie_params(),
    )
    return response


@router.post("/logout", response_class=HTMLResponse, dependencies=[Depends(require_user)])
def logout() -> Response:
    """Clear the session cookie. Harmless when not logged in."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


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
