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
ScreenSeeker CLI.

Plumbing only. Browsing, searching and filtering live in the web UI; this
exists to set the tool up, keep the local mirror fresh, and start the server.
"""

import sys

import click

from . import config, settings, user_config
from .database import get_session, init_db
from .exceptions import ConfigurationError
from .logger import get_logger, setup_logger
from .services import enrichment, ingest_watchlist, members
from .services.enrichment import build_enricher, enrich_films
from .services.sync import HouseholdSyncReport, SyncReport, build_scraper

setup_logger(level=config.LOG_LEVEL, log_to_file=config.LOG_TO_FILE, use_colors=True)
logger = get_logger(__name__)


def _load_config_or_exit() -> dict:
    """Read the config file, or explain how to create one and stop."""
    try:
        return user_config.load_config()
    except Exception as e:
        click.secho(f"❌ {e}", fg="red")
        sys.exit(1)


def _build_or_exit(factory, cfg: dict):
    """
    Construct a scraper or enricher from config, or explain and stop.

    The construction itself lives in `services` because the background job
    runner needs the same objects; this only turns a ConfigurationError into
    an exit code.
    """
    try:
        return factory(cfg)
    except ConfigurationError as e:
        click.secho(f"❌ {e}", fg="red", bold=True)
        sys.exit(1)


@click.group()
@click.version_option(version="0.1.0", prog_name="screenseeker")
def cli():
    """
    ScreenSeeker - find where to watch films from your Letterboxd watchlist.

    \b
    Typical use:
      screenseeker config init    # first-time setup
      screenseeker sync           # pull the watchlist from Letterboxd
      screenseeker refresh        # fetch streaming availability from TMDB
      screenseeker serve          # open the web UI

    Browsing and filtering live in the web UI.
    """
    pass


# ==============================================================================
# Configuration
# ==============================================================================


@cli.group(name="config")
def config_group():
    """Manage your configuration."""
    pass


@config_group.command(name="init")
def config_init():
    """Interactive first-time setup wizard."""
    if user_config.config_exists():
        click.secho(f"Config already exists at {user_config.CONFIG_PATH}", fg="yellow")
        if not click.confirm("Overwrite it?"):
            click.echo("Cancelled.")
            return

    click.echo("\nWelcome to Screenseeker! Let's set up your profile.\n")

    username = click.prompt("Your Letterboxd username").strip()
    base_country = click.prompt("Your base country code (e.g. FR, US, GB)", default="FR")
    base_country = base_country.upper().strip()

    click.echo("\nYou need a free TMDB API key to fetch streaming data.")
    click.echo("Get one at: https://www.themoviedb.org/settings/api")
    api_key = click.prompt("\nTMDB API key", hide_input=True)

    click.echo("\nNow let's add your streaming subscriptions.")
    click.echo("Press Enter with no name to finish.\n")

    subscriptions = []
    i = 1
    while True:
        provider_name = click.prompt(f"Provider {i} name", default="", show_default=False)
        if not provider_name.strip():
            break

        vpn_enabled = click.confirm("  VPN enabled?", default=False)

        if vpn_enabled and click.confirm("  Available in all countries?", default=True):
            available_countries = "all"
        else:
            countries_input = click.prompt("  Countries (comma-separated)")
            available_countries = [
                c.strip().upper() for c in countries_input.split(",") if c.strip()
            ]

        bundles_input = click.prompt(
            "  Bundles other services? (comma-separated, or Enter to skip)",
            default="",
            show_default=False,
        )
        bundle_includes = [b.strip() for b in bundles_input.split(",") if b.strip()]

        sub = {
            "provider_names": [provider_name.strip()],
            "vpn_enabled": vpn_enabled,
            "available_countries": available_countries,
        }
        if bundle_includes:
            sub["bundle_includes"] = bundle_includes

        subscriptions.append(sub)
        click.secho(f"  ✓ Added {provider_name}", fg="green")
        click.echo()
        i += 1

    user_config.save_config(
        {
            # Kept so an install upgraded from the single-user version still
            # has the name that seeded its first member. The household itself
            # lives in the database - see `screenseeker members`.
            "letterboxd": {"username": username},
            "tmdb": {"api_key": api_key, "rate_limit": 5.0, "language": "en-US"},
            "profile": {
                "base_country": base_country,
                "max_vpn_suggestions": 3,
                "vpn_country_priority": user_config.DEFAULT_VPN_PRIORITY,
                "subscriptions": subscriptions,
            },
        }
    )
    click.secho(f"\n✓ Saved to {user_config.CONFIG_PATH}", fg="green")

    init_db()
    with get_session() as session:
        if members.get_by_username(session, username) is None:
            try:
                members.create_member(session, username)
                click.secho(f"✓ Added {username} to the household", fg="green")
            except ConfigurationError as e:
                click.secho(f"⚠️  Could not add {username}: {e}", fg="yellow")

    click.echo("\nAdd anyone else with `screenseeker members add <username>`.")
    click.echo("Next: screenseeker sync")


@config_group.command()
def edit():
    """Open the config file in your editor."""
    if not user_config.config_exists():
        click.secho("No config found. Run `screenseeker config init` first.", fg="red")
        sys.exit(1)

    click.edit(filename=str(user_config.CONFIG_PATH))


@config_group.command()
def path():
    """Print where the config and database live."""
    click.echo(f"config:   {user_config.CONFIG_PATH}")
    click.echo(f"database: {settings.DB_PATH}")


# ==============================================================================
# The household
#
# A member is a Letterboxd account to scrape, not a login: the app still has
# one password and one subscription profile. These live in the database rather
# than the config file, so the web UI can edit them too.
# ==============================================================================


@cli.group(name="members")
def members_group():
    """Manage whose watchlists are combined."""
    pass


@members_group.command(name="list")
def members_list():
    """Show the household."""
    init_db()
    with get_session() as session:
        household = members.list_members(session)

    if not household:
        click.echo("Nobody yet. Add one with `screenseeker members add <username>`.")
        return

    for member in household:
        state = "" if member.active else "  (paused)"
        synced = (
            f"synced {member.last_synced_at:%Y-%m-%d}" if member.last_synced_at else "never synced"
        )
        click.echo(
            f"  {member.display_name}  ({member.letterboxd_username})  "
            f"{member.film_count} film(s), {synced}{state}"
        )


@members_group.command(name="add")
@click.argument("username")
@click.option("--name", "-n", "display_name", default="", help="Name shown on the cards")
def members_add(username, display_name):
    """Add a Letterboxd account to the household."""
    init_db()
    try:
        with get_session() as session:
            member = members.create_member(session, username, display_name=display_name)
    except ConfigurationError as e:
        click.secho(f"❌ {e}", fg="red")
        sys.exit(1)

    click.secho(f"✓ Added {member.display_name} ({member.letterboxd_username})", fg="green")
    click.echo(f"\nNext: screenseeker sync --member {member.letterboxd_username}")


@members_group.command(name="remove")
@click.argument("username")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt")
def members_remove(username, yes):
    """
    Remove a member, their entries, and any film nobody else wants.

    Films another member still lists are untouched, enrichment included.
    """
    init_db()
    with get_session() as session:
        row = members.get_by_username(session, username)
        if row is None:
            click.secho(f"❌ No member '{username}'.", fg="red")
            sys.exit(1)

        member_id, name = row.id, row.display_name

    if not yes and not click.confirm(f"Remove {name}? Films nobody else wants go too."):
        click.echo("Cancelled.")
        return

    with get_session() as session:
        report = members.delete_member(session, member_id)

    click.secho(
        f"✓ Removed {report.display_name}: {report.entries_removed} entries, "
        f"{report.films_removed} film(s) nobody else wanted",
        fg="green",
    )


# ==============================================================================
# Keeping the mirror fresh
# ==============================================================================


@cli.command()
@click.option("--member", "-m", "only", help="Sync one member by Letterboxd username")
def sync(only):
    """
    Pull every member's Letterboxd watchlist into the local database.

    Watchlists are combined: the same film on three lists is one row wanted by
    three people. Films dropped from a watchlist stop counting; nothing is
    deleted. Streaming availability is fetched separately by
    `screenseeker refresh`.
    """
    init_db()

    with get_session() as session:
        household = members.list_members(session, active_only=True)

    if only:
        household = [m for m in household if m.letterboxd_username == only.strip().lower()]
        if not household:
            click.secho(f"❌ No active member '{only}'. See `screenseeker members list`.", fg="red")
            sys.exit(1)

    if not household:
        click.secho(
            "❌ No members yet. Add one with `screenseeker members add <username>`.", fg="red"
        )
        sys.exit(1)

    reports = []
    for member in household:
        click.echo(f"📡 Scraping {member.display_name} ({member.letterboxd_username})...")
        try:
            scraper = build_scraper(member.letterboxd_username)
            with scraper, get_session() as session:
                report = ingest_watchlist(
                    session,
                    scraper,
                    member_id=member.id,
                    member_name=member.display_name,
                )
        except KeyboardInterrupt:
            click.echo("\n\nCancelled")
            sys.exit(0)
        except Exception as e:
            # One bad account must not cost the other watchlists their sync.
            click.secho(f"  ❌ {e}", fg="red")
            reports.append(
                SyncReport(
                    member=member.display_name, scraped=0, success=False, error_message=str(e)
                )
            )
            continue

        reports.append(report)

        if not report.success:
            click.secho(f"  ❌ {report.error_message}", fg="red")
        elif report.scraped == 0:
            click.secho("  ⚠️  No films found — entries left as they were", fg="yellow")
        else:
            click.echo(
                f"  ✓ {report.scraped} film(s): {report.added} added, "
                f"{report.restored} restored, {report.removed} removed"
            )

    household_report = HouseholdSyncReport(reports=reports)

    if not household_report.success:
        click.secho("\n❌ Every watchlist failed.", fg="red", bold=True)
        sys.exit(1)

    click.secho(f"\n✅ {household_report.scraped} film(s) seen", fg="green", bold=True)
    click.echo(f"  • New to the library: {household_report.new_films}")
    click.echo(f"  • No longer wanted: {household_report.removed}")
    if household_report.failures:
        click.secho(f"  • Failed: {len(household_report.failures)} member(s)", fg="yellow")

    if household_report.new_films:
        click.echo("\nNext: screenseeker refresh")


@cli.command()
@click.option("--days", "-d", default=None, type=int, help="Refresh data older than N days")
@click.option("--limit", "-l", type=int, help="Maximum films to refresh")
@click.option("--dry-run", is_flag=True, help="Show what would be refreshed")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt")
def refresh(days, limit, dry_run, yes):
    """
    Fetch streaming availability from TMDB for films that need it.

    Covers both films that have never been checked and those whose data has
    aged past the cache TTL - a film that was never checked is stale.
    """
    days = settings.CACHE_TTL_DAYS if days is None else days
    cfg = _load_config_or_exit()

    init_db()

    with get_session() as session:
        films, total = enrichment.select_stale(session, days=days, limit=limit)

        if not films:
            click.secho(f"✅ Everything is fresh (checked within {days} days)", fg="green")
            return

        click.echo(
            f"\n🔄 {total} film(s) need refreshing" + (f", doing {len(films)}" if limit else "")
        )
        click.echo()

        for film in films[:10]:
            age = "never checked" if film.cache_age_days is None else f"{film.cache_age_days}d old"
            click.echo(f"  • {film.full_title} ({age})")
        if len(films) > 10:
            click.echo(f"  ... and {len(films) - 10} more")

        if dry_run:
            click.echo("\n(Dry run - no changes made)")
            return

        if not yes and not click.confirm(f"\nRefresh {len(films)} film(s)?"):
            click.echo("Cancelled")
            return

        click.echo()
        try:
            with _build_or_exit(build_enricher, cfg) as enricher:
                with click.progressbar(length=len(films), label="Refreshing") as bar:
                    report = enrich_films(
                        session,
                        enricher,
                        films,
                        force_refresh=True,
                        on_progress=lambda done, total_, title: bar.update(1),
                    )
        except KeyboardInterrupt:
            click.echo("\n\nCancelled - films already refreshed are saved")
            sys.exit(0)

    click.secho(f"\n✅ Refreshed {report.succeeded} film(s)", fg="green")

    if report.failed:
        click.secho(f"⚠️  Failed: {report.failed}", fg="yellow")
        for failure in report.errors[:5]:
            click.echo(f"  • {failure.title}: {failure.error}")
        if report.failed > 5:
            click.echo(f"  ... and {report.failed - 5} more")


# ==============================================================================
# Web UI
# ==============================================================================


@cli.command()
@click.option("--host", default=None, help=f"Bind address (default {settings.HOST})")
@click.option("--port", "-p", default=None, type=int, help=f"Port (default {settings.PORT})")
@click.option("--reload", is_flag=True, help="Reload on code changes (development)")
def serve(host, port, reload):
    """
    Start the web UI.

    Binds to loopback unless told otherwise. Exposing it beyond this machine
    is a deliberate act - put it behind a VPN or an authenticating proxy.
    """
    try:
        import uvicorn
    except ImportError:
        click.secho("❌ uvicorn is not installed.", fg="red")
        click.echo("Install the web extras: pip install 'screenseeker[web]'")
        sys.exit(1)

    init_db()

    host = host or settings.HOST
    port = port or settings.PORT

    click.secho(f"\n🎬 ScreenSeeker on http://{host}:{port}\n", fg="cyan", bold=True)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        click.secho(
            "⚠️  Bound beyond loopback. There is no authentication - "
            "only do this behind a VPN or an authenticating proxy.",
            fg="yellow",
        )

    uvicorn.run(
        "screenseeker.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level="info" if settings.DEBUG else "warning",
    )


if __name__ == "__main__":
    cli()
