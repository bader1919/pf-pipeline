"""
PropertyFinder Bahrain -- comprehensive reporting script.
Generates detailed reports on pipeline performance, data quality, and change statistics.
"""

import os
import csv
import json
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
LATEST_DIR = os.path.join(BASE_DIR, "data", "latest")
CHANGES_DIR = os.path.join(BASE_DIR, "data", "changes")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")

def get_file_info(file_path: str) -> dict:
    """Get basic file information."""
    if not os.path.exists(file_path):
        return {"exists": False, "size": 0, "rows": 0}

    size = os.path.getsize(file_path)
    rows = 0

    if file_path.endswith('.csv'):
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            rows = sum(1 for _ in csv.reader(f)) - 1  # Subtract header

    return {"exists": True, "size": size, "rows": rows}

def analyze_csv_quality(file_path: str) -> dict:
    """Analyze data quality of CSV files."""
    if not os.path.exists(file_path):
        return {}

    quality_metrics = {
        "total_rows": 0,
        "empty_ids": 0,
        "empty_prices": 0,
        "empty_locations": 0,
        "complete_records": 0
    }

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                quality_metrics["total_rows"] += 1

                # Check data completeness
                if not row.get("listing_id") or row.get("listing_id").strip() == "":
                    quality_metrics["empty_ids"] += 1
                if not row.get("price_value") or row.get("price_value").strip() == "":
                    quality_metrics["empty_prices"] += 1
                if not row.get("latitude") or row.get("latitude").strip() == "":
                    quality_metrics["empty_locations"] += 1

                # Check if record is reasonably complete (has listing_id is most important)
                if row.get("listing_id"):
                    quality_metrics["complete_records"] += 1
    except Exception as e:
        print(f"    Error analyzing {file_path}: {e}")

    return quality_metrics

def get_category_stats() -> dict:
    """Get statistics for each category."""
    categories = {}

    category_files = {
        "residential_rent": "residential_rent.csv",
        "residential_sale": "residential_sale.csv",
        "commercial_rent": "commercial_rent.csv",
        "commercial_sale": "commercial_sale.csv",
        "new_projects": "new_projects.csv"
    }

    for category, filename in category_files.items():
        file_path = os.path.join(LATEST_DIR, filename)
        file_info = get_file_info(file_path)
        quality = analyze_csv_quality(file_path) if file_info["exists"] else {}

        categories[category] = {
            **file_info,
            **quality
        }

    return categories

def get_change_stats() -> dict:
    """Get change tracking statistics."""
    all_changes_path = os.path.join(CHANGES_DIR, "all_changes.csv")

    if not os.path.exists(all_changes_path):
        return {"total_changes": 0, "by_type": {}}

    stats = {
        "total_changes": 0,
        "by_type": {"new": 0, "removed": 0, "price_changed": 0}
    }

    try:
        with open(all_changes_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                stats["total_changes"] += 1
                change_type = row.get("change_type", "")
                if change_type in stats["by_type"]:
                    stats["by_type"][change_type] += 1
    except Exception as e:
        print(f"    Error analyzing changes: {e}")

    return stats

def get_raw_data_stats() -> dict:
    """Get raw data statistics."""
    manifest_path = os.path.join(RAW_DIR, "manifest.json")

    if not os.path.exists(manifest_path):
        return {"exists": False}

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
            return {
                "exists": True,
                "scraped_at": manifest.get("scraped_at", ""),
                "categories": manifest.get("categories", 0),
                "total_records": manifest.get("total", 0),
                "counts": manifest.get("counts", {})
            }
    except Exception as e:
        return {"exists": False, "error": str(e)}

def generate_report() -> dict:
    """Generate comprehensive pipeline report."""
    report_time = datetime.now(timezone.utc).isoformat()

    all_listings_path = os.path.join(LATEST_DIR, "all_listings.csv")
    all_file_info = get_file_info(all_listings_path)
    all_quality = analyze_csv_quality(all_listings_path)

    category_stats = get_category_stats()
    change_stats = get_change_stats()
    raw_stats = get_raw_data_stats()

    total_listings = sum(cat.get("rows", 0) for cat in category_stats.values())
    total_complete = sum(cat.get("complete_records", 0) for cat in category_stats.values())

    report = {
        "report_generated_at": report_time,
        "pipeline_status": "success" if total_listings > 0 else "no_data",
        "total_listings": total_listings,
        "complete_records": total_complete,
        "data_completeness_rate": round((total_complete / total_listings * 100) if total_listings > 0 else 0, 2),
        "categories": category_stats,
        "changes": change_stats,
        "raw_data": raw_stats,
        "all_listings_file": {**all_file_info, **all_quality}
    }

    return report

def print_report(report: dict):
    """Print formatted report to console."""
    print("=" * 80)
    print(f"PROPERTYFINDER BAHRAIN PIPELINE REPORT")
    print(f"Generated: {report['report_generated_at']}")
    print(f"Status: {report['pipeline_status'].upper()}")
    print("=" * 80)

    print(f"\n[STATISTICS] OVERALL STATISTICS")
    print(f"  Total Listings: {report['total_listings']:,}")
    print(f"  Complete Records: {report['complete_records']:,}")
    print(f"  Data Completeness: {report['data_completeness_rate']}%")

    print(f"\n[CATEGORIES] CATEGORY BREAKDOWN")
    for category, stats in report['categories'].items():
        if stats.get('exists', False):
            print(f"  {category}:")
            print(f"    Total: {stats['rows']:,}")
            print(f"    Complete: {stats['complete_records']:,}")
            if stats.get('empty_ids', 0) > 0:
                print(f"    [!] Missing IDs: {stats['empty_ids']:,}")

    print(f"\n[CHANGES] CHANGE TRACKING")
    changes = report['changes']
    print(f"  Total Changes: {changes['total_changes']:,}")
    print(f"  New: {changes['by_type']['new']:,}")
    print(f"  Removed: {changes['by_type']['removed']:,}")
    print(f"  Price Changed: {changes['by_type']['price_changed']:,}")

    print(f"\n[RAW_DATA] RAW DATA")
    raw = report['raw_data']
    if raw.get('exists', False):
        print(f"  Last Scraped: {raw['scraped_at']}")
        print(f"  Categories: {raw['categories']}")
        print(f"  Total Records: {raw['total_records']:,}")
    else:
        print(f"  [!] No raw data found")

    print(f"\n[HEALTH] PIPELINE HEALTH")
    issues = []
    if report['data_completeness_rate'] < 90:
        issues.append(f"Low data completeness ({report['data_completeness_rate']}%)")

    if report['total_listings'] == 0:
        issues.append("No listings found")

    category_issues = [cat for cat, stats in report['categories'].items()
                       if stats.get('empty_ids', 0) > 100]
    if category_issues:
        issues.append(f"Categories with many missing IDs: {', '.join(category_issues)}")

    if issues:
        print(f"  [!] Issues Found:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"  [OK] All systems operational")

    print("=" * 80)

def main():
    """Generate and display comprehensive report."""
    report = generate_report()
    print_report(report)

    # Save report to file
    report_path = os.path.join(BASE_DIR, "data", "latest_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"\n[REPORT] Report saved to: {report_path}")

if __name__ == "__main__":
    main()