"""household members

Turns a one-person library into a household one. Films stay deduplicated and
globally enriched; who wants them moves onto a join table, so three people
wanting the same film is one Film row, one TMDB lookup, and three entries.

The backfill attaches every existing film to a single member built from the
configured Letterboxd username, so an existing install upgrades to exactly the
library it already had.

Revision ID: b7d4e8a91c30
Revises: a3f7c1d9e2b4
Create Date: 2026-07-31 00:00:00.000000

"""

from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e8a91c30"
down_revision: Union[str, Sequence[str], None] = "a3f7c1d9e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Used when films exist but no username is configured, so the backfill never
# leaves rows with no owner. Renameable from the profile page afterwards.
FALLBACK_USERNAME = "household"
FALLBACK_DISPLAY_NAME = "Household"


def _configured_username() -> str:
    """
    The Letterboxd username from config, or "" if it cannot be read.

    Wrapped broadly on purpose: a migration must not fail because the config
    file is missing, unreadable or from an older shape. The fallback member is
    always enough to keep existing films attached.
    """
    try:
        from screenseeker import user_config

        return (user_config.load_config().get("letterboxd", {}).get("username") or "").strip()
    except Exception:
        return ""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("letterboxd_username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_members_letterboxd_username", "members", ["letterboxd_username"], unique=True
    )

    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("film_id", sa.Integer(), nullable=False),
        sa.Column("date_added", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["film_id"], ["films.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "film_id", name="uq_entry_member_film"),
    )
    op.create_index("ix_watchlist_entries_member_id", "watchlist_entries", ["member_id"])
    op.create_index("ix_watchlist_entries_film_id", "watchlist_entries", ["film_id"])
    op.create_index("idx_entries_film_live", "watchlist_entries", ["film_id", "removed_at"])

    _backfill()


def _backfill() -> None:
    """Attach every existing film to one member, preserving its added date."""
    bind = op.get_bind()

    film_count = bind.execute(sa.text("SELECT COUNT(*) FROM films")).scalar() or 0
    username = _configured_username()

    # Nothing to own and nobody configured: leave the tables empty and let the
    # user add members from the profile page.
    if not film_count and not username:
        return

    display_name = username or FALLBACK_DISPLAY_NAME
    now = datetime.now(UTC)

    bind.execute(
        sa.text(
            "INSERT INTO members "
            "(letterboxd_username, display_name, color, active, created_at, last_synced_at) "
            "VALUES (:username, :display_name, NULL, 1, :now, NULL)"
        ),
        {"username": username or FALLBACK_USERNAME, "display_name": display_name, "now": now},
    )
    member_id = bind.execute(sa.text("SELECT id FROM members WHERE rowid = last_insert_rowid()"))
    member_id = member_id.scalar()

    if film_count:
        bind.execute(
            sa.text(
                "INSERT INTO watchlist_entries "
                "(member_id, film_id, date_added, removed_at, created_at) "
                "SELECT :member_id, id, date_added, NULL, :now FROM films"
            ),
            {"member_id": member_id, "now": now},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_entries_film_live", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_film_id", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_member_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
    op.drop_index("ix_members_letterboxd_username", table_name="members")
    op.drop_table("members")
