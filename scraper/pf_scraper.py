"""
PropertyFinder Bahrain — full catalogue scraper.
Hits the backend JSON API directly (no HTML parsing).
Saves raw JSON per category to data/raw/.
"""

import json
import os
import time
import requests
from datetime import datetime, timezone

API_URL = "https://api-prd.propertyfinder.bh/v2/search"

TARGETS = [
    {"name": "residential_rent",  "payload": {"category_id": "2", "type": "residential"}},
    {"name": "residential_sale",  "payload": {"category_id": "1", "type": "residential"}},
    {"name": "commercial_rent",   "payload": {"category_id": "4", "type": "commercial"}},
    {"name": "commercial_sale",   "payload": {"category_id": "3", "type": "commercial"}},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.propertyfinder.bh",
    "Referer": "https://www.propertyfinder.bh/",
}

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")


def scrape_category(target: dict) -> list:
    os.makedirs(RAW_DIR, exist_ok=True)
    name = target["name"]
    all_records = []
    print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Scraping: {name.upper()}")

    for page in range(1, 2000):
        params = {**target["payload"], "page[number]": page}

        try:
            r = requests.get(API_URL, headers=HEADERS, params=params, timeout=30)
        except Exception as exc:
            print(f"  Page {page} — network error: {exc}. Stopping.")
            break

        if r.status_code != 200:
            print(f"  Page {page} — HTTP {r.status_code}. Stopping.")
            break

        try:
            data = r.json()
        except ValueError:
            print(f"  Page {page} — non-JSON response. Stopping.")
            break

        records = (data.get("searchResult") or {}).get("listings") or []
        if not records:
            print(f"  End of data after page {page - 1}. Total: {len(all_records)}")
            break

        all_records.extend(records)
        print(f"  Page {page}: +{len(records)} (total {len(all_records)})")
        time.sleep(1.5)

    return all_records


def main():
    scrape_start = datetime.now(timezone.utc).isoformat()
    summary = {}

    for target in TARGETS:
        records = scrape_category(target)
        out_path = os.path.join(RAW_DIR, f"{target['name']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        summary[target["name"]] = len(records)
        print(f"  Saved {len(records)} records -> {out_path}")

    # Write a scrape manifest so the cleaner knows when data was pulled
    manifest = {
        "scraped_at": scrape_start,
        "counts": summary,
        "total": sum(summary.values()),
    }
    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    total = manifest["total"]
    print(f"\nDone. Total listings: {total}")

    if total == 0:
        print("\nERROR: 0 listings scraped across all categories.")
        print("Possible causes: API blocked this IP, endpoint changed, or network error.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
