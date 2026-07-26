"""jobs table

Background sync and refresh runs, and the single-flight guard that keeps two
of the same kind from running at once.

Revision ID: 8f31a0b5c4d2
Revises: 1c2a24ce75f0
Create Date: 2026-07-22 23:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f31a0b5c4d2"
down_revision: Union[str, Sequence[str], None] = "1c2a24ce75f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_jobs_created_at", "jobs", ["created_at"], unique=False)

    # The single-flight guard. A partial unique index rather than an
    # application check: two requests can both read "nothing is running"
    # before either inserts, and two concurrent syncs race get_or_create_film
    # into duplicate films.
    #
    # Written as raw SQL because op.create_index cannot express a partial
    # index portably. Keep the predicate identical to the sqlite_where on
    # Job's index in database/models.py, or create_all and this migration
    # produce different schemas.
    op.execute(
        "CREATE UNIQUE INDEX idx_jobs_one_active_per_kind "
        "ON jobs (kind) WHERE status IN ('queued', 'running')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_jobs_one_active_per_kind")
    op.drop_index("idx_jobs_created_at", table_name="jobs")
    op.drop_table("jobs")
