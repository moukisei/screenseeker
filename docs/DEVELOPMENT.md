# Development Guide

Guide for contributing to ScreenSeeker.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                            │
│                         (cli.py)                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────┬──────────────┬──────────────┬────────────────┐
│  Scrapers   │  Enrichers   │   Database   │   Exporters    │
├─────────────┼──────────────┼──────────────┼────────────────┤
│ HTMLScraper │ TMDBEnricher │ SQLAlchemy   │ JSONExporter   │
│ CSVScraper  │ WatchStrategy│ ORM Models   │                │
└─────────────┴──────────────┴──────────────┴────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   SQLite DB      │
                    └──────────────────┘
```

### Layer Responsibilities

**CLI Layer (`cli.py`)**
- User interface
- Input validation
- Output formatting
- Error handling

**Scrapers (`scrapers/`)**
- Letterboxd data acquisition
- HTML parsing or CSV import
- Data normalization

**Enrichers (`enrichers/`)**
- TMDB API integration
- Streaming availability lookup
- Personalized watch strategy

**Database (`database/`)**
- Data persistence (SQLite)
- Query optimization
- Caching logic

**Exporters (`exporters/`)**
- JSON export
- Data serialization

---

## Project Structure

```
screenseeker/
├── cli.py                      # Click-based CLI
├── config.py                   # Configuration (loads .env)
├── models.py                   # Pydantic models (scrapers)
├── logger.py                   # Colored logging
├── exceptions.py               # Custom exceptions
│
├── database/
│   ├── models.py              # SQLAlchemy ORM models
│   ├── queries.py             # Query helpers
│   ├── service.py             # Business logic
│   ├── session.py             # Session management
│   └── init_db.py             # Database initialization
│
├── enrichers/
│   ├── tmdb_enricher.py       # TMDB API client
│   ├── watch_strategy.py      # Recommendation engine
│   ├── enrichment_models.py   # Pydantic models
│   └── base.py                # Abstract base
│
├── scrapers/
│   ├── html_scraper.py        # Live Letterboxd scraping
│   ├── csv_scraper.py         # CSV import
│   └── base.py                # Abstract base
│
├── exporters/
│   └── json_exporter.py       # JSON export
│
└── tests/
    ├── conftest.py            # Pytest fixtures
    └── test_*.py              # Test modules
```

---

## Development Setup

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/screenseeker.git
cd screenseeker

# Install with dev dependencies
poetry install

# Or with pip
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your TMDB API key
```

### 3. Initialize Database

```bash
python cli.py db init
```

### 4. Run Tests

```bash
pytest
```

---

## Database Schema

### Films Table

```sql
CREATE TABLE films (
    id INTEGER PRIMARY KEY,
    letterboxd_title TEXT NOT NULL,
    letterboxd_year INTEGER,
    tmdb_id INTEGER UNIQUE,        -- Canonical identifier
    tmdb_title TEXT,
    tmdb_year INTEGER,
    match_confidence TEXT,          -- exact/high/medium/low/none
    year_mismatch BOOLEAN,
    watched BOOLEAN DEFAULT FALSE,
    last_checked DATETIME,          -- For cache staleness
    ...
);
```

### StreamingOffers Table

```sql
CREATE TABLE streaming_offers (
    id INTEGER PRIMARY KEY,
    film_id INTEGER REFERENCES films(id) ON DELETE CASCADE,
    country_code TEXT(2),
    provider_name TEXT,
    monetization_type TEXT,        -- flatrate/rent/buy/free/ads
    checked_at DATETIME,
    ...
);
```

**Key Design Decisions:**

1. **TMDB ID as canonical** - Prevents duplicates across sources
2. **Year mismatch handling** - Stores both Letterboxd and TMDB years
3. **Cascade deletes** - Cleaning up orphaned streaming offers
4. **Indexed queries** - `tmdb_id`, `(letterboxd_title, letterboxd_year)`, `last_checked`

---

## Code Style

### Tools

- **Ruff** - Fast linter
- **Black** - Code formatter
- **mypy** - Type checking

```bash
# Run linter
ruff check .

# Format code
black .

# Type check
mypy .
```

### Conventions

**Type Hints:**
```python
def get_film(session: Session, title: str, year: int | None) -> Film | None:
    ...
```

**Pydantic for Validation:**
```python
class Film(BaseModel):
    film_title: str = Field(..., description="Film title")
    year: Optional[int] = None
```

**Context Managers:**
```python
with get_session() as session:
    # Session auto-commits on success, rolls back on error
```

**Logging:**
```python
from logger import get_logger
logger = get_logger(__name__)
logger.info("Message")
```

---

## Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific file
pytest tests/test_database_queries.py -v

# Single test
pytest tests/test_database_queries.py::TestGetOrCreateFilm::test_creates_new_film
```

### Writing Tests

Tests use in-memory SQLite:

```python
def test_something(test_session):
    # test_session is a fixture from conftest.py
    film, created = get_or_create_film(test_session, "Test", 2020)
    assert created is True
```

**Test Structure:**
- `conftest.py` - Shared fixtures
- `test_*.py` - Test modules
- Group related tests in classes

---

## Contributing

### 1. Create Branch

```bash
git checkout -b feature/your-feature
```

### 2. Make Changes

- Write tests first (TDD)
- Follow code style
- Update documentation

### 3. Run Checks

```bash
# Tests
pytest

# Linting
ruff check .

# Format
black .
```

### 4. Commit

```bash
git add .
git commit -m "feat: add feature description"
```

**Commit Format:**
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `test:` - Tests
- `refactor:` - Code refactoring

### 5. Push & PR

```bash
git push origin feature/your-feature
```

Open pull request on GitHub with:
- Clear description
- Tests passing
- Documentation updated

---

## Key Design Patterns

### Service Layer Pattern

Business logic in `database/service.py`:

```python
def enrich_and_save_film(
    session: Session,
    enricher: TMDBEnricher,
    title: str,
    year: int | None,
    force_refresh: bool = False
) -> tuple[Film, EnrichmentResult]:
    # Combines enrichment + database logic
    ...
```

### Repository Pattern

Query helpers in `database/queries.py`:

```python
def get_film_by_title_year(session: Session, title: str, year: int | None) -> Film | None:
    # Encapsulates query logic
    ...
```

### Strategy Pattern

Watch strategy analysis in `enrichers/watch_strategy.py`:

```python
class WatchStrategyAnalyzer:
    def analyze(self, enrichment: EnrichmentResult) -> WatchStrategy:
        # Personalizes recommendations
        ...
```

---

## Adding Features

### Add New Scraper

1. Extend `scrapers/base.py`
2. Implement `scrape()` method
3. Return `ScrapingResult`
4. Add to `create_scraper()` in `cli.py`

### Add New Provider

1. Update `config.SUBSCRIPTION_PROFILE`
2. Add to `bundle_includes` if part of bundle
3. Test with `python cli.py providers --provider "New Provider"`

### Add New Command

1. Add function to `cli.py` with `@cli.command()` decorator
2. Use Click options for parameters
3. Follow existing error handling pattern
4. Update `docs/CLI_REFERENCE.md`

---

## Debugging

### Enable Debug Logging

```bash
# In .env
LOG_LEVEL=DEBUG
```

### Database Inspection

```bash
# SQLite CLI
sqlite3 data/screenseeker.db

# Show tables
.tables

# Query
SELECT * FROM films LIMIT 5;
```

### API Debugging

Set breakpoint in `enrichers/tmdb_enricher.py`:

```python
import pdb; pdb.set_trace()
```

---

## Resources

- **TMDB API Docs:** https://developers.themoviedb.org/3
- **SQLAlchemy:** https://docs.sqlalchemy.org/
- **Click:** https://click.palletsprojects.com/
- **Pydantic:** https://docs.pydantic.dev/

---

For technical audit and recommendations, see [AUDIT.md](../AUDIT.md)
