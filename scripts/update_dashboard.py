"""
Dashboard Data Generator for PropertyFinder Pipeline.
Reads pipeline outputs directly from data/ and writes a rich dashboard/data.json
that an analyst can use to understand collection, cleaning, and change-tracking
health at a glance -- without needing to open GitHub Actions or browse CSVs.
"""

import csv
import glob
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

LATEST_REPORT   = Path("data/latest_report.json")
QUALITY_REPORT  = Path("data/latest/quality_report.json")
ALL_LISTINGS    = Path("data/latest/all_listings.csv")
CHANGES_DIR     = Path("data/changes")
ALL_CHANGES     = CHANGES_DIR / "all_changes.csv"
DASHBOARD_DATA  = Path("dashboard/data.json")

TREND_DAYS = 14   # how many days of daily change history to surface

GITHUB_API     = "https://api.github.com"
GITHUB_REPO    = os.environ.get("GITHUB_REPOSITORY", "bader1919/pf-pipeline")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN")
ACTIONS_LOOKBACK = 25   # how many recent workflow runs to scan for health


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def file_age_hours(path: Path):
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return round((datetime.now(timezone.utc) - mtime).total_seconds() / 3600, 1)


# ---------------------------------------------------------------------------
# GitHub Actions run health -- tells an analyst whether the "red" runs they
# see in the Actions tab are real failures (jobs ran and broke) or cosmetic
# no-ops (GitHub creates a check-suite for every workflow file on every push,
# even when that workflow's triggers don't match the event, and marks it red
# with zero jobs spawned). Without this, red runs look alarming but most are
# noise -- this lets the dashboard say so explicitly, with receipts.
# ---------------------------------------------------------------------------
def _gh_get(url, params=None):
    if not url:
        return None
    if params:
        url = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError, OSError):
        return None


def load_actions_health():
    runs_data = _gh_get(
        f"{GITHUB_API}/repos/{GITHUB_REPO}/actions/runs",
        params={"per_page": ACTIONS_LOOKBACK},
    )
    if not runs_data or "workflow_runs" not in runs_data:
        return None

    by_workflow = {}
    real_failures = []

    for run in runs_data["workflow_runs"]:
        name = run.get("name") or run.get("path", "unknown")
        wf = by_workflow.setdefault(name, {
            "name": name,
            "last_status": run.get("status"),
            "last_conclusion": run.get("conclusion"),
            "last_run_at": run.get("run_started_at") or run.get("created_at"),
            "real_failures_recent": 0,
            "cosmetic_red_recent": 0,
        })

        if run.get("conclusion") != "failure":
            continue

        jobs = _gh_get(run.get("jobs_url")) if run.get("jobs_url") else None
        job_count = (jobs or {}).get("total_count", 0)

        if job_count == 0:
            wf["cosmetic_red_recent"] += 1
        else:
            wf["real_failures_recent"] += 1
            failed_step = None
            for job in (jobs or {}).get("jobs", []):
                if job.get("conclusion") == "failure":
                    for step in job.get("steps", []):
                        if step.get("conclusion") == "failure":
                            failed_step = step.get("name")
                            break
                    break
            real_failures.append({
                "workflow": name,
                "run_id": run.get("id"),
                "failed_step": failed_step,
                "ran_at": run.get("run_started_at") or run.get("created_at"),
                "html_url": run.get("html_url"),
            })

    workflows = []
    for wf in by_workflow.values():
        note = None
        if wf["cosmetic_red_recent"] and not wf["real_failures_recent"]:
            note = (f"{wf['cosmetic_red_recent']} red run(s) shown by GitHub but 0 jobs executed -- "
                    f"this workflow's triggers don't match those push events, so nothing ran or broke. Safe to ignore.")
        elif wf["real_failures_recent"]:
            note = f"{wf['real_failures_recent']} run(s) actually failed -- see details below, needs attention."
        workflows.append({**wf, "note": note})

    return {
        "workflows": sorted(workflows, key=lambda w: -(w["real_failures_recent"])),
        "real_failure_details": real_failures,
    }


# ---------------------------------------------------------------------------
# Daily change trend -- read each data/changes/YYYY-MM-DD.csv directly so the
# dashboard reflects reality even if latest_report.json is stale.
# ---------------------------------------------------------------------------
def load_daily_change_trend():
    trend = []
    files = sorted(glob.glob(str(CHANGES_DIR / "20*-*-*.csv")))[-TREND_DAYS:]
    for fpath in files:
        date = os.path.basename(fpath).replace(".csv", "")
        counts = Counter()
        scraped_at = None
        with open(fpath, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                counts[row.get("change_type", "")] += 1
                scraped_at = scraped_at or row.get("scraped_at")
        trend.append({
            "date": date,
            "new": counts.get("new", 0),
            "removed": counts.get("removed", 0),
            "price_changed": counts.get("price_changed", 0),
            "total": sum(counts.values()),
            "scraped_at": scraped_at,
        })
    return trend


# ---------------------------------------------------------------------------
# Aging analysis -- how long listings stay live before disappearing
# (sourced from "removed" rows in the cumulative change log, which carry
# days_on_market computed by the comparator).
# ---------------------------------------------------------------------------
def load_aging_stats():
    if not ALL_CHANGES.exists():
        return None
    doms = []
    cat_doms = {}
    with open(ALL_CHANGES, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("change_type") != "removed":
                continue
            try:
                dom = int(row.get("days_on_market") or 0)
            except (ValueError, TypeError):
                continue
            doms.append(dom)
            cat = row.get("category") or "unknown"
            cat_doms.setdefault(cat, []).append(dom)

    if not doms:
        return None

    buckets = Counter()
    for d in doms:
        if d == 0:
            buckets["same_day"] += 1
        elif d <= 7:
            buckets["1-7_days"] += 1
        elif d <= 30:
            buckets["8-30_days"] += 1
        elif d <= 90:
            buckets["31-90_days"] += 1
        else:
            buckets["90+_days"] += 1

    return {
        "sample_size": len(doms),
        "avg_days_on_market": round(mean(doms), 1),
        "median_days_on_market": round(median(doms), 1),
        "max_days_on_market": max(doms),
        "distribution": dict(buckets),
        "by_category_avg": {
            cat: round(mean(vals), 1)
            for cat, vals in sorted(cat_doms.items(), key=lambda kv: -len(kv[1]))[:6]
        },
    }


# ---------------------------------------------------------------------------
# Category breakdown -- straight from the quality report, since that already
# captures per-category row counts and completeness.
# ---------------------------------------------------------------------------
def load_category_breakdown(quality_report):
    if not quality_report:
        return []
    cats = quality_report.get("categories", {})
    out = []
    for name, c in cats.items():
        out.append({
            "category": name,
            "rows": c.get("row_count"),
            "quality_score": c.get("quality_score"),
        })
    return sorted(out, key=lambda c: -(c["rows"] or 0))


# ---------------------------------------------------------------------------
# Anomaly detection -- the things an analyst would want flagged automatically
# ---------------------------------------------------------------------------
def detect_anomalies(latest_report, quality_report, trend, listings_age_hours, all_listings_total, actions_health=None):
    anomalies = []

    if actions_health:
        for failure in actions_health.get("real_failure_details", []):
            step = f" (failed at step: {failure['failed_step']})" if failure.get("failed_step") else ""
            anomalies.append({
                "severity": "warning",
                "message": f"'{failure['workflow']}' run actually failed{step} -- "
                           f"see {failure['html_url']} for logs.",
            })

    if listings_age_hours is not None and listings_age_hours > 30:
        anomalies.append({
            "severity": "warning",
            "message": f"Snapshot data is {listings_age_hours:.0f}h old -- the pipeline may not have run on schedule.",
        })

    if quality_report:
        score = quality_report.get("all_listings", {}).get("quality_score")
        if score is not None and score < 100:
            anomalies.append({
                "severity": "warning",
                "message": f"Overall data quality score is {score}% (below 100%) -- check quality_report.md for affected fields.",
            })
        price_stats = quality_report.get("all_listings", {}).get("price_stats", {})
        if price_stats.get("min") is not None and price_stats["min"] <= 1:
            anomalies.append({
                "severity": "info",
                "message": f"Minimum listed price is {price_stats['min']:.0f} BHD -- likely placeholder/incomplete listings worth spot-checking.",
            })
        if price_stats.get("max") and price_stats["max"] > 50_000_000:
            anomalies.append({
                "severity": "info",
                "message": f"Maximum listed price is {price_stats['max']:,.0f} BHD -- verify this isn't a data-entry/scrape outlier.",
            })

    if trend:
        recent = trend[-7:]
        zero_price_change_days = sum(1 for d in recent if d["price_changed"] == 0)
        if zero_price_change_days == len(recent) and len(recent) >= 5:
            anomalies.append({
                "severity": "warning",
                "message": f"price_changed = 0 for all of the last {len(recent)} days -- the comparator's price-change "
                           f"detection may be misreading a column (this happened before; verify the field mapping in comparator.py).",
            })
        zero_total_days = [d["date"] for d in recent if d["total"] == 0]
        if zero_total_days:
            anomalies.append({
                "severity": "info",
                "message": f"No changes recorded on: {', '.join(zero_total_days)} -- confirm the pipeline actually ran that day.",
            })

    if latest_report:
        raw = latest_report.get("raw_data", {}).get("counts", {})
        empty_categories = [name for name, n in raw.items() if n == 0]
        if empty_categories:
            anomalies.append({
                "severity": "info",
                "message": f"Categories returned 0 records in the last full report: {', '.join(empty_categories)} "
                           f"-- could be normal (e.g. 'agents' is excluded from listings) or a discovery-phase issue.",
            })

    if all_listings_total and latest_report and latest_report.get("total_listings"):
        prev_total = latest_report["total_listings"]
        if abs(all_listings_total - prev_total) / prev_total > 0.15:
            anomalies.append({
                "severity": "warning",
                "message": f"Listing count moved >15% since the last full report ({prev_total:,} -> {all_listings_total:,}) "
                           f"-- worth confirming this reflects a real market shift and not a scrape/category issue.",
            })

    if not anomalies:
        anomalies.append({"severity": "ok", "message": "No anomalies detected -- pipeline outputs look consistent."})

    return anomalies


# ---------------------------------------------------------------------------
# Pipeline steps -- static description of the scrape -> clean -> compare chain
# so an analyst can see what runs, in order, without opening the workflow YAML.
# ---------------------------------------------------------------------------
PIPELINE_STEPS = [
    {"step": "1. Scrape",    "script": "scraper/pf_scraper.py",       "does": "Discovers subcategories, hits the PF API, writes raw JSON to data/raw/"},
    {"step": "2. Clean",     "script": "scraper/cleaner.py",          "does": "Flattens raw JSON into the 114-column CSV schema in data/latest/"},
    {"step": "3. Compare",   "script": "scraper/comparator.py",       "does": "Diffs today vs. yesterday -- new / removed / price_changed -- updates data/changes/"},
    {"step": "4. Report",    "script": "scraper/reporter.py",         "does": "Builds data/latest_report.json with category + change summaries"},
    {"step": "5. Quality",   "script": "scraper/quality_gate.py",     "does": "Scores completeness per field/category -- writes quality_report.json/.md"},
    {"step": "6. Dashboard", "script": "scripts/update_dashboard.py", "does": "Generates this page's data.json (runs after Daily Scrape or Timing Study)"},
]


def determine_status(latest_report, quality_report, listings_age_hours, anomalies):
    if listings_age_hours is not None and listings_age_hours > 48:
        return "error"
    if quality_report:
        if quality_report.get("passed_gate") is False or quality_report.get("overall_status") == "FAIL":
            return "error"
        if quality_report.get("overall_status") == "WARNING":
            return "warning"
    if latest_report and latest_report.get("pipeline_status") in ("error", "failure", "failed"):
        return "error"
    if any(a["severity"] == "warning" for a in anomalies):
        return "warning"
    if latest_report or quality_report:
        return "healthy"
    return "unknown"


def main():
    print("Generating dashboard data...")

    latest_report  = load_json(LATEST_REPORT)
    quality_report = load_json(QUALITY_REPORT)

    trend = load_daily_change_trend()
    aging = load_aging_stats()
    categories = load_category_breakdown(quality_report)
    listings_age_hours = file_age_hours(ALL_LISTINGS)

    # Always recount the live snapshot so the headline number is never stale,
    # even if latest_report.json wasn't regenerated this run.
    all_listings_total = None
    if ALL_LISTINGS.exists():
        with open(ALL_LISTINGS, encoding="utf-8-sig") as f:
            all_listings_total = sum(1 for _ in csv.DictReader(f))

    last_run = None
    for report in (latest_report, quality_report):
        if report:
            for field in ("report_generated_at", "report_time", "scraped_at", "generated_at"):
                if report.get(field):
                    last_run = report[field]
                    break
        if last_run:
            break

    actions_health = load_actions_health()
    anomalies = detect_anomalies(latest_report, quality_report, trend, listings_age_hours, all_listings_total, actions_health)
    status = determine_status(latest_report, quality_report, listings_age_hours, anomalies)

    quality_score = None
    if quality_report:
        quality_score = quality_report.get("all_listings", {}).get("quality_score") \
            or quality_report.get("overall_status")

    # Today's change totals (for the headline metrics) come from the trend
    # we just computed off the actual daily CSVs -- not the cached report.
    today_changes = trend[-1] if trend else {}

    dashboard_data = {
        "status": status,
        "last_run": last_run,
        "data_age_hours": listings_age_hours,
        "quality_score": quality_score,
        "total_listings": all_listings_total,
        "new_listings": today_changes.get("new"),
        "removed_listings": today_changes.get("removed"),
        "price_changed_listings": today_changes.get("price_changed"),
        "categories": categories,
        "change_trend": trend,
        "aging": aging,
        "anomalies": anomalies,
        "actions_health": actions_health,
        "pipeline_steps": PIPELINE_STEPS,
        "dashboard_updated": datetime.now(timezone.utc).isoformat(),
    }

    DASHBOARD_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_DATA, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)

    print(f"Dashboard data updated: {DASHBOARD_DATA}")
    print(f"Status: {status} | Total listings: {all_listings_total} | Anomalies: {len(anomalies)}")


if __name__ == "__main__":
    main()
