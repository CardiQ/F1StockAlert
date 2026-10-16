"""Fetch product pages with a real (headless) Google Chrome.

Many stores (e.g. the F1 store, run by Fanatics) sit behind Akamai bot protection that
rejects plain HTTP clients and stock Playwright. patchright + the real Chrome binary
passes the JS challenge.
"""
import os

from patchright.sync_api import sync_playwright

PROFILE_DIR = os.environ.get(
    "RESTOCK_PROFILE_DIR", os.path.expanduser("~/.cache/restock-watch/chrome-profile")
)
# Strings that mean the page's real data has rendered.
READY_MARKERS = ("__platform_data__", "application/ld+json", '"variants"')
BLOCKED_MARKERS = ("Access Denied", "sec-if-cpt-container")


class FetchError(Exception):
    pass


class Browser:
    def __enter__(self):
        self._pw = sync_playwright().start()
        headless = os.environ.get("RESTOCK_HEADLESS", "1") != "0"
        # "chrome" = installed Google Chrome (gets past bot protection far more often than
        # the bundled Chromium); set RESTOCK_BROWSER_CHANNEL=chromium to use the bundled one.
        channel = os.environ.get("RESTOCK_BROWSER_CHANNEL", "chrome")
        self.ctx = self._pw.chromium.launch_persistent_context(
            PROFILE_DIR, channel=channel, headless=headless, no_viewport=True,
            args=["--no-sandbox"] if os.geteuid() == 0 else [],   # root in Docker
        )
        return self

    def __exit__(self, *exc):
        self.ctx.close()
        self._pw.stop()

    def get(self, url, timeout_s=45):
        page = self.ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            html = ""
            for _ in range(timeout_s // 2):
                page.wait_for_timeout(2000)
                try:
                    html = page.content()
                except Exception:   # page navigated mid-read (challenge reload)
                    continue
                if any(m in html for m in READY_MARKERS):
                    return html
            if any(m in html for m in BLOCKED_MARKERS):
                raise FetchError("blocked by the site's bot protection")
            raise FetchError("page never showed product data")
        finally:
            page.close()
