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
    # batch_alter_table because SQLite implements DROP COLUMN by rebuilding the
    # table; alembic does that rebuild for us, indexes and constraints intact.
    with op.batch_alter_table("films") as batch:
        batch.drop_column("watched_at")
        batch.drop_column("watched")


def downgrade() -> None:
    """
    Downgrade schema.

    Restores the columns, not the data - every film comes back unwatched. The
    app on the previous revision reads that as "nothing has been seen yet",
    which is wrong but harmless: it only ever meant "hide this from Tonight".
    """
    with op.batch_alter_table("films") as batch:
        batch.add_column(
            sa.Column("watched", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch.add_column(sa.Column("watched_at", sa.DateTime(), nullable=True))
