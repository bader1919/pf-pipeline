"""
PropertyFinder Pipeline Briefing Generator
==========================================
Compares the latest pipeline run to the previous one and writes a
markdown briefing to briefing/latest.md.

Usage:
    python scripts/generate_briefing.py

Output:
    briefing/latest.md
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

QUALITY_REPORT   = Path("data/latest/quality_report.md")
PIPELINE_REPORT  = Path("data/latest_report.json")
TIMING_LOG       = Path("data/timing_study/daily_log.jsonl")
HISTORY_DIR      = Path("data/history")          # optional – previous runs
BRIEFING_DIR     = Path("briefing")
BRIEFING_FILE    = BRIEFING_DIR / "latest.md"

# ---------------------------------------------------------------------------
# Parsing (same helpers as email_notification.py, kept self-contained)
# ---------------------------------------------------------------------------

def parse_quality_report(path: Path) -> dict:
    if not path.exists():
        return {"error": f"Not found: {path}"}
    text = path.read_text(encoding="utf-8")
    passed = None
    if re.search(r"(?i)(quality gate[:\s]+PASS|✅\s*PASS|status[:\s]+PASS)", text):
        passed = True
    elif re.search(r"(?i)(quality gate[:\s]+FAIL|❌\s*FAIL|status[:\s]+FAIL)", text):
        passed = False
    else:
        passed = "FAIL" not in text.upper()

    score = None
    m = re.search(r"(?i)(?:quality\s+)?score[:\s]+([0-9.]+)\s*%?", text)
    if m:
        score = float(m.group(1))

    total = None
    m = re.search(r"(?i)total\s+listings?[:\s]+([0-9,]+)", text)
    if m:
        total = int(m.group(1).replace(",", ""))

    violations = []
    in_v = False
    for line in text.splitlines():
        if re.match(r"(?i)##?\s*violations?", line):
            in_v = True
            continue
        if in_v:
            if line.startswith("#"):
                in_v = False
            elif line.strip().startswith(("-", "*", "•")) and line.strip()[1:].strip():
                violations.append(line.strip().lstrip("-*• "))

    return {"passed": passed, "quality_score": score, "total_listings": total, "violations": violations}


def parse_pipeline_report(path: Path) -> dict:
    if not path.exists():
        return {"error": f"Not found: {path}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"error": str(e)}
    return {
        "total_listings":   data.get("total_listings")   or data.get("total")   or data.get("count"),
        "new_listings":     data.get("new_listings")     or data.get("new")     or data.get("added"),
        "removed_listings": data.get("removed_listings") or data.get("removed") or data.get("deleted"),
        "timestamp":        data.get("timestamp")        or data.get("run_at")  or data.get("generated_at"),
        "duration_seconds": data.get("duration_seconds") or data.get("duration"),
    }


def load_previous_report() -> dict | None:
    """Try to find the previous run's report in data/history/."""
    if not HISTORY_DIR.exists():
        return None
    reports = sorted(HISTORY_DIR.glob("*_report.json"))
    if not reports:
        return None
    try:
        data = json.loads(reports[-1].read_text(encoding="utf-8"))
        return {
            "total_listings": data.get("total_listings") or data.get("total") or data.get("count"),
            "quality_score":  data.get("quality_score"),
            "passed":         data.get("passed"),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Timing study helpers
# ---------------------------------------------------------------------------

def parse_timing_study() -> dict:
    result = {"days_logged": 0, "best_window": "N/A", "entries": []}
    if not TIMING_LOG.exists():
        return result

    entries = []
    for line in TIMING_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    result["days_logged"] = len(entries)
    result["entries"] = entries

    # Try to determine best window by highest quality_score or listing count
    best = None
    for e in entries:
        score = e.get("quality_score") or e.get("score")
        if score is not None:
            if best is None or score > (best.get("quality_score") or best.get("score") or 0):
                best = e
    if best:
        window = best.get("window") or best.get("time_window") or best.get("hour")
        result["best_window"] = str(window) if window else "N/A"

    return result


# ---------------------------------------------------------------------------
# Trend helpers
# ---------------------------------------------------------------------------

def quality_trend(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "unknown"
    diff = current - previous
    if diff > 1:
        return "improving ↑"
    if diff < -1:
        return "degrading ↓"
    return "stable →"


def listing_delta(current: int | None, previous: int | None) -> str:
    if current is None or previous is None:
        return "N/A"
    diff = current - previous
    if diff > 0:
        return f"+{diff}"
    return str(diff)


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------

def generate_briefing(quality: dict, pipeline: dict, prev: dict | None, timing: dict) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts = pipeline.get("timestamp") or now_str

    passed      = quality.get("passed")
    score       = quality.get("quality_score")
    total       = pipeline.get("total_listings") or quality.get("total_listings")
    new_lst     = pipeline.get("new_listings")
    removed     = pipeline.get("removed_listings")
    violations  = quality.get("violations", [])
    duration    = pipeline.get("duration_seconds")

    status_icon  = "✅ PASS" if passed else "❌ FAIL" if passed is not None else "⚠️ UNKNOWN"
    score_str    = f"{score:.1f}%" if score is not None else "N/A"
    total_str    = str(total) if total is not None else "N/A"
    new_str      = str(new_lst) if new_lst is not None else "N/A"
    removed_str  = str(removed) if removed is not None else "N/A"
    dur_str      = f"{duration}s" if duration else "N/A"

    prev_score   = (prev or {}).get("quality_score")
    prev_total   = (prev or {}).get("total_listings")
    trend        = quality_trend(score, prev_score)
    delta        = listing_delta(total, prev_total)

    # ---- Bullet 1: what happened ----
    if passed:
        b1 = f"Pipeline ran successfully at {ts} — {total_str} listings, {new_str} new, {removed_str} removed."
    else:
        b1 = f"Pipeline FAILED at {ts}. Quality gate not met — review required before production use."

    # ---- Bullet 2: any issues ----
    if violations:
        b2 = "Issues detected: " + "; ".join(violations[:3])
        if len(violations) > 3:
            b2 += f" (+{len(violations) - 3} more)"
    elif not passed:
        b2 = "Quality gate failed but no specific violations were parsed — check the full quality report."
    else:
        b2 = "No violations. Data quality looks clean."

    # ---- Bullet 3: recommendations ----
    if not passed:
        b3 = "Action required: Investigate quality violations before next scheduled run."
    elif score is not None and score < 90:
        b3 = f"Quality score is below 90% ({score_str}). Consider tightening scraper filters."
    elif delta.startswith("-"):
        b3 = f"Listing count dropped by {abs(int(delta))} vs previous run. Check for source-side changes."
    else:
        b3 = "Everything looks good. No immediate action needed."

    # ---- Timing study section ----
    days   = timing["days_logged"]
    window = timing["best_window"]
    timing_section = f"Day {days} of 7\nBest window so far: {window}" if days > 0 else "No data yet."

    briefing = f"""# PropertyFinder Pipeline Briefing
Generated: {now_str}

## Latest Run Summary
- Run at: {ts}
- Status: {status_icon}
- Quality Score: {score_str}
- Total Listings: {total_str} ({delta} vs previous)
- New: {new_str} | Removed: {removed_str}
- Duration: {dur_str}

## This Run's Highlights
- {b1}
- {b2}
- {b3}

## Quality Trends
- Current quality: {score_str}
- Previous quality: {f"{prev_score:.1f}%" if prev_score else "N/A"}
- Trend: {trend}

## Next Steps
- {"Investigate quality violations immediately." if not passed else "No action needed — monitor next run."}
- {"Archive this run's report to data/history/ if not automated." if not (HISTORY_DIR / "last.json").exists() else "History logging active."}

## Timing Study Status
{timing_section}
"""
    return briefing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    quality  = parse_quality_report(QUALITY_REPORT)
    pipeline = parse_pipeline_report(PIPELINE_REPORT)
    prev     = load_previous_report()
    timing   = parse_timing_study()

    briefing = generate_briefing(quality, pipeline, prev, timing)

    BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFING_FILE.write_text(briefing, encoding="utf-8")
    print(f"Briefing written to {BRIEFING_FILE}")
    print()
    print(briefing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
