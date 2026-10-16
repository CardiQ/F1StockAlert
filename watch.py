#!/usr/bin/env python3
"""Watch a product option (e.g. size XS) and email when it's back in stock or cheaper.

  python watch.py add URL --option XS --email you@example.com [--every 1w]
  python watch.py list
  python watch.py set-interval ID 1w
  python watch.py remove ID
  python watch.py check [--dry-run] [--all]   # check watches that are due, once
  python watch.py run                         # stay running; check each watch when due
  python watch.py test-email you@example.com

Intervals: 30m, 6h, 1d, 1w, or hourly / daily / weekly. Default 30m.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from restock.parsers import parse, pick_option

ROOT = os.path.dirname(os.path.abspath(__file__))
WATCHES_FILE = os.environ.get("RESTOCK_WATCHES", os.path.join(ROOT, "watches.json"))
FAILURE_ALERT_AFTER = 6       # consecutive failed checks before emailing about it
DEFAULT_EVERY = "30m"
ERROR_RETRY_S = 3600          # after a failed check, retry within an hour even for weekly watches
DUE_SLACK_S = 300             # treat a watch as due a little early, so cron jitter doesn't skip a cycle
STATE_FIELDS = ("title", "last_available", "last_price", "currency",
                "last_checked", "last_error", "error_streak")
UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
NAMED = {"hourly": "1h", "daily": "1d", "weekly": "1w"}


def log(msg):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_every(text):
    """'1w' -> 604800 seconds. Raises ValueError on junk."""
    text = NAMED.get(text.strip().lower(), text.strip().lower())
    m = re.fullmatch(r"(\d+)\s*([mhdw])", text)
    if not m or int(m.group(1)) == 0:
        raise ValueError(f"bad interval {text!r}; use e.g. 30m, 6h, 1d, 1w, weekly")
    return int(m.group(1)) * UNITS[m.group(2)]


def every_arg(text):
    try:
        parse_every(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    return NAMED.get(text.strip().lower(), text.strip().lower())


@contextmanager
def locked():
    """Exclusive lock around read-modify-write of watches.json (CLI vs. running daemon)."""
    with open(WATCHES_FILE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load():
    if not os.path.exists(WATCHES_FILE):
        return []
    with open(WATCHES_FILE) as f:
        return json.load(f)


def save(watches):
    tmp = WATCHES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(watches, f, indent=2)
        f.write("\n")
    os.replace(tmp, WATCHES_FILE)


def fmt_price(price, currency):
    if price is None:
        return "?"
    return f"{currency + ' ' if currency else ''}{price:,.2f}"


def seconds_until_due(w, at=None):
    at = at or time.time()
    if not w.get("last_checked"):
        return 0
    interval = parse_every(w.get("every") or DEFAULT_EVERY)
    if w.get("error_streak"):
        interval = min(interval, ERROR_RETRY_S)
    last = datetime.fromisoformat(w["last_checked"]).timestamp()
    return last + interval - DUE_SLACK_S - at


def fetch_product(browser, url):
    html = browser.get(url)
    product = parse(html)
    if not product:
        raise RuntimeError("could not find product/option data on the page")
    return product


def cmd_add(args):
    from restock.fetch import Browser

    wid = hashlib.sha1(f"{args.url}|{args.option}|{args.email}".encode()).hexdigest()[:8]
    if any(w["id"] == wid for w in load()):
        print(f"Already watching ({wid}).")
        return
    w = {"id": wid, "url": args.url, "option": args.option, "email": args.email,
         "every": args.every, "created": now(), "title": None, "last_available": None,
         "last_price": None, "currency": None, "last_checked": None, "last_error": None,
         "error_streak": 0}
    if not args.no_verify:
        with Browser() as b:
            product = fetch_product(b, args.url)
        opt = pick_option(product, args.option)
        if not opt:
            labels = ", ".join(o.label for o in product.options)
            sys.exit(f"Option {args.option!r} not found on {product.title!r}. Options: {labels}")
        w["title"], w["option"] = product.title, opt.label
        print(f"{product.title} — {opt.label}: "
              f"{'IN STOCK' if opt.available else 'out of stock'}, {fmt_price(opt.price, opt.currency)}")
    with locked():
        watches = load()
        watches.append(w)
        save(watches)
    print(f"Added watch {wid} -> {args.email}, checked every {args.every}")


def cmd_list(_args):
    for w in load():
        state = {True: "in stock", False: "out of stock", None: "not checked"}[w["last_available"]]
        due = seconds_until_due(w)
        due_s = "due now" if due <= 0 else f"next in {due / 3600:.1f}h"
        print(f"{w['id']}  [{w['option']}] {state}, {fmt_price(w['last_price'], w['currency'])}"
              f"  -> {w['email']}  (every {w.get('every') or DEFAULT_EVERY}, {due_s})"
              f"\n          {w['title'] or w['url']}")
        if w.get("last_error"):
            print(f"          last error: {w['last_error']} (x{w['error_streak']})")


def _edit(wid, fn):
    with locked():
        watches = load()
        hits = [w for w in watches if w["id"] == wid]
        if not hits:
            sys.exit(f"No watch with id {wid}")
        save(fn(watches, hits[0]))


def cmd_remove(args):
    _edit(args.id, lambda ws, w: [x for x in ws if x is not w])
    print(f"Removed {args.id}")


def cmd_set_interval(args):
    def fn(ws, w):
        w["every"] = args.every
        return ws
    _edit(args.id, fn)
    print(f"{args.id} now checked every {args.every}")


def build_alerts(w, opt):
    """Compare with the last check; return (subject, body) pairs to send."""
    alerts = []
    name = f"{w['title'] or 'Product'} ({w['option']})"
    price = fmt_price(opt.price, opt.currency)
    if opt.available and w["last_available"] is not True:
        alerts.append((f"Back in stock: {name}",
                       f"{name} is available now at {price}.\n\n{w['url']}\n"))
    if (opt.price is not None and w["last_price"] is not None
            and opt.price < w["last_price"] - 0.005):
        old = fmt_price(w["last_price"], w["currency"])
        stock = "in stock" if opt.available else "still out of stock"
        alerts.append((f"Price drop: {name} {old} -> {price}",
                       f"{name} dropped from {old} to {price} ({stock}).\n\n{w['url']}\n"))
    return alerts


def check_one(browser, w, dry_run):
    """Check one watch, email if needed, and update its state fields in place."""
    from restock.notify import send_email

    try:
        product = fetch_product(browser, w["url"])
        opt = pick_option(product, w["option"])
        if not opt:
            raise RuntimeError(f"option {w['option']!r} no longer listed "
                               f"({', '.join(o.label for o in product.options)})")
    except Exception as e:
        w["error_streak"] = (w.get("error_streak") or 0) + 1
        w["last_error"] = str(e)[:300]
        w["last_checked"] = now()
        log(f"[{w['id']}] ERROR ({w['error_streak']}x): {e}")
        if w["error_streak"] == FAILURE_ALERT_AFTER and not dry_run:
            try:
                send_email(w["email"], f"Restock watch can't read {w['title'] or w['url']}",
                           f"The last {FAILURE_ALERT_AFTER} checks failed: {e}\n\n{w['url']}\n")
            except Exception as mail_err:
                log(f"[{w['id']}] could not send failure email: {mail_err}")
        return 0

    w["title"] = product.title
    alerts = build_alerts(w, opt)
    log(f"[{w['id']}] {opt.label}: {'IN STOCK' if opt.available else 'out of stock'}, "
        f"{fmt_price(opt.price, opt.currency)}  ({len(alerts)} alert(s))")
    sent = 0
    for subject, body in alerts:
        if dry_run:
            log(f"  would email {w['email']}: {subject}")
            continue
        try:
            send_email(w["email"], subject, body)
            sent += 1
        except Exception as e:
            # Leave the old state so the same alert is tried again next check.
            log(f"[{w['id']}] could not send email: {e}")
            w["last_checked"] = now()
            return sent
    w.update(last_available=opt.available, last_price=opt.price, currency=opt.currency,
             last_checked=now(), last_error=None, error_streak=0)
    return sent


def run_due(force=False, dry_run=False):
    """Check every watch that is due (or all, if force). Returns emails sent."""
    from restock.fetch import Browser

    due = [w for w in load() if force or seconds_until_due(w) <= 0]
    if not due:
        return 0
    sent = 0
    with Browser() as b:
        for w in due:
            sent += check_one(b, w, dry_run)
    if not dry_run:
        # Merge state into the current file, so watches added/removed meanwhile survive.
        with locked():
            watches = load()
            by_id = {w["id"]: w for w in due}
            for w in watches:
                if w["id"] in by_id:
                    w.update({k: by_id[w["id"]].get(k) for k in STATE_FIELDS})
            save(watches)
    return sent


def cmd_check(args):
    if not load():
        print("No watches.")
        return
    sent = run_due(force=args.all, dry_run=args.dry_run)
    log(f"Done. {sent} email(s) sent.")


def cmd_run(args):
    """Long-running loop for a server: check each watch when it's due, forever."""
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    log(f"restock-watch running; state in {WATCHES_FILE}")
    while not stop:
        try:
            run_due()
        except Exception as e:   # never let one bad cycle kill a months-long run
            log(f"cycle failed: {e!r}")
        waits = [seconds_until_due(w) for w in load()]
        # Re-read the file at least every poll interval to pick up newly added watches.
        sleep_s = max(30, min([args.poll] + [w for w in waits if w > 0]))
        for _ in range(int(sleep_s)):
            if stop:
                break
            time.sleep(1)
    log("stopped")


def cmd_test_email(args):
    from restock.notify import send_email

    send_email(args.email, "Restock watch test", "Email notifications are working.\n")
    print(f"Sent test email to {args.email}")


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="watch a product option")
    a.add_argument("url")
    a.add_argument("--option", required=True, help="option label as shown on the page, e.g. XS")
    a.add_argument("--email", required=True, help="address to notify")
    a.add_argument("--every", type=every_arg, default=DEFAULT_EVERY,
                   help="how often to check: 30m, 6h, 1d, 1w, weekly (default 30m)")
    a.add_argument("--no-verify", action="store_true", help="skip fetching the page now")
    a.set_defaults(func=cmd_add)
    sub.add_parser("list").set_defaults(func=cmd_list)
    r = sub.add_parser("remove")
    r.add_argument("id")
    r.set_defaults(func=cmd_remove)
    s = sub.add_parser("set-interval", help="change how often a watch is checked")
    s.add_argument("id")
    s.add_argument("every", type=every_arg)
    s.set_defaults(func=cmd_set_interval)
    c = sub.add_parser("check", help="check the watches that are due, once")
    c.add_argument("--all", action="store_true", help="check every watch, due or not")
    c.add_argument("--dry-run", action="store_true", help="print alerts instead of emailing; don't save")
    c.set_defaults(func=cmd_check)
    rn = sub.add_parser("run", help="keep running and check each watch when due (for servers)")
    rn.add_argument("--poll", type=int, default=300, help="max seconds between looks at watches.json")
    rn.set_defaults(func=cmd_run)
    t = sub.add_parser("test-email")
    t.add_argument("email")
    t.set_defaults(func=cmd_test_email)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
