"""
PropertyFinder Bahrain -- full catalogue scraper.

Strategy:
  1. DISCOVER: fetch each category page, extract subcategory links + counts
  2. AUTO-SPLIT: if a URL has >MAX_PAGES*PER_PAGE listings, drill into location sub-pages
  3. PAGINATE: for each final URL combo, paginate through all pages (multithreaded)
  4. DEDUP: merge listings by ID

Rate limiting:
  - 4 concurrent workers (conservative for a single domain)
  - 0.5s base delay between pages + random jitter (0.0-0.5s)
  - Each worker gets its own requests.Session (connection pooling per thread)
  - ~120 requests/min total -- well below typical server thresholds
"""

import json
import os
import random
import re
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

# ── Source of truth -- category entry points ──────────────────────────────────
# Price trends collection flag - set to True to enable detailed price history collection
# WARNING: This will significantly slow down scraping (potentially adding 1+ hour)
ENABLE_PRICE_TRENDS = False

CATEGORIES = [
    {
        "name": "residential_rent",
        "url": "https://www.propertyfinder.bh/en/rent/properties-for-rent.html",
        "data_key": "listings",
    },
    {
        "name": "residential_sale",
        "url": "https://www.propertyfinder.bh/en/buy/properties-for-sale.html",
        "data_key": "listings",
    },
    {
        "name": "commercial_rent",
        "url": "https://www.propertyfinder.bh/en/commercial-rent/properties-for-rent.html",
        "data_key": "listings",
    },
    {
        "name": "commercial_sale",
        "url": "https://www.propertyfinder.bh/en/search?c=3&fu=0&ob=mr",
        "data_key": "listings",
    },
    {
        "name": "new_projects",
        "url": "https://www.propertyfinder.bh/en/new-projects",
        "data_key": "projects",
    },
    {
        "name": "agents",
        "url": "https://www.propertyfinder.bh/en/find-agent/search",
        "data_key": "agents",
    },
]
# ─────────────────────────────────────────────────────────────────────────────

MAX_PAGES = 50
PER_PAGE = 25
MAX_LISTINGS = MAX_PAGES * PER_PAGE  # 1250

# Rate limiting
WORKERS = 4            # concurrent threads
BASE_DELAY = 0.5       # seconds between pages (per worker)
JITTER_MAX = 0.5       # random extra delay 0-0.5s

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# Thread-safe print
_print_lock = threading.Lock()

def safe_print(msg: str):
    with _print_lock:
        print(msg)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_html(url: str, session: requests.Session) -> str:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_next_data(html: str) -> dict:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def build_page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["page"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


def get_meta(next_data: dict) -> dict:
    sr = next_data.get("props", {}).get("pageProps", {}).get("searchResult", {})
    meta = sr.get("meta", {})
    return {
        "total_count": meta.get("total_count", 0),
        "page_count": meta.get("page_count", 0),
        "per_page": meta.get("per_page", 25),
        "page": meta.get("page", 1),
    }


def get_listings_from_page(next_data: dict, data_key: str) -> list:
    sr = next_data.get("props", {}).get("pageProps", {}).get("searchResult", {})
    if data_key == "listings":
        return sr.get("listings") or []
    elif data_key == "projects":
        data = sr.get("data") or {}
        return data.get("projects") or sr.get("projects") or []
    elif data_key == "agents":
        return sr.get("agents") or (sr.get("data") or {}).get("agents") or []
    else:
        return sr.get(data_key) or []


def discover_subcategory_links(html: str) -> list:
    links = []
    soup = BeautifulSoup(html, "html.parser")
    for a_tag in soup.find_all("a", href=True):
        text = a_tag.get_text(strip=True)
        match = re.match(r"^(.+?)\(([0-9,]+)\)$", text)
        if match:
            name = match.group(1).strip()
            count = int(match.group(2).replace(",", ""))
            href = a_tag["href"]
            if href.startswith("/en/") and count > 0:
                full_url = f"https://www.propertyfinder.bh{href}"
                links.append({"name": name, "url": full_url, "count": count})
    return links


def drill_level(session: requests.Session, parent_name: str, sub: dict, data_key: str, results: list, level: int):
    """Recursively drill into sub-pages until count <= MAX_LISTINGS."""
    indent = "      " + "  " * level
    sub_name = f"{parent_name}/{sub['name']}"
    sub_count = sub["count"]
    sub_url = sub["url"]

    if sub_count <= MAX_LISTINGS:
        safe_print(f"{indent}{sub_name}: {sub_count} - OK")
        results.append({"name": sub_name, "url": sub_url, "count": sub_count, "data_key": data_key})
        return

    safe_print(f"{indent}{sub_name}: {sub_count} - drilling...")
    time.sleep(BASE_DELAY + random.uniform(0, JITTER_MAX))

    try:
        html = fetch_html(sub_url, session)
    except Exception as e:
        safe_print(f"{indent}  Error: {e}, keeping as-is")
        results.append({"name": sub_name, "url": sub_url, "count": sub_count, "data_key": data_key})
        return

    deeper = discover_subcategory_links(html)
    if not deeper:
        safe_print(f"{indent}  No deeper links, keeping as-is")
        results.append({"name": sub_name, "url": sub_url, "count": sub_count, "data_key": data_key})
        return

    for d in deeper:
        drill_level(session, sub_name, d, data_key, results, level + 1)


def discover_and_split(category: dict, session: requests.Session) -> list:
    base_url = category["url"]
    data_key = category["data_key"]
    name = category["name"]

    print(f"\n  Discovering: {name}")

    html = fetch_html(base_url, session)
    next_data = parse_next_data(html)
    meta = get_meta(next_data)
    total = meta["total_count"]

    if data_key != "listings":
        print(f"    {name}: {total} records (non-listing, no split)")
        return [{"name": name, "url": base_url, "count": total, "data_key": data_key}]

    if total == 0:
        print(f"    {name}: no listings found")
        return []

    if total <= MAX_LISTINGS:
        print(f"    {name}: {total} listings - fits in single URL")
        return [{"name": name, "url": base_url, "count": total, "data_key": data_key}]

    print(f"    {name}: {total} listings - splitting...")

    sub_links = discover_subcategory_links(html)
    print(f"    Found {len(sub_links)} sub-links")

    results = []
    for sub in sub_links:
        drill_level(session, name, sub, data_key, results, level=0)

    total_split = sum(u["count"] for u in results)
    print(f"    Split into {len(results)} URLs, sum: {total_split}")
    return results


def fetch_price_trends(share_url: str, session: requests.Session) -> dict:
    """Fetch price trends data from a listing detail page."""
    try:
        html = fetch_html(share_url, session)
        next_data = parse_next_data(html)
        if not next_data:
            return {}

        page_props = next_data.get("props", {}).get("pageProps", {})
        price_trends = page_props.get("priceTrendsData", {})

        # Extract key trends data
        trends_summary = {
            "has_trends": bool(price_trends),
            "axis_label": price_trends.get("axisLabel", ""),
            "community_name": price_trends.get("communityName", ""),
            "tower_name": price_trends.get("towerName", ""),
        }

        # Add latest prices from different timeframes
        graph = price_trends.get("graph", {})
        for timeframe in ["1Y", "2Y", "5Y"]:
            if timeframe in graph and graph[timeframe]:
                latest = graph[timeframe][-1]  # Get most recent data point
                trends_summary[f"latest_{timeframe.lower()}_community_price"] = latest.get("communityPrice", "")
                trends_summary[f"latest_{timeframe.lower()}_tower_price"] = latest.get("towerPrice", "")
                trends_summary[f"latest_{timeframe.lower()}_date"] = latest.get("date", "")

        return trends_summary

    except Exception as e:
        safe_print(f"    Price trends fetch error: {e}")
        return {}

def scrape_url(url_info: dict) -> list:
    """Paginate through all pages of a single URL. Creates its own session (thread-safe)."""
    session = make_session()
    base_url = url_info["url"]
    data_key = url_info["data_key"]
    name = url_info["name"]
    all_records = []

    page = 1
    while page <= MAX_PAGES:
        url = build_page_url(base_url, page)
        try:
            html = fetch_html(url, session)
        except Exception as exc:
            safe_print(f"    {name} p{page} error: {exc}")
            break

        next_data = parse_next_data(html)
        records = get_listings_from_page(next_data, data_key)

        if not records:
            break

        # Add price trends data to each record (only for listings, not projects/agents)
        # NOTE: Price trends collection is disabled by default due to performance impact
        # To enable, set ENABLE_PRICE_TRENDS = True at the top of the file
        if data_key == "listings" and ENABLE_PRICE_TRENDS:
            for record in records:
                if isinstance(record, dict) and record.get("listing_type") == "property":
                    prop = record.get("property", {})
                    share_url = prop.get("share_url", "")
                    if share_url:
                        trends = fetch_price_trends(share_url, session)
                        record["price_trends"] = trends
                        # Small delay to avoid overwhelming the server
                        time.sleep(0.2)

        all_records.extend(records)
        safe_print(f"    {name} p{page}: +{len(records)} ({len(all_records)})")

        if len(records) < PER_PAGE:
            break

        page += 1
        time.sleep(BASE_DELAY + random.uniform(0, JITTER_MAX))

    return all_records


def scrape_category(plan: dict) -> tuple:
    """Scrape all URLs for a category using thread pool. Returns (cat_name, records_list)."""
    category = plan["category"]
    urls = plan["urls"]
    cat_name = category["name"]
    all_records = []
    seen_ids = set()

    safe_print(f"\n[{cat_name.upper()}] -- {len(urls)} URLs, {WORKERS} workers")

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(scrape_url, u): u for u in urls}
        for future in as_completed(futures):
            try:
                records = future.result()
            except Exception as e:
                url_info = futures[future]
                safe_print(f"    FAILED {url_info['name']}: {e}")
                continue

            new_count = 0
            for rec in records:
                # Skip non-listing records like project_recommendation
                if isinstance(rec, dict) and rec.get("listing_type") not in ["property", None]:
                    continue

                rec_id = None
                if isinstance(rec, dict):
                    prop = rec.get("property") or {}
                    rec_id = prop.get("id") or rec.get("id")
                if rec_id and rec_id not in seen_ids:
                    seen_ids.add(rec_id)
                    all_records.append(rec)
                    new_count += 1
                elif not rec_id:
                    all_records.append(rec)
                    new_count += 1

    return cat_name, all_records


def main():
    scrape_start = datetime.now(timezone.utc).isoformat()
    os.makedirs(RAW_DIR, exist_ok=True)

    print(f"Starting scrape -- {len(CATEGORIES)} categories")
    print(f"Config: {WORKERS} workers, {BASE_DELAY}s delay + {JITTER_MAX}s jitter")
    print(f"Max {MAX_PAGES} pages/URL, {PER_PAGE}/page, {MAX_LISTINGS} max/URL")

    discovery_session = make_session()

    # Phase 1: Discover all URLs (sequential -- each level depends on previous)
    all_url_plans = []
    for category in CATEGORIES:
        urls = discover_and_split(category, discovery_session)
        all_url_plans.append({"category": category, "urls": urls})
        time.sleep(BASE_DELAY)

    total_urls = sum(len(p["urls"]) for p in all_url_plans)
    total_expected = sum(sum(u["count"] for u in p["urls"]) for p in all_url_plans)
    print(f"\n{'='*60}")
    print(f"Discovery: {total_urls} URLs, ~{total_expected} expected listings")
    print(f"{'='*60}")

    # Phase 2: Scrape all categories (parallel across categories)
    summary = {}
    for plan in all_url_plans:
        cat_name, records = scrape_category(plan)

        out_path = os.path.join(RAW_DIR, f"{cat_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        summary[cat_name] = len(records)
        safe_print(f"  {cat_name}: {len(records)} unique records -> {out_path}")

    manifest = {
        "scraped_at": scrape_start,
        "categories": len(CATEGORIES),
        "counts": summary,
        "total": sum(summary.values()),
    }
    with open(os.path.join(RAW_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {manifest['total']} total records in {len(CATEGORIES)} categories.")


if __name__ == "__main__":
    main()
