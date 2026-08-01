"""drop the watched flag

Logging a film on Letterboxd removes it from the watchlist, so the next sync
drops it from the library on its own. A flag here was a second source of truth.

Discards whatever was marked watched in the app; that history is in the diary.

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
    # NOT batch_alter_table: it rebuilds the table, and the DROP cascades away
    # every streaming_offer and watchlist_entry. It did, in production.
    # Native DROP COLUMN needs SQLite 3.35+ (2021); Ubuntu 24.04 ships 3.45.
    op.drop_column("films", "watched_at")
    op.drop_column("films", "watched")


def downgrade() -> None:
    """
    Downgrade schema.

    Restores the columns, not the data. ADD COLUMN is native everywhere, so no
    batch mode here either - see `upgrade`.
    """
    op.add_column(
        "films", sa.Column("watched", sa.Boolean(), nullable=True, server_default=sa.false())
    )
    op.add_column("films", sa.Column("watched_at", sa.DateTime(), nullable=True))
