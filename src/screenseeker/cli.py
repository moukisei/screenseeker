# Copyright 2025 Mouktar ABDILLAHI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
ScreenSeeker CLI - Find where to watch films from your Letterboxd watchlist.

A comprehensive CLI for managing your film watchlist, finding streaming availability,
and tracking what you've watched.
"""

import sys
from datetime import datetime
from pathlib import Path

import click

from . import config
from .database import get_session, init_db
from .database.models import Film
from .database.queries import (
    get_database_stats,
    get_film_by_title_year,
    get_films_by_country,
    get_films_by_provider,
    get_stale_films,
    get_unwatched_films,
    mark_film_watched,
    search_films_by_title,
)
from .database.service import enrich_and_save_film
from .database.session import get_database_info, reset_database
from .enrichers import TMDBEnricher, WatchStrategyAnalyzer
from .exporters import JSONExporter
from .logger import get_logger, setup_logger
from .scrapers import CSVScraper, HTMLScraper

# Set up logging
setup_logger(level=config.LOG_LEVEL, log_to_file=config.LOG_TO_FILE, use_colors=True)
logger = get_logger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="screenseeker")
def cli():
    """
    ScreenSeeker - Find where to watch films from your Letterboxd watchlist.

    \b
    🎬 Use Cases:
      • Find where to watch any film with personalized recommendations
      • Scrape your Letterboxd watchlist
      • Build a personal film database with streaming data
      • Query films by provider, country, or title
      • Track watched status and add notes
      • Generate statistics and reports

    \b
    Examples:
      screenseeker watch "The Matrix (1999)"
      screenseeker sync
      screenseeker search matrix
      screenseeker providers --provider Netflix --country FR

    Use 'screenseeker COMMAND --help' for more information on a command.
    """
    pass


# ==============================================================================
# USE CASE 1: Find Where to Watch a Film
# ==============================================================================


@cli.command()
@click.argument("title", required=False)
@click.option("--year", "-y", type=int, help="Release year")
@click.option("--force", "-f", is_flag=True, help="Force refresh (ignore cache)")
def watch(title, year, force):
    """
    Find where to watch a film with personalized recommendations.

    Data is fetched from TMDB and saved to the database for future queries.

    \b
    Examples:
      screenseeker watch "The Matrix (1999)"
      screenseeker watch "Inception" --year 2010
      screenseeker watch "Arrival" --force  # Force refresh

    If no title provided, enters interactive mode.
    """
    # Initialize database
    init_db()

    # Get input
    if not title:
        try:
            title = click.prompt("Enter film title (with optional year)", type=str)
        except (click.Abort, EOFError):
            click.echo("\nCancelled")
            return

    # Parse title/year if in format "Title (Year)"
    if not year and "(" in title and title.endswith(")"):
        import re

        match = re.match(r"^(.+?)\s*\((\d{4})\)$", title.strip())
        if match:
            title = match.group(1).strip()
            year = int(match.group(2))

    click.echo(f"🔍 Searching for: '{title}' ({year or 'no year specified'})")

    # Check TMDB API key
    if not config.TMDB_API_KEY or config.TMDB_API_KEY == "your_tmdb_api_key_here":
        click.secho("❌ TMDB API key not configured!", fg="red", bold=True)
        click.echo("\nPlease set TMDB_API_KEY in your .env file:")
        click.echo("  1. Copy .env.example to .env")
        click.echo("  2. Get your free API key at: https://www.themoviedb.org/settings/api")
        click.echo("  3. Add it to .env: TMDB_API_KEY=your_key_here")
        sys.exit(1)

    try:
        with TMDBEnricher(
            api_key=config.TMDB_API_KEY,
            rate_limit_per_second=config.TMDB_RATE_LIMIT,
            language=config.TMDB_LANGUAGE,
        ) as enricher:
            with get_session() as session:
                # Enrich and save to database
                film, result = enrich_and_save_film(
                    session, enricher, title, year, force_refresh=force
                )

                # Log cache info
                if film.last_checked:
                    age = datetime.utcnow() - film.last_checked
                    if age.total_seconds() < 60:
                        click.secho("📊 Data freshly fetched from TMDB", fg="green")
                    else:
                        days = age.days
                        click.echo(
                            f"📊 Using cached data ({days} day{'s' if days != 1 else ''} old)"
                        )

                # Analyze with watch strategy
                analyzer = WatchStrategyAnalyzer(config.SUBSCRIPTION_PROFILE)
                strategy = analyzer.analyze(result)

                # Display results
                _display_watch_strategy(result, strategy)

                # Show year mismatch note
                if film.year_mismatch:
                    click.secho(
                        f"\n📅 Note: Year mismatch - "
                        f"Letterboxd: {film.letterboxd_year}, TMDB: {film.tmdb_year}",
                        fg="yellow",
                    )

    except KeyboardInterrupt:
        click.echo("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        click.secho(f"❌ Error: {e}", fg="red")
        click.echo("\nFor more details, run with LOG_LEVEL=DEBUG in your .env file")
        if config.LOG_LEVEL == "DEBUG":
            import traceback

            click.echo("\nFull traceback:")
            click.echo(traceback.format_exc())
        sys.exit(1)


# ==============================================================================
# USE CASE 2: Scrape Letterboxd Watchlist
# ==============================================================================


@cli.command()
@click.option(
    "--method",
    "-m",
    type=click.Choice(["html", "csv"]),
    help="Scraping method (overrides config)",
)
@click.option("--csv-file", "-c", type=click.Path(exists=True), help="Path to CSV export file")
@click.option("--save-json/--no-save-json", default=True, help="Save result to JSON")
def sync(method, csv_file, save_json):
    """
    Scrape your Letterboxd watchlist and save to database.

    \b
    Methods:
      html  - Scrape live from Letterboxd.com (respects rate limits)
      csv   - Import from Letterboxd CSV export (faster)

    \b
    Examples:
      screenseeker sync                    # Use config.py settings
      screenseeker sync --method html      # Force HTML scraping
      screenseeker sync --method csv --csv-file watchlist.csv

    The scraped films are automatically saved to the database.
    """
    # Determine scraping method
    scraper_type = method or config.SCRAPER_TYPE

    # Create scraper
    if scraper_type.lower() == "html":
        click.echo(f"📡 Scraping {config.USERNAME}'s watchlist from Letterboxd...")
        scraper = HTMLScraper(
            base_url=config.HTML_URL,
            delay_between_requests=config.HTML_DELAY_BETWEEN_REQUESTS,
            timeout=config.HTML_TIMEOUT,
            save_raw_data=config.SAVE_RAW_DATA,
            output_dir=config.OUTPUT_DIR,
        )
    elif scraper_type.lower() == "csv":
        csv_path = csv_file or config.CSV_FILE_PATH
        click.echo(f"📄 Importing watchlist from CSV: {csv_path}")
        scraper = CSVScraper(
            csv_file_path=csv_path,
            save_raw_data=config.SAVE_RAW_DATA,
            output_dir=config.OUTPUT_DIR,
        )
    else:
        click.secho(f"❌ Invalid scraper type: {scraper_type}", fg="red")
        sys.exit(1)

    # Initialize database
    init_db()

    try:
        with scraper:
            # Scrape
            result = scraper.scrape()

            if not result.success:
                click.secho(f"❌ Scraping failed: {result.error_message}", fg="red")
                sys.exit(1)

            if result.film_count == 0:
                click.secho("⚠️  No films found", fg="yellow")
                return

            # Display summary
            click.secho(f"\n✅ Scraped {result.film_count} films", fg="green", bold=True)

            # Save to database
            click.echo("\n💾 Saving to database...")

            with get_session() as session:
                from .database.queries import get_or_create_film

                added = 0
                existing = 0

                with click.progressbar(result.films, label="Importing") as films:
                    for film_data in films:
                        film, created = get_or_create_film(
                            session, film_data.film_title, film_data.year
                        )

                        if created:
                            added += 1
                        else:
                            existing += 1

                session.commit()

            click.secho("\n✅ Database updated:", fg="green", bold=True)
            click.echo(f"  • Added: {added} new films")
            click.echo(f"  • Existing: {existing} films")

            # Save to JSON
            if save_json:
                output_file = JSONExporter.export_to_default_location(result, config.OUTPUT_DIR)
                click.echo(f"  • JSON saved: {output_file}")

            # Show stats
            films_with_year = sum(1 for f in result.films if f.year is not None)
            year_percentage = (
                (films_with_year / result.film_count * 100) if result.film_count > 0 else 0
            )

            click.echo("\n📊 Statistics:")
            click.echo(f"  • Films with year: {films_with_year} ({year_percentage:.1f}%)")

            if result.source == "html":
                click.echo(f"  • Pages scraped: {result.total_pages_scraped}")

    except KeyboardInterrupt:
        click.echo("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        click.secho(f"❌ Error: {e}", fg="red")
        click.echo("\nFor more details, run with LOG_LEVEL=DEBUG in your .env file")
        if config.LOG_LEVEL == "DEBUG":
            import traceback

            click.echo("\nFull traceback:")
            click.echo(traceback.format_exc())
        sys.exit(1)


# ==============================================================================
# USE CASE 3 & 4: Database Management
# ==============================================================================


@cli.group()
def db():
    """Database management commands."""
    pass


@db.command()
@click.option("--reset", is_flag=True, help="Reset database (delete all data)")
def init(reset):
    """
    Initialize the database.

    Creates tables and indexes. Safe to run multiple times.
    Use --reset to delete all data and start fresh.
    """
    if reset:
        if click.confirm("⚠️  This will DELETE ALL DATA. Continue?", abort=True):
            reset_database()
            click.secho("✅ Database reset complete", fg="green")

    init_db()

    # Show info
    info = get_database_info()
    click.echo("\n📊 Database Information:")
    click.echo(f"  • Location: {info['path']}")
    click.echo(f"  • Status: {'Exists' if info['exists'] else 'Created'}")

    if info.get("size_mb"):
        click.echo(f"  • Size: {info['size_mb']} MB")

    if info.get("film_count") is not None:
        click.echo(f"  • Films: {info['film_count']}")
        click.echo(f"  • Streaming Offers: {info['offer_count']}")

    click.secho("\n✅ Database is ready!", fg="green")


@db.command()
def stats():
    """Show database statistics."""
    init_db()

    with get_session() as session:
        stats = get_database_stats(session)

        click.echo("\n📊 Database Statistics:\n")

        # Films
        click.secho("Films:", fg="cyan", bold=True)
        click.echo(f"  • Total: {stats['total_films']}")
        click.echo(f"  • Watched: {stats['watched_films']}")
        click.echo(f"  • Unwatched: {stats['unwatched_films']}")

        # TMDB matching
        click.secho("\nTMDB Matching:", fg="cyan", bold=True)
        click.echo(f"  • Matched: {stats['films_with_tmdb']}")
        click.echo(f"  • Match rate: {stats['match_rate']}%")

        # Streaming
        click.secho("\nStreaming Data:", fg="cyan", bold=True)
        click.echo(f"  • Total offers: {stats['total_offers']}")
        click.echo(f"  • Unique providers: {stats['unique_providers']}")
        click.echo(f"  • Unique countries: {stats['unique_countries']}")

        # Maintenance
        click.secho("\nMaintenance:", fg="cyan", bold=True)
        click.echo(f"  • Needs refresh: {stats['stale_films']} films (>7 days old)")

        # Database info
        info = get_database_info()
        if info.get("size_mb"):
            click.secho("\nStorage:", fg="cyan", bold=True)
            click.echo(f"  • Size: {info['size_mb']} MB")
            click.echo(f"  • Location: {info['path']}")


@db.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("--all", "import_all", is_flag=True, help="Import all JSON files from output/")
def import_json(path, import_all):
    """
    Import films from JSON export files.

    \b
    Examples:
      screenseeker db import-json --all
      screenseeker db import-json output/letterboxd_films_html_20251110.json
    """
    init_db()

    # Determine files to import
    if import_all:
        json_files = list(config.OUTPUT_DIR.glob("letterboxd_films_*.json"))
        if not json_files:
            click.secho(f"⚠️  No JSON files found in {config.OUTPUT_DIR}", fg="yellow")
            return

        click.echo(f"Found {len(json_files)} JSON file(s):")
        for f in json_files:
            click.echo(f"  • {f.name}")
        click.echo()
    elif path:
        json_files = [Path(path)]
    else:
        click.secho("❌ Specify a file path or use --all", fg="red")
        sys.exit(1)

    # Import files
    total_imported = 0
    total_skipped = 0

    for json_file in json_files:
        click.echo(f"📄 Processing: {json_file.name}")

        imported, skipped = _import_json_file(json_file)
        total_imported += imported
        total_skipped += skipped

        click.echo(f"  ✅ Imported: {imported}, ⏭️  Skipped: {skipped}\n")

    # Summary
    click.secho("✅ Migration complete!", fg="green", bold=True)
    click.echo(f"  • Files processed: {len(json_files)}")
    click.echo(f"  • Films imported: {total_imported}")
    click.echo(f"  • Films skipped: {total_skipped}")


# ==============================================================================
# USE CASE 5: Search & Query Films
# ==============================================================================


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Maximum results to show")
def search(query, limit):
    """
    Search films by title (case-insensitive partial match).

    \b
    Examples:
      screenseeker search matrix
      screenseeker search "blade runner" --limit 5
    """
    init_db()

    with get_session() as session:
        results = search_films_by_title(session, query, limit=limit)

        if not results:
            click.secho(f"No films found matching '{query}'", fg="yellow")
            return

        click.echo(f"\n🔍 Found {len(results)} film(s) matching '{query}':\n")

        for film in results:
            # Title and year
            click.secho(f"📽️  {film.full_title}", fg="cyan", bold=True)

            # TMDB info
            if film.tmdb_id:
                click.echo(f"   TMDB ID: {film.tmdb_id} | Match: {film.match_confidence}")
                if film.year_mismatch:
                    click.secho(
                        f"   ⚠️  Year mismatch: Letterboxd={film.letterboxd_year}, TMDB={film.tmdb_year}",
                        fg="yellow",
                    )
            else:
                click.secho("   ⚠️  Not enriched yet", fg="yellow")

            # Status
            if film.watched:
                click.secho("   ✓ Watched", fg="green")
                if film.watched_at:
                    click.echo(f"     on {film.watched_at.strftime('%Y-%m-%d')}")
            else:
                click.echo("   ☐ Unwatched")

            # Streaming offers count
            if film.streaming_offers:
                click.echo(f"   📊 {len(film.streaming_offers)} streaming offers")

                if film.last_checked:
                    age = datetime.utcnow() - film.last_checked
                    if age.days > 7:
                        click.secho(f"   ⚠️  Data is {age.days} days old", fg="yellow")

            click.echo()


@cli.command()
@click.option("--provider", "-p", required=True, help="Provider name (e.g., Netflix)")
@click.option("--country", "-c", help="Country code (e.g., FR, US)")
@click.option(
    "--type",
    "-t",
    "offer_type",
    type=click.Choice(["flatrate", "rent", "buy", "free", "ads"]),
    help="Monetization type",
)
@click.option("--limit", "-l", type=int, help="Maximum results to show")
def providers(provider, country, offer_type, limit):
    """
    List films available on a specific provider.

    \b
    Examples:
      screenseeker providers --provider Netflix
      screenseeker providers --provider "Prime Video" --country US
      screenseeker providers -p Netflix -c FR --type flatrate
    """
    init_db()

    with get_session() as session:
        films = get_films_by_provider(
            session,
            provider_name=provider,
            country_code=country,
            monetization_type=offer_type,
        )

        if not films:
            msg = f"No films found on {provider}"
            if country:
                msg += f" in {country}"
            if offer_type:
                msg += f" ({offer_type})"
            click.secho(msg, fg="yellow")
            return

        # Header
        title = f"Films on {provider}"
        if country:
            title += f" in {country}"
        if offer_type:
            title += f" ({offer_type})"

        click.echo(f"\n📺 {title}:\n")
        click.secho(f"Found {len(films)} film(s)", fg="green")
        click.echo()

        # List films
        display_films = films[:limit] if limit else films

        for i, film in enumerate(display_films, 1):
            status = "✓" if film.watched else "☐"
            click.echo(f"{i:3}. {status} {film.full_title}")

        if limit and len(films) > limit:
            click.echo(f"\n... and {len(films) - limit} more")
            click.echo(f"Use --limit {len(films)} to see all")


@cli.command()
@click.option("--country", "-c", required=True, help="Country code (e.g., FR, US)")
@click.option(
    "--type",
    "-t",
    "offer_type",
    type=click.Choice(["flatrate", "rent", "buy", "free", "ads"]),
    help="Monetization type",
)
def country(country, offer_type):
    """
    List films available in a specific country.

    \b
    Examples:
      screenseeker country --country FR
      screenseeker country -c US --type flatrate
    """
    init_db()

    with get_session() as session:
        films = get_films_by_country(session, country, offer_type)

        if not films:
            msg = f"No films found in {country}"
            if offer_type:
                msg += f" ({offer_type})"
            click.secho(msg, fg="yellow")
            return

        click.echo(f"\n🌍 Films available in {country}:\n")
        click.secho(f"Found {len(films)} film(s)", fg="green")
        click.echo()

        for i, film in enumerate(films, 1):
            status = "✓" if film.watched else "☐"
            click.echo(f"{i:3}. {status} {film.full_title}")


# ==============================================================================
# USE CASE 6: Track Watched Status
# ==============================================================================


@cli.command()
@click.option("--list", "show_list", is_flag=True, help="Show watchlist")
@click.option("--count", is_flag=True, help="Show count only")
def watchlist(show_list, count):
    """
    Show your unwatched films.

    \b
    Examples:
      screenseeker watchlist
      screenseeker watchlist --count
    """
    init_db()

    with get_session() as session:
        films = get_unwatched_films(session)

        if count:
            click.echo(f"{len(films)}")
            return

        if not films:
            click.secho("✅ No unwatched films! Time to add more to your watchlist.", fg="green")
            return

        click.echo(f"\n📋 Your Watchlist ({len(films)} unwatched films):\n")

        for i, film in enumerate(films, 1):
            click.echo(f"{i:3}. {film.full_title}")

            # Show if enriched
            if not film.tmdb_id:
                click.secho(
                    f'     ⚠️  Not enriched yet - run: screenseeker watch "{film.full_title}"',
                    fg="yellow",
                    dim=True,
                )


@cli.command()
@click.argument("title")
@click.option("--year", "-y", type=int, help="Release year")
@click.option("--unwatch", is_flag=True, help="Mark as unwatched")
def watched(title, year, unwatch):
    """
    Mark a film as watched or unwatched.

    \b
    Examples:
      screenseeker watched "The Matrix"
      screenseeker watched "Inception" --year 2010
      screenseeker watched "The Matrix" --unwatch
    """
    init_db()

    with get_session() as session:
        film = get_film_by_title_year(session, title, year)

        if not film:
            click.secho(f"❌ Film not found: {title} ({year or 'any year'})", fg="red")
            click.echo("\n💡 Suggestions:")
            click.echo(f'   • Try searching: screenseeker search "{title}"')
            click.echo(f'   • Or enrich it first: screenseeker watch "{title}"')
            if not year:
                click.echo(f'   • Try adding the year: screenseeker watched "{title}" --year YYYY')
            sys.exit(1)

        # Mark watched/unwatched
        mark_film_watched(session, film.id, watched=not unwatch)
        session.commit()

        if unwatch:
            click.secho(f"☐ Marked '{film.full_title}' as unwatched", fg="yellow")
        else:
            click.secho(f"✓ Marked '{film.full_title}' as watched!", fg="green")


# ==============================================================================
# USE CASE 7: Batch Operations
# ==============================================================================


@cli.command()
@click.option("--days", "-d", default=7, help="Consider films stale after N days")
@click.option("--limit", "-l", type=int, help="Maximum films to refresh")
@click.option("--dry-run", is_flag=True, help="Show what would be refreshed without doing it")
def refresh(days, limit, dry_run):
    """
    Refresh stale streaming data from TMDB.

    Finds films whose streaming data is older than N days and refreshes them.

    \b
    Examples:
      screenseeker refresh                # Refresh films >7 days old
      screenseeker refresh --days 30      # Only films >30 days old
      screenseeker refresh --limit 10     # Refresh max 10 films
      screenseeker refresh --dry-run      # See what would be refreshed
    """
    init_db()

    # Check TMDB API key
    if not config.TMDB_API_KEY or config.TMDB_API_KEY == "your_tmdb_api_key_here":
        click.secho("❌ TMDB API key not configured!", fg="red", bold=True)
        sys.exit(1)

    with get_session() as session:
        stale_films = get_stale_films(session, days=days)

        if not stale_films:
            click.secho(f"✅ All films are fresh! (checked within {days} days)", fg="green")
            return

        # Apply limit
        if limit:
            stale_films = stale_films[:limit]

        click.echo(f"\n🔄 Found {len(stale_films)} film(s) to refresh:\n")

        for film in stale_films:
            age_str = (
                "never checked"
                if not film.last_checked
                else f"{(datetime.utcnow() - film.last_checked).days} days old"
            )
            click.echo(f"  • {film.full_title} ({age_str})")

        if dry_run:
            click.echo("\n(Dry run - no changes made)")
            return

        if not click.confirm(f"\nRefresh {len(stale_films)} film(s)?"):
            click.echo("Cancelled")
            return

        # Refresh films
        click.echo()

        with TMDBEnricher(
            api_key=config.TMDB_API_KEY,
            rate_limit_per_second=config.TMDB_RATE_LIMIT,
            language=config.TMDB_LANGUAGE,
        ) as enricher:
            with click.progressbar(stale_films, label="Refreshing") as films:
                for film in films:
                    try:
                        enrich_and_save_film(
                            session,
                            enricher,
                            film.letterboxd_title,
                            film.letterboxd_year,
                            force_refresh=True,
                        )
                    except Exception as e:
                        click.echo(f"\n⚠️  Error refreshing {film.full_title}: {e}")

        click.secho(f"\n✅ Refreshed {len(stale_films)} film(s)!", fg="green")


@cli.command()
@click.option("--limit", "-l", type=int, help="Maximum films to enrich")
@click.option(
    "--unenriched-only",
    is_flag=True,
    default=True,
    help="Only enrich films without TMDB data (default)",
)
@click.option(
    "--all",
    "enrich_all",
    is_flag=True,
    help="Enrich all films (including already enriched)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be enriched without doing it")
def enrich(limit, unenriched_only, enrich_all, dry_run):
    """
    Batch enrich films from your watchlist with TMDB data.

    Finds films in your database and fetches streaming availability from TMDB.
    By default, only enriches films that haven't been enriched yet.

    \b
    Examples:
      screenseeker enrich                      # Enrich all unenriched films
      screenseeker enrich --limit 10           # Enrich max 10 films
      screenseeker enrich --all                # Re-enrich everything
      screenseeker enrich --dry-run            # Preview what would be enriched
    """
    init_db()

    # Check TMDB API key
    if not config.TMDB_API_KEY or config.TMDB_API_KEY == "your_tmdb_api_key_here":
        click.secho("❌ TMDB API key not configured!", fg="red", bold=True)
        click.echo("\nPlease set TMDB_API_KEY in your .env file:")
        click.echo("  1. Copy .env.example to .env")
        click.echo("  2. Get your free API key at: https://www.themoviedb.org/settings/api")
        click.echo("  3. Add it to .env: TMDB_API_KEY=your_key_here")
        sys.exit(1)

    with get_session() as session:
        # Get films to enrich
        if enrich_all:
            films_to_enrich = session.query(Film).all()
            mode = "all"
        else:
            films_to_enrich = session.query(Film).filter(Film.tmdb_id.is_(None)).all()
            mode = "unenriched"

        if not films_to_enrich:
            if mode == "unenriched":
                click.secho("✅ All films are already enriched!", fg="green")
                click.echo("\nUse --all to re-enrich everything")
            else:
                click.secho("⚠️  No films found in database", fg="yellow")
                click.echo("\nRun 'screenseeker sync' first to import your watchlist")
            return

        # Apply limit
        total_found = len(films_to_enrich)
        if limit:
            films_to_enrich = films_to_enrich[:limit]

        click.echo(f"\n🔍 Found {total_found} {mode} film(s)")
        if limit and total_found > limit:
            click.echo(f"   Limiting to {limit} films\n")
        else:
            click.echo()

        # Show preview
        click.echo("Films to enrich:\n")
        for i, film in enumerate(films_to_enrich[:10], 1):
            click.echo(f"  {i:3}. {film.full_title}")

        if len(films_to_enrich) > 10:
            click.echo(f"  ... and {len(films_to_enrich) - 10} more")

        if dry_run:
            click.echo("\n(Dry run - no changes made)")
            return

        click.echo()
        if not click.confirm(f"Enrich {len(films_to_enrich)} film(s)?"):
            click.echo("Cancelled")
            return

        # Enrich films
        click.echo()

        success_count = 0
        error_count = 0
        errors = []

        with TMDBEnricher(
            api_key=config.TMDB_API_KEY,
            rate_limit_per_second=config.TMDB_RATE_LIMIT,
            language=config.TMDB_LANGUAGE,
        ) as enricher:
            with click.progressbar(films_to_enrich, label="Enriching") as films:
                for film in films:
                    try:
                        enrich_and_save_film(
                            session,
                            enricher,
                            film.letterboxd_title,
                            film.letterboxd_year,
                            force_refresh=enrich_all,  # Force if enriching all
                        )
                        success_count += 1
                    except Exception as e:
                        error_count += 1
                        errors.append((film.full_title, str(e)))

        # Summary
        click.echo()
        click.secho(f"✅ Successfully enriched: {success_count} film(s)", fg="green")

        if error_count > 0:
            click.secho(f"⚠️  Errors: {error_count} film(s)", fg="yellow")
            click.echo("\nFailed films:")
            for title, error in errors[:5]:
                click.echo(f"  • {title}: {error}")
            if len(errors) > 5:
                click.echo(f"  ... and {len(errors) - 5} more errors")

        # Show what to do next
        if success_count > 0:
            click.echo("\n💡 Next steps:")
            click.echo("  • View your films: screenseeker search <title>")
            click.echo("  • Check availability: screenseeker report")
            click.echo("  • Query by provider: screenseeker providers --provider Netflix")


# ==============================================================================
# USE CASE 8: Reports & Statistics
# ==============================================================================


@cli.command()
@click.option("--provider", "-p", multiple=True, help="Providers to check (can specify multiple)")
def report(provider):
    """
    Generate availability report for your subscriptions.

    Shows how many films are available on each provider.

    \b
    Examples:
      screenseeker report
      screenseeker report --provider Netflix --provider "Prime Video"
    """
    init_db()

    # Get providers from config or args
    if provider:
        providers = list(provider)
    else:
        # Extract from subscription profile
        providers = []
        for sub in config.SUBSCRIPTION_PROFILE.get("subscriptions", []):
            providers.extend(sub["provider_names"])

    if not providers:
        click.secho("❌ No providers specified", fg="red")
        click.echo("Use --provider or configure SUBSCRIPTION_PROFILE in config.py")
        sys.exit(1)

    base_country = config.SUBSCRIPTION_PROFILE.get("base_country", "FR")

    click.echo(f"\n📊 Availability Report ({base_country}):\n")

    with get_session() as session:
        for provider_name in providers:
            films = get_films_by_provider(
                session,
                provider_name=provider_name,
                country_code=base_country,
                monetization_type="flatrate",
            )

            click.secho(f"📺 {provider_name}", fg="cyan", bold=True)
            click.echo(f"   {len(films)} film(s) available")

            if films:
                # Show first 3
                for film in films[:3]:
                    status = "✓" if film.watched else "☐"
                    click.echo(f"   {status} {film.full_title}")

                if len(films) > 3:
                    click.echo(f"   ... and {len(films) - 3} more")

            click.echo()


# ==============================================================================
# Helper Functions
# ==============================================================================


def _display_watch_strategy(result, strategy):
    """Display personalized watch strategy."""
    click.echo("\n" + "=" * 80)
    click.secho("HOW TO WATCH", fg="cyan", bold=True)
    click.echo("=" * 80)

    # Query info
    click.echo(f"\n📽️  '{result.query_title}' ({result.query_year or 'no year'})")

    # Match status
    if not result.success:
        click.secho(f"\n❌ Enrichment failed: {result.error_message}", fg="red")
        return

    if result.match_confidence == "none":
        click.secho("\n⚠️  No match found on TMDB", fg="yellow")
        return

    # TMDB match
    movie = result.tmdb_movie
    confidence_emoji = {"exact": "🎯", "high": "✅", "medium": "⚠️", "low": "❓"}.get(
        result.match_confidence, "❓"
    )

    click.echo(
        f"{confidence_emoji} TMDB Match: {movie.title} ({movie.year or 'N/A'}) - Confidence: {result.match_confidence}"
    )
    if movie.vote_average:
        click.echo(f"   ⭐ Rating: {movie.vote_average}/10")

    # Check if any watching options available
    if not strategy.has_any_option():
        click.secho("\n❌ NOT AVAILABLE on your subscriptions", fg="red", bold=True)
        click.echo(
            f"   Available globally in {result.total_countries} countries on {result.total_providers} providers"
        )
        click.echo("=" * 80)
        return

    # Best option (no VPN needed)
    if strategy.best_option:
        click.secho("\n✅ WATCH NOW (No VPN needed):", fg="green", bold=True)
        opt = strategy.best_option
        if opt.via_bundle:
            click.echo(f"   🇫🇷 {opt.provider} (via {opt.via_bundle}) - {opt.country_name}")
        else:
            click.echo(f"   🇫🇷 {opt.provider} - {opt.country_name}")

    # VPN options
    if strategy.vpn_options:
        click.secho("\n🌍 VPN OPTIONS:", fg="blue", bold=True)
        for opt in strategy.vpn_options:
            if opt.via_bundle:
                click.echo(
                    f"   {opt.provider} (via {opt.via_bundle}) - Connect to {opt.country_name}"
                )
            else:
                click.echo(f"   {opt.provider} - Connect to {opt.country_name}")

    # Rent/Buy alternatives
    if strategy.base_country_alternatives:
        click.secho("\n💰 RENT/BUY:", fg="yellow", bold=True)
        rent_providers = [
            opt.provider for opt in strategy.base_country_alternatives if opt.offer_type == "rent"
        ]
        buy_providers = [
            opt.provider for opt in strategy.base_country_alternatives if opt.offer_type == "buy"
        ]

        if rent_providers:
            click.echo(f"   Rent: {', '.join(rent_providers)}")
        if buy_providers:
            click.echo(f"   Buy: {', '.join(buy_providers)}")

    # Summary
    click.echo("\n📊 Summary:")
    click.echo(f"   Global: {result.total_countries} countries, {result.total_providers} providers")
    click.echo(f"   Your subscriptions: {len(strategy.all_owned_options)} options")

    click.echo("\n" + "=" * 80)


def _import_json_file(json_path):
    """Import films from JSON file."""
    import json

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        click.secho(f"Failed to read JSON: {e}", fg="red")
        return 0, 0

    # Handle different JSON structures
    films = []
    if isinstance(data, dict):
        if "films" in data:
            films = data["films"]
    elif isinstance(data, list):
        films = data

    if not films:
        return 0, 0

    imported = 0
    skipped = 0

    with get_session() as session:
        from .database.queries import get_or_create_film

        for film_data in films:
            try:
                title = film_data.get("film_title") or film_data.get("title")
                year = film_data.get("year")

                if not title:
                    skipped += 1
                    continue

                film, created = get_or_create_film(session, title, year)

                if created:
                    imported += 1
                else:
                    skipped += 1

            except Exception:
                skipped += 1

        session.commit()

    return imported, skipped


# ==============================================================================
# Entry Point
# ==============================================================================

if __name__ == "__main__":
    cli()
