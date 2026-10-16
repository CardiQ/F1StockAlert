"""Turn a product page's HTML into a list of options with availability and price.

Each parser returns a list of Option, or None if it doesn't recognise the page.
"""
import json
import re
from dataclasses import dataclass


@dataclass
class Option:
    label: str          # e.g. "XS"
    available: bool
    price: float | None
    currency: str | None


@dataclass
class Product:
    title: str
    options: list[Option]
    source: str         # which parser produced this


def _num(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _extract_js_object(html, marker):
    """Decode the JSON literal that follows `marker` (e.g. 'var __platform_data__=')."""
    i = html.find(marker)
    if i < 0:
        return None
    i += len(marker)
    while html[i] in " =\t\n":
        i += 1
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, i)
    except json.JSONDecodeError:
        return None
    return obj


def _title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# --- Fanatics platform (f1store.formula1.com, fanatics.com, nflshop.com, ...) ---

def _find_size_lists(node):
    if isinstance(node, list):
        if node and all(isinstance(x, dict) and "size" in x and "available" in x for x in node):
            yield node
        for x in node:
            yield from _find_size_lists(x)
    elif isinstance(node, dict):
        for v in node.values():
            yield from _find_size_lists(v)


def _fanatics_price(size):
    card = size.get("priceCard") or {}
    prices = card.get("prices") or []
    lowest = card.get("lowestPrice")
    for p in prices:
        if p.get("priceType") == lowest and p.get("price"):
            return _num(p["price"].get("userCurrencyValue")), p["price"].get("userCurrencyCode")
    price = size.get("price") or {}
    for key in ("discountPrice", "sale", "regular"):
        money = (price.get(key) or {}).get("money") or {}
        if money.get("userCurrencyValue"):
            return _num(money["userCurrencyValue"]), money.get("userCC")
    return None, None


def parse_fanatics(html):
    data = _extract_js_object(html, "var __platform_data__")
    if not data:
        return None
    pdp = data.get("pdp-data") or data
    seen, options = set(), []
    for sizes in _find_size_lists(pdp):
        for s in sizes:
            label = str(s.get("size", "")).strip()
            if not label or label in seen:
                continue
            seen.add(label)
            price, cur = _fanatics_price(s)
            options.append(Option(label, bool(s.get("available")), price, cur))
    if not options:
        return None
    return Product(_title(html), options, "fanatics")


# --- Shopify (product JSON embedded in the page) ---

def parse_shopify(html):
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        prod = obj.get("product", obj) if isinstance(obj, dict) else None
        if not isinstance(prod, dict) or not isinstance(prod.get("variants"), list):
            continue
        variants = prod["variants"]
        if not variants or "available" not in variants[0]:
            continue
        options = []
        for v in variants:
            price = _num(v.get("price"))
            if isinstance(v.get("price"), int):   # Shopify cents
                price = v["price"] / 100
            options.append(Option(str(v.get("title") or v.get("public_title")), bool(v["available"]), price, None))
        return Product(prod.get("title") or _title(html), options, "shopify")
    return None


# --- Generic schema.org JSON-LD ---

def _ld_nodes(html):
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        stack = [obj]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
            elif isinstance(n, dict):
                yield n
                stack.extend(n.get("@graph", []) if isinstance(n.get("@graph"), list) else [])


def _offer_option(label, offer):
    spec = offer.get("priceSpecification") or {}
    price = _num(offer.get("price", spec.get("price")))
    cur = offer.get("priceCurrency", spec.get("priceCurrency"))
    avail = "instock" in str(offer.get("availability", "")).lower().replace("_", "")
    return Option(label, avail, price, cur)


def parse_jsonld(html):
    for n in _ld_nodes(html):
        types = n.get("@type")
        types = types if isinstance(types, list) else [types]
        if "ProductGroup" in types and n.get("hasVariant"):
            opts = []
            for v in n["hasVariant"]:
                offer = v.get("offers") or {}
                offer = offer[0] if isinstance(offer, list) else offer
                label = v.get("size") or v.get("name") or v.get("sku")
                opts.append(_offer_option(str(label), offer))
            return Product(n.get("name") or _title(html), opts, "jsonld-variants")
        if "Product" in types and n.get("offers"):
            offers = n["offers"] if isinstance(n["offers"], list) else [n["offers"]]
            opts = [_offer_option(str(o.get("name") or o.get("sku") or "default"), o) for o in offers]
            return Product(n.get("name") or _title(html), opts, "jsonld")
    return None


PARSERS = [parse_fanatics, parse_shopify, parse_jsonld]


def parse(html):
    for p in PARSERS:
        product = p(html)
        if product:
            return product
    return None


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def pick_option(product, wanted):
    """Find the option matching `wanted` (case/punctuation-insensitive)."""
    if wanted is None and len(product.options) == 1:
        return product.options[0]
    w = norm(wanted or "")
    for o in product.options:
        if norm(o.label) == w:
            return o
    return None
