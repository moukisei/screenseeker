# Logging Guide

## Overview

The project uses a centralized logging system that provides colored, readable output in the terminal and optional file logging for debugging.

## Quick Start

### Using the Logger

In any module, import and get a logger:

```python
from logger import get_logger

logger = get_logger(__name__)

# Then use it
logger.debug("Detailed debug information")
logger.info("General information")
logger.warning("Warning message")
logger.error("Error occurred")
logger.critical("Critical failure")
```

### Configuration

Edit `config.py` to adjust logging behavior:

```python
LOG_LEVEL = "INFO"      # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_FILE = False     # Set to True to save logs to output/scraper.log
```

## Features

### 1. **Colored Console Output**

The logger uses ANSI colors for better readability:

- **DEBUG**: Cyan - Detailed diagnostic information
- **INFO**: Green - General informational messages
- **WARNING**: Yellow - Warning messages
- **ERROR**: Red - Error messages
- **CRITICAL**: Magenta - Critical failures

Example output:
```
INFO     screenseeker.main → Starting Letterboxd scraper...
INFO     HTMLScraper → Scraping page 1...
WARNING  models → Could not parse year from title: Untitled
ERROR    CSVScraper → CSV file not found: export.csv
```

### 2. **Hierarchical Logger Names**

All loggers are under the `screenseeker` namespace:

- `screenseeker.main` - Main application
- `screenseeker.models` - Data models
- `screenseeker.HTMLScraper` - HTML scraper
- `screenseeker.CSVScraper` - CSV scraper
- `screenseeker.json_exporter` - JSON exporter

This allows you to:
- Filter logs by module
- Control verbosity per component
- See exactly where each log message comes from

### 3. **File Logging (Optional)**

When `LOG_TO_FILE = True`, logs are saved to `output/scraper.log` with full timestamps:

```
2025-01-04 14:30:22 | INFO     | screenseeker.main | Starting Letterboxd scraper...
2025-01-04 14:30:23 | INFO     | HTMLScraper | Scraping page 1...
2025-01-04 14:30:25 | WARNING  | models | Could not parse year from title
```

File logs:
- Include timestamps for every message
- No colors (for better file parsing)
- Append mode (doesn't overwrite previous logs)
- UTF-8 encoding (supports all characters)

### 4. **Smart Color Detection**

Colors are automatically disabled when:
- Output is piped to a file: `python main.py > output.txt`
- Running in non-terminal environments
- Use `use_colors=False` in setup to force disable

## Best Practices

### 1. **Choose the Right Log Level**

```python
# DEBUG - Detailed diagnostic info (variables, state, flow)
logger.debug(f"Processing film: {film.title}, ID: {film.film_id}")

# INFO - General progress and status updates
logger.info(f"Successfully scraped {count} films from {pages} pages")

# WARNING - Something unexpected but recoverable
logger.warning(f"Could not parse year from title: {title}")

# ERROR - An error occurred but program can continue
logger.error(f"Failed to scrape page {page}: {error}")

# CRITICAL - Severe error, program may not be able to continue
logger.critical(f"Database connection lost, cannot continue")
```

### 2. **Include Context in Messages**

Bad:
```python
logger.error("Failed")
```

Good:
```python
logger.error(f"Failed to fetch page {page_num}: {error_msg}")
```

### 3. **Use f-strings for Formatting**

Modern and readable:
```python
logger.info(f"Scraped {film_count} films in {elapsed_time:.2f}s")
```

Avoid old-style formatting:
```python
logger.info("Scraped %d films in %.2f seconds" % (film_count, elapsed_time))
```

### 4. **Log Exceptions Properly**

Include stack traces for debugging:
```python
try:
    scrape_page()
except Exception as e:
    logger.error(f"Scraping failed: {e}", exc_info=True)
```

The `exc_info=True` parameter includes the full stack trace.

### 5. **Don't Over-Log**

- Don't log inside tight loops (every item in a list)
- Use DEBUG level for verbose output
- Aggregate information when possible

Bad (logs 10,000 times):
```python
for film in films:
    logger.info(f"Processing {film.title}")
```

Good (logs once):
```python
logger.info(f"Processing {len(films)} films...")
for film in films:
    process(film)
logger.info("Processing complete")
```

## Advanced Usage

### Custom Logger Setup

You can customize the logger programmatically:

```python
from logger import setup_logger

# Custom setup with file logging
setup_logger(
    name="screenseeker",
    level="DEBUG",
    log_to_file=True,
    log_file_path=Path("/custom/path/app.log"),
    use_colors=True
)
```

### Convenience Functions

For quick logging without getting a logger instance:

```python
from logger import info, warning, error

info("Quick info message")
warning("Quick warning")
error("Quick error")
```

### Module-Specific Loggers

Each module should get its own logger:

```python
# In scrapers/html_scraper.py
from logger import get_logger

logger = get_logger(__name__)  # Creates "screenseeker.html_scraper"
```

The `BaseScraper` class automatically creates loggers based on class name:
```python
self.logger = get_logger(self.__class__.__name__)  # e.g., "screenseeker.HTMLScraper"
```

## Troubleshooting

### No colored output

**Problem**: Logs appear without colors

**Solutions**:
- Check if output is being piped: `python main.py` (not `python main.py > file.txt`)
- Verify terminal supports ANSI colors
- Check `use_colors=True` in setup

### Logs not appearing

**Problem**: No log messages are shown

**Solutions**:
- Check `LOG_LEVEL` in config.py
- Ensure log level is appropriate (DEBUG shows more than INFO)
- Verify logger is set up before use

### Duplicate log messages

**Problem**: Each log message appears multiple times

**Solutions**:
- Don't call `setup_logger()` multiple times
- Call it once in main.py before any other imports use logging
- The logger clears existing handlers to prevent duplicates

## Log Level Hierarchy

Logs are hierarchical - setting a level shows that level and above:

```
DEBUG    → Shows: DEBUG, INFO, WARNING, ERROR, CRITICAL (everything)
INFO     → Shows: INFO, WARNING, ERROR, CRITICAL
WARNING  → Shows: WARNING, ERROR, CRITICAL
ERROR    → Shows: ERROR, CRITICAL
CRITICAL → Shows: CRITICAL only
```

## Examples

### Example 1: Basic Usage

```python
from logger import get_logger

logger = get_logger(__name__)

def scrape_page(page_num):
    logger.info(f"Scraping page {page_num}")

    try:
        # Scraping logic
        films = fetch_films(page_num)
        logger.debug(f"Found {len(films)} films on page {page_num}")
        return films
    except ConnectionError as e:
        logger.error(f"Connection failed for page {page_num}: {e}")
        return []
```

### Example 2: Progress Tracking

```python
from logger import get_logger

logger = get_logger(__name__)

def process_films(films):
    total = len(films)
    logger.info(f"Processing {total} films...")

    for i, film in enumerate(films, 1):
        if i % 10 == 0:  # Log every 10 films
            logger.debug(f"Progress: {i}/{total} films processed")

        process_film(film)

    logger.info(f"Successfully processed all {total} films")
```

### Example 3: Error Handling with Context

```python
from logger import get_logger

logger = get_logger(__name__)

def save_to_database(film):
    try:
        db.insert(film)
        logger.debug(f"Saved film: {film.title}")
    except DatabaseError as e:
        logger.error(
            f"Failed to save film '{film.title}' (ID: {film.film_id}): {e}",
            exc_info=True
        )
        raise
```

## Summary

- **One logger per module**: Use `get_logger(__name__)`
- **Configure once**: Call `setup_logger()` in main.py
- **Use appropriate levels**: DEBUG for details, INFO for progress, ERROR for failures
- **Include context**: Always explain what failed and why
- **Enable file logging**: Set `LOG_TO_FILE = True` for debugging
- **Enjoy readable output**: Colors make it easy to scan logs quickly!
