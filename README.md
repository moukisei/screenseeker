# ScreenSeeker 🎬

Find where to watch films from your Letterboxd watchlist with personalized recommendations based on your streaming subscriptions.

## Features

- **Personalized Recommendations** - Analyzes YOUR specific subscriptions (Netflix, Prime, Canal+, etc.)
- **VPN-Aware** - Suggests which countries to connect to for optimal streaming
- **Smart Caching** - 7-day local database cache for instant queries
- **Letterboxd Integration** - Import your watchlist via HTML scraping or CSV
- **Watch Tracking** - Mark films as watched and manage your progress

## Quick Start

### 1. Install

```bash
# Clone the repository
git clone https://github.com/moukisei/screenseeker.git
cd screenseeker

# Install the package (this makes the 'screenseeker' command available)
pip install -e .
# or with poetry
poetry install
```

### 2. Configure

Run the setup wizard — it walks you through everything interactively:

```bash
screenseeker config init
```

You will be prompted for:
- Your Letterboxd username (used to scrape your watchlist)
- Your base country (e.g. `FR`, `US`, `GB`)
- Your TMDB API key — get one free at [themoviedb.org](https://www.themoviedb.org/settings/api)
- Your streaming subscriptions (name, VPN availability, bundled services)

The config is saved to `~/.config/screenseeker/config.toml`.

### 3. Run

```bash
# Find where to watch a film
screenseeker watch "The Matrix (1999)"

# Sync your Letterboxd watchlist
screenseeker sync

# Search your library
screenseeker search matrix
```

## Example Output

```
🔍 Searching for: 'The Matrix' (1999)

================================================================================
HOW TO WATCH
================================================================================

🎯 TMDB Match: The Matrix (1999) - Confidence: exact
   ⭐ Rating: 8.7/10

✅ WATCH NOW (No VPN needed):
   Netflix - France

🌍 VPN OPTIONS:
   Netflix - Connect to United States
   Netflix - Connect to United Kingdom
```

## Configuration

### Subscription profile

```bash
screenseeker config init          # First-time interactive setup
screenseeker config show          # Display current config
screenseeker config add           # Add a subscription (guided prompts)
screenseeker config remove NAME   # Remove a subscription
screenseeker config set-country CODE  # Change your base country (e.g. US)
screenseeker config edit          # Open config file in $EDITOR
```

The config file lives at `~/.config/screenseeker/config.toml`:

```toml
[tmdb]
api_key = "your_api_key_here"
rate_limit = 5.0
language = "en-US"

[profile]
base_country = "FR"
max_vpn_suggestions = 3
vpn_country_priority = ["US", "GB", "CA", ...]

[[profile.subscriptions]]
provider_names = ["Netflix"]
vpn_enabled = true
available_countries = "all"

[[profile.subscriptions]]
provider_names = ["Canal+", "Canal Plus"]
vpn_enabled = false
available_countries = ["FR"]
bundle_includes = ["HBO Max", "Apple TV+"]
```

### Scraper & logging settings

These are optional and can be overridden via shell environment variables:

```bash
LOG_LEVEL=DEBUG screenseeker watch "Inception"
OUTPUT_DIR=/tmp/screenseeker screenseeker sync
```

## Project Structure

```
screenseeker/
├── src/screenseeker/
│   ├── cli.py              # Main CLI interface
│   ├── config.py           # Low-level defaults (scraper, logging)
│   ├── user_config.py      # Config file management (~/.config/screenseeker/)
│   ├── database/           # SQLAlchemy ORM & queries
│   ├── enrichers/          # TMDB API & watch strategy
│   ├── scrapers/           # Letterboxd HTML/CSV import
│   └── exporters/          # JSON export
└── tests/                  # Test suite (mirrors src/ structure)
```

## Requirements

- Python 3.14+
- TMDB API key (free at [themoviedb.org](https://www.themoviedb.org/settings/api))
- Optional: Letterboxd account for watchlist import

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/screenseeker --cov-report=html

# Run specific test file
pytest tests/database/test_database.py -v
```

## Troubleshooting

**"No config file found"**
→ Run `screenseeker config init` to create your config

**"TMDB API key not configured"**
→ Run `screenseeker config init` or set `api_key` in `~/.config/screenseeker/config.toml`

**"Film not found"**
→ Try adding the year: `screenseeker watch "Dune" --year 2021`

**"No films found"**
→ Run `screenseeker sync` first to import your watchlist

## Contributing

1. Fork the repository
2. Create a feature branch
3. Install pre-commit hooks: `pre-commit install`
4. Make your changes (pre-commit will run automatically)
5. Add tests
6. Submit a pull request

### Pre-commit Hooks

This project uses pre-commit hooks to maintain code quality:
- **Ruff**: Fast linting and formatting
- **isort**: Import sorting
- **mypy**: Static type checking
- **Bandit**: Security checks

Run manually: `pre-commit run --all-files`

## License

Apache 2.0 — see [LICENSE](LICENSE) file for details.

## Links

- TMDB API: https://www.themoviedb.org/settings/api
- Letterboxd: https://letterboxd.com/

---

**Made with ❤️ for cinephiles who want to actually watch their watchlist**
