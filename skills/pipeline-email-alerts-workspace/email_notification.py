"""
PropertyFinder Pipeline Email Notification Script
=================================================
Reads quality_report.md and latest_report.json, then sends a summary email.

Usage:
    python scripts/email_notification.py [--test]

Environment variables (set via GitHub Secrets):
    RECIPIENT_EMAIL   - Where to send the notification
    SMTP_PASSWORD     - Gmail App Password (not your account password)
    SMTP_FROM         - Sender address (defaults to RECIPIENT_EMAIL)
    GITHUB_SERVER_URL - Auto-set by GitHub Actions
    GITHUB_REPOSITORY - Auto-set by GitHub Actions
    GITHUB_RUN_ID     - Auto-set by GitHub Actions
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

QUALITY_REPORT_PATH = Path("data/latest/quality_report.md")
PIPELINE_REPORT_PATH = Path("data/latest_report.json")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_quality_report(path: Path) -> dict:
    """Extract status and metrics from quality_report.md."""
    result = {
        "passed": None,
        "quality_score": None,
        "total_listings": None,
        "violations": [],
        "raw": "",
    }

    if not path.exists():
        result["error"] = f"File not found: {path}"
        return result

    text = path.read_text(encoding="utf-8")
    result["raw"] = text

    # Quality gate verdict — look for common patterns
    if re.search(r"(?i)(quality gate[:\s]+PASS|✅\s*PASS|status[:\s]+PASS)", text):
        result["passed"] = True
    elif re.search(r"(?i)(quality gate[:\s]+FAIL|❌\s*FAIL|status[:\s]+FAIL)", text):
        result["passed"] = False
    else:
        # Fallback: if the word FAIL appears, treat as failed
        result["passed"] = "FAIL" not in text.upper()

    # Quality score  e.g. "Quality Score: 97.3%" or "Score: 97.3"
    m = re.search(r"(?i)(?:quality\s+)?score[:\s]+([0-9.]+)\s*%?", text)
    if m:
        result["quality_score"] = float(m.group(1))

    # Total listings
    m = re.search(r"(?i)total\s+listings?[:\s]+([0-9,]+)", text)
    if m:
        result["total_listings"] = int(m.group(1).replace(",", ""))

    # Violations — collect bulleted lines after a "Violations" heading
    in_violations = False
    for line in text.splitlines():
        if re.match(r"(?i)##?\s*violations?", line):
            in_violations = True
            continue
        if in_violations:
            if line.startswith("#"):
                in_violations = False
            elif line.strip().startswith(("-", "*", "•")) and line.strip()[1:].strip():
                result["violations"].append(line.strip().lstrip("-*• "))

    return result


def parse_pipeline_report(path: Path) -> dict:
    """Extract key metrics from latest_report.json."""
    result = {
        "total_listings": None,
        "new_listings": None,
        "removed_listings": None,
        "timestamp": None,
        "duration_seconds": None,
    }

    if not path.exists():
        result["error"] = f"File not found: {path}"
        return result

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse error: {e}"
        return result

    # Common key patterns — adapt if your schema differs
    result["total_listings"] = data.get("total_listings") or data.get("total") or data.get("count")
    result["new_listings"]   = data.get("new_listings")   or data.get("new")     or data.get("added")
    result["removed_listings"] = data.get("removed_listings") or data.get("removed") or data.get("deleted")
    result["timestamp"]      = data.get("timestamp")      or data.get("run_at")  or data.get("generated_at")
    result["duration_seconds"] = data.get("duration_seconds") or data.get("duration")

    return result


# ---------------------------------------------------------------------------
# Email formatting
# ---------------------------------------------------------------------------

def build_run_url() -> str:
    server  = os.getenv("GITHUB_SERVER_URL",  "https://github.com")
    repo    = os.getenv("GITHUB_REPOSITORY",  "bader1919/pf-pipeline")
    run_id  = os.getenv("GITHUB_RUN_ID",      "")
    if run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return f"{server}/{repo}/actions"


def format_email(quality: dict, pipeline: dict, test_mode: bool = False) -> tuple[str, str]:
    """Return (subject, body)."""

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Prefer pipeline timestamp; fall back to now
    ts = pipeline.get("timestamp") or now_str

    passed = quality.get("passed")
    status_label = "PASS" if passed else "FAIL" if passed is not None else "UNKNOWN"
    status_icon  = "✅" if passed else "❌" if passed is not None else "⚠️"

    # Metrics — prefer pipeline report, fall back to quality report
    total    = pipeline.get("total_listings")    or quality.get("total_listings")    or "N/A"
    new_lst  = pipeline.get("new_listings")      or "N/A"
    removed  = pipeline.get("removed_listings")  or "N/A"
    score    = quality.get("quality_score")
    score_str = f"{score:.1f}%" if score is not None else "N/A"

    violations = quality.get("violations", [])
    violations_section = ""
    if violations:
        violations_section = "\nViolations:\n" + "\n".join(f"  • {v}" for v in violations) + "\n"

    # 1-2 sentence summary
    if passed:
        summary = (
            f"Pipeline completed successfully with {total} total listings "
            f"({new_lst} new). Quality score: {score_str}."
        )
    else:
        vcount = len(violations)
        summary = (
            f"Pipeline FAILED the quality gate with {vcount} violation(s). "
            f"Manual review required before data is considered production-ready."
        )

    run_url = build_run_url()
    test_banner = "[TEST MODE] " if test_mode else ""

    subject = f"{test_banner}[PropertyFinder] Pipeline Run — {status_icon} {status_label} — {now_str[:10]}"

    body = f"""Pipeline run completed: {ts}

Status:           {status_icon} {status_label}
Quality Score:    {score_str}
Total Listings:   {total}
New Listings:     {new_lst}
Removed Listings: {removed}
{violations_section}
Summary:
{summary}

Workflow run: {run_url}
"""

    return subject, body


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str, recipient: str, smtp_password: str, sender: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, smtp_password)
        server.sendmail(sender, [recipient], msg.as_string())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    test_mode = "--test" in sys.argv

    recipient     = os.getenv("RECIPIENT_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender        = os.getenv("SMTP_FROM") or recipient

    if not test_mode and (not recipient or not smtp_password):
        print("ERROR: RECIPIENT_EMAIL and SMTP_PASSWORD must be set.", file=sys.stderr)
        return 1

    quality  = parse_quality_report(QUALITY_REPORT_PATH)
    pipeline = parse_pipeline_report(PIPELINE_REPORT_PATH)

    subject, body = format_email(quality, pipeline, test_mode=test_mode)

    if test_mode:
        print("=" * 60)
        print("SUBJECT:", subject)
        print("=" * 60)
        print(body)
        print("=" * 60)
        print("[Test mode] Email NOT sent.")
        return 0

    try:
        send_email(subject, body, recipient, smtp_password, sender)
        print(f"Email sent to {recipient}: {subject}")
        return 0
    except Exception as e:
        # Log but do NOT block the pipeline
        print(f"WARNING: Failed to send email: {e}", file=sys.stderr)
        return 0  # intentionally non-fatal


if __name__ == "__main__":
    sys.exit(main())
