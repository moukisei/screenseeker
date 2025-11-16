# CLI Reference

Quick reference for all ScreenSeeker commands.

## Global Options

```bash
--help     # Show help
--version  # Show version
```

---

## Commands

### watch
Find where to watch a film with personalized recommendations

```bash
python cli.py watch [TITLE] [OPTIONS]
```

**Options:**
- `-y, --year` - Release year
- `-f, --force` - Force refresh (ignore cache)

**Examples:**
```bash
python cli.py watch "The Matrix (1999)"
python cli.py watch "Inception" --year 2010
python cli.py watch "Arrival" --force
```

---

### sync
Import Letterboxd watchlist to database

```bash
python cli.py sync [OPTIONS]
```

**Options:**
- `-m, --method` - Scraping method: `html` or `csv`
- `-c, --csv-file` - Path to CSV file
- `--save-json / --no-save-json` - Save to JSON (default: yes)

**Examples:**
```bash
python cli.py sync
python cli.py sync --method csv --csv-file watchlist.csv
python cli.py sync --method html
```

---

### search
Search films in database by title

```bash
python cli.py search QUERY [OPTIONS]
```

**Options:**
- `-l, --limit` - Max results (default: 10)

**Examples:**
```bash
python cli.py search matrix
python cli.py search "blade" --limit 5
```

---

### watchlist
Show unwatched films

```bash
python cli.py watchlist [OPTIONS]
```

**Options:**
- `--list` - Show full list (default)
- `--count` - Show count only

**Examples:**
```bash
python cli.py watchlist
python cli.py watchlist --count
```

---

### watched
Mark film as watched or unwatched

```bash
python cli.py watched TITLE [OPTIONS]
```

**Options:**
- `-y, --year` - Release year
- `--unwatch` - Mark as unwatched

**Examples:**
```bash
python cli.py watched "The Matrix"
python cli.py watched "Dune" --year 2021
python cli.py watched "The Matrix" --unwatch
```

---

### providers
List films by streaming provider

```bash
python cli.py providers [OPTIONS]
```

**Options:**
- `-p, --provider` - Provider name (required)
- `-c, --country` - Country code (e.g., "FR", "US")
- `-t, --type` - Type: `flatrate`, `rent`, `buy`, `free`, `ads`
- `-l, --limit` - Max results

**Examples:**
```bash
python cli.py providers --provider Netflix
python cli.py providers --provider Netflix --country FR
python cli.py providers --provider "Prime Video" --type flatrate
```

---

### country
List films by country

```bash
python cli.py country [OPTIONS]
```

**Options:**
- `-c, --country` - Country code (required)
- `-t, --type` - Monetization type

**Examples:**
```bash
python cli.py country --country FR
python cli.py country --country US --type flatrate
```

---

### refresh
Refresh stale streaming data

```bash
python cli.py refresh [OPTIONS]
```

**Options:**
- `-d, --days` - Staleness threshold (default: 7)
- `-l, --limit` - Max films to refresh
- `--dry-run` - Preview without changing

**Examples:**
```bash
python cli.py refresh
python cli.py refresh --days 30 --limit 10
python cli.py refresh --dry-run
```

---

### report
Generate availability report

```bash
python cli.py report [OPTIONS]
```

**Options:**
- `-p, --provider` - Specific providers (repeatable)

**Examples:**
```bash
python cli.py report
python cli.py report --provider Netflix --provider "Prime Video"
```

---

## Database Commands

### db init
Initialize database

```bash
python cli.py db init [OPTIONS]
```

**Options:**
- `--reset` - Delete all data and reset

**Examples:**
```bash
python cli.py db init
python cli.py db init --reset  # ⚠️ Deletes everything
```

---

### db stats
Show database statistics

```bash
python cli.py db stats
```

**Example:**
```bash
python cli.py db stats
```

---

### db import-json
Import films from JSON files

```bash
python cli.py db import-json [PATH] [OPTIONS]
```

**Options:**
- `--all` - Import all JSON files from output/

**Examples:**
```bash
python cli.py db import-json --all
python cli.py db import-json output/letterboxd_films_20251110.json
```

---

## Monetization Types

- `flatrate` - Subscription streaming
- `rent` - Temporary rental
- `buy` - Permanent purchase
- `free` - Free with ads/registration
- `ads` - Ad-supported

---

## Country Codes

Use ISO 3166-1 alpha-2 codes:
- `US` - United States
- `GB` - United Kingdom
- `FR` - France
- `DE` - Germany
- `CA` - Canada
- `JP` - Japan

Full list: https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2

---

## Exit Codes

- `0` - Success
- `1` - Error

---

## Tips

**Aliases:** Add to `.bashrc` or `.zshrc`:
```bash
alias ss='python /path/to/cli.py'
alias ssw='python /path/to/cli.py watch'
```

**Shell Completion:** Generate with:
```bash
python cli.py --help > screenseeker-help.txt
```

---

For detailed usage, see [USER_GUIDE.md](USER_GUIDE.md)
