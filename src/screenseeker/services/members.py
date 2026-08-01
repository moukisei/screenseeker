"""
The household: who the watchlists come from.

A member is a Letterboxd account to scrape and a name to show on a card. It is
deliberately not a login and not a profile - the app keeps one shared password
and one shared subscription profile, because a household shares a television
and a Netflix account. The only thing that varies per person is which films
they want, which is what `watchlist_entries` records.

Everything here returns Pydantic models, so callers never hold an ORM instance
past the session.
"""

import re
from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database.models import Film, Member, WatchlistEntry
from ..exceptions import ConfigurationError
from ..logger import get_logger
from .models import MEMBER_PALETTE as PALETTE
from .models import member_color, member_initials

logger = get_logger(__name__)

# Letterboxd usernames are lowercase alphanumerics with underscores.
_USERNAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")

# What a pasted profile URL looks like, so the field accepts one.
_PROFILE_URL_RE = re.compile(r"letterboxd\.com/([^/?#]+)", re.IGNORECASE)


class MemberOut(BaseModel):
    """A member as the UI consumes it. Holds no ORM state."""

    model_config = ConfigDict(frozen=True)

    id: int
    letterboxd_username: str
    display_name: str
    color: Optional[str] = None
    active: bool = True

    last_synced_at: Optional[datetime] = None
    film_count: int = Field(default=0, description="Films currently on their watchlist")

    @property
    def initials(self) -> str:
        """One or two letters for the grid chip."""
        return member_initials(self.display_name)

    @property
    def chip_color(self) -> str:
        """The colour to render, derived from the username when none is stored."""
        return member_color(self.color, self.letterboxd_username)

    @classmethod
    def from_row(cls, member: Member, *, film_count: int = 0) -> "MemberOut":
        return cls(
            id=member.id,
            letterboxd_username=member.letterboxd_username,
            display_name=member.display_name,
            color=member.color,
            active=bool(member.active),
            last_synced_at=member.last_synced_at,
            film_count=film_count,
        )


def normalise_username(value: str) -> str:
    """
    Clean a username field into a Letterboxd username.

    Accepts a pasted profile URL, since that is what a browser gives you when
    you go looking for someone's watchlist. Raises ConfigurationError rather
    than silently storing something the scraper will 404 on for minutes.
    """
    raw = (value or "").strip()
    if not raw:
        raise ConfigurationError("A Letterboxd username is required.")

    url_match = _PROFILE_URL_RE.search(raw)
    if url_match:
        raw = url_match.group(1)

    username = raw.strip("/").strip().lower()

    if not _USERNAME_RE.match(username):
        raise ConfigurationError(
            f"'{value.strip()}' is not a Letterboxd username. "
            "Use the name from the profile URL, e.g. letterboxd.com/<name>/."
        )

    return username


def _film_counts(session: Session, member_ids: list[int]) -> dict[int, int]:
    """Live entry count per member, in one query."""
    if not member_ids:
        return {}

    rows = (
        session.query(WatchlistEntry.member_id, func.count(WatchlistEntry.id))
        .filter(
            WatchlistEntry.member_id.in_(member_ids),
            WatchlistEntry.removed_at.is_(None),
        )
        .group_by(WatchlistEntry.member_id)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def list_members(session: Session, *, active_only: bool = False) -> list[MemberOut]:
    """
    Every member, ordered by name.

    `active_only` is what sync iterates; the profile page shows everyone, so a
    paused member can be resumed.
    """
    query = session.query(Member)
    if active_only:
        query = query.filter(Member.active.is_(True))

    rows = query.order_by(func.lower(Member.display_name).asc(), Member.id.asc()).all()
    counts = _film_counts(session, [m.id for m in rows])

    return [MemberOut.from_row(m, film_count=counts.get(m.id, 0)) for m in rows]


def count_members(session: Session) -> int:
    """
    How many people are in the household.

    One COUNT rather than len(list_members()): the card partial needs this on
    every page that renders a grid, and it only ever asks whether the number
    is above one.
    """
    return int(session.query(func.count(Member.id)).scalar() or 0)


def get_member(session: Session, member_id: int) -> Optional[MemberOut]:
    """One member by primary key."""
    row = session.query(Member).filter(Member.id == member_id).first()
    if row is None:
        return None
    return MemberOut.from_row(row, film_count=_film_counts(session, [row.id]).get(row.id, 0))


def get_by_username(session: Session, username: str) -> Optional[Member]:
    """
    The ORM row for a username, or None.

    Returns the row rather than a MemberOut because sync needs the identity to
    write entries against. Nothing above the service layer may call this.
    """
    return (
        session.query(Member)
        .filter(func.lower(Member.letterboxd_username) == username.strip().lower())
        .first()
    )


def _next_color(session: Session) -> str:
    """The first palette colour nobody is using, or the next one round."""
    taken = {row[0] for row in session.query(Member.color).all() if row[0]}
    for color in PALETTE:
        if color not in taken:
            return color
    return PALETTE[(session.query(func.count(Member.id)).scalar() or 0) % len(PALETTE)]


def create_member(
    session: Session,
    username: str,
    *,
    display_name: str = "",
    color: Optional[str] = None,
) -> MemberOut:
    """
    Add a member. Raises ConfigurationError if the username is taken or invalid.

    The username is the sync key and is unique: two members pointing at one
    account would write the same entries twice and double every "wanted by"
    count, which is the number the whole feature is for.
    """
    normalised = normalise_username(username)

    if get_by_username(session, normalised) is not None:
        raise ConfigurationError(f"'{normalised}' is already in the household.")

    member = Member(
        letterboxd_username=normalised,
        display_name=(display_name or "").strip() or normalised,
        color=color or _next_color(session),
        active=True,
    )
    session.add(member)
    session.flush()

    logger.info(f"Added member '{member.display_name}' ({normalised})")
    return MemberOut.from_row(member)


def update_member(
    session: Session,
    member_id: int,
    *,
    display_name: Optional[str] = None,
    color: Optional[str] = None,
    active: Optional[bool] = None,
) -> Optional[MemberOut]:
    """
    Edit a member's presentation or pause their syncing.

    The username is deliberately not editable: it identifies the entries
    already stored, and changing it means "this is a different person", which
    is an add and a delete.
    """
    member = session.query(Member).filter(Member.id == member_id).first()
    if member is None:
        return None

    if display_name is not None and display_name.strip():
        member.display_name = display_name.strip()
    if color is not None:
        member.color = color.strip() or None
    if active is not None:
        member.active = active

    session.flush()
    return MemberOut.from_row(
        member, film_count=_film_counts(session, [member.id]).get(member.id, 0)
    )


class RemovalReport(BaseModel):
    """What deleting a member took with it."""

    model_config = ConfigDict(frozen=True)

    display_name: str
    entries_removed: int = 0
    films_removed: int = Field(default=0, description="Films nobody else had listed")


def delete_member(session: Session, member_id: int) -> Optional[RemovalReport]:
    """
    Remove a member, their entries, and any film left with no owner at all.

    Dropping the orphans is the point: a film only this person wanted is not
    part of the household's list once they leave, and keeping it would turn the
    library into a graveyard nothing can clear. Films anyone else still lists -
    including entries they have since removed - are untouched, so their TMDB
    enrichment survives.
    """
    member = session.query(Member).filter(Member.id == member_id).first()
    if member is None:
        return None

    name = member.display_name

    film_ids = [
        row[0]
        for row in session.query(WatchlistEntry.film_id)
        .filter(WatchlistEntry.member_id == member_id)
        .all()
    ]

    entries_removed = (
        session.query(WatchlistEntry).filter(WatchlistEntry.member_id == member_id).delete()
    )
    session.delete(member)
    session.flush()

    films_removed = 0
    if film_ids:
        # Whoever is left, live entry or not. A film someone removed from their
        # own watchlist is still theirs to restore, so it is not an orphan.
        still_owned = {
            row[0]
            for row in session.query(WatchlistEntry.film_id)
            .filter(WatchlistEntry.film_id.in_(film_ids))
            .all()
        }
        orphans = [fid for fid in film_ids if fid not in still_owned]
        if orphans:
            films_removed = (
                session.query(Film).filter(Film.id.in_(orphans)).delete(synchronize_session=False)
            )

    logger.info(
        f"Removed member '{name}': {entries_removed} entries, {films_removed} orphaned films"
    )
    return RemovalReport(
        display_name=name, entries_removed=entries_removed, films_removed=films_removed
    )


def mark_synced(session: Session, member_id: int) -> None:
    """Record that this member's watchlist was scraped just now."""
    session.query(Member).filter(Member.id == member_id).update(
        {Member.last_synced_at: datetime.now(UTC)}
    )
