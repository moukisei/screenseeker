import os
from pathlib import Path

# Output Configuration
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
SAVE_RAW_DATA = os.getenv("SAVE_RAW_DATA", "True").lower() == "true"

# HTML Scraper Settings
HTML_DELAY_BETWEEN_REQUESTS = float(os.getenv("HTML_DELAY_BETWEEN_REQUESTS", "2.0"))
HTML_TIMEOUT = int(os.getenv("HTML_TIMEOUT", "10"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "False").lower() == "true"

# All user settings (Letterboxd username, TMDB credentials, subscriptions)
# are stored in ~/.config/screenseeker/config.toml.
# Run `screenseeker config init` to set them up.
