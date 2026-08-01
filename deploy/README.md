# Deploying ScreenSeeker

Two ways to run this beyond your laptop. Pick one.

- **Tailscale** — bind to the tailnet, reach it from your own devices, no auth
  code and no TLS. Least moving parts. Recommended unless you specifically need
  public access.
- **Public internet** — a password, a session cookie, and Caddy for TLS. Every
  seam for this already exists in the code; this directory is the plumbing.

The app always binds to loopback (or the tailnet). It never faces the internet
directly — a reverse proxy does.

---

## Option A — Tailscale (no auth code)

1. Install Tailscale on the server and `tailscale up`.
2. Point the app at the tailnet address and leave the password empty:

   ```
   SCREENSEEKER_HOST=<your-tailscale-ip>   # or 127.0.0.1 and use `tailscale serve`
   SCREENSEEKER_PASSWORD=                   # empty: require_user stays a no-op
   SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db
   TMDB_API_KEY=...
   ```

3. Use the systemd unit below (drop `--proxy-headers`; there is no proxy).

Access control is the tailnet. `require_user` is a no-op, there is no login
page, and there is no TLS to manage. If you later want a password even here,
just set `SCREENSEEKER_PASSWORD` — nothing else changes.

---

## Option B — Public internet (password + TLS)

Files in this directory, in the order you install them:

| File | Where it goes | What it does |
|---|---|---|
| `screenseeker.env.example` | `/etc/screenseeker.env` (0600) | Secrets and paths. |
| `screenseeker.service` | `/etc/systemd/system/` | Runs the app on loopback. |
| `Caddyfile` | `/etc/caddy/Caddyfile` | TLS + reverse proxy. |
| `backup.sh` | `/opt/screenseeker/deploy/` | Consistent DB snapshot. |
| `screenseeker.cron` | `/etc/cron.d/screenseeker` | Nightly refresh + backup. |

### Steps

1. **User and directories**

   ```bash
   sudo useradd --system --home /opt/screenseeker screenseeker
   sudo mkdir -p /opt/screenseeker /var/lib/screenseeker/backups
   sudo chown -R screenseeker:screenseeker /opt/screenseeker /var/lib/screenseeker
   ```

2. **Code and venv** — clone into `/opt/screenseeker`, then:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e '.[web]'
   ```

3. **Environment** — fill in the env file, and *set a real password*:

   ```bash
   sudo install -m 600 -o root -g root deploy/screenseeker.env.example /etc/screenseeker.env
   sudo "$EDITOR" /etc/screenseeker.env
   ```

   The migration to the database schema runs from the checkout. Pass the config
   path as well as the database — a migration may read config.toml to backfill,
   and the household one seeds your first member from it:

   ```bash
   sudo -u screenseeker env \
     SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db \
     SCREENSEEKER_CONFIG_PATH=/var/lib/screenseeker/config.toml \
     .venv/bin/alembic upgrade head
   ```

4. **Service**

   ```bash
   sudo cp deploy/screenseeker.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now screenseeker
   journalctl -u screenseeker -f
   ```

5. **TLS** — edit the domain in the Caddyfile, then `sudo systemctl reload caddy`.
   Caddy obtains and renews the certificate itself.

6. **Schedule** — `sudo cp deploy/screenseeker.cron /etc/cron.d/screenseeker`.

### What the password buys you

Setting `SCREENSEEKER_PASSWORD` turns on, in one move:

- Every page requires a valid session cookie; anonymous requests are redirected
  to `/login` (htmx requests get an `HX-Redirect`).
- The session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` behind TLS.
- Every state-changing request is checked for a same-origin `Origin`/`Referer`
  header — the CSRF defence, cheap because every mutation is already a POST.

Unset it and all of that reverts to a no-op. There is no third state.

---

## A known sharp edge: the nightly refresh

The cron entry runs `screenseeker refresh --yes` directly against the database.
The **web** refresh takes a single-flight lock on the `jobs` table; the **CLI**
refresh does not, so in principle a 04:00 cron refresh and a refresh you start
from the web UI at the same moment can run at once.

For one user this is close to harmless: refresh only rewrites offers for films
that already exist (it cannot create the duplicate films a concurrent *sync*
could), SQLite's WAL mode and `busy_timeout` serialise the writes, and 04:00 is
not when you are clicking buttons. But it is not *guaranteed* safe. If you want
it to be, either move the cron to a `screenseeker` subcommand that claims a job
row first, or simply don't run the web refresh manually — the cron keeps things
fresh on its own.

`sync` is the one to never run concurrently with itself, and nothing here
schedules it: the watchlists change rarely, so run `screenseeker sync` by hand
when someone adds films. One run covers every active member.

---

## The household

Members live in the database, not in config.toml, so **backups are the only
copy**. `deploy/backup.sh` already covers them — it snapshots the whole file.

Two things to know before you touch the household on a server:

- **Removing a member deletes the films nobody else lists.** That is the point,
  but it means the order matters when you are fixing up a member: add and sync
  the replacement first, remove the old one second.
- **Pausing beats removing** when someone's profile goes private or they are
  just away. Clear the *Sync* checkbox on the profile page and their entries
  stay exactly as they are.
