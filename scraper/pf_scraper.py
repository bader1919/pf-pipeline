"""
PropertyFinder Bahrain — full catalogue scraper.
Step 1: Discover all search categories from the site navigation (no hardcoding).
Step 2: Scrape every page of every category until exhausted.
Saves raw JSON per category to data/raw/.
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

BASE_URL = "https://www.propertyfinder.bh"

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


def fetch_page(url: str, session: requests.Session) -> str | None:
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.text
        print(f"  HTTP {r.status_code} for {url}")
        return None
    except Exception as exc:
        print(f"  Network error for {url}: {exc}")
        return None


def parse_next_data(html: str) -> dict:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def discover_categories(session: requests.Session) -> list[dict]:
    """
    Fetch the homepage and extract all search category URLs from __NEXT_DATA__.
    Returns a list of {name, url} dicts — one per discovered category.
    """
    print("Discovering categories from homepage...")
    html = fetch_page(BASE_URL + "/en", session)
    if not html:
        html = fetch_page(BASE_URL, session)
    if not html:
        print("  Could not reach homepage.")
        return []

    data = parse_next_data(html)
    page_props = data.get("props", {}).get("pageProps", {})

    categories = []
    seen_urls = set()

    # Look for navigation links, category links, or search links in __NEXT_DATA__
    def walk(obj, depth=0):
        if depth > 12 or not obj:
            return
        if isinstance(obj, dict):
            # Look for objects that look like nav/category items with a URL
            url = obj.get("url") or obj.get("href") or obj.get("link") or obj.get("path") or ""
            label = (
                obj.get("label") or obj.get("name") or obj.get("title")
                or obj.get("text") or obj.get("slug") or ""
            )
            if isinstance(url, str) and isinstance(label, str):
                # Filter: must be a search-style URL on propertyfinder.bh
                full_url = urljoin(BASE_URL, url) if url.startswith("/") else url
                if (
                    "propertyfinder.bh" in full_url
                    and any(kw in full_url for kw in ["/rent/", "/buy/", "/search"])
                    and full_url not in seen_urls
                    and label.strip()
                ):
                    # Strip any existing page param so we start from page 1
                    parsed = urlparse(full_url)
                    qs = parse_qs(parsed.query)
                    qs.pop("page", None)
                    clean_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
                    seen_urls.add(full_url)
                    safe_name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                    categories.append({"name": safe_name, "base_url": clean_url, "label": label})
            for v in obj.values():
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(page_props)

    # Fallback: scan all anchor hrefs in the raw HTML
    if not categories:
        print("  __NEXT_DATA__ navigation not found — scanning HTML links...")
        for match in re.finditer(r'href="(/en/(?:rent|buy)/[^"]+\.html)"', html):
            path = match.group(1)
            full_url = BASE_URL + path
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                # Derive a name from the path
                safe_name = re.sub(r"[^a-z0-9]+", "_", path.split("/")[-1].replace(".html", "")).strip("_")
                categories.append({"name": safe_name, "base_url": full_url, "label": safe_name})

    print(f"  Found {len(categories)} categories:")
    for c in categories:
        print(f"    - {c['label']} -> {c['base_url']}")

    return categories


def scrape_category(category: dict, session: requests.Session) -> list:
    """
    Scrape all pages of a single category. Stops when a page returns no listings.
    """
    name     = category["name"]
    base_url = category["base_url"]
    all_records = []
    total_reported = None

    print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {category['label'].upper()}")

    page = 1
    while True:
        # Build page URL — handle both ?page=N and existing query strings
        parsed = urlparse(base_url)
        qs = parse_qs(parsed.query)
        qs["page"] = [str(page)]
        url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

        html = fetch_page(url, session)
        if not html:
            print(f"  Page {page} failed — stopping.")
            break

        next_data = parse_next_data(html)
        search_result = (
            next_data.get("props", {})
                     .get("pageProps", {})
                     .get("searchResult") or {}
        )

        listings = search_result.get("listings") or []
        total    = search_result.get("totalCount") or search_result.get("total") or 0

        if total_reported is None and total:
            total_reported = int(total)
            print(f"  Total available: {total_reported}")

        if not listings:
            print(f"  No listings on page {page} — done. Collected: {len(all_records)}")
            break

        all_records.extend(listings)
        pct = f"{len(all_records)}/{total_reported}" if total_reported else str(len(all_records))
        print(f"  Page {page}: +{len(listings)} ({pct})")

        page += 1
        time.sleep(1.5)

    return all_records


def main():
    scrape_start = datetime.now(timezone.utc).isoformat()
    os.makedirs(RAW_DIR, exist_ok=True)
    summary = {}

    with requests.Session() as session:
        # Step 1: discover all categories dynamically
        categories = discover_categories(session)

        if not categories:
            print("No categories found — cannot continue.")
            return

        # Step 2: scrape every category, all pages
        for category in categories:
            records = scrape_category(category, session)
            out_path = os.path.join(RAW_DIR, f"{category['name']}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False)
            summary[category["name"]] = len(records)
            print(f"  Saved {len(records)} records -> {out_path}")

    # Write manifest
    manifest = {
        "scraped_at": scrape_start,
        "categories_found": len(categories),
        "counts": summary,
        "total": sum(summary.values()),
    }
    with open(os.path.join(RAW_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. {len(categories)} categories, {manifest['total']} total listings.")


if __name__ == "__main__":
    main()
