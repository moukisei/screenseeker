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
git clone https://github.com/yourusername/screenseeker.git
cd screenseeker

# Install dependencies
poetry install
# or
pip install -r requirements.txt

# (Optional) Set up pre-commit hooks for development
pre-commit install
```

### 2. Configure

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your TMDB API key
# Get free key at: https://www.themoviedb.org/settings/api
nano .env
```

**Required in `.env`:**
```
TMDB_API_KEY=your_api_key_here
LETTERBOXD_USERNAME=your_username
```

### 3. Run

```bash
# Find where to watch a film
python cli.py watch "The Matrix (1999)"

# Sync your Letterboxd watchlist
python cli.py sync

# Search your library
python cli.py search matrix
```

## Example Output

```
🔍 Searching for: 'The Matrix' (1999)
```
================================================================================
HOW TO WATCH
================================================================================

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** - Complete usage guide
- **[CLI Reference](docs/CLI_REFERENCE.md)** - All commands and options
- **[Development Guide](docs/DEVELOPMENT.md)** - Contributing and architecture
- **[Technical Audit](AUDIT.md)** - Codebase analysis and recommendations

## Project Structure

```
screenseeker/
├── cli.py              # Main CLI interface
├── config.py           # Configuration (uses .env)
├── database/           # SQLAlchemy ORM & queries
├── enrichers/          # TMDB API & watch strategy
├── scrapers/           # Letterboxd HTML/CSV import
├── exporters/          # JSON export
└── tests/              # Test suite
```

## Configuration

Edit `.env` to customize:

```bash
# TMDB Settings
TMDB_API_KEY=your_key
TMDB_RATE_LIMIT=5.0
TMDB_LANGUAGE=en-US

# Letterboxd
LETTERBOXD_USERNAME=your_username

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=False
```

Edit `config.py` for subscription profile:

Colored console output with configurable levels:
```python
SUBSCRIPTION_PROFILE = {
    "base_country": "FR",
    "subscriptions": [
        {
            "provider_names": ["Netflix"],
            "vpn_enabled": True,
        },
        {
            "provider_names": ["Canal+"],
            "vpn_enabled": False,
            "bundle_includes": ["HBO Max", "Apple TV+"],
        }
    ]
}
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
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_database_queries.py -v
```

    if strategy.best_option:
        print(f"Watch on {strategy.best_option.provider}")

**"TMDB API key not configured"**
→ Set `TMDB_API_KEY` in your `.env` file

**"Film not found"**
→ Try adding the year: `python cli.py watch "Dune" --year 2021`

**"No films found"**
→ Run `python cli.py sync` first to import your watchlist

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

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for details.

## Limitations

MIT License - see LICENSE file for details

## Links

- TMDB API: https://www.themoviedb.org/settings/api
- Letterboxd: https://letterboxd.com/

---

**Made with ❤️ for cinephiles who want to actually watch their watchlist**
