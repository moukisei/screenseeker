"""
Migrations must not destroy data.

`drop_watched` once used batch_alter_table, which rebuilds the table on SQLite;
the DROP cascaded away every streaming_offer and watchlist_entry in production.
Nothing caught it because the schema afterwards was correct - only rows were
gone. These run the real chain against a real file for that reason.
"""

import ast
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

# Every revision after the initial schema that alters an existing table. A new
# one belongs here, so the downgrade test walks back over it.
REVISIONS_ALTERING_FILMS = ["c4a1f60d8e27"]

# Operations SQLite cannot do in place. Inside a batch_alter_table block these
# rebuild the table, and rebuilding `films` cascade-deletes its children.
REBUILDING_OPERATIONS = (
    "drop_column",
    "alter_column",
    "drop_constraint",
    "create_check_constraint",
    "create_unique_constraint",
    "create_foreign_key",
)


def _rebuilding_ops_inside_batch(source: str) -> list[str]:
    """
    Rebuild-forcing calls inside a `with op.batch_alter_table(...)` block.

    Parsed, not grepped: a substring search also matches the comments warning
    against it, so the guard would fire on migrations that got it right.
    """
    found = set()

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.With):
            continue

        opens_batch = any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "attr", "") == "batch_alter_table"
            for item in node.items
        )
        if not opens_batch:
            continue

        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                name = getattr(inner.func, "attr", "")
                if name in REBUILDING_OPERATIONS:
                    found.add(name)

    return sorted(found)


@pytest.fixture
def migrated(tmp_path):
    """
    An alembic Config, and the database it will actually write to.

    env.py overwrites `sqlalchemy.url` with session.DATABASE_URL, so setting
    our own path here would be ignored and the tests would find nothing.
    """
    from screenseeker.database import session as db_session

    db = Path(str(db_session.DATABASE_URL).replace("sqlite:///", ""))

    cfg = Config("alembic.ini")
    cfg.attributes["configure_logger"] = False

    return cfg, db


def seed(db):
    """One film, with a child row in each table that cascades from it."""
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO films (letterboxd_title, letterboxd_year, date_added, watched, created_at) "
        "VALUES ('Heat', 1995, '2026-01-01', 0, '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO streaming_offers (film_id, country_code, country_name, provider_id, "
        "provider_name, monetization_type, checked_at, created_at) "
        "VALUES (1, 'FR', 'France', 8, 'Netflix', 'flatrate', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO members (letterboxd_username, display_name, active, created_at) "
        "VALUES ('alice', 'Alice', 1, '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO watchlist_entries (member_id, film_id, date_added, created_at) "
        "VALUES (1, 1, '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()


def counts(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT (SELECT count(*) FROM films), "
            "       (SELECT count(*) FROM streaming_offers), "
            "       (SELECT count(*) FROM watchlist_entries)"
        ).fetchone()
    finally:
        conn.close()


class TestNoCascadeWipe:
    def test_upgrading_to_head_keeps_offers_and_entries(self, migrated):
        """
        The regression. A film's offers and watchlist entries must survive
        every migration that touches the films table.
        """
        cfg, db = migrated

        # The last revision before anything alters films again.
        command.upgrade(cfg, "b7d4e8a91c30")
        seed(db)
        assert counts(db) == (1, 1, 1)

        command.upgrade(cfg, "head")

        assert counts(db) == (1, 1, 1), (
            "a migration cascade-deleted child rows - see this module's docstring; "
            "the usual cause is batch_alter_table on `films`"
        )

    def test_downgrading_keeps_them_too(self, migrated):
        cfg, db = migrated

        command.upgrade(cfg, "b7d4e8a91c30")
        seed(db)
        command.upgrade(cfg, "head")

        for _ in REVISIONS_ALTERING_FILMS:
            command.downgrade(cfg, "-1")

        assert counts(db) == (1, 1, 1)

    def test_no_revision_rebuilds_a_table_through_batch_mode(self):
        """
        Caught at authoring time rather than after it eats a database.

        batch_alter_table is fine for create_index, which SQLite does natively.
        Pairing it with an operation that forces a table rebuild is not.
        """
        offenders = {}
        for path in sorted(Path("migrations/versions").glob("*.py")):
            found = _rebuilding_ops_inside_batch(path.read_text())
            if found:
                offenders[path.name] = found

        assert offenders == {}, (
            f"{offenders} pair batch_alter_table with a rebuilding operation. "
            "That copies the table, DROPs the original and renames - which "
            "cascade-deletes streaming_offers and watchlist_entries. Use the "
            "plain op.* form; SQLite has supported native DROP COLUMN since 3.35."
        )


class TestChainIsSound:
    def test_upgrade_then_full_downgrade_then_upgrade(self, migrated):
        """The whole chain runs both ways without an error."""
        cfg, db = migrated

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        assert counts(db) == (0, 0, 0)
