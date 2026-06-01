#!/bin/bash
# PropertyFinder Pipeline - Quick Quality Check
# Usage: cd /path/to/pf-pipeline && bash scripts/check_quality.sh

echo "==================================="
echo "PropertyFinder - Quality Check"
echo "==================================="
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Check if data exists
if [ ! -f "data/latest/all_listings.csv" ]; then
    echo "✗ No data found. Run pipeline first:"
    echo "  python scraper/cleaner.py"
    exit 1
fi

echo "Checking data quality..."
echo ""

# Run quality gate
python scraper/quality_gate.py --detailed

# Show report location
echo ""
echo "==================================="
echo "Quality Report Available:"
echo "==================================="
echo ""
echo "  Markdown: data/latest/quality_report.md"
echo "  JSON:     data/latest/quality_report.json"
echo ""
echo "Quick checks:"
echo "  - View summary: head -20 data/latest/quality_report.md"
echo "  - Check violations: grep -A5 'VIOLATIONS' data/latest/quality_report.md"
