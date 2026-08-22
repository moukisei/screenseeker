"""
Return types for the service layer.

These are the contract between the use cases and whatever renders them - the
CLI today, the web layer next. They hold no ORM instances so they stay valid
after the database session closes.
"""

from datetime import UTC, datetime
from typing import Optional
from zlib import crc32

from pydantic import BaseModel, ConfigDict, Field

from .. import settings
from ..database.models import Film, Member
from ..database.models import StreamingOffer as OfferRow

# Chip colours, handed out in order as members are added. Chosen to stay
# distinguishable against both the light and dark card background; after six
# members they repeat, which is fine for a household. Lives here because both
# the chip and the member editor need it, and this module is what they share.
MEMBER_PALETTE = [
    "#e0546c",
    "#4c9be8",
    "#48b884",
    "#e0a13a",
    "#a67ce0",
    "#4fb3c4",
]


def poster_url(poster_path: Optional[str], size: str = settings.TMDB_POSTER_SIZE) -> Optional[str]:
    """Turn a stored TMDB path into a full image URL."""
    if not poster_path:
        return None
    return f"{settings.TMDB_IMAGE_BASE}/{size}{poster_path}"


def logo_url(logo_path: Optional[str], size: str = settings.TMDB_LOGO_SIZE) -> Optional[str]:
    """Turn a stored TMDB provider logo path into a full image URL."""
    if not logo_path:
        return None
    return f"{settings.TMDB_IMAGE_BASE}/{size}{logo_path}"


def member_initials(display_name: str) -> str:
    """One or two letters for a member chip."""
    parts = [p for p in display_name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def member_color(color: Optional[str], username: str) -> str:
    """
    A member's chip colour, derived from the username when none is stored.

    crc32 rather than hash(): Python randomises string hashing per process, so
    a member with no stored colour would change colour on every restart.
    """
    if color:
        return color
    return MEMBER_PALETTE[crc32(username.encode()) % len(MEMBER_PALETTE)]


# Brand-ish fills for the providers a household is most likely to hold. Keyed
# on a normalised name (lowercased, letters/digits only) so "Max", "HBO Max"
# and "Disney+" / "Disney Plus" all land on the same colour regardless of
# which spelling TMDB hands back.
_PROVIDER_COLORS: dict[str, str] = {
    "netflix": "#E50914",
    "disneyplus": "#0F3D8C",
    "hbomax": "#6C2BD9",
    "max": "#6C2BD9",
    "amazonprimevideo": "#00A8E1",
    "primevideo": "#00A8E1",
    "appletvplus": "#1D1D1F",
    "appletv": "#1D1D1F",
    "canal": "#1D1D1F",
    "canalplus": "#1D1D1F",
    "mycanal": "#1D1D1F",
    "hulu": "#0F9D66",
    "paramountplus": "#0064FF",
    "peacock": "#4B2991",
    "showtime": "#B1060F",
    "starz": "#9C7A1F",
    "crunchyroll": "#F47521",
    "youtube": "#CC0000",
    "amcplus": "#E4002B",
    "mubi": "#262626",
    "britbox": "#001C46",
    "discoveryplus": "#0072CE",
    "espnplus": "#D00000",
}

# Distinguishable fallback fills for a provider not in the map above -
# regional or niche services still get a colour of their own rather than
# one shared grey.
_PROVIDER_FALLBACK_PALETTE = [
    "#4338CA",  # indigo
    "#0D9488",  # teal
    "#C026D3",  # magenta
    "#D97706",  # amber
    "#0284C7",  # sky
    "#16A34A",  # green
    "#E11D48",  # rose
    "#7C3AED",  # violet
]


def _normalise_provider(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def provider_color(name: str) -> str:
    """
    A provider's badge fill: its own brand-ish colour when recognised,
    otherwise a stable colour picked from the name so the same provider is
    always the same colour across a session and between restarts.
    """
    key = _normalise_provider(name)
    if key in _PROVIDER_COLORS:
        return _PROVIDER_COLORS[key]
    return _PROVIDER_FALLBACK_PALETTE[crc32(key.encode()) % len(_PROVIDER_FALLBACK_PALETTE)]


class MemberRef(BaseModel):
    """
    A member as a card chip: who wants this film.

    Deliberately smaller than MemberOut - the grid renders one of these per
    member per card, and none of the editing fields are on the hot path.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    display_name: str
    initials: str
    color: str

    @classmethod
    def from_row(cls, member: Member) -> "MemberRef":
        """Build from an ORM row. Must be called while the session is open."""
        return cls(
            id=member.id,
            display_name=member.display_name,
            initials=member_initials(member.display_name),
            color=member_color(member.color, member.letterboxd_username),
        )


class OfferOut(BaseModel):
    """
    A streaming offer as the UI consumes it.

    This is the only place the `monetization_type` column is translated to the
    `offer_type` name used everywhere above the database. Do not map it at a
    call site.
    """

    model_config = ConfigDict(frozen=True)

    country_code: str
    country_name: str
    provider_id: int
    provider_name: str
    offer_type: str = Field(..., description="flatrate / rent / buy / free / ads")

    streaming_url: Optional[str] = None
    logo_path: Optional[str] = Field(None, description="TMDB path, not a full URL")
    display_priority: Optional[int] = None

    @property
    def logo(self) -> Optional[str]:
        """Full URL for the provider logo."""
        return logo_url(self.logo_path)

    @classmethod
    def from_row(cls, offer: OfferRow) -> "OfferOut":
        """Build from an ORM row. Must be called while the session is open."""
        return cls(
            country_code=offer.country_code,
            country_name=offer.country_name,
            provider_id=offer.provider_id,
            provider_name=offer.provider_name,
            offer_type=offer.monetization_type,
            streaming_url=offer.streaming_url,
            logo_path=offer.logo_path,
            display_priority=offer.display_priority,
        )


class FilmSummary(BaseModel):
    """A film as it appears in a list. Holds no ORM state."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str = Field(..., description="Best display title")
    year: Optional[int] = None
    full_title: str = Field(..., description="Title with year when known")

    tmdb_id: Optional[int] = None
    poster_path: Optional[str] = Field(None, description="TMDB path, not a full URL")
    vote_average: Optional[float] = None
    runtime: Optional[int] = Field(None, description="Minutes; null until enriched")
    match_confidence: Optional[str] = None

    # Both years are kept so a mismatch can be shown, not just flagged.
    letterboxd_year: Optional[int] = None
    tmdb_year: Optional[int] = None
    year_mismatch: bool = False

    offer_count: int = Field(default=0, description="Persisted offers; 0 if not loaded")
    last_checked: Optional[datetime] = None
    cache_age_days: Optional[int] = None

    members: list[MemberRef] = Field(
        default_factory=list, description="Who currently has this on their watchlist"
    )

    @property
    def wanted_by(self) -> int:
        """How many people want this. The number the household ranks by."""
        return len(self.members)

    @property
    def poster(self) -> Optional[str]:
        """Full URL for the poster image."""
        return poster_url(self.poster_path)

    @property
    def is_stale(self) -> bool:
        """True when the streaming data has aged past the cache TTL."""
        return self.cache_age_days is None or self.cache_age_days > settings.CACHE_TTL_DAYS

    @classmethod
    def from_film(
        cls,
        film: Film,
        *,
        offer_count: Optional[int] = None,
        members: Optional[list[MemberRef]] = None,
    ) -> "FilmSummary":
        """
        Build from an ORM row. Must be called while the session is open.

        Always pass offer_count and members in a list context. Omitting either
        reads a relationship, which lazy-loads once per row - 182 queries for a
        181-film library. `library.wanted_by` loads them for a whole page.
        """
        last_checked = film.last_checked
        age_days = None
        if last_checked is not None:
            aware = last_checked if last_checked.tzinfo else last_checked.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - aware).days

        return cls(
            id=film.id,
            title=film.display_title,
            year=film.display_year,
            full_title=film.full_title,
            tmdb_id=film.tmdb_id,
            poster_path=film.poster_path,
            vote_average=film.vote_average,
            runtime=film.runtime,
            match_confidence=film.match_confidence,
            letterboxd_year=film.letterboxd_year,
            tmdb_year=film.tmdb_year,
            year_mismatch=bool(film.year_mismatch),
            offer_count=offer_count if offer_count is not None else len(film.streaming_offers),
            last_checked=last_checked,
            cache_age_days=age_days,
            members=(
                members
                if members is not None
                else [
                    MemberRef.from_row(entry.member)
                    for entry in film.watchlist_entries
                    if entry.removed_at is None
                ]
            ),
        )


class FilmDetail(FilmSummary):
    """A single film with its streaming offers, for the detail page."""

    overview: Optional[str] = None
    tmdb_release_date: Optional[str] = None
    date_added: Optional[datetime] = None
    notes: Optional[str] = None

    offers: list[OfferOut] = Field(default_factory=list)

    @property
    def countries(self) -> list[str]:
        """Distinct country codes, sorted."""
        return sorted({o.country_code for o in self.offers})

    @property
    def providers(self) -> list[str]:
        """Distinct provider names, sorted."""
        return sorted({o.provider_name for o in self.offers})

    def offers_in(self, country_code: str) -> list[OfferOut]:
        """Offers for one country."""
        return [o for o in self.offers if o.country_code == country_code]

    @property
    def is_scoped(self) -> bool:
        """
        True when `offers` holds fewer than the film really has.

        The detail page loads only the countries the user can reach; without
        this the page would silently claim to show everything.
        """
        return len(self.offers) < self.offer_count

    @classmethod
    def from_film(
        cls,
        film: Film,
        *,
        offers: Optional[list[OfferRow]] = None,
        offer_count: Optional[int] = None,
        members: Optional[list[MemberRef]] = None,
    ) -> "FilmDetail":
        """
        Build from an ORM row and the offer rows to display.

        `offers` is passed in rather than read off film.streaming_offers so the
        caller can scope the query; omitting it reads the relationship, which
        lazy-loads every offer the film has. `offer_count` is the unscoped
        total and defaults to the number displayed.
        """
        rows = film.streaming_offers if offers is None else offers
        out = [OfferOut.from_row(row) for row in rows]
        summary = FilmSummary.from_film(
            film,
            offer_count=offer_count if offer_count is not None else len(out),
            members=members,
        )

        return cls(
            **summary.model_dump(),
            overview=film.overview,
            tmdb_release_date=film.tmdb_release_date,
            date_added=film.date_added,
            notes=film.notes,
            offers=out,
        )
