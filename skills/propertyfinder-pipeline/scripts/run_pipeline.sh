#!/bin/bash
# PropertyFinder Pipeline - Run All Stages
# Usage: cd /path/to/pf-pipeline && bash scripts/run_pipeline.sh

set -e  # Exit on error

echo "==================================="
echo "PropertyFinder Pipeline - Full Run"
echo "==================================="
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Step 1: Scrape
echo "[1/5] Scraping PropertyFinder API..."
python scraper/pf_scraper.py
echo "✓ Scraping complete"
echo ""

# Step 2: Clean
echo "[2/5] Cleaning data (JSON → CSV)..."
python scraper/cleaner.py
echo "✓ Cleaning complete"
echo ""

# Step 3: Compare
echo "[3/5] Comparing with previous snapshot..."
python scraper/comparator.py
echo "✓ Comparison complete"
echo ""

# Step 4: Quality Gate
echo "[4/5] Running quality gate..."
if python scraper/quality_gate.py --detailed; then
    echo "✓ Quality gate PASSED"
else
    echo "✗ Quality gate FAILED"
    echo "Check data/latest/quality_report.md for details"
    exit 1
fi
echo ""

# Step 5: Report
echo "[5/5] Generating pipeline report..."
python scraper/reporter.py
echo "✓ Reporting complete"
echo ""

echo "==================================="
echo "Pipeline Complete!"
echo "==================================="
echo ""
echo "Output files:"
echo "  - data/latest/all_listings.csv"
echo "  - data/latest/quality_report.md"
echo "  - data/latest_report.json"
echo ""
echo "Next steps:"
echo "  1. Review quality report: cat data/latest/quality_report.md"
echo "  2. Check for violations"
echo "  3. Update HANDOVER.md if needed"
