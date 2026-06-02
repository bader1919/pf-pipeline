"""
Dashboard Data Generator for PropertyFinder Pipeline
Reads pipeline reports and generates dashboard/data.json for the GitHub Pages dashboard.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# File paths
LATEST_REPORT = Path("data/latest_report.json")
QUALITY_REPORT = Path("data/latest/quality_report.json")
DASHBOARD_DATA = Path("dashboard/data.json")

def load_json(path):
    """Load JSON file safely."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None

def determine_pipeline_status(latest_report, quality_report):
    """Determine overall pipeline health status."""
    if not latest_report:
        return "unknown"

    # Check quality gate status first
    if quality_report:
        if quality_report.get("passed_gate") is False:
            return "error"
        elif quality_report.get("overall_status") == "FAIL":
            return "error"
        elif quality_report.get("overall_status") == "WARNING":
            return "warning"

    # Check pipeline status
    pipeline_status = latest_report.get("pipeline_status", "unknown")
    if pipeline_status == "success":
        return "healthy"
    elif pipeline_status in ["error", "failure", "failed"]:
        return "error"

    return "unknown"

def extract_quality_score(quality_report):
    """Extract quality score from report."""
    if not quality_report:
        return None
    return quality_report.get("overall_status") or \
           quality_report.get("all_listings", {}).get("quality_score")

def get_last_run_time(latest_report, quality_report):
    """Get the most recent run timestamp."""
    # Try multiple possible timestamp fields
    for report in [latest_report, quality_report]:
        if not report:
            continue
        for field in ["report_generated_at", "scraped_at", "generated_at", "timestamp"]:
            if field in report and report[field]:
                return report[field]
    return None

def get_recent_runs():
    """Get recent pipeline runs from GitHub Actions runs."""
    # For now, return current run as recent data
    # This can be extended to fetch from GitHub Actions API
    return []

def main():
    """Generate dashboard data from pipeline reports."""
    print("Generating dashboard data...")

    # Load existing reports
    latest_report = load_json(LATEST_REPORT)
    quality_report = load_json(QUALITY_REPORT)

    # Determine pipeline status
    status = determine_pipeline_status(latest_report, quality_report)

    # Extract metrics
    quality_score = extract_quality_score(quality_report)
    last_run = get_last_run_time(latest_report, quality_report)

    # Get listing counts
    total_listings = None
    new_listings = None
    removed_listings = None

    if latest_report:
        total_listings = latest_report.get("total_listings")
        changes = latest_report.get("changes", {})
        if isinstance(changes, dict):
            by_type = changes.get("by_type", {})
            new_listings = by_type.get("new")
            removed_listings = by_type.get("removed")

    if quality_report:
        if total_listings is None:
            all_listings = quality_report.get("all_listings", {})
            total_listings = all_listings.get("row_count")

    # Create dashboard data structure
    dashboard_data = {
        "status": status,
        "last_run": last_run,
        "quality_score": quality_score,
        "total_listings": total_listings,
        "new_listings": new_listings,
        "removed_listings": removed_listings,
        "recent_runs": get_recent_runs(),
        "dashboard_updated": datetime.now(timezone.utc).isoformat()
    }

    # Ensure dashboard directory exists
    DASHBOARD_DATA.parent.mkdir(parents=True, exist_ok=True)

    # Write dashboard data
    with open(DASHBOARD_DATA, 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)

    print(f"Dashboard data updated: {DASHBOARD_DATA}")
    print(f"Status: {status}")
    print(f"Total listings: {total_listings}")
    print(f"Quality score: {quality_score}")

if __name__ == "__main__":
    main()