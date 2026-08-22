# Deploying on an Oracle Cloud Always Free VM (with DuckDNS)

An end-to-end, **$0** public deployment: an Oracle Always Free ARM VM, a free
DuckDNS domain, and Caddy for automatic HTTPS. This is the concrete version of
the public-internet path in [README.md](README.md); read that for the general
model. Everything here has been done on a live instance.

The shape of it: the VM runs the app on loopback under systemd, Caddy terminates
TLS and proxies to it, and DuckDNS gives you a hostname so Let's Encrypt can
issue a certificate (it won't for a bare IP).

---

## What you need

- An Oracle Cloud account (the Always Free tier is enough).
- A free [DuckDNS](https://duckdns.org) subdomain.
- Your TMDB API key and a password you choose.

A note on Always Free: the ARM **VM.Standard.A1.Flex** shape (1 OCPU / 6 GB is
plenty) is the one to use — it's roomier than the tiny E2 micro and stays free.
Capacity for it is often exhausted in a region ("Out of capacity" on create). If
you keep hitting that, upgrading the account to **Pay As You Go** removes the
free-tier capacity deprioritization; you still pay nothing as long as you only
run Always Free resources.

---

## 1. Create the VM

- **Compute → Instances → Create.**
- **Shape:** Ampere **VM.Standard.A1.Flex**, 1 OCPU / 6 GB.
- **Image:** Canonical **Ubuntu 24.04**.
- **Networking:** create a new VCN with a **public subnet**, and make sure
  **"Assign a public IPv4 address"** is on. (If the toggle is greyed out, the
  selected subnet is private — pick the public one.)
- **SSH keys:** upload your public key or download the generated key pair. You
  need the private key to log in.

Then reserve the public IP so it survives reboots: on the instance, open the
primary VNIC → **IPv4 Addresses** → edit the primary private IP → set the public
IP to **Reserved**. Note the resulting IP.

## 2. Open the firewall — both of them

Oracle has two independent firewalls. **Both** must allow 80 and 443, or the site
is unreachable even though everything else is right. This is the single most
common mistake.

**Cloud firewall** (Security List): in the instance's subnet → **Security List →
Add Ingress Rules**, add two stateful rules, source `0.0.0.0/0`, IP protocol TCP,
destination ports **80** and **443**. (22 is already open.)

**Instance firewall** (iptables): the Ubuntu image ships local rules that block
everything but 22. SSH in, then:

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

If `netfilter-persistent` is missing: `sudo apt install -y iptables-persistent`,
then run the `save` again.

## 3. SSH in and prep the system

```bash
ssh -i /path/to/your-key.key ubuntu@<reserved-ip>

sudo apt update && sudo apt -y upgrade
# sqlite3 is the CLI, not the Python module: deploy/backup.sh shells out to it
# for a consistent `.backup` snapshot. Without it the nightly backup cron fails
# every night into a log nobody reads.
sudo apt -y install git sqlite3
```

Python 3.14 is required and Ubuntu ships 3.12, so install 3.14 with `uv` (it has
prebuilt ARM CPython — no compiling):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv python install 3.14
```

Install Caddy (arm64 apt repo):

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy
```

## 4. Install the app

```bash
# Service user and data directories.
sudo useradd --system --home /opt/screenseeker screenseeker
sudo mkdir -p /opt/screenseeker /var/lib/screenseeker/backups
sudo chown -R screenseeker:screenseeker /opt/screenseeker /var/lib/screenseeker

# Put the 3.14 interpreter somewhere the service user can execute (not in a
# home directory, which the hardened unit's ProtectHome hides).
sudo mkdir -p /opt/python
sudo env UV_PYTHON_INSTALL_DIR=/opt/python $HOME/.local/bin/uv python install 3.14
sudo chmod -R a+rX /opt/python

# Clone.
sudo -u screenseeker git clone https://github.com/moukisei/screenseeker.git /opt/screenseeker
sudo -u screenseeker git -C /opt/screenseeker checkout main   # or your release branch

# Build the venv on 3.14 and install (with the web extras).
sudo env UV_PYTHON_INSTALL_DIR=/opt/python $HOME/.local/bin/uv venv --seed --python 3.14 /opt/screenseeker/.venv
cd /opt/screenseeker && sudo .venv/bin/pip install -e '.[web]'
sudo chown -R screenseeker:screenseeker /opt/screenseeker
```

## 5. Environment file

```bash
sudo install -m 600 -o root -g root /opt/screenseeker/deploy/screenseeker.env.example /etc/screenseeker.env
sudo nano /etc/screenseeker.env
```

Set:

```
SCREENSEEKER_PASSWORD=<a strong password>
SCREENSEEKER_SECRET_KEY=<output of: openssl rand -hex 32>
SCREENSEEKER_COOKIE_SECURE=true
TMDB_API_KEY=<your tmdb key>
SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db
SCREENSEEKER_DEBUG=false
```

Add one line the template doesn't include, so your config/profile is stored on
the writable data disk rather than the read-only code directory (the systemd
unit only grants write access to `/var/lib/screenseeker`):

```
SCREENSEEKER_CONFIG_PATH=/var/lib/screenseeker/config.toml
```

## 6. Migrate, configure, start

```bash
# Create the schema.
cd /opt/screenseeker
sudo -u screenseeker env SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db \
  .venv/bin/alembic upgrade head

# Setup wizard (Letterboxd username, base country, TMDB key, subscriptions),
# written to the path the service reads.
sudo -u screenseeker env \
  SCREENSEEKER_CONFIG_PATH=/var/lib/screenseeker/config.toml \
  SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db \
  .venv/bin/screenseeker config init

# Install and start the service.
sudo cp /opt/screenseeker/deploy/screenseeker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now screenseeker

# Confirm it's serving on loopback.
systemctl status screenseeker --no-pager
curl -sI http://127.0.0.1:8000/login
```

## 7. DuckDNS + TLS

Create a subdomain at [duckdns.org](https://duckdns.org), and set its **current
ip** to your **reserved public IP** (not the IP the page auto-fills, which is your
own browser's). Verify:

```bash
dig +short <yoursubdomain>.duckdns.org      # must return the reserved IP
```

Point Caddy at it:

```bash
sudo cp /opt/screenseeker/deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/screenseeker\.example\.com/<yoursubdomain>.duckdns.org/g' /etc/caddy/Caddyfile
grep duckdns /etc/caddy/Caddyfile          # confirm your real subdomain, not a placeholder
sudo systemctl reload caddy
sudo journalctl -u caddy -n 30 --no-pager  # look for "certificate obtained successfully"
```

Open `https://<yoursubdomain>.duckdns.org` — the login page, over HTTPS.

## 8. The household

`config init` adds you as the first member. Add everyone else who shares the
television — each is a Letterboxd account to scrape, not a login, so there is
still one password for the whole app:

```bash
sudo -u screenseeker env \
  SCREENSEEKER_CONFIG_PATH=/var/lib/screenseeker/config.toml \
  SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db \
  .venv/bin/screenseeker members add <username> --name "Their name"
```

Or do it from **Profile → Household** in the browser, which is easier and is
also where you rename, recolour, pause or remove someone.

## 9. First data load and schedule

From the web UI, click **Sync watchlists** then **Refresh availability** — on a
fresh database every film is "never checked", so one refresh fetches everything,
runtimes included. Or from the CLI (pass the same env vars as in step 6).

Sync scrapes each member in turn, so it takes roughly as long as one watchlist
times the number of people. It is one background job either way; the single
active job per kind is enforced by the schema.

Install the nightly refresh + backup cron:

```bash
sudo cp /opt/screenseeker/deploy/screenseeker.cron /etc/cron.d/screenseeker
```

Do not assume it works. A cron job that fails silently looks exactly like one
that has nothing to do, so run both by hand once and confirm they write:

```bash
sudo -u screenseeker bash -c 'set -a; . /etc/screenseeker.env; \
  /opt/screenseeker/deploy/backup.sh >> /var/lib/screenseeker/backup.log 2>&1'
cat /var/lib/screenseeker/backup.log
ls -l /var/lib/screenseeker/backups/
```

---

## Updating the deployment

```bash
cd /opt/screenseeker
sudo -u screenseeker git pull

# If the update added a migration. Pass the config path too, not just the
# database: a migration may read config.toml to backfill (the household one
# seeds your first member from it), and without it the fallback is silently
# worse.
sudo -u screenseeker env \
  SCREENSEEKER_DB_PATH=/var/lib/screenseeker/screenseeker.db \
  SCREENSEEKER_CONFIG_PATH=/var/lib/screenseeker/config.toml \
  .venv/bin/alembic upgrade head

sudo systemctl restart screenseeker
```

Back the database up before a migration that adds tables or moves data:
`sudo -u screenseeker /opt/screenseeker/deploy/backup.sh` (it reads
`SCREENSEEKER_DB_PATH` from the environment, so pass it the same way).

Template and static changes need the restart (Jinja caches templates in
production). Static assets are served fresh; hard-reload the browser to drop a
cached favicon or CSS.

---

## Troubleshooting

- **`https://` times out, cert never issues** — port 80 is blocked. Recheck
  *both* firewalls (step 2): the cloud Security List ingress rule, and
  `sudo iptables -L INPUT -n | grep -E 'dpt:(80|443)'` on the box.

- **`git pull` fails with "detected dubious ownership"**, or a follow-up
  `git config --global` fails with "Permission denied" on `.gitconfig` — some
  earlier command touched `/opt/screenseeker` as `root` or `ubuntu` instead of
  `sudo -u screenseeker`, leaving root-owned files in a tree git expects the
  running user to own. Fix both the damage and the check, once, as root:

  ```bash
  sudo chown -R screenseeker:screenseeker /opt/screenseeker
  sudo git config --system --add safe.directory /opt/screenseeker
  ```

  `--system` writes to `/etc/gitconfig` rather than `screenseeker`'s own
  `.gitconfig`, so it doesn't depend on that account's home directory being
  writable and won't need re-doing if ownership drifts again. The actual
  prevention is discipline, not config: always run git/pip/alembic against
  this tree as `sudo -u screenseeker`, never plain `sudo` or as `ubuntu`.
- **`dig` returns the wrong IP** — DuckDNS still points at your laptop or the old
  ephemeral IP. Fix the "current ip" field.
- **App logs `No config file found at /var/lib/screenseeker/config.toml`** — run
  the `config init` from step 6 with `SCREENSEEKER_CONFIG_PATH` set to that path.
- **After upgrading, Profile shows a member called "Household"** — the household
  migration could not read config.toml (it ran without `SCREENSEEKER_CONFIG_PATH`)
  and fell back to a placeholder that owns your existing films. `household` is
  not a real Letterboxd account, so syncing it fails. Fix it in this order:
  **add your real account, sync it, and only then remove `household`**. Removing
  it first deletes every film nobody else lists — which, at that point, is all
  of them.
- **`backup.sh: sqlite3: command not found`** — `sudo apt -y install sqlite3`.
  The Python module is built in; the command-line tool is a separate package,
  and `.backup` is what makes the snapshot consistent under WAL.
- **The cron never runs and leaves no log** — earlier versions of
  `screenseeker.cron` redirected to `/var/log/`, which is root-owned while the
  jobs run as `screenseeker`. The shell cannot create the file, so the
  redirection fails before the command does anything, and there is no log to
  explain it. Reinstall the current cron file (it writes to
  `/var/lib/screenseeker/`) and check `sudo grep CRON /var/log/syslog` for the
  old failures.
- **`pip install` fails building a wheel on ARM** — install build deps:
  `sudo apt install -y build-essential libffi-dev`, then retry.
- **Service won't start** — `journalctl -u screenseeker -n 50 --no-pager`. A
  common cause is the venv's Python living under a home directory that
  `ProtectHome` hides; keep the interpreter in `/opt/python` as in step 4.
