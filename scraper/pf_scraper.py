"""
PropertyFinder Bahrain — full catalogue scraper.

Source-of-truth category URLs are defined here.
Scrapes every page of every category until exhausted.
Saves raw JSON per category to data/raw/.
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# ── Source of truth — category URLs ──────────────────────────────────────────
CATEGORIES = [
    {
        "name":    "residential_rent",
        "url":     "https://www.propertyfinder.bh/en/rent/properties-for-rent.html",
        "data_key": "listings",          # searchResult.listings
    },
    {
        "name":    "residential_sale",
        "url":     "https://www.propertyfinder.bh/en/buy/properties-for-sale.html",
        "data_key": "listings",
    },
    {
        "name":    "commercial_rent",
        "url":     "https://www.propertyfinder.bh/en/commercial-rent/properties-for-rent.html",
        "data_key": "listings",
    },
    {
        "name":    "commercial_sale",
        "url":     "https://www.propertyfinder.bh/en/search?c=3&fu=0&ob=mr",
        "data_key": "listings",
    },
    {
        "name":    "new_projects",
        "url":     "https://www.propertyfinder.bh/en/new-projects",
        "data_key": "projects",          # searchResult.data.projects
    },
    {
        "name":    "agents",
        "url":     "https://www.propertyfinder.bh/en/find-agent/search",
        "data_key": "agents",            # different structure
    },
]
# ─────────────────────────────────────────────────────────────────────────────

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


def fetch_html(url: str, session: requests.Session) -> str:
    r = session.get(url, headers=HEADERS, timeout=30)
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
    """Add or replace the page param in a URL."""
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["page"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


def extract_records(next_data: dict, data_key: str) -> tuple:
    """
    Pull the records array and total count from __NEXT_DATA__.
    Handles the three structures found across category types:
      - listings  →  props.pageProps.searchResult.listings
      - projects  →  props.pageProps.searchResult.data.projects
      - agents    →  props.pageProps.searchResult.agents  (or similar)
    Returns (records_list, total_count).
    """
    page_props    = next_data.get("props", {}).get("pageProps", {})
    search_result = page_props.get("searchResult") or {}

    total = (
        search_result.get("totalCount")
        or search_result.get("total")
        or page_props.get("totalCount")
        or 0
    )

    if data_key == "listings":
        records = search_result.get("listings") or []

    elif data_key == "projects":
        # new-projects embeds under searchResult.data.projects
        records = (
            (search_result.get("data") or {}).get("projects")
            or search_result.get("projects")
            or page_props.get("projects")
            or []
        )
        if not total:
            total = len(records)

    elif data_key == "agents":
        records = (
            search_result.get("agents")
            or search_result.get("data", {}).get("agents")
            or page_props.get("agents")
            or []
        )

    else:
        # Generic fallback — try the key directly
        records = search_result.get(data_key) or []

    return records, int(total)


def scrape_category(category: dict, session: requests.Session) -> list:
    all_records    = []
    total_reported = None
    name           = category["name"]
    base_url       = category["url"]
    data_key       = category["data_key"]

    print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}]  {name.upper()}")
    print(f"  URL: {base_url}")

    page = 1
    while True:
        url = build_page_url(base_url, page)

        try:
            html = fetch_html(url, session)
        except Exception as exc:
            print(f"  Page {page} error: {exc} — stopping.")
            break

        next_data         = parse_next_data(html)
        records, total    = extract_records(next_data, data_key)

        if total_reported is None and total:
            total_reported = total
            print(f"  Total available: {total_reported}")

        if not records:
            print(f"  No records on page {page} — done. Collected: {len(all_records)}")
            break

        all_records.extend(records)
        collected = f"{len(all_records)}/{total_reported}" if total_reported else str(len(all_records))
        print(f"  Page {page}: +{len(records)}  ({collected})")

        page += 1
        time.sleep(1.5)

    return all_records


def main():
    scrape_start = datetime.now(timezone.utc).isoformat()
    os.makedirs(RAW_DIR, exist_ok=True)
    summary = {}

    print(f"Starting scrape — {len(CATEGORIES)} categories\n")

    with requests.Session() as session:
        for category in CATEGORIES:
            records = scrape_category(category, session)
            out_path = os.path.join(RAW_DIR, f"{category['name']}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False)
            summary[category["name"]] = len(records)
            print(f"  Saved {len(records)} records → {out_path}")

    manifest = {
        "scraped_at":       scrape_start,
        "categories":       len(CATEGORIES),
        "counts":           summary,
        "total":            sum(summary.values()),
    }
    with open(os.path.join(RAW_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nFinished. {len(CATEGORIES)} categories · {manifest['total']} total records.")


if __name__ == "__main__":
    main()
