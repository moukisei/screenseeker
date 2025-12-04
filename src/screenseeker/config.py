import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# User Configuration
USERNAME = os.getenv("LETTERBOXD_USERNAME", "your_letterboxd_username")
HTML_URL = f"https://letterboxd.com/{USERNAME}/watchlist/"

# Scraper Configuration
SCRAPER_TYPE = os.getenv("SCRAPER_TYPE", "html")  # Options: "html" or "csv"
CSV_FILE_PATH = os.getenv("CSV_FILE_PATH", "./watchlist.csv")  # Path to CSV export file

# Output Configuration
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
SAVE_RAW_DATA = os.getenv("SAVE_RAW_DATA", "True").lower() == "true"

# HTML Scraper Settings
HTML_DELAY_BETWEEN_REQUESTS = float(os.getenv("HTML_DELAY_BETWEEN_REQUESTS", "2.0"))
HTML_TIMEOUT = int(os.getenv("HTML_TIMEOUT", "10"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "False").lower() == "true"

# TMDB Enrichment Configuration
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "your_tmdb_api_key_here")
TMDB_RATE_LIMIT = float(os.getenv("TMDB_RATE_LIMIT", "5.0"))
TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "en-US")

# Subscription Profile Configuration
SUBSCRIPTION_PROFILE = {
    "base_country": "FR",  # Your base country where you live
    "subscriptions": [
        {
            "provider_names": ["Canal+", "Canal Plus", "Canal+ Ciné", "Canal+ Cine"],
            "vpn_enabled": False,
            "available_countries": ["FR"],  # Only works in France
            "bundle_includes": [
                "HBO Max",
                "Apple TV+",
                "Apple TV Plus",
                "Paramount+",
                "Paramount Plus",
            ],
        },
        {
            "provider_names": ["Netflix"],
            "vpn_enabled": True,
            "available_countries": "all",  # Works with VPN in all countries
        },
        {
            "provider_names": ["Amazon Prime Video", "Prime Video", "Amazon Prime"],
            "vpn_enabled": True,
            "available_countries": "all",  # Works with VPN in all countries
        },
    ],
    # Country priority for VPN (English-speaking first, then European)
    "vpn_country_priority": [
        # English-speaking countries (priority 1)
        "US",
        "GB",
        "CA",
        "AU",
        "NZ",
        "IE",
        # European countries (priority 2)
        "DE",
        "ES",
        "IT",
        "NL",
        "BE",
        "CH",
        "AT",
        "SE",
        "NO",
        "DK",
        "FI",
        "PT",
        # Other countries (priority 3)
        "BR",
        "MX",
        "AR",
        "JP",
        "KR",
        "IN",
        "SG",
        "HK",
    ],
    "max_vpn_suggestions": 3,  # Show max 3 VPN country suggestions
}
