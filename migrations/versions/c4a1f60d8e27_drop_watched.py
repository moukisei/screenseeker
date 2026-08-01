"""drop the watched flag

The library is now exactly what is on someone's watchlist right now. Logging a
film on Letterboxd removes it from the watchlist there, the next sync retires
the entry, and the film leaves the app - so a `watched` flag here was a second
source of truth for the same fact, kept in agreement by hand and usually not.

Dropping the columns rather than leaving them unread: nothing writes them, and
a column the code has forgotten is the one someone later trusts.

This discards whatever was marked watched in the app. That history lives in the
Letterboxd diary, which is where it was always going to be read from.

Revision ID: c4a1f60d8e27
Revises: b7d4e8a91c30
Create Date: 2026-08-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a1f60d8e27"
down_revision: Union[str, Sequence[str], None] = "b7d4e8a91c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A plain DROP COLUMN, deliberately NOT batch_alter_table.
    #
    # Batch mode emulates ALTER by rebuilding the table: create a copy, move
    # the rows, DROP the original, rename. On this schema that is catastrophic.
    # `streaming_offers` and `watchlist_entries` both reference films with ON
    # DELETE CASCADE, and database/session.py registers a global connect
    # listener that turns `PRAGMA foreign_keys=ON` - including on the
    # connection Alembic migrates with, because env.py imports that module.
    # Dropping the old films table therefore deletes every offer and every
    # watchlist entry in the database. It did exactly that in production.
    #
    # Turning the pragma off is not a fix: SQLite ignores `PRAGMA foreign_keys`
    # inside a transaction, and Alembic runs migrations in one.
    #
    # SQLite has supported native DROP COLUMN since 3.35 (2021), which rewrites
    # the column list in place and leaves child rows untouched. Ubuntu 24.04
    # ships 3.45. Any future migration that removes a column from `films` must
    # do the same, or repeat this.
    op.drop_column("films", "watched_at")
    op.drop_column("films", "watched")


def downgrade() -> None:
    """
    Downgrade schema.

    Restores the columns, not the data - every film comes back unwatched. The
    app on the previous revision reads that as "nothing has been seen yet",
    which is wrong but harmless: it only ever meant "hide this from Tonight".

    ADD COLUMN is native on every SQLite, so this side never needed batch mode
    either - and must not use it, for the cascade reason in `upgrade`.
    """
    op.add_column(
        "films", sa.Column("watched", sa.Boolean(), nullable=True, server_default=sa.false())
    )
    op.add_column("films", sa.Column("watched_at", sa.DateTime(), nullable=True))
