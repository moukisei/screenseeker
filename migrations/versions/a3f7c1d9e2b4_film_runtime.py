"""film runtime

The movie's length in minutes, from TMDB. Null on existing rows until the film
is next enriched; the UI simply omits it, as it does for a missing rating.

Revision ID: a3f7c1d9e2b4
Revises: 8f31a0b5c4d2
Create Date: 2026-07-26 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c1d9e2b4"
down_revision: Union[str, Sequence[str], None] = "8f31a0b5c4d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("films", sa.Column("runtime", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("films", "runtime")
