# restock-watch

Give it a product link, the option you want (e.g. size `XS`) and an email address. It checks
the page every 30 minutes and emails you when:

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
python watch.py list
python watch.py check            # check now and send emails
python watch.py check --dry-run  # show what would be emailed
python watch.py remove <id>
```

`add` loads the page right away and lists the valid options if yours doesn't match.
Watches and their last-seen state live in `watches.json` (keep the repo private — it holds
email addresses).

## Running on a schedule

**GitHub Actions** (`.github/workflows/check.yml`) runs `check` every 30 minutes and commits
the updated `watches.json`. Add repo secrets `SMTP_USER` and `SMTP_PASSWORD` (optionally
`SMTP_HOST`, `SMTP_PORT`). New watches can be added from the Actions tab → **add-watch** →
Run workflow.

Stores with bot protection may block GitHub's data-center IPs. If the `check` runs log
`blocked by the site's bot protection`, run it from your Mac instead:

```bash
scripts/install_mac_schedule.sh
```

That installs a launchd job that runs `check` every 30 minutes while the Mac is awake and
pushes state back to the repo. (If you use both, they share state through git.)
