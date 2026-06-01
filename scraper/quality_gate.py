"""
PropertyFinder Bahrain -- Data Quality Gate.

Validates data quality after cleaning, before committing.
Can run in two modes:
  1. Gate mode (default): Exit code 1 if quality fails - blocks commit
  2. Report mode (--report-only): Generate comprehensive report, don't fail

Usage:
  python scraper/quality_gate.py              # Gate mode - fails if quality < threshold
  python scraper/quality_gate.py --report    # Report mode - always succeeds
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
LATEST_DIR = os.path.join(BASE_DIR, "data", "latest")
CHANGES_DIR = os.path.join(BASE_DIR, "data", "changes")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")

# Quality thresholds
THRESHOLDS = {
    "min_completeness": 95.0,        # Must have 95% of critical fields populated
    "min_listings": 20000,           # Bahrain market should have ~20k+ listings
    "max_empty_prices_pct": 10,      # No more than 10% missing prices
    "max_empty_locations_pct": 10,   # No more than 10% missing coordinates
    "min_categories": 4,             # At least 4 categories should have data
}

# Critical fields for quality assessment
CRITICAL_FIELDS = ["listing_id", "price_value", "latitude", "longitude", "title"]


def read_csv_rows(file_path: str) -> list:
    """Read all rows from CSV file."""
    if not os.path.exists(file_path):
        return []

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return list(reader)


def analyze_file_quality(file_path: str, filename: str) -> dict:
    """Analyze quality metrics for a single CSV file."""
    rows = read_csv_rows(file_path)

    if not rows:
        return {
            "filename": filename,
            "exists": False,
            "row_count": 0,
            "quality_score": 0
        }

    total_rows = len(rows)

    # Check critical field completeness
    field_stats = {}
    for field in CRITICAL_FIELDS:
        empty_count = sum(1 for row in rows if not row.get(field) or row.get(field).strip() == "")
        field_stats[field] = {
            "empty": empty_count,
            "populated": total_rows - empty_count,
            "completeness_pct": ((total_rows - empty_count) / total_rows * 100) if total_rows > 0 else 0
        }

    # Calculate overall quality score
    avg_completeness = sum(f["completeness_pct"] for f in field_stats.values()) / len(field_stats)

    # Price-specific checks
    price_values = []
    for row in rows:
        try:
            price = float(row.get("price_value", 0))
            if price > 0:
                price_values.append(price)
        except (ValueError, TypeError):
            pass

    avg_price = sum(price_values) / len(price_values) if price_values else 0
    min_price = min(price_values) if price_values else 0
    max_price = max(price_values) if price_values else 0

    return {
        "filename": filename,
        "exists": True,
        "row_count": total_rows,
        "quality_score": round(avg_completeness, 2),
        "field_stats": field_stats,
        "price_stats": {
            "avg": round(avg_price, 2),
            "min": round(min_price, 2),
            "max": round(max_price, 2),
            "populated_count": len(price_values)
        }
    }


def check_thresholds(metrics: dict) -> dict:
    """Check if metrics meet quality thresholds."""
    violations = []

    all_listings = metrics.get("all_listings", {})

    # Check minimum listings
    if all_listings.get("row_count", 0) < THRESHOLDS["min_listings"]:
        violations.append({
            "check": "min_listings",
            "threshold": THRESHOLDS["min_listings"],
            "actual": all_listings.get("row_count", 0),
            "severity": "critical"
        })

    # Check quality score
    if all_listings.get("quality_score", 0) < THRESHOLDS["min_completeness"]:
        violations.append({
            "check": "quality_score",
            "threshold": THRESHOLDS["min_completeness"],
            "actual": all_listings.get("quality_score", 0),
            "severity": "critical"
        })

    # Check empty prices
    price_stats = all_listings.get("field_stats", {}).get("price_value", {})
    empty_prices_pct = price_stats.get("completeness_pct", 0)
    if empty_prices_pct < (100 - THRESHOLDS["max_empty_prices_pct"]):
        violations.append({
            "check": "max_empty_prices",
            "threshold": f"<{THRESHOLDS['max_empty_prices_pct']}%",
            "actual": f"{100 - empty_prices_pct:.1f}%",
            "severity": "warning"
        })

    # Check empty locations
    loc_stats = all_listings.get("field_stats", {}).get("latitude", {})
    empty_locs_pct = loc_stats.get("completeness_pct", 0)
    if empty_locs_pct < (100 - THRESHOLDS["max_empty_locations_pct"]):
        violations.append({
            "check": "max_empty_locations",
            "threshold": f"<{THRESHOLDS['max_empty_locations_pct']}%",
            "actual": f"{100 - empty_locs_pct:.1f}%",
            "severity": "warning"
        })

    # Check category count
    categories_with_data = sum(1 for cat in metrics.get("categories", {}).values() if cat.get("row_count", 0) > 0)
    if categories_with_data < THRESHOLDS["min_categories"]:
        violations.append({
            "check": "min_categories",
            "threshold": THRESHOLDS["min_categories"],
            "actual": categories_with_data,
            "severity": "critical"
        })

    return violations


def generate_full_report() -> dict:
    """Generate comprehensive quality report."""
    report_time = datetime.now(timezone.utc).isoformat()

    # Analyze all files
    all_listings_path = os.path.join(LATEST_DIR, "all_listings.csv")
    all_listings_metrics = analyze_file_quality(all_listings_path, "all_listings.csv")

    # Analyze categories
    category_metrics = {}
    for category in ["residential_rent", "residential_sale", "commercial_rent", "commercial_sale", "new_projects"]:
        cat_path = os.path.join(LATEST_DIR, f"{category}.csv")
        category_metrics[category] = analyze_file_quality(cat_path, f"{category}.csv")

    # Get raw data stats
    raw_metrics = {}
    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
            raw_metrics = {
                "scraped_at": manifest.get("scraped_at", ""),
                "total_records": manifest.get("total", 0),
                "categories": manifest.get("counts", {})
            }

    # Get changes stats
    changes_metrics = {}
    all_changes_path = os.path.join(CHANGES_DIR, "all_changes.csv")
    if os.path.exists(all_changes_path):
        changes_rows = read_csv_rows(all_changes_path)
        changes_metrics = {
            "total_changes": len(changes_rows),
            "latest_date": changes_rows[-1].get("date") if changes_rows else ""
        }

    metrics = {
        "report_time": report_time,
        "all_listings": all_listings_metrics,
        "categories": category_metrics,
        "raw_data": raw_metrics,
        "changes": changes_metrics
    }

    # Check thresholds
    violations = check_thresholds(metrics)

    metrics["violations"] = violations
    metrics["passed_gate"] = len([v for v in violations if v["severity"] == "critical"]) == 0
    metrics["overall_status"] = "PASS" if metrics["passed_gate"] else "FAIL"

    return metrics


def print_report(metrics: dict, detailed: bool = False):
    """Print formatted report to console."""
    print("=" * 80)
    print("DATA QUALITY GATE REPORT")
    print(f"Generated: {metrics['report_time']}")
    print(f"Status: {metrics['overall_status']}")
    print("=" * 80)

    print("\n[OVERALL] ALL LISTINGS")
    all_listings = metrics.get("all_listings", {})
    print(f"  Total Rows: {all_listings.get('row_count', 0):,}")
    print(f"  Quality Score: {all_listings.get('quality_score', 0)}%")

    print(f"\n  Critical Field Completeness:")
    for field, stats in all_listings.get("field_stats", {}).items():
        print(f"    {field}: {stats['completeness_pct']:.1f}% ({stats['populated']:,} populated)")

    if detailed:
        print(f"\n  Price Statistics:")
        price_stats = all_listings.get("price_stats", {})
        print(f"    Average: {price_stats['avg']} BHD")
        print(f"    Min: {price_stats['min']} BHD")
        print(f"    Max: {price_stats['max']} BHD")
        print(f"    Populated: {price_stats['populated_count']:,}")

    print(f"\n[CATEGORIES] CATEGORY BREAKDOWN")
    for cat_name, cat_metrics in metrics.get("categories", {}).items():
        if cat_metrics.get("exists"):
            print(f"  {cat_name}:")
            print(f"    Rows: {cat_metrics['row_count']:,}")
            print(f"    Quality: {cat_metrics['quality_score']}%")

    print(f"\n[VIOLATIONS] QUALITY THRESHOLDS")
    violations = metrics.get("violations", [])
    if violations:
        for v in violations:
            severity_symbol = "[CRITICAL]" if v["severity"] == "critical" else "[WARNING]"
            print(f"  {severity_symbol} {v['check']}: {v['actual']} (threshold: {v['threshold']})")
    else:
        print("  [PASS] All quality thresholds passed")

    print(f"\n[PIPELINE] PIPELINE STATUS")
    raw = metrics.get("raw_data", {})
    print(f"  Raw Data Records: {raw.get('total_records', 0):,}")
    print(f"  Last Scraped: {raw.get('scraped_at', 'N/A')}")

    changes = metrics.get("changes", {})
    print(f"  Total Changes Tracked: {changes.get('total_changes', 0):,}")

    print("=" * 80)


def save_report_json(metrics: dict, output_path: str):
    """Save report as JSON."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)


def generate_markdown_report(metrics: dict) -> str:
    """Generate markdown report for GitHub Actions summary."""
    md = []

    # Header
    md.append("# Data Quality Gate Report")
    md.append(f"**Generated:** {metrics['report_time']}")
    md.append(f"**Status:** {'PASS' if metrics['passed_gate'] else 'FAIL'}")
    md.append("")

    # Overall stats
    all_listings = metrics.get("all_listings", {})
    md.append("## Overall Statistics")
    md.append(f"- **Total Listings:** {all_listings.get('row_count', 0):,}")
    md.append(f"- **Quality Score:** {all_listings.get('quality_score', 0)}%")
    md.append("")

    # Critical fields
    md.append("## Critical Field Completeness")
    for field, stats in all_listings.get("field_stats", {}).items():
        status = "[PASS]" if stats['completeness_pct'] >= 95 else "[FAIL]"
        md.append(f"- {status} **{field}:** {stats['completeness_pct']:.1f}% ({stats['populated']:,} / {all_listings.get('row_count', 0):,})")
    md.append("")

    # Categories
    md.append("## Categories")
    for cat_name, cat_metrics in metrics.get("categories", {}).items():
        if cat_metrics.get("exists"):
            md.append(f"### {cat_name}")
            md.append(f"- Rows: {cat_metrics['row_count']:,}")
            md.append(f"- Quality: {cat_metrics['quality_score']}%")
            md.append("")

    # Violations
    violations = metrics.get("violations", [])
    if violations:
        md.append("## Quality Threshold Violations")
        for v in violations:
            status = "[CRITICAL]" if v["severity"] == "critical" else "[WARNING]"
            md.append(f"- {status} **{v['check']}:** {v['actual']} (threshold: {v['threshold']})")
        md.append("")

    # Pipeline info
    md.append("## Pipeline Status")
    raw = metrics.get("raw_data", {})
    md.append(f"- **Raw Records:** {raw.get('total_records', 0):,}")
    md.append(f"- **Last Scrape:** {raw.get('scraped_at', 'N/A')}")
    changes = metrics.get("changes", {})
    md.append(f"- **Total Changes:** {changes.get('total_changes', 0):,}")
    md.append("")

    return "\n".join(md)


def save_report_markdown(metrics: dict, output_path: str):
    """Save markdown report to file."""
    md_content = generate_markdown_report(metrics)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)


def main():
    parser = argparse.ArgumentParser(description="Data quality gate for PropertyFinder pipeline")
    parser.add_argument("--report-only", action="store_true", help="Generate report without failing on quality issues")
    parser.add_argument("--detailed", action="store_true", help="Print detailed report to console")
    parser.add_argument("--output-dir", default=None, help="Output directory for reports (default: data/latest)")

    args = parser.parse_args()

    # Generate full report
    metrics = generate_full_report()

    # Print console report
    print_report(metrics, detailed=args.detailed)

    # Save reports
    output_dir = args.output_dir or LATEST_DIR
    os.makedirs(output_dir, exist_ok=True)

    # JSON report
    json_path = os.path.join(output_dir, "quality_report.json")
    save_report_json(metrics, json_path)
    print(f"\n[JSON] Report saved: {json_path}")

    # Markdown report
    md_path = os.path.join(output_dir, "quality_report.md")
    save_report_markdown(metrics, md_path)
    print(f"[MARKDOWN] Report saved: {md_path}")

    # GitHub Actions summary (if running in Actions)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], 'a') as f:
            f.write("\n" + generate_markdown_report(metrics))
        print(f"[GITHUB] Summary added to workflow")

    # Exit code based on gate mode
    if args.report_only:
        print("\n[MODE] Report-only mode - always succeeds")
        sys.exit(0)
    else:
        if metrics["passed_gate"]:
            print(f"\n[MODE] Gate mode - PASSED")
            sys.exit(0)
        else:
            print(f"\n[MODE] Gate mode - FAILED")
            print("[ACTION] Quality gate failed - commit blocked")
            sys.exit(1)


if __name__ == "__main__":
    main()
