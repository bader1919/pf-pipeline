"""
Handover Log Auto-Updater.

Updates HANDOVER.md when GitHub Actions run.
Keeps a running log of all pipeline activity.
"""

import os
import json
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
HANDOVER_PATH = os.path.join(BASE_DIR, "HANDOVER.md")


def update_handover(event_type: str, details: dict):
    """Append a new entry to the handover log."""
    if not os.path.exists(HANDOVER_PATH):
        create_handover()

    # Read current handover
    with open(HANDOVER_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the change log section
    change_log_start = content.find("## 🔄 Change Log")

    if change_log_start == -1:
        print("[ERROR] Could not find Change Log section")
        return

    # Create new entry
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_entry = format_entry(timestamp, event_type, details)

    # Insert after the change log header
    insert_position = content.find("\n###", change_log_start)
    if insert_position == -1:
        # No existing entries, insert after header
        insert_position = content.find("\n", content.find("---", change_log_start))

    updated_content = content[:insert_position] + "\n" + new_entry + "\n" + content[insert_position:]

    # Write back
    with open(HANDOVER_PATH, 'w', encoding='utf-8') as f:
        f.write(updated_content)

    print(f"[HANDOVER] Updated: {event_type}")


def format_entry(timestamp: str, event_type: str, details: dict) -> str:
    """Format a handover log entry."""
    who = details.get("who", "GitHub Actions")
    what = details.get("what", "Pipeline run")

    entry = f"""### **{timestamp} - {event_type}**

**Who:** {who}
**What:** {what}

**Details:**
"""

    # Add details
    for key, value in details.items():
        if key not in ["who", "what"]:
            entry += f"- **{key}:** {value}\n"

    entry += f"""
**Status:** {details.get("status", "Completed")}
**Files Generated:** {", ".join(details.get("files", []))}

---

"""
    return entry


def create_handover():
    """Create initial handover file if it doesn't exist."""
    initial_content = """# PropertyFinder Bahrain Pipeline - Handover Log

**Project:** Real estate data pipeline for Bahrain market intelligence
**Repo:** `bader1919/pf-pipeline`
**Started:** {timestamp}
**Last Updated:** {timestamp}

---

## 🔄 Change Log

"""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(HANDOVER_PATH, 'w', encoding='utf-8') as f:
        f.write(initial_content.format(timestamp=timestamp))


def log_pipeline_run(run_type: str, metrics: dict):
    """Log a pipeline run to handover."""
    details = {
        "who": "GitHub Actions",
        "what": f"{run_type} pipeline run",
        "status": "Success",
        "total_listings": metrics.get("total_listings", 0),
        "quality_score": f"{metrics.get('quality_score', 0)}%",
        "new_listings": metrics.get("new_listings", 0),
        "removed_listings": metrics.get("removed_listings", 0),
        "files": ["all_listings.csv", "quality_report.json", "quality_report.md"]
    }

    update_handover(f"{run_type} Run", details)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Update handover log")
    parser.add_argument("--event", required=True, help="Event type")
    parser.add_argument("--who", default="GitHub Actions", help="Who triggered event")
    parser.add_argument("--what", required=True, help="What happened")
    parser.add_argument("--status", default="Completed", help="Event status")

    args = parser.parse_args()

    details = {
        "who": args.who,
        "what": args.what,
        "status": args.status
    }

    update_handover(args.event, details)


if __name__ == "__main__":
    main()
