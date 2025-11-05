from pathlib import Path

# User Configuration
USERNAME = "moukisei"
HTML_URL = f"https://letterboxd.com/{USERNAME}/watchlist/"

# Scraper Configuration
SCRAPER_TYPE = "csv"  # Options: "html" or "csv"
CSV_FILE_PATH = "/Users/mouktarabdillahi/Downloads/watchlist-moukisei-2025-11-03-19-13-utc.csv"  # Path to CSV export file (used when SCRAPER_TYPE="csv")

# Output Configuration
OUTPUT_DIR = Path("./output")
SAVE_RAW_DATA = True  # Save raw HTML or keep copy of CSV for analysis

# HTML Scraper Settings
HTML_DELAY_BETWEEN_REQUESTS = 2.0  # Seconds between page requests
HTML_TIMEOUT = 10  # Request timeout in seconds

# Logging Configuration
LOG_LEVEL = "INFO"  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_FILE = False  # Set to True to also log to output/scraper.log
