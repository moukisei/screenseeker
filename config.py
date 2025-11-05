from pathlib import Path

# User Configuration
USERNAME = "moukisei"
HTML_URL = f"https://letterboxd.com/{USERNAME}/watchlist/"

# Scraper Configuration
SCRAPER_TYPE = "html"  # Options: "html" or "csv"
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

# TMDB Enrichment Configuration
TMDB_API_KEY = "255e9aafab2f223d9c5da659026f16f8"  # Get free API key at https://www.themoviedb.org/settings/api
TMDB_RATE_LIMIT = (
    5.0  # Requests per second (TMDB allows up to 50/s, but we're conservative)
)
TMDB_LANGUAGE = "en-US"  # Language for movie metadata (not streaming availability)

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
