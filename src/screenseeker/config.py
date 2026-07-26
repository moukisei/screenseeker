"""
Backwards-compatible aliases for the low-level tunables.

The values now live in settings.py, which resolves them from the environment
in one place. This module stays so existing imports keep working.
"""

from .settings import (
    HTML_DELAY_BETWEEN_REQUESTS,
    HTML_TIMEOUT,
    LOG_LEVEL,
    LOG_TO_FILE,
    OUTPUT_DIR,
    SAVE_RAW_DATA,
)

__all__ = [
    "HTML_DELAY_BETWEEN_REQUESTS",
    "HTML_TIMEOUT",
    "LOG_LEVEL",
    "LOG_TO_FILE",
    "OUTPUT_DIR",
    "SAVE_RAW_DATA",
]

# All user settings (Letterboxd username, TMDB credentials, subscriptions)
# are stored in the config file at settings.CONFIG_PATH.
# Run `screenseeker config init` to set them up.
