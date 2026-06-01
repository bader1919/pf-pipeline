"""
PropertyFinder Bahrain -- Timing Analysis Study.

Tracks listing changes across different time windows to identify
the optimal daily scraping time. Runs every 4 hours for 7 days.

Data collected:
- New listings count
- Removed listings count
- Price changes count
- Total listings count
- Time window metadata

Output: timing_study/ directory with JSON logs and weekly analysis.
"""

import json
import os
import csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
LATEST_DIR = os.path.join(BASE_DIR, "data", "latest")
CHANGES_DIR = os.path.join(BASE_DIR, "data", "changes")
TIMING_DIR = os.path.join(BASE_DIR, "data", "timing_study")

# Time windows (4-hour intervals)
TIME_WINDOWS = [
    "00-04 UTC",  # Midnight - 4am UTC (3am-7am Bahrain)
    "04-08 UTC",  # 4am-8am UTC (7am-11am Bahrain)
    "08-12 UTC",  # 8am-12pm UTC (11am-3pm Bahrain)
    "12-16 UTC",  # 12pm-4pm UTC (3pm-7pm Bahrain)
    "16-20 UTC",  # 4pm-8pm UTC (7pm-11pm Bahrain)
    "20-24 UTC",  # 8pm-midnight UTC (11pm-3am Bahrain)
]


def get_time_window(utc_time: str) -> str:
    """Determine which 4-hour time window a timestamp falls in."""
    try:
        dt = datetime.fromisoformat(utc_time.replace('Z', '+00:00'))
        hour = dt.hour
        window_idx = hour // 4
        return TIME_WINDOWS[window_idx]
    except:
        return "unknown"


def read_change_data() -> dict:
    """Read the latest change data from all_changes.csv."""
    all_changes_path = os.path.join(CHANGES_DIR, "all_changes.csv")

    if not os.path.exists(all_changes_path):
        return {"new": 0, "removed": 0, "price_changed": 0, "total": 0}

    changes = {"new": 0, "removed": 0, "price_changed": 0, "total": 0}

    try:
        with open(all_changes_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                change_type = row.get("change_type", "")
                if change_type in changes:
                    changes[change_type] += 1
                changes["total"] += 1
    except Exception as e:
        print(f"Error reading changes: {e}")

    return changes


def read_total_listings() -> int:
    """Get total count of listings."""
    all_listings_path = os.path.join(LATEST_DIR, "all_listings.csv")

    if not os.path.exists(all_listings_path):
        return 0

    try:
        with open(all_listings_path, 'r', encoding='utf-8-sig') as f:
            return sum(1 for _ in f) - 1  # Subtract header
    except Exception as e:
        print(f"Error reading listings: {e}")
        return 0


def get_current_run_metadata() -> dict:
    """Get metadata about the current timing study run."""
    now = datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat(),
        "utc_hour": now.hour,
        "bahrain_hour": (now.hour + 3) % 24,  # Bahrain is UTC+3
        "time_window": get_time_window(now.isoformat()),
        "day_of_week": now.strftime("%A"),
        "study_day": get_study_day_number()
    }


def get_study_day_number() -> int:
    """Calculate which day of the study this is."""
    start_date = datetime(2026, 6, 2, tzinfo=timezone.utc)  # Study start date
    now = datetime.now(timezone.utc)
    days = (now - start_date).days + 1
    return max(1, days)


def record_timing_run():
    """Record a single timing study run."""
    os.makedirs(TIMING_DIR, exist_ok=True)

    metadata = get_current_run_metadata()
    changes = read_change_data()
    total_listings = read_total_listings()

    run_data = {
        **metadata,
        "metrics": {
            "new_listings": changes["new"],
            "removed_listings": changes["removed"],
            "price_changes": changes["price_changed"],
            "total_changes": changes["total"],
            "total_listings": total_listings,
            "net_change": changes["new"] - changes["removed"]
        }
    }

    # Append to daily log
    log_path = os.path.join(TIMING_DIR, "daily_log.jsonl")
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(run_data) + "\n")

    # Save snapshot
    snapshot_path = os.path.join(TIMING_DIR, f"snapshot_{metadata['timestamp'].replace(':', '-')}.json")
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(run_data, f, indent=2)

    print(f"\n[TIMING STUDY] Run recorded: {metadata['time_window']}")
    print(f"  New listings: {changes['new']}")
    print(f"  Removed listings: {changes['removed']}")
    print(f"  Price changes: {changes['price_changed']}")
    print(f"  Total listings: {total_listings}")
    print(f"  Net change: {changes['new'] - changes['removed']}")

    return run_data


def analyze_timing_patterns() -> dict:
    """Analyze timing patterns from collected data."""
    log_path = os.path.join(TIMING_DIR, "daily_log.jsonl")

    if not os.path.exists(log_path):
        return {"error": "No timing data available yet"}

    # Read all runs
    runs = []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                runs.append(json.loads(line.strip()))
    except Exception as e:
        return {"error": f"Error reading log: {e}"}

    if not runs:
        return {"error": "No runs recorded yet"}

    # Group by time window
    window_stats = defaultdict(lambda: {
        "runs": 0,
        "new_listings": [],
        "removed_listings": [],
        "price_changes": [],
        "net_change": [],
        "total_listings": []
    })

    for run in runs:
        window = run.get("time_window", "unknown")
        metrics = run.get("metrics", {})

        stats = window_stats[window]
        stats["runs"] += 1
        stats["new_listings"].append(metrics.get("new_listings", 0))
        stats["removed_listings"].append(metrics.get("removed_listings", 0))
        stats["price_changes"].append(metrics.get("price_changes", 0))
        stats["net_change"].append(metrics.get("net_change", 0))
        stats["total_listings"].append(metrics.get("total_listings", 0))

    # Calculate averages per window
    window_analysis = {}
    for window, stats in window_stats.items():
        if stats["runs"] > 0:
            window_analysis[window] = {
                "runs": stats["runs"],
                "avg_new_listings": sum(stats["new_listings"]) / stats["runs"],
                "avg_removed_listings": sum(stats["removed_listings"]) / stats["runs"],
                "avg_price_changes": sum(stats["price_changes"]) / stats["runs"],
                "avg_net_change": sum(stats["net_change"]) / stats["runs"],
                "avg_total_listings": sum(stats["total_listings"]) / stats["runs"],
                "total_new_listings": sum(stats["new_listings"]),
                "total_removed_listings": sum(stats["removed_listings"]),
                "total_activity": sum(stats["new_listings"]) + sum(stats["removed_listings"]) + sum(stats["price_changes"])
            }

    # Find optimal time window
    optimal_window = None
    max_activity = 0
    for window, data in window_analysis.items():
        if data.get("total_activity", 0) > max_activity:
            max_activity = data["total_activity"]
            optimal_window = window

    return {
        "study_duration_days": get_study_day_number(),
        "total_runs": len(runs),
        "window_analysis": window_analysis,
        "optimal_window": optimal_window,
        "optimal_window_activity": max_activity,
        "recommendation": generate_recommendation(window_analysis, optimal_window)
    }


def generate_recommendation(window_analysis: dict, optimal_window: str) -> str:
    """Generate recommendation based on timing analysis."""
    if not optimal_window or not window_analysis:
        return "Insufficient data for recommendation"

    optimal_data = window_analysis.get(optimal_window, {})
    avg_new = optimal_data.get("avg_new_listings", 0)
    avg_removed = optimal_data.get("avg_removed_listings", 0)

    # Convert time window to recommended hour (middle of window)
    window_to_hour = {
        "00-04 UTC": "02:00 UTC (5:00 AM Bahrain)",
        "04-08 UTC": "06:00 UTC (9:00 AM Bahrain)",
        "08-12 UTC": "10:00 UTC (1:00 PM Bahrain)",
        "12-16 UTC": "14:00 UTC (5:00 PM Bahrain)",
        "16-20 UTC": "18:00 UTC (9:00 PM Bahrain)",
        "20-24 UTC": "22:00 UTC (1:00 AM Bahrain)"
    }

    recommended_time = window_to_hour.get(optimal_window, optimal_window)

    return (
        f"Recommended daily scrape time: {recommended_time}\n"
        f"Reason: This window shows highest activity with {avg_new:.1f} new listings "
        f"and {avg_removed:.1f} removed listings on average."
    )


def print_weekly_report(analysis: dict):
    """Print formatted weekly analysis report."""
    print("=" * 80)
    print("TIMING STUDY WEEKLY REPORT")
    print("=" * 80)

    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return

    print(f"\n[STUDY INFO]")
    print(f"  Duration: {analysis['study_duration_days']} days")
    print(f"  Total Runs: {analysis['total_runs']}")

    print(f"\n[TIME WINDOW ANALYSIS]")
    window_analysis = analysis.get("window_analysis", {})

    # Sort windows by total activity
    sorted_windows = sorted(
        window_analysis.items(),
        key=lambda x: x[1].get("total_activity", 0),
        reverse=True
    )

    for i, (window, data) in enumerate(sorted_windows, 1):
        rank = f"#{i}"
        symbol = "[WINNER]" if i == 1 else "       "

        print(f"\n  {symbol} {window}:")
        print(f"    Runs: {data['runs']}")
        print(f"    Avg New Listings: {data['avg_new_listings']:.1f}")
        print(f"    Avg Removed Listings: {data['avg_removed_listings']:.1f}")
        print(f"    Avg Price Changes: {data['avg_price_changes']:.1f}")
        print(f"    Total Activity: {data['total_activity']}")

    print(f"\n[RECOMMENDATION]")
    print(f"  {analysis['recommendation']}")

    print("=" * 80)


def save_analysis_report(analysis: dict):
    """Save analysis report to JSON."""
    os.makedirs(TIMING_DIR, exist_ok=True)

    report_path = os.path.join(TIMING_DIR, "weekly_analysis.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2)

    print(f"\n[REPORT] Analysis saved: {report_path}")


def generate_markdown_report(analysis: dict) -> str:
    """Generate markdown report for GitHub Actions."""
    md = []

    md.append("# Timing Study Analysis")
    md.append("")

    if "error" in analysis:
        md.append(f"**Error:** {analysis['error']}")
        return "\n".join(md)

    md.append(f"**Study Duration:** {analysis['study_duration_days']} days")
    md.append(f"**Total Runs:** {analysis['total_runs']}")
    md.append("")

    md.append("## Time Window Ranking")
    md.append("")

    window_analysis = analysis.get("window_analysis", {})
    sorted_windows = sorted(
        window_analysis.items(),
        key=lambda x: x[1].get("total_activity", 0),
        reverse=True
    )

    for i, (window, data) in enumerate(sorted_windows, 1):
        symbol = "[WINNER]" if i == 1 else "       "
        md.append(f"### {symbol} {window}")
        md.append(f"- **Runs:** {data['runs']}")
        md.append(f"- **Avg New Listings:** {data['avg_new_listings']:.1f}")
        md.append(f"- **Avg Removed Listings:** {data['avg_removed_listings']:.1f}")
        md.append(f"- **Avg Price Changes:** {data['avg_price_changes']:.1f}")
        md.append(f"- **Total Activity:** {data['total_activity']}")
        md.append("")

    md.append("## Recommendation")
    md.append(f"**{analysis['recommendation']}**")
    md.append("")

    return "\n".join(md)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Timing analysis for PropertyFinder scraping schedule")
    parser.add_argument("--weekly-report", action="store_true", help="Generate weekly analysis report")
    parser.add_argument("--analyze-only", action="store_true", help="Analyze existing data without recording new run")

    args = parser.parse_args()

    if args.analyze_only or args.weekly_report:
        # Analyze existing data
        analysis = analyze_timing_patterns()
        print_weekly_report(analysis)
        save_analysis_report(analysis)

        # GitHub Actions summary
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], 'a') as f:
                f.write("\n" + generate_markdown_report(analysis))
            print("\n[GITHUB] Summary added to workflow")
    else:
        # Record new run
        record_timing_run()

        # Also show current analysis
        analysis = analyze_timing_patterns()
        if "error" not in analysis:
            print(f"\n[PRELIMINARY ANALYSIS] Study Day {analysis['study_duration_days']}")
            print(f"Optimal window so far: {analysis.get('optimal_window', 'TBD')}")


if __name__ == "__main__":
    main()
