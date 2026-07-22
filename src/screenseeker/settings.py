"""
Runtime settings, resolved once at import from the environment.

Everything that varies between a laptop, a test run and a server lives here.
Nothing else in the package may derive a path from __file__ or the working
directory - that is what made the package unusable outside a git checkout.
"""

import os
from pathlib import Path

# Directory the package is installed into, three levels up from this file:
# src/screenseeker/settings.py -> src/screenseeker -> src -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Where the database used to live: <project root>/data/screenseeker.db. Kept as
# a fallback so an existing checkout keeps its data instead of silently
# starting from an empty database somewhere else.
LEGACY_DB_PATH = _PROJECT_ROOT / "data" / "screenseeker.db"

XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
XDG_CONFIG_HOME = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))

DEFAULT_DATA_DIR = XDG_DATA_HOME / "screenseeker"
DEFAULT_CONFIG_DIR = XDG_CONFIG_HOME / "screenseeker"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_db_path() -> Path:
    """
    Pick the database location.

    1. SCREENSEEKER_DB_PATH, if set.
    2. The legacy in-checkout path, if that file already exists. Moving a
       user's database without being asked is not this function's job.
    3. The XDG data directory.
    """
    override = os.getenv("SCREENSEEKER_DB_PATH")
    if override:
        return Path(override).expanduser()

    if LEGACY_DB_PATH.exists():
        return LEGACY_DB_PATH

    return DEFAULT_DATA_DIR / "screenseeker.db"


def _resolve_output_dir() -> Path:
    override = os.getenv("SCREENSEEKER_OUTPUT_DIR") or os.getenv("OUTPUT_DIR")
    if override:
        return Path(override).expanduser()

    legacy = _PROJECT_ROOT / "output"
    if legacy.exists():
        return legacy

    return DEFAULT_DATA_DIR / "output"


# --- Storage -----------------------------------------------------------------

DB_PATH = _resolve_db_path()
DB_DIR = DB_PATH.parent
DATABASE_URL = f"sqlite:///{DB_PATH}"

CONFIG_PATH = Path(
    os.getenv("SCREENSEEKER_CONFIG_PATH", str(DEFAULT_CONFIG_DIR / "config.toml"))
).expanduser()

OUTPUT_DIR = _resolve_output_dir()
SAVE_RAW_DATA = _env_flag("SAVE_RAW_DATA", True)

# --- SQLite ------------------------------------------------------------------

# Milliseconds a blocked writer waits before giving up with "database is
# locked". Concurrent web requests need this; a single CLI process does not.
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SCREENSEEKER_SQLITE_BUSY_TIMEOUT_MS", "5000"))

# --- Web server --------------------------------------------------------------

# Loopback by default. Binding to 0.0.0.0 must be a deliberate act.
HOST = os.getenv("SCREENSEEKER_HOST", "127.0.0.1")
PORT = int(os.getenv("SCREENSEEKER_PORT", "8000"))
DEBUG = _env_flag("SCREENSEEKER_DEBUG", False)

# --- Scraping ----------------------------------------------------------------

HTML_DELAY_BETWEEN_REQUESTS = float(os.getenv("HTML_DELAY_BETWEEN_REQUESTS", "2.0"))
HTML_TIMEOUT = int(os.getenv("HTML_TIMEOUT", "10"))

# --- TMDB --------------------------------------------------------------------

# Overrides the value in config.toml when set, so a deployment can keep the key
# out of a file on disk.
TMDB_API_KEY_ENV = os.getenv("TMDB_API_KEY")

# --- Logging -----------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_FILE = _env_flag("LOG_TO_FILE", False)
