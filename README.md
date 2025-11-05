# ScreenSeeker

Letterboxd watchlist scraper + streaming availability finder with personalized recommendations based on your subscriptions and VPN.

## Features

- **Scraping**: Extract films from Letterboxd (HTML or CSV)
- **Enrichment**: Find global streaming availability via TMDB API
- **Smart Recommendations**: Personalized watch strategy based on your subscriptions
- **VPN-Aware**: Prioritizes English-speaking countries, respects VPN limitations

## Installation

```bash
poetry install
# or
pip install requests beautifulsoup4 pydantic tenacity
```

## Quick Start

### 1. Configuration (`config.py`)

```python
# Scraping
USERNAME = "your_letterboxd_username"
SCRAPER_TYPE = "html"  # or "csv"

# TMDB (get free key at themoviedb.org)
TMDB_API_KEY = "your_api_key"

# Your subscriptions
SUBSCRIPTION_PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {
            "provider_names": ["Netflix"],
            "vpn_enabled": True,
        },
        # ... add yours
    ]
}
```

### 2. Scrape Watchlist

```bash
# HTML scraping
python main.py

# CSV parsing (export from Letterboxd first)
# Set SCRAPER_TYPE = "csv" in config.py
python main.py
```

**Output**: `output/letterboxd_films_html_YYYYMMDD_HHMMSS.json`

### 3. Find Where to Watch

```bash
python enrich.py "The Matrix (1999)"
```

**Output**:
```
================================================================================
HOW TO WATCH
================================================================================

📽️  'The Matrix' (1999)
🎯 TMDB Match: The Matrix (1999) - Confidence: exact
   ⭐ Rating: 8.2/10

✅ WATCH NOW (No VPN needed):
   🇫🇷 Netflix - France

🌍 VPN OPTIONS (Use NordVPN):
   🇺🇸 Netflix - Connect to United States
   🇬🇧 Prime Video - Connect to United Kingdom
   🇨🇦 Netflix - Connect to Canada

💰 RENT/BUY IN FRANCE:
   Rent: Apple TV, Google Play Movies
```

## Project Structure

```
screenseeker/
├── main.py              # Scraper entry point
├── enrich.py            # Enrichment CLI
├── config.py            # Configuration
├── models.py            # Film data models
├── logger.py            # Centralized logging
│
├── scrapers/            # Letterboxd scrapers
│   ├── base.py         # Abstract base
│   ├── html_scraper.py # HTML scraping
│   └── csv_scraper.py  # CSV parsing
│
├── enrichers/           # Streaming availability
│   ├── enrichment_models.py  # Data models
│   ├── tmdb_enricher.py      # TMDB API
│   └── watch_strategy.py     # Personalized recommendations
│
└── exporters/           # Data export
    └── json_exporter.py
```

## Data Models

### Film (Scraping)
```python
{
  "film_id": "a1b2c3d4e5f6",      # Auto-generated hash
  "film_full_title": "The Matrix (1999)",
  "film_title": "The Matrix",
  "year": 1999,
  "date_added": "2025-01-04"       # From CSV or today
}
```

### EnrichmentResult
```python
{
  "tmdb_movie": {...},              # TMDB metadata
  "match_confidence": "exact",       # exact/high/medium/low
  "streaming_offers": [...],         # All global offers
  "total_countries": 45,
  "total_providers": 12
}
```

### WatchStrategy
```python
{
  "best_option": {...},              # No VPN needed
  "vpn_options": [...],              # Top 3 VPN countries
  "base_country_alternatives": [...] # Rent/buy options
}
```

## Configuration Details

### Scraper Settings
```python
SCRAPER_TYPE = "html"                    # or "csv"
CSV_FILE_PATH = "./export.csv"
HTML_DELAY_BETWEEN_REQUESTS = 2.0       # Rate limiting
SAVE_RAW_DATA = True                     # Save raw HTML
```

### Enrichment Settings
```python
TMDB_API_KEY = "your_key"               # Required
TMDB_RATE_LIMIT = 5.0                   # Req/second
TMDB_LANGUAGE = "en-US"                 # Metadata language
```

### Subscription Profile
```python
SUBSCRIPTION_PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {
            "provider_names": ["Canal+"],
            "vpn_enabled": False,           # Blocks VPN
            "available_countries": ["FR"],
            "bundle_includes": ["HBO Max", "Apple TV+", "Paramount+"]
        },
        {
            "provider_names": ["Netflix"],
            "vpn_enabled": True,
            "available_countries": "all"
        }
    ],
    "vpn_country_priority": [
        "US", "GB", "CA", "AU", "NZ", "IE",  # English-speaking
        "DE", "ES", "IT", "NL", ...           # European
    ],
    "max_vpn_suggestions": 3
}
```

## Logging

Colored console output with configurable levels:
```python
LOG_LEVEL = "INFO"      # DEBUG/INFO/WARNING/ERROR/CRITICAL
LOG_TO_FILE = False     # Set True to log to output/scraper.log
```

Colors: DEBUG (cyan), INFO (green), WARNING (yellow), ERROR (red), CRITICAL (magenta)

## Key Features

### Scraping
- **Rate limiting**: Respects Letterboxd servers (2s delay)
- **Title parsing**: Extracts title and year from "Title (YYYY)"
- **Auto ID generation**: Deterministic hash from title+year
- **Dual source**: HTML for live data, CSV for exports

### Enrichment
- **TMDB integration**: Official API, 50 req/s limit
- **Global coverage**: 50+ countries automatically
- **Match confidence**: Scores how well TMDB result matches query
- **Retry logic**: Exponential backoff (3 attempts, 2s→4s→8s max)

### Watch Strategy
- **Fuzzy matching**: Handles provider name variations (80% similarity)
- **Bundle handling**: Recognizes Canal+ includes HBO Max/Apple TV+/Paramount+
- **VPN prioritization**: English-speaking countries first
- **Smart filtering**: Only shows your owned subscriptions
- **Tie handling**: Shows all equal-priority options

## Usage Examples

### Scrape and Save
```bash
python main.py
# Output: output/letterboxd_films_html_20250104_143022.json
```

### Find Streaming Options
```bash
# Single film
python enrich.py "Inception (2010)"

# Interactive mode
python enrich.py
```

### Python API
```python
from enrichers import TMDBEnricher, WatchStrategyAnalyzer
import config

with TMDBEnricher(api_key=config.TMDB_API_KEY) as enricher:
    result = enricher.enrich("The Matrix", 1999)

    analyzer = WatchStrategyAnalyzer(config.SUBSCRIPTION_PROFILE)
    strategy = analyzer.analyze(result)

    if strategy.best_option:
        print(f"Watch on {strategy.best_option.provider}")

    for opt in strategy.vpn_options:
        print(f"VPN to {opt.country_code}: {opt.provider}")
```

## Troubleshooting

**"TMDB API key not configured"**
→ Get free key at https://www.themoviedb.org/settings/api

**"No TMDB results"**
→ Add release year for better matching

**"CSV file not found"**
→ Export from Letterboxd: Settings → Import & Export → Export Your Data

**No VPN options shown**
→ Check that Netflix/Prime are in your `SUBSCRIPTION_PROFILE` with `vpn_enabled: True`

**Rate limit errors (429)**
→ Decrease `TMDB_RATE_LIMIT` in config.py

## Limitations

- **No language data**: TMDB doesn't provide audio/subtitle languages per offer
- **Title matching only**: Best results with year included
- **No caching yet**: Each query hits TMDB API (Phase 2 feature)
- **VPN detection**: Canal+ blocks VPN, hardcoded in config

## Future Features

- [ ] SQLite database integration
- [ ] Batch enrichment from watchlist JSON
- [ ] Results caching (7-day TTL)
- [ ] Language data from alternative APIs
- [ ] Web UI for browsing results
- [ ] Watched films tracking

## License

Personal use and educational purposes. Respect Letterboxd and TMDB Terms of Service.

---

**Quick Links**
- Letterboxd: https://letterboxd.com/
- TMDB API: https://www.themoviedb.org/settings/api
- TMDB Docs: https://developers.themoviedb.org/3
