# ScreenSeeker 🎬

Find where to watch the films on your household's Letterboxd watchlists, ranked
by what you already pay for.

ScreenSeeker takes three things — everyone's Letterboxd watchlist, your streaming
subscriptions, and (optionally) which countries your VPN can reach — and answers
the only question that matters on a given evening: *what can we actually watch
tonight, without paying for anything new?* It pulls each watchlist, looks up
each film's streaming availability per country from TMDB, and matches that
against your subscriptions, flagging the ones that are one click from playing.

Watchlists are **combined, not merged away**. The same film on three lists is
one card with three chips, and *Most wanted* puts what everyone agrees on first.

The primary interface is a **web app**. The CLI exists to set the tool up and
keep the local mirror fresh; browsing, searching and filtering all live in the
browser.

---

## How it works

1. **`sync`** scrapes every member's Letterboxd watchlist into a local SQLite
   database, deduplicating films across them.
2. **`refresh`** asks TMDB, per film, where it streams in every country and how
   long it runs, caching the answer for 7 days.
3. The **web app** reads that cache and, against your subscription profile,
   shows each film as "watchable tonight" (a green ▶ with the provider),
   "available somewhere" (an offer count), or "nowhere to stream".

None of the browsing touches the network — it's all served from the local cache,
so the grid is instant. Only `sync` and `refresh` reach out.

---

## The web app

Start it with `screenseeker serve` and open `http://127.0.0.1:8000`. The pages:

- **Library** (`/`) — the whole household's watchlist as a poster grid. Filter
  by provider, country, offer type and **whose list it is on** (any of them, or
  all of them), sort, and search by title as you type. Every filter is a query
  parameter, so any view is a bookmarkable URL. Each card shows year, rating,
  runtime, a chip per person who wants it, and a "watchable tonight" badge when
  one applies.
- **Tonight** (`/tonight`) — the films you can start right now: streaming in
  your base country, no VPN, on a subscription you already pay for, **most
  wanted first**. Free and ad-supported offers are deliberately not here; they
  are reachable from the Library filter and each film's page.
- **Stale** (`/stale`) — films whose streaming data has aged past the cache TTL,
  with a button to refresh them.
- **Profile** (`/profile`) — manage the household (add, rename, recolour, pause
  or remove a member) and edit your base country, subscriptions and VPN settings
  in the browser instead of the CLI wizard.
- **Film detail** (`/film/{id}`) — every way to watch one film, including VPN
  suggestions ranked by your country priority.

`sync` and `refresh` can also be launched from the web UI (the buttons at the
top of the Library). They run as background jobs; a running job survives page
navigation and only one of each kind runs at a time.

### Authentication

Set `SCREENSEEKER_PASSWORD` and the whole app requires a login: every page needs
a session cookie, and every state-changing request is checked for a same-origin
header (CSRF). Leave it empty and the app is open — the right choice behind a
private network (e.g. Tailscale), and the wrong one on the public internet. There
is no third state. See [Deployment](#deployment).

---

## Quick start (local)

Requires **Python 3.14+** and a free [TMDB API key](https://www.themoviedb.org/settings/api).

```bash
git clone https://github.com/moukisei/screenseeker.git
cd screenseeker

# Install with the web extras (uvicorn, FastAPI, Jinja, htmx are bundled).
pip install -e '.[web]'

# One-time interactive setup: Letterboxd username, base country, TMDB key,
# and your streaming subscriptions. Adds you as the first household member.
screenseeker config init

# Add everyone else who shares the television.
screenseeker members add partner --name "Sam"
screenseeker members add flatmate --name "Alex"

# Pull every watchlist, then fetch availability + runtimes.
screenseeker sync
screenseeker refresh

# Start the web app.
screenseeker serve            # http://127.0.0.1:8000
```

By default `serve` binds to loopback only. Exposing it to a network is a
deliberate act — see [Deployment](#deployment).

---

## The CLI

The CLI is plumbing: set up, keep fresh, serve.

| Command | What it does |
|---|---|
| `screenseeker config init` | Interactive first-time setup wizard. |
| `screenseeker config edit` | Open the config file in `$EDITOR`. |
| `screenseeker config path` | Print where the config and database live. |
| `screenseeker members list` | Show the household, film counts and last sync. |
| `screenseeker members add <username>` | Add a Letterboxd account (`--name` sets the display name). |
| `screenseeker members remove <username>` | Remove a member, their entries, and films nobody else wants. |
| `screenseeker sync` | Scrape every member's watchlist. `--member <username>` does just one. |
| `screenseeker refresh` | Fetch TMDB availability + runtime for films whose cache is stale. |
| `screenseeker serve` | Start the web app (`--host`, `--port`, `--reload`). |

`refresh` only touches films older than the cache TTL (7 days) or never checked.
To force a full re-fetch — for example to backfill a newly added field across the
whole library — use `screenseeker refresh --days 0`. Other flags: `--limit N`
(cap how many films), `--dry-run`, `--yes` (skip the prompt).

> **Never run two `sync`s at once.** Sync is the one operation that can create
> duplicate films if it races itself. `refresh` is safe to overlap — it only
> rewrites offers for films that already exist.

---

## The household

A member is **a Letterboxd account to scrape, not a login**. There is still one
password for the whole app and one set of subscriptions, because a household
shares a television and a Netflix account. The only thing that varies per person
is which films they want.

That has a few consequences worth knowing:

- **Films are shared.** Three people wanting *Heat* is one row and three
  entries, so TMDB enrichment — the slow, rate-limited part — is paid once.
- **Dropping a film from your watchlist un-wants it, it does not delete it.**
  The entry is retired; the film stays for anyone else who lists it, and comes
  back with its original date if you add it again.
- **A scrape that returns nothing changes nothing.** A rate limit or a login
  wall reads as "your watchlist is empty", so entries stand until a scrape that
  actually read something disagrees with them.
- **There is no "watched" button.** Logging a film on Letterboxd takes it off
  your watchlist there, so the next sync retires the entry and the film leaves
  the app on its own. A flag here would be a second source of truth for the
  same fact, and the two would disagree within a week.
- **A film nobody lists is not in the library.** It disappears from the grid,
  from Tonight, from the detail page and from the refresh queue — the entry is
  kept, not deleted, so re-adding the film restores it without another TMDB
  lookup.
- **Removing a member takes the films nobody else wanted.** Anything another
  member still lists is untouched, enrichment included.

Pausing a member (the *Sync* checkbox on the profile page) stops scraping them
without touching their entries — useful when someone's profile goes private.

---

## Configuration

Setup writes a TOML file (default `~/.config/screenseeker/config.toml`) holding
your TMDB key, base country and subscriptions. The household lives in the
database, not here, so the web UI can edit it too — `[letterboxd].username` is
kept only to seed the first member:

```toml
[letterboxd]
username = "moukisei"

[tmdb]
api_key = "your_api_key_here"
rate_limit = 5.0
language = "en-US"

[profile]
base_country = "FR"
max_vpn_suggestions = 3
vpn_country_priority = ["US", "GB", "CA", "..."]

[[profile.subscriptions]]
provider_names = ["Netflix"]
vpn_enabled = true
available_countries = "all"

[[profile.subscriptions]]
provider_names = ["Canal+"]
vpn_enabled = false
available_countries = ["FR"]
bundle_includes = ["HBO Max", "Apple TV+", "Paramount+"]
```

`provider_names` is a list because a service can be renamed or span multiple TMDB
names; `bundle_includes` lets a subscription (e.g. Canal+) cover the services it
bundles.

### Environment variables

Every setting is read once at process start. Anything sensitive or
deployment-specific is best set here rather than in the config file.

| Variable | Default | Purpose |
|---|---|---|
| `TMDB_API_KEY` | — | TMDB key. Overrides the config file; keeps the key out of `config.toml`. |
| `SCREENSEEKER_PASSWORD` | *(empty)* | Set it to require a login. Empty = open app. |
| `SCREENSEEKER_SECRET_KEY` | *(derived from password)* | Signs the session cookie. Set it (`openssl rand -hex 32`) so a password change doesn't log every device out. |
| `SCREENSEEKER_COOKIE_SECURE` | `true` | Cookie only sent over HTTPS. Keep true behind TLS; false only for local http testing. |
| `SCREENSEEKER_HOST` | `127.0.0.1` | Bind address. Loopback by default. |
| `SCREENSEEKER_PORT` | `8000` | Bind port. |
| `SCREENSEEKER_DB_PATH` | `~/.local/share/screenseeker/screenseeker.db` | SQLite database file. |
| `SCREENSEEKER_CONFIG_PATH` | `~/.config/screenseeker/config.toml` | Config file location. |
| `SCREENSEEKER_CACHE_TTL_DAYS` | `7` | How long availability data stays fresh before a film is "stale". |
| `SCREENSEEKER_SESSION_MAX_AGE_DAYS` | `14` | Login session lifetime. |
| `SCREENSEEKER_DEBUG` | `false` | Enables `/docs` and tracebacks. Keep off in production. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |

`screenseeker config path` prints the resolved config and database locations for
your environment.

---

## Deployment

The app never faces the internet directly — a reverse proxy terminates TLS and
forwards to it on loopback. Two supported models:

- **Private (Tailscale)** — reachable from your own devices, no domain, no TLS,
  no password. Fewest moving parts.
- **Public (password + TLS)** — a login gates it and Caddy handles Let's Encrypt
  certificates automatically. Needs a domain.

The [`deploy/`](deploy/) directory is the complete kit — a systemd unit, a Caddy
config, an environment template, a backup script and a cron entry — with a
walkthrough in **[`deploy/README.md`](deploy/README.md)**.

For a concrete, end-to-end **free** deployment on an Oracle Cloud Always Free VM
with a free DuckDNS domain, see
**[`deploy/oracle-free-tier.md`](deploy/oracle-free-tier.md)**.

---

## Architecture

- **FastAPI + uvicorn**, server-rendered Jinja templates, **htmx** for in-page
  updates (vendored, no CDN). One long-running process, a single worker — the
  background job runner and its single-flight guard live in-process, so the app
  is not safe to run multi-worker or autoscaled.
- **SQLite** for storage, one file. Schema changes ship as **Alembic**
  migrations (`alembic upgrade head`).
- **TMDB** for availability, ratings and runtime, fetched once per film per
  refresh (a details call with providers appended) and cached.
- **Letterboxd** watchlist import via HTML scraping, one member at a time.
- **Films are deduplicated across members** and joined to them through
  `watchlist_entries`, so enrichment cost does not scale with household size.

```
src/screenseeker/
├── cli.py              # The CLI commands
├── settings.py         # Environment-resolved runtime settings
├── user_config.py      # config.toml read/write
├── database/           # SQLAlchemy models + session
├── enrichers/          # TMDB client + watch strategy
├── scrapers/           # Letterboxd import
├── services/           # Library, enrichment, watch, jobs, profile
└── web/                # FastAPI app, routes, templates, static, auth
migrations/             # Alembic migrations
deploy/                 # Production deployment kit
tests/                  # Test suite, mirrors src/
```

---

## Development

```bash
pip install -e '.[web]'
pre-commit install          # ruff, isort, mypy, bandit

pytest                      # run the suite
pytest tests/web -q         # a subset
```

New database columns need a migration:

```bash
alembic revision -m "describe the change"   # then edit the generated file
alembic upgrade head
```

Pre-commit runs ruff (lint + format), isort, mypy and bandit on every commit.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

**Made for cinephiles who want to actually watch their watchlist.**
