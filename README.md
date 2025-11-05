# ScreenSeeker - Letterboxd Scraper

A professional Python scraper for extracting and managing film data from Letterboxd watchlists. Supports both HTML web scraping and CSV export parsing with a clean, modular architecture.

## Features

- **Dual Scraping Methods**
  - HTML scraping: Automatically paginate through Letterboxd watchlist pages
  - CSV parsing: Process official Letterboxd export files

- **Smart Data Parsing**
  - Automatic title and year extraction from various formats
  - Unique film ID generation from Letterboxd URIs
  - Handles missing or malformed data gracefully

- **Professional Architecture**
  - Pydantic models for data validation
  - Abstract base classes for extensibility
  - Modular design with separation of concerns
  - Type hints throughout

- **Data Export**
  - JSON export with metadata (timestamps, source info, statistics)
  - Optional raw HTML archiving for analysis
  - Timestamped output files

- **Configuration-Based**
  - User preference selection (HTML vs CSV)
  - Configurable delays and timeouts
  - Flexible output options

## Installation

### Prerequisites
- Python 3.10+
- Poetry (recommended) or pip

### Using Poetry

```bash
# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Using pip

```bash
# Install dependencies
pip install -r requirements.txt
```

### Required Dependencies

- `requests` - HTTP requests for web scraping
- `beautifulsoup4` - HTML parsing
- `pydantic` - Data validation and models
- `lxml` - XML/HTML parser (recommended for BeautifulSoup)

## Configuration

Edit `config.py` to customize scraper behavior:

```python
# User Configuration
USERNAME = "your_letterboxd_username"

# Scraper Configuration
SCRAPER_TYPE = "html"  # Options: "html" or "csv"
CSV_FILE_PATH = "./letterboxd_export.csv"  # Used when SCRAPER_TYPE="csv"

# Output Configuration
OUTPUT_DIR = Path("./output")
SAVE_RAW_DATA = True  # Save raw HTML or CSV for analysis

# HTML Scraper Settings
HTML_DELAY_BETWEEN_REQUESTS = 2.0  # Seconds (be respectful!)
HTML_TIMEOUT = 10  # Request timeout in seconds

# Logging Configuration
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Usage

### HTML Scraping (Default)

Scrape directly from a Letterboxd watchlist:

```bash
# 1. Set your username in config.py
USERNAME = "your_username"

# 2. Set scraper type
SCRAPER_TYPE = "html"

# 3. Run the scraper
python main.py
```

### CSV Parsing

Parse an official Letterboxd export file:

```bash
# 1. Export your data from Letterboxd:
#    Settings → Import & Export → Export Your Data

# 2. Update config.py
SCRAPER_TYPE = "csv"
CSV_FILE_PATH = "./path/to/watchlist.csv"

# 3. Run the scraper
python main.py
```

## Output Structure

```
output/
├── letterboxd_films_html_20250104_143022.json
├── letterboxd_films_csv_20250104_150000.json
└── raw_html/
    └── 20250104_143022/
        ├── page_0001.html
        ├── page_0002.html
        └── ...
```

### JSON Output Format

```json
{
  "scraped_at": "2025-01-04T14:30:22.123456",
  "source": "html",
  "total_films": 245,
  "total_pages_scraped": 5,
  "success": true,
  "error_message": null,
  "films": [
    {
      "film_id": "the-matrix",
      "film_full_title": "The Matrix (1999)",
      "film_title": "The Matrix",
      "year": 1999,
      "letterboxd_uri": "https://letterboxd.com/film/the-matrix/",
      "date_added": "2024-12-15"
    }
  ]
}
```

## Project Structure

```
screenseeker/
├── models.py                    # Pydantic data models
│   ├── Film                     # Film data model
│   └── ScrapingResult           # Result container
│
├── scrapers/                    # Scraper implementations
│   ├── __init__.py             # Package exports
│   ├── base.py                 # Abstract base scraper
│   ├── html_scraper.py         # HTML web scraper
│   └── csv_scraper.py          # CSV parser
│
├── exporters/                   # Export functionality
│   ├── __init__.py             # Package exports
│   └── json_exporter.py        # JSON export
│
├── config.py                    # Configuration settings
├── main.py                      # Entry point & orchestration
└── README.md                    # This file
```

## How It Works

### HTML Scraping Flow

1. **Initialization**: `HTMLScraper` connects to Letterboxd with appropriate headers
2. **Pagination**: Iterates through pages (`/page/1/`, `/page/2/`, etc.)
3. **Parsing**: Extracts film data from HTML grid items using BeautifulSoup
4. **Data Creation**: Creates `Film` objects with parsed title and year
5. **Export**: Saves results to timestamped JSON file

### CSV Parsing Flow

1. **Validation**: Checks CSV file exists and has required columns
2. **Reading**: Uses `csv.DictReader` for column-based parsing
3. **ID Extraction**: Extracts film slug from Letterboxd URI
4. **Data Creation**: Creates `Film` objects from CSV rows
5. **Export**: Saves results to timestamped JSON file

### Film ID Generation

- **HTML**: Uses the `data-film-id` attribute from the page
- **CSV**: Extracts slug from Letterboxd URI
  - Input: `https://letterboxd.com/film/the-matrix/`
  - Output: `the-matrix`

## Data Models

### Film

```python
Film(
    film_id: str                    # Unique identifier (slug)
    film_full_title: str            # "The Matrix (1999)"
    film_title: str                 # "The Matrix"
    year: Optional[int]             # 1999
    letterboxd_uri: Optional[str]   # Full URL (CSV only)
    date_added: Optional[str]       # Date added to watchlist (CSV only)
)
```

### ScrapingResult

```python
ScrapingResult(
    films: list[Film]               # List of scraped films
    total_pages_scraped: int        # Number of pages processed
    success: bool                   # Whether scraping succeeded
    error_message: Optional[str]    # Error details if failed
    source: str                     # "html" or "csv"
)
```

## Extending the Project

### Adding a New Scraper

1. Create a new file in `scrapers/` (e.g., `api_scraper.py`)
2. Inherit from `BaseScraper`
3. Implement the `scrape()` method
4. Return a `ScrapingResult` object
5. Add to `scrapers/__init__.py`
6. Update config options

```python
from scrapers.base import BaseScraper
from models import Film, ScrapingResult

class APIScraper(BaseScraper):
    def scrape(self) -> ScrapingResult:
        # Your implementation
        return ScrapingResult(
            films=films,
            success=True,
            source="api"
        )
```

### Adding a New Exporter

1. Create a new file in `exporters/` (e.g., `csv_exporter.py`)
2. Implement export logic
3. Add to `exporters/__init__.py`

## Error Handling

The scraper handles various error scenarios:

- **Network errors**: Timeouts, connection issues
- **Parsing errors**: Missing data, malformed HTML/CSV
- **File errors**: Missing CSV files, permission issues
- **Validation errors**: Invalid data that doesn't meet Pydantic constraints

All errors are logged with appropriate detail levels.

## Best Practices

### When Using HTML Scraper

- Set reasonable delays (2+ seconds) to avoid rate limiting
- Use `SAVE_RAW_DATA=True` for debugging or later analysis
- Respect Letterboxd's servers - don't run repeatedly

### When Using CSV Parser

- Export fresh data from Letterboxd regularly
- Verify CSV has required columns: `Name`, `Year`, `Letterboxd URI`
- Optional `Date` column will be preserved if present

## Troubleshooting

### "CSV file not found"
- Check `CSV_FILE_PATH` in `config.py`
- Verify file exists at specified path
- Use absolute path if relative path fails

### "Missing required columns in CSV"
- Ensure CSV is from Letterboxd export (not manually created)
- Check column names match exactly: `Name`, `Year`, `Letterboxd URI`

### "Received status code 404"
- Verify `USERNAME` in `config.py` is correct
- Check that the watchlist is public (not private)
- Try accessing the URL in a browser first

### No films found
- Watchlist may be empty or private
- HTML structure may have changed (update selectors)
- Check logs for specific error messages

## Future Enhancements

Potential features for future development:

- [ ] SQLite database integration for persistent storage
- [ ] Multiple watchlist support (different users)
- [ ] Film metadata enrichment (TMDB/IMDB integration)
- [ ] Watched films scraping (not just watchlist)
- [ ] Diary entries and reviews extraction
- [ ] Duplicate detection and merging
- [ ] Data analytics and visualization
- [ ] CLI arguments for runtime configuration
- [ ] Async/parallel scraping for better performance

## License

This project is for personal use and educational purposes. Please respect Letterboxd's Terms of Service and use responsibly.

## Contributing

This is a personal project, but suggestions and improvements are welcome!

## Acknowledgments

- Built with [Pydantic](https://pydantic-docs.helpmanual.io/) for data validation
- Powered by [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) for HTML parsing
- Data sourced from [Letterboxd](https://letterboxd.com/)

---

**Note**: This is an unofficial tool and is not affiliated with Letterboxd. Please use responsibly and respect the platform's resources.