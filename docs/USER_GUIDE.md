# ScreenSeeker User Guide

Complete guide to using ScreenSeeker for finding where to watch your films.

## Installation

### Requirements
- Python 3.14+
- TMDB API key (free)

### Install Dependencies

```bash
# Using Poetry (recommended)
poetry install

# Using pip
pip install -r requirements.txt
```

### Get TMDB API Key

1. Create account at [themoviedb.org](https://www.themoviedb.org/)
2. Go to [Settings → API](https://www.themoviedb.org/settings/api)
3. Request API key (choose "Developer")
4. Copy your key

### Configure

```bash
# Copy template
cp .env.example .env

# Edit .env
nano .env
```

Add your credentials:
```
TMDB_API_KEY=your_tmdb_api_key_here
LETTERBOXD_USERNAME=your_username
```

### Configure Subscriptions

Edit `config.py` to add your streaming services:

```python
SUBSCRIPTION_PROFILE = {
    "base_country": "FR",  # Your country
    "subscriptions": [
        {
            "provider_names": ["Netflix"],
            "vpn_enabled": True,
        },
        {
            "provider_names": ["Prime Video"],
            "vpn_enabled": True,
        },
        {
            "provider_names": ["Canal+"],
            "vpn_enabled": False,  # Blocks VPN
            "available_countries": ["FR"],
            "bundle_includes": ["HBO Max", "Apple TV+"],
        }
    ]
}
```

### Initialize Database

```bash
python cli.py db init
```

---

## Common Workflows

### 1. Find Where to Watch a Film

```bash
# Basic usage
python cli.py watch "The Matrix (1999)"

# With year separately
python cli.py watch "Inception" --year 2010

# Force refresh (ignore cache)
python cli.py watch "Arrival" --force
```

**Output shows:**
- ✅ Best option (no VPN needed)
- 🌍 VPN options (which country to connect to)
- 💰 Rent/buy alternatives

### 2. Import Your Watchlist

**Option A: CSV (Recommended)**

1. Export from Letterboxd:
   - Settings → Import & Export → Export Your Data
   - Download ZIP and extract `watchlist.csv`

2. Import:
```bash
python cli.py sync --method csv --csv-file watchlist.csv
```

**Option B: HTML Scraping**

```bash
# Set LETTERBOXD_USERNAME in .env first
python cli.py sync --method html
```

*Note: HTML is slower (2s per page) but always current*

### 3. Search Your Library

```bash
# Find films by title
python cli.py search matrix

# Limit results
python cli.py search "the" --limit 5
```

### 4. Mark Films as Watched

```bash
# Mark watched
python cli.py watched "The Matrix"

# Mark unwatched
python cli.py watched "The Matrix" --unwatch

# With year (if multiple matches)
python cli.py watched "Dune" --year 2021
```

### 5. Query by Provider

```bash
# All Netflix films
python cli.py providers --provider Netflix

# Netflix in specific country
python cli.py providers --provider Netflix --country FR

# Only subscription (not rentals)
python cli.py providers --provider Netflix --type flatrate
```

### 6. Generate Availability Report

```bash
# Report for all your subscriptions
python cli.py report
```

Shows what's available on each service in your base country.

### 7. Refresh Stale Data

```bash
# Refresh films >7 days old
python cli.py refresh

# Custom staleness threshold
python cli.py refresh --days 30

# Preview without changing
python cli.py refresh --dry-run

# Limit number refreshed
python cli.py refresh --limit 10
```

---

## Tips & Best Practices

### Performance

**Use Cache:** Cached queries are 250x faster
```bash
python cli.py watch "Film"          # Fast (uses cache)
python cli.py watch "Film" --force  # Slow (hits API)
```

**CSV vs HTML:** CSV import is much faster for large watchlists

### Accuracy

**Always include year** for better matching:
```bash
python cli.py watch "Dune (2021)"  # ✅ Good
python cli.py watch "Dune"          # ⚠️ May match wrong film
```

**Year mismatches are normal:** Festival dates vs. release dates often differ

### Organization

**Regular syncs:** Update watchlist weekly
```bash
python cli.py sync
```

**Track progress:** Mark films as watched
```bash
python cli.py watched "Film Title"
```

**Check stats:** Monitor your library
```bash
python cli.py db stats
```

---

## Troubleshooting

### "TMDB API key not configured"

**Cause:** Missing or invalid API key in `.env`

**Fix:**
1. Check `.env` file exists
2. Verify `TMDB_API_KEY=your_actual_key`
3. No quotes around the key

### "Film not found"

**Causes:**
- Film not in database yet
- Typo in title
- Year mismatch

**Fixes:**
```bash
# Enrich first
python cli.py watch "Film Title"

# Search for correct title
python cli.py search "title"

# Try without year
python cli.py watch "Film Title"
```

### "Rate limit exceeded (429)"

**Cause:** Too many TMDB API requests

**Fix:**
Decrease rate limit in `.env`:
```
TMDB_RATE_LIMIT=2.0
```

### Slow Performance

**Causes:**
- Using `--force` unnecessarily
- No cache data

**Fixes:**
- Remove `--force` flag
- Let cache populate naturally
- Use database queries instead: `search`, `providers`

### No VPN Options Shown

**Causes:**
- VPN not enabled in config
- Film only in base country

**Check:**
```python
# In config.py
{
    "provider_names": ["Netflix"],
    "vpn_enabled": True  # Must be True
}
```

---

## Advanced Features

### Custom VPN Priority

Edit `config.py`:
```python
"vpn_country_priority": [
    "US",      # Check US first
    "GB", "CA", # Then English-speaking
    "FR", "DE"  # Then European
]
```

### Bundle Configuration

If one subscription includes others:
```python
{
    "provider_names": ["Canal+"],
    "bundle_includes": ["HBO Max", "Apple TV+", "Paramount+"]
}
```

ScreenSeeker recognizes when films are available via bundles.

---

## FAQ

**Q: How often is streaming data refreshed?**
A: Default is 7 days. Use `--force` for immediate refresh.

**Q: Can I use multiple countries?**
A: Yes, set `available_countries: ["FR", "US", "GB"]` for providers

**Q: Does it work with Plex/Jellyfin?**
A: No, only commercial streaming services via TMDB

**Q: Can I export my data?**
A: Films are stored in SQLite (`data/screenseeker.db`). Use any SQLite tool.

**Q: How do I backup my database?**
```bash
cp data/screenseeker.db data/backup.db
```

**Q: Is my data shared?**
A: No. Everything is local. TMDB API is the only external call.

---

## Getting Help

- Check [CLI Reference](CLI_REFERENCE.md) for all commands
- Review [AUDIT.md](../AUDIT.md) for technical details
- Open an issue on GitHub

---

**Happy watching! 🎬**
