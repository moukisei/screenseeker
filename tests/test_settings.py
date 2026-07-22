"""
Tests for environment-driven settings resolution.

settings.py reads the environment at import, so these reload the module under
a patched environment rather than mutating already-resolved values.
"""

import importlib
from pathlib import Path

import pytest

from screenseeker import settings as settings_module


def reload_settings(monkeypatch, **env):
    """Re-import settings with the given environment applied."""
    for key in (
        "SCREENSEEKER_DB_PATH",
        "SCREENSEEKER_CONFIG_PATH",
        "SCREENSEEKER_OUTPUT_DIR",
        "SCREENSEEKER_HOST",
        "SCREENSEEKER_PORT",
        "SCREENSEEKER_DEBUG",
        "OUTPUT_DIR",
        "TMDB_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    return importlib.reload(settings_module)


@pytest.fixture(autouse=True)
def restore_settings():
    """Leave the module as the rest of the suite expects to find it."""
    yield
    importlib.reload(settings_module)


class TestDatabasePath:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.db"
        s = reload_settings(monkeypatch, SCREENSEEKER_DB_PATH=str(target))

        assert s.DB_PATH == target
        assert s.DB_DIR == tmp_path
        assert s.DATABASE_URL == f"sqlite:///{target}"

    def test_expands_user_home(self, monkeypatch):
        s = reload_settings(monkeypatch, SCREENSEEKER_DB_PATH="~/somewhere/db.sqlite")

        assert "~" not in str(s.DB_PATH)
        assert s.DB_PATH.is_absolute()

    def test_falls_back_to_legacy_path_when_present(self, monkeypatch):
        """An existing in-checkout database must not be orphaned."""
        s = reload_settings(monkeypatch)

        if s.LEGACY_DB_PATH.exists():
            assert s.DB_PATH == s.LEGACY_DB_PATH
        else:
            assert s.DB_PATH == s.DEFAULT_DATA_DIR / "screenseeker.db"


class TestConfigPath:
    def test_default_is_xdg_config(self, monkeypatch):
        s = reload_settings(monkeypatch)
        assert s.CONFIG_PATH.name == "config.toml"
        assert s.CONFIG_PATH.parent.name == "screenseeker"

    def test_env_override(self, monkeypatch, tmp_path):
        target = tmp_path / "elsewhere.toml"
        s = reload_settings(monkeypatch, SCREENSEEKER_CONFIG_PATH=str(target))
        assert s.CONFIG_PATH == target


class TestWebDefaults:
    def test_binds_loopback_by_default(self, monkeypatch):
        """Binding beyond loopback must be a deliberate act."""
        s = reload_settings(monkeypatch)
        assert s.HOST == "127.0.0.1"

    def test_debug_off_by_default(self, monkeypatch):
        s = reload_settings(monkeypatch)
        assert s.DEBUG is False

    @pytest.mark.parametrize("raw", ["1", "true", "True", "yes", "on"])
    def test_debug_truthy_values(self, monkeypatch, raw):
        assert reload_settings(monkeypatch, SCREENSEEKER_DEBUG=raw).DEBUG is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", ""])
    def test_debug_falsy_values(self, monkeypatch, raw):
        assert reload_settings(monkeypatch, SCREENSEEKER_DEBUG=raw).DEBUG is False

    def test_port_is_int(self, monkeypatch):
        assert reload_settings(monkeypatch, SCREENSEEKER_PORT="9001").PORT == 9001


class TestTmdbKey:
    def test_unset_by_default(self, monkeypatch):
        assert reload_settings(monkeypatch).TMDB_API_KEY_ENV is None

    def test_read_from_env(self, monkeypatch):
        assert reload_settings(monkeypatch, TMDB_API_KEY="abc123").TMDB_API_KEY_ENV == "abc123"


class TestNoWorkingDirectoryDependence:
    def test_paths_are_absolute(self, monkeypatch):
        """
        Nothing may resolve against the process working directory.

        Relative paths are why the database landed inside site-packages.
        """
        s = reload_settings(monkeypatch)

        for path in (s.DB_PATH, s.CONFIG_PATH, s.OUTPUT_DIR):
            assert isinstance(path, Path)
            assert path.is_absolute(), f"{path} is not absolute"
