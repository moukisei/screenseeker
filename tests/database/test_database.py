"""
Tests for the database package: the engine, the session factory and init.

Queries and the enrichment write path used to live here too, under
database/queries.py and database/service.py. They now sit in services/ and are
tested there - this file covers only what database/ still owns.
"""

from unittest.mock import patch

import pytest

from screenseeker.database.models import Film
from screenseeker.database.session import (
    DATABASE_DIR,
    DATABASE_PATH,
    DATABASE_URL,
    SessionLocal,
    engine,
    get_database_info,
    get_session,
    init_db,
    reset_database,
)

# Database Session Tests
# =============================================================================


class TestDatabaseConfiguration:
    """Test database configuration."""

    def test_database_url_configured(self):
        """Test that DATABASE_URL is configured."""
        assert DATABASE_URL is not None
        assert "sqlite:///" in DATABASE_URL

    def test_database_path_configured(self):
        """Test that DATABASE_PATH is configured."""
        assert DATABASE_PATH is not None
        assert DATABASE_PATH.suffix == ".db"

    def test_database_dir_configured(self):
        """Test that DATABASE_DIR is configured."""
        assert DATABASE_DIR is not None
        assert DATABASE_PATH.parent == DATABASE_DIR


class TestEngine:
    """Test database engine."""

    def test_engine_created(self):
        """Test that engine is created."""
        assert engine is not None

    def test_session_local_created(self):
        """Test that SessionLocal is created."""
        assert SessionLocal is not None


class TestGetSession:
    """Test get_session context manager."""

    def test_get_session_returns_session(self):
        """Test that get_session returns a session."""
        with get_session() as session:
            assert session is not None

    def test_get_session_error_handling(self):
        """Test that get_session handles errors properly."""
        # Deliberately cause an error and verify rollback
        with pytest.raises(ValueError):
            with get_session():
                raise ValueError("Test error")


class TestInitDB:
    """Test init_db function."""

    def test_init_db_callable(self):
        """Test that init_db is callable."""
        assert callable(init_db)

    def test_init_db_creates_database(self, tmp_path):
        """Test that init_db actually creates database."""
        # Call init_db - should not raise
        init_db()

        # Database should be accessible
        assert DATABASE_PATH.exists()

    def test_init_db_idempotent(self):
        """Test that init_db can be called multiple times."""
        # Call init_db twice - should not raise
        init_db()
        init_db()


class TestGetDatabaseInfo:
    """Test get_database_info function."""

    def test_get_database_info_returns_dict(self):
        """Test that get_database_info returns a dictionary."""
        info = get_database_info()
        assert isinstance(info, dict)
        assert "path" in info
        assert "exists" in info

    def test_database_info_has_path(self):
        """Test that database info includes path."""
        info = get_database_info()
        assert info["path"] is not None

    def test_database_info_has_exists_flag(self):
        """Test that database info includes exists flag."""
        info = get_database_info()
        assert isinstance(info["exists"], bool)

    def test_get_database_info_with_stats(self):
        """Test get_database_info with existing database."""
        # Ensure database exists
        init_db()

        info = get_database_info()

        # Should have file size info
        assert "size_bytes" in info
        assert "size_mb" in info
        assert info["size_mb"] > 0

        # Should have counts (even if 0)
        assert "film_count" in info
        assert "offer_count" in info
        assert info["film_count"] is not None
        assert info["offer_count"] is not None


class TestResetDatabase:
    """Test reset_database function."""

    def test_reset_database_callable(self):
        """Test that reset_database is callable."""
        assert callable(reset_database)

    def test_reset_database_executes(self):
        """Test that reset_database actually works."""
        # Call reset_database - should not raise
        reset_database()

        # Database should still be accessible after reset
        with get_session() as session:
            count = session.query(Film).count()
            assert count == 0  # Should be empty after reset


# =============================================================================
# Database Init Module Tests
# =============================================================================


class TestInitDBMain:
    """Test init_db.py main function."""

    @patch("screenseeker.database.init_db.init_db")
    @patch("screenseeker.database.init_db.get_database_info")
    def test_main_success(self, mock_get_info, mock_init_db):
        """Test successful database initialization."""
        from screenseeker.database.init_db import main

        mock_get_info.return_value = {
            "path": "/test/path/screenseeker.db",
            "exists": True,
            "size_mb": 1.5,
            "film_count": 10,
            "offer_count": 25,
        }

        result = main()

        assert result == 0
        mock_init_db.assert_called_once()
        mock_get_info.assert_called_once()

    @patch("screenseeker.database.init_db.init_db")
    @patch("screenseeker.database.init_db.get_database_info")
    def test_main_with_minimal_info(self, mock_get_info, mock_init_db):
        """Test main with minimal database info."""
        from screenseeker.database.init_db import main

        mock_get_info.return_value = {
            "path": "/test/path/screenseeker.db",
            "exists": False,
        }

        result = main()

        assert result == 0
        mock_init_db.assert_called_once()

    @patch("screenseeker.database.init_db.init_db")
    def test_main_failure(self, mock_init_db):
        """Test main function when init_db raises exception."""
        from screenseeker.database.init_db import main

        mock_init_db.side_effect = Exception("Database error")

        result = main()

        assert result == 1
        mock_init_db.assert_called_once()
