"""Product suggestions for predicted conditions.

The curated catalogue (``amazon_categories.xlsx``) maps a condition to an Amazon
affiliate short link. Instead of showing screenshots of Amazon, we render live
cards from that data:

* every link is validated (https + known Amazon hosts only),
* the short link is *resolved* with a single redirect lookup so the card can show
  the real search terms and store region,
* conditions without a curated link get a plain Amazon search for the same region.

We never download or scrape Amazon pages -- only the ``Location`` header of the
short link is read, which is cheap, allowed, and does not break when Amazon changes
its HTML.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
import pandas as pd

log = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).with_name("amazon_categories.xlsx")
DEFAULT_DOMAIN = "www.amazon.in"  # the curated catalogue is for the Indian store
RESOLVE_TIMEOUT = 4.0
CACHE_TTL = 24 * 3600
_SHORT_HOSTS = {"amzn.to", "a.co", "amzn.in", "amzn.eu"}
# Exact store domains only. A loose "startswith('amazon.')" test would accept
# lookalikes such as amazon.evil.com.
_STORE_HOST = re.compile(
    r"^(www\.)?amazon\.(com|in|de|fr|it|es|nl|se|pl|ca|sg|ae|sa|eg|"
    r"co\.uk|co\.jp|com\.au|com\.br|com\.mx|com\.tr|com\.be)$"
)


def is_allowed_url(url: str) -> bool:
    """True for https links to Amazon stores or its official short-link domains."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or not host:
        return False
    return host in _SHORT_HOSTS or bool(_STORE_HOST.match(host))


@dataclass(frozen=True)
class Product:
    condition: str
    url: str
    curated: bool  # False => generic fallback search, not an affiliate link
    search_terms: str | None = None  # what the link searches for, if we could tell
    domain: str = DEFAULT_DOMAIN


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, str]:
    """Read the spreadsheet once. Invalid rows are skipped, not fatal."""
    try:
        df = pd.read_excel(CATALOG_PATH)
    except Exception:  # missing/corrupt file must not take the whole app down
        log.exception("Could not read %s", CATALOG_PATH)
        return {}

    catalog: dict[str, str] = {}
    for _, row in df.iterrows():
        name = str(row.get("class", "")).strip()
        url = str(row.get("profit_link", "")).strip()
        if not name or name in catalog:
            continue
        if not is_allowed_url(url):
            log.warning("Ignoring non-Amazon or non-https link for %r", name)
            continue
        catalog[name] = url
    return catalog


# --- link resolution --------------------------------------------------------

_resolve_cache: dict[str, tuple[float, tuple[str | None, str | None]]] = {}
_resolve_lock = threading.Lock()


def _resolve_uncached(url: str, client: httpx.Client) -> tuple[str | None, str | None]:
    """Return (search_terms, domain) from the redirect target, or (None, None)."""
    try:
        resp = client.head(url, follow_redirects=False, timeout=RESOLVE_TIMEOUT)
        location = resp.headers.get("location", "")
    except httpx.HTTPError:
        return None, None
    if resp.status_code not in (301, 302, 303, 307, 308) or not is_allowed_url(location):
        return None, None
    parsed = urlparse(location)
    terms = parse_qs(parsed.query).get("k", [None])[0]
    return (terms.strip() if terms else None), parsed.hostname


def resolve_link(url: str, client: httpx.Client | None = None) -> tuple[str | None, str | None]:
    """Cached redirect lookup. Failures are *not* cached so the next run retries."""
    now = time.time()
    with _resolve_lock:
        hit = _resolve_cache.get(url)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    own_client = client is None
    client = client or httpx.Client(headers={"User-Agent": "Mozilla/5.0 FaceSkinAI-link-check"})
    try:
        result = _resolve_uncached(url, client)
    finally:
        if own_client:
            client.close()

    if result != (None, None):
        with _resolve_lock:
            _resolve_cache[url] = (now, result)
    return result


def fallback_url(condition: str, domain: str = DEFAULT_DOMAIN) -> str:
    return f"https://{domain}/s?k={quote_plus(condition.lower() + ' treatment for face')}"


def build_products(conditions: list[str], client: httpx.Client | None = None) -> list[Product]:
    """Cards for ``conditions`` in the given order (callers pass most-likely first)."""
    catalog = load_catalog()

    curated = {c: catalog[c] for c in conditions if c in catalog}
    resolved: dict[str, tuple[str | None, str | None]] = {}
    if curated:
        with ThreadPoolExecutor(max_workers=len(curated)) as pool:
            futures = {c: pool.submit(resolve_link, u, client) for c, u in curated.items()}
            resolved = {c: f.result() for c, f in futures.items()}

    # Region for fallback links: follow whatever the curated links resolved to.
    domains = [d for _, d in resolved.values() if d]
    region = domains[0] if domains else DEFAULT_DOMAIN

    products = []
    for cond in conditions:
        if cond in catalog:
            terms, domain = resolved[cond]
            products.append(Product(cond, catalog[cond], True, terms, domain or region))
        else:
            products.append(Product(cond, fallback_url(cond, region), False, None, region))
    return products
