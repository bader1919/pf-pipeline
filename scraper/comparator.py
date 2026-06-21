"""
PropertyFinder Bahrain — change comparator.
Diffs today's snapshot (data/latest/) vs yesterday's backup (data/previous/).
Outputs:
  data/changes/YYYY-MM-DD.csv     — today's delta (new / removed / price_changed)
  data/changes/all_changes.csv    — cumulative history (appended every run)

Change types:
  new           → listing appeared for the first time (new supply)
  removed       → listing no longer in results (likely sold or rented — demand signal)
  price_changed → same listing, different price
  unchanged     → same listing, same price (not written to changes file)
"""

import csv
import json
import os
import shutil
from datetime import datetime, timezone

BASE_DIR    = os.path.join(os.path.dirname(__file__), "..")
LATEST_DIR  = os.path.join(BASE_DIR, "data", "latest")
PREV_DIR    = os.path.join(BASE_DIR, "data", "previous")
CHANGES_DIR = os.path.join(BASE_DIR, "data", "changes")

ALL_CHANGES_FILE = os.path.join(CHANGES_DIR, "all_changes.csv")

CHANGE_COLUMNS = [
    "change_date",
    "change_type",        # new | removed | price_changed
    "listing_id",
    "category",
    "listing_type",
    "property_type",
    "title",
    "price_prev",
    "price_curr",
    "price_delta",        # price_curr - price_prev (negative = price drop)
    "price_delta_pct",    # rounded to 2dp
    "currency",
    "price_period",
    "area_size",
    "area_unit",
    "beds_min",
    "beds_max",
    "baths_min",
    "city",
    "area",
    "community",
    "sub_community",
    "compound",
    "latitude",
    "longitude",
    "developer",
    "project_name",
    "agency_name",
    "agent_name",
    "agent_phone",
    "furnished",
    "completion_status",
    "permit_number",
    "rera_number",
    "amenities",
    "share_url",
    "first_seen_at",      # scraped_at of the first time this pf_id appeared
    "last_seen_at",       # scraped_at of the most recent appearance
    "days_on_market",     # calendar days between first_seen and removal/today
    "scraped_at",
]


CRITICAL_COLUMNS = ["listing_id", "price_value"]


def warn_if_columns_missing(headers: list):
    """Warn loudly if a critical column is missing from this CSV's header --
    that warning shows up in GitHub Actions logs so a cleaner.py schema
    change is never silent."""
    for col in CRITICAL_COLUMNS:
        if col not in headers:
            print(f"  [schema] WARNING: could not find '{col}' in CSV headers. Available: {headers[:10]}...")


def load_csv_by_id(path: str) -> dict:
    """Load a CSV into {listing_id: row_dict}. Empty dict if file missing."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        warn_if_columns_missing(reader.fieldnames or [])
        rows = {row["listing_id"]: row for row in reader if row.get("listing_id")}
    return rows


def load_first_seen(all_changes_path: str) -> dict:
    """Return {pf_id: first_seen_at} from cumulative history."""
    first_seen = {}
    if not os.path.exists(all_changes_path):
        return first_seen
    with open(all_changes_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pid = row.get("listing_id")
            if pid and pid not in first_seen:
                first_seen[pid] = row.get("first_seen_at") or row.get("scraped_at", "")
    return first_seen


def days_between(start_iso: str, end_iso: str) -> int:
    """Return calendar days between two ISO timestamps. Returns 0 on error."""
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end   = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return max(0, (end - start).days)
    except Exception:
        return 0


def build_change_row(
    change_type: str,
    today_row: dict | None,
    prev_row: dict | None,
    change_date: str,
    first_seen: dict,
) -> dict:
    base = today_row or prev_row or {}
    pid  = base.get("listing_id", "")

    try:
        price_curr = float(today_row["price_value"]) if today_row and today_row.get("price_value") else None
        price_prev = float(prev_row["price_value"])  if prev_row  and prev_row.get("price_value")  else None
    except (ValueError, TypeError):
        price_curr = None
        price_prev = None

    if price_curr is not None and price_prev is not None:
        delta     = round(price_curr - price_prev, 2)
        delta_pct = round((delta / price_prev) * 100, 2) if price_prev else ""
    else:
        delta     = ""
        delta_pct = ""

    scraped_at   = base.get("scraped_at", change_date)
    first_seen_at = first_seen.get(pid) or scraped_at
    last_seen_at  = scraped_at
    dom = days_between(first_seen_at, scraped_at)

    return {
        "change_date":     change_date,
        "change_type":     change_type,
        "listing_id":      pid,
        "category":        base.get("category", ""),
        "listing_type":    base.get("listing_type", ""),
        "property_type":   base.get("property_type", ""),
        "title":           base.get("title", ""),
        "price_prev":      price_prev if price_prev is not None else "",
        "price_curr":      price_curr if price_curr is not None else "",
        "price_delta":     delta,
        "price_delta_pct": delta_pct,
        "currency":        base.get("currency", "BHD"),
        "price_period":    base.get("price_period", ""),
        "area_size":       base.get("area_size", ""),
        "area_unit":       base.get("area_unit", ""),
        "beds_min":        base.get("beds_min", ""),
        "beds_max":        base.get("beds_max", ""),
        "baths_min":       base.get("baths_min", ""),
        "city":            base.get("city", ""),
        "area":            base.get("area", ""),
        "community":       base.get("community", ""),
        "sub_community":   base.get("sub_community", ""),
        "compound":        base.get("compound", ""),
        "latitude":        base.get("latitude", ""),
        "longitude":       base.get("longitude", ""),
        "developer":       base.get("developer", ""),
        "project_name":    base.get("project_name", ""),
        "agency_name":     base.get("agency_name", ""),
        "agent_name":      base.get("agent_name", ""),
        "agent_phone":     base.get("agent_phone", ""),
        "furnished":       base.get("furnished", ""),
        "completion_status": base.get("completion_status", ""),
        "permit_number":   base.get("permit_number", ""),
        "rera_number":     base.get("rera_number", ""),
        "amenities":       base.get("amenities", ""),
        "share_url":       base.get("share_url", ""),
        "first_seen_at":   first_seen_at,
        "last_seen_at":    last_seen_at,
        "days_on_market":  dom,
        "scraped_at":      scraped_at,
    }


def append_to_all_changes(rows: list, all_changes_path: str):
    if not rows:
        return
    write_header = not os.path.exists(all_changes_path)
    with open(all_changes_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CHANGE_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_daily_csv(rows: list, change_date: str):
    if not rows:
        return
    path = os.path.join(CHANGES_DIR, f"{change_date}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CHANGE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Daily delta -> {path}")


def main():
    os.makedirs(CHANGES_DIR, exist_ok=True)

    change_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Comparing snapshots for: {change_date}\n")

    today_all = load_csv_by_id(os.path.join(LATEST_DIR, "all_listings.csv"))
    prev_all  = load_csv_by_id(os.path.join(PREV_DIR,  "all_listings.csv"))

    if not today_all:
        print("  No today snapshot found — aborting comparison.")
        return

    if not prev_all:
        print("  No previous snapshot — treating all current listings as 'new'.")

    # Load first-seen history
    first_seen = load_first_seen(ALL_CHANGES_FILE)

    today_ids = set(today_all.keys())
    prev_ids  = set(prev_all.keys())

    new_ids     = today_ids - prev_ids
    removed_ids = prev_ids  - today_ids
    common_ids  = today_ids & prev_ids

    change_rows = []

    # New listings
    for pid in sorted(new_ids):
        change_rows.append(build_change_row("new", today_all[pid], None, change_date, first_seen))

    # Removed listings (sold / rented / expired)
    for pid in sorted(removed_ids):
        change_rows.append(build_change_row("removed", None, prev_all[pid], change_date, first_seen))

    # Price changes
    for pid in sorted(common_ids):
        t_price = today_all[pid].get("price_value", "")
        p_price = prev_all[pid].get("price_value", "")
        if t_price != p_price and t_price and p_price:
            change_rows.append(
                build_change_row("price_changed", today_all[pid], prev_all[pid], change_date, first_seen)
            )

    print(f"  New:           {sum(1 for r in change_rows if r['change_type'] == 'new')}")
    print(f"  Removed:       {sum(1 for r in change_rows if r['change_type'] == 'removed')}")
    print(f"  Price changed: {sum(1 for r in change_rows if r['change_type'] == 'price_changed')}")
    print(f"  Unchanged:     {len(common_ids) - sum(1 for r in change_rows if r['change_type'] == 'price_changed')}")

    if change_rows:
        write_daily_csv(change_rows, change_date)
        append_to_all_changes(change_rows, ALL_CHANGES_FILE)
        print(f"  Appended {len(change_rows)} rows -> {ALL_CHANGES_FILE}")
    else:
        print("  No changes detected.")

    # Rotate: copy today -> previous for next run
    if os.path.exists(LATEST_DIR):
        if os.path.exists(PREV_DIR):
            shutil.rmtree(PREV_DIR)
        shutil.copytree(LATEST_DIR, PREV_DIR)
        print(f"\n  Rotated: latest -> previous (ready for next run)")


if __name__ == "__main__":
    main()
