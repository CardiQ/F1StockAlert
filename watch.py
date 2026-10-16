#!/usr/bin/env python3
"""Watch a product option (e.g. size XS) and email when it's back in stock or cheaper.

  python watch.py add URL --option XS --email you@example.com
  python watch.py list
  python watch.py remove ID
  python watch.py check [--dry-run]
  python watch.py test-email you@example.com
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from restock.parsers import parse, pick_option

ROOT = os.path.dirname(os.path.abspath(__file__))
WATCHES_FILE = os.path.join(ROOT, "watches.json")
FAILURE_ALERT_AFTER = 6   # consecutive failed checks before emailing about it


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


def fetch_product(browser, url):
    html = browser.get(url)
    product = parse(html)
    if not product:
        raise RuntimeError("could not find product/option data on the page")
    return product


def cmd_add(args):
    from restock.fetch import Browser

    watches = load()
    wid = hashlib.sha1(f"{args.url}|{args.option}|{args.email}".encode()).hexdigest()[:8]
    if any(w["id"] == wid for w in watches):
        print(f"Already watching ({wid}).")
        return
    w = {"id": wid, "url": args.url, "option": args.option, "email": args.email,
         "created": now(), "title": None, "last_available": None, "last_price": None,
         "currency": None, "last_checked": None, "last_error": None, "error_streak": 0}
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
    watches.append(w)
    save(watches)
    print(f"Added watch {wid} -> {args.email}")


def cmd_list(_args):
    for w in load():
        state = {True: "in stock", False: "out of stock", None: "not checked"}[w["last_available"]]
        print(f"{w['id']}  [{w['option']}] {state}, {fmt_price(w['last_price'], w['currency'])}"
              f"  -> {w['email']}\n          {w['title'] or w['url']}")
        if w.get("last_error"):
            print(f"          last error: {w['last_error']} (x{w['error_streak']})")


def cmd_remove(args):
    watches = load()
    kept = [w for w in watches if w["id"] != args.id]
    if len(kept) == len(watches):
        sys.exit(f"No watch with id {args.id}")
    save(kept)
    print(f"Removed {args.id}")


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


def cmd_check(args):
    from restock.fetch import Browser
    from restock.notify import send_email

    watches = load()
    if not watches:
        print("No watches.")
        return
    sent = 0
    with Browser() as b:
        for w in watches:
            try:
                product = fetch_product(b, w["url"])
                opt = pick_option(product, w["option"])
                if not opt:
                    raise RuntimeError(f"option {w['option']!r} no longer listed "
                                       f"({', '.join(o.label for o in product.options)})")
            except Exception as e:
                w["error_streak"] = w.get("error_streak", 0) + 1
                w["last_error"] = str(e)[:300]
                w["last_checked"] = now()
                print(f"[{w['id']}] ERROR ({w['error_streak']}x): {e}")
                if w["error_streak"] == FAILURE_ALERT_AFTER and not args.dry_run:
                    send_email(w["email"], f"Restock watch can't read {w['title'] or w['url']}",
                               f"The last {FAILURE_ALERT_AFTER} checks failed: {e}\n\n{w['url']}\n")
                continue

            w["title"] = product.title
            alerts = build_alerts(w, opt)
            print(f"[{w['id']}] {opt.label}: {'IN STOCK' if opt.available else 'out of stock'}, "
                  f"{fmt_price(opt.price, opt.currency)}  ({len(alerts)} alert(s))")
            for subject, body in alerts:
                if args.dry_run:
                    print(f"  would email {w['email']}: {subject}")
                else:
                    send_email(w["email"], subject, body)
                    sent += 1
            w.update(last_available=opt.available, last_price=opt.price, currency=opt.currency,
                     last_checked=now(), last_error=None, error_streak=0)
    if not args.dry_run:
        save(watches)
    print(f"Done. {sent} email(s) sent.")


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
    a.add_argument("--no-verify", action="store_true", help="skip fetching the page now")
    a.set_defaults(func=cmd_add)
    sub.add_parser("list").set_defaults(func=cmd_list)
    r = sub.add_parser("remove")
    r.add_argument("id")
    r.set_defaults(func=cmd_remove)
    c = sub.add_parser("check", help="check all watches and send emails")
    c.add_argument("--dry-run", action="store_true", help="print alerts instead of emailing; don't save")
    c.set_defaults(func=cmd_check)
    t = sub.add_parser("test-email")
    t.add_argument("email")
    t.set_defaults(func=cmd_test_email)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
