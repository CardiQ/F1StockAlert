# restock-watch

Give it a product link, the option you want (e.g. size `XS`) and an email address. It checks
the page on a schedule you pick per watch (every 30 minutes by default, or as rarely as once a
week) and emails you when:

- that option is **back in stock**, or
- its **price drops** below the last price seen.

It also emails once if the page can't be read 6 checks in a row (e.g. the store started
blocking the checker).

Supported pages: Fanatics-run stores (F1 Store, fanatics.com, NFL/NBA shops…), Shopify
stores, and any page with schema.org product data. Pages are loaded in headless Google
Chrome (via [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)) because stores
like the F1 Store use Akamai bot protection that blocks plain HTTP clients.

## Setup

```bash
python3 -m venv ~/.venvs/restock-watch
~/.venvs/restock-watch/bin/pip install -r requirements.txt
cp .env.example .env   # fill in SMTP_USER / SMTP_PASSWORD (Gmail: use an App Password)
~/.venvs/restock-watch/bin/python watch.py test-email you@example.com
```

Requires Google Chrome installed.

## Usage

```bash
python watch.py add "https://f1store.formula1.com/en/red-bull-racing/oracle-red-bull-racing-pepe-jeans-jacket-navy-womens/t-76867505+p-57336965247946+z-8-3260788547" --option XS --email you@example.com
python watch.py add "<url>" --option M --email you@example.com --every 1w   # weekly
python watch.py list                       # state, interval, next check
python watch.py set-interval <id> weekly   # 30m, 6h, 1d, 1w, hourly, daily, weekly
python watch.py check                      # check the watches that are due, once
python watch.py check --all --dry-run      # check everything now; show what would be emailed
python watch.py run                        # stay running, check each watch when due
python watch.py remove <id>
```

If a check fails, that watch is retried within an hour even if its interval is a week.

`add` loads the page right away and lists the valid options if yours doesn't match.
Watches and their last-seen state live in `watches.json` (keep the repo private — it holds
email addresses).

## Running on a schedule

### Linux server (recommended for months-long runs)

**systemd** (Debian/Ubuntu):

```bash
git clone git@github.com:CardiQ/F1StockAlert.git && cd F1StockAlert
scripts/setup_linux.sh        # first run creates .env; fill in SMTP, run it again
journalctl -u restock-watch -f
```

This installs Google Chrome, a venv in `~/.venvs/restock-watch`, and a `restock-watch`
service running `watch.py run`. The service restarts if it crashes, comes back after a reboot,
and restarts once a day so Chrome can't build up leaked memory. Add watches with
`~/.venvs/restock-watch/bin/python watch.py add ...`; the running service picks them up within
5 minutes.

**Docker:**

```bash
cp .env.example .env          # fill in SMTP
docker compose up -d --build
docker compose run --rm restock-watch add "<url>" --option XS --email you@example.com --every 1w
docker compose run --rm restock-watch list
docker compose logs -f
```

State lives in `./data/watches.json`.

**Bot protection:** stores like the F1 Store run Akamai, which is much stricter with data-center
IPs (cloud VPSes, GitHub Actions) than with home connections. If the log shows
`blocked by the site's bot protection`, try a machine on a residential connection (e.g. a home
mini PC), or your Mac (below).

Google Chrome only ships for x86-64 Linux, so the server (or Docker host) must be x86-64, not ARM.

Run the checker in **one** place only. If a server and GitHub Actions both run it, you get
every email twice; disable the `check` workflow in the Actions tab once the server is up.

### GitHub Actions

`.github/workflows/check.yml` runs `check` every 30 minutes (only due watches are checked) and commits
the updated `watches.json`. Add repo secrets `SMTP_USER` and `SMTP_PASSWORD` (optionally
`SMTP_HOST`, `SMTP_PORT`). New watches can be added from the Actions tab → **add-watch** →
Run workflow.

Note: on a public repo, `watches.json` (including email addresses) is public.

### Your Mac

```bash
scripts/install_mac_schedule.sh
```

That installs a launchd job that runs `check` every 30 minutes while the Mac is awake and
pushes state back to the repo. (If you use both, they share state through git.)
