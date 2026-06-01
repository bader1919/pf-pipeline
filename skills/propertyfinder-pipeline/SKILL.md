---
name: propertyfinder-pipeline
description: Use when working with the PropertyFinder Bahrain real estate data pipeline (pf-pipeline repo). Trigger for: running/scraping/debugging the pipeline, checking data quality, adding features to scraper/cleaner, debugging empty data issues, updating handover logs, or any questions about the Bahrain market intelligence pipeline.
---

# PropertyFinder Bahrain Pipeline

## Overview

Bahrain real estate market intelligence pipeline with 5 stages producing 24,600+ listings at 100% data quality.

**Stages:** scrape → clean → compare → quality gate → report

**Current Status:** Timing study running (June 2-9, 2026), daily scrape paused.

## Architecture

```
1. SCRAPE (pf_scraper.py)
   ├─ Discovery: Find subcategory URLs dynamically
   ├─ Scrape: 4 workers, rate limited (0.5s + 0.5s jitter)
   └─ Output: Raw JSON (data/raw/)

2. CLEAN (cleaner.py)
   ├─ Flatten: Extract nested JSON → flat CSV
   ├─ Validate: Critical field extraction
   └─ Output: Clean CSVs (data/latest/)

3. COMPARE (comparator.py)
   ├─ Diff: Today vs yesterday
   ├─ Track: New/removed/price changes
   └─ Output: Change logs (data/changes/)

4. QUALITY GATE (quality_gate.py)
   ├─ Validate: 5 critical fields (95% threshold)
   ├─ Report: JSON + Markdown
   └─ Gate: Exit code 1 on failure

5. REPORT (reporter.py)
   ├─ Analyze: Pipeline health
   └─ Output: latest_report.json
```

**Data Schema:** 114 columns (listings), 120 columns (projects)

## Common Workflows

### Running the Pipeline Locally

```bash
# Full pipeline
pip install -r scraper/requirements.txt
python scraper/pf_scraper.py      # Step 1: Scrape
python scraper/cleaner.py          # Step 2: Clean
python scraper/comparator.py       # Step 3: Compare
python scraper/quality_gate.py     # Step 4: Quality check
python scraper/reporter.py         # Step 5: Report
```

**Expected time:** 10-15 minutes for ~25k listings

### Checking Data Quality

```bash
# Quick quality check
python scraper/quality_gate.py

# Detailed quality report
python scraper/quality_gate.py --detailed
```

**Quality thresholds:**
- 95% critical field completeness
- Max 10% missing prices
- Max 10% missing locations
- Minimum 20,000 listings

**Critical fields:** listing_id, price_value, latitude, longitude, title

### Debugging Data Issues

**Step 1: Check quality report**
```bash
# Read the quality report
cat data/latest/quality_report.md
```

**Step 2: Verify raw JSON structure**
```bash
# Check if raw data exists
ls data/raw/*.json

# Sample raw JSON to see structure
python -c "import json; print(json.load(open('data/raw/residential_rent.json'))[0])"
```

**Step 3: Test extraction manually**
```bash
# Re-run cleaner
python scraper/cleaner.py

# Check output
head -5 data/latest/residential_rent.csv
```

**Common Issue - Empty CSV Data:**
- **Symptom:** CSV has correct row count but all values empty
- **Root Cause:** Nested JSON structure not extracted
- **Fix Location:** `scraper/cleaner.py` - check `flatten_listing()` function
- **Typical Bug:** `property` object is nested, need `p.get("property", {})` not `p.get()`
- **Another Bug:** `coordinates.lat/lon` nested under `location.coordinates`

### Adding New Extraction Fields

**When:** API returns new field you need to capture

**Steps:**
1. **Add column name** to `COLUMNS` list in `cleaner.py` (line ~40)
2. **Add extraction** in `flatten_listing()` function:
   ```python
   "new_field": s(p.get("newField") or get(nested_obj, "key"))
   ```
3. **Test locally:**
   ```bash
   python scraper/cleaner.py
   python scraper/quality_gate.py --detailed
   ```
4. **Verify quality score** still 100%
5. **Update HANDOVER.md** with the change

**What NOT to do:**
- Don't forget to test after adding
- Don't skip quality verification
- Don't commit without updating HANDOVER.md

### Updating Handover Log

**When:** After any code changes, bug fixes, or feature additions

**Option 1: Manual (for complex changes)**
- Edit `HANDOVER.md` following the template
- Use format: `### **YYYY-MM-DD - Brief Title**`
- Include: Who, What, Changes, Why, Status, Files Modified
- Commit with format: `docs: description of change`

**Option 2: Automatic (for simple updates)**
```bash
python scraper/update_handover.py --event "Bug Fix" --what "Fixed extraction bug" --status "Completed"
```

**Golden Rule:** Update BEFORE pushing to GitHub

## Quick Reference

| File | Purpose | When to Modify |
|------|---------|-----------------|
| `pf_scraper.py` | Scrapes PropertyFinder API | Adding new category, changing rate limits |
| `cleaner.py` | Flattens JSON to CSV | Adding new fields, fixing extraction bugs |
| `quality_gate.py` | Validates data quality | Changing thresholds, adding new checks |
| `comparator.py` | Tracks changes over time | Change tracking logic |
| `reporter.py` | Generates reports | Report format changes |
| `timing_analysis.py` | Analyzes timing study | Timing study customization |
| `HANDOVER.md` | Project log | EVERY code change |

| Command | What It Does | When to Use |
|---------|--------------|--------------|
| `python scraper/pf_scraper.py` | Scrape raw data | Fresh data needed |
| `python scraper/cleaner.py` | Clean to CSV | After scraping |
| `python scraper/quality_gate.py` | Check quality | Before committing data |
| `python scraper/reporter.py` | Generate report | Pipeline health check |
| `python scraper/update_handover.py --event "X" --what "Y"` | Log changes | After code changes |

## Quality Standards

**Current Quality:** 100% (all critical fields complete)

**Validation:**
- 5 critical fields must be 95%+ complete
- Price ranges: 1 BHD - 584M BHD (sanity check)
- Location coordinates: Required for mapping
- No missing listing IDs

**If quality fails:**
1. Read `data/latest/quality_report.json` for violation details
2. Identify which threshold failed
3. Determine if:
   - **Data issue:** Fix extraction in cleaner.py
   - **Threshold too strict:** Adjust in quality_gate.py
4. Re-test with `python scraper/quality_gate.py --detailed`

## Development Patterns

### Pattern 1: Adding New Category to Scrape

1. **Add to CATEGORIES list** in `pf_scraper.py`
2. **Define data_key:** "listings", "projects", or "agents"
3. **Add column schema** (if new structure) in `cleaner.py`
4. **Test with single category first**
5. **Run quality gate** to verify

### Pattern 2: Modifying Quality Thresholds

1. **Edit THRESHOLDS dict** in `quality_gate.py`
2. **Consider impact:**
   - Too strict = legitimate failures blocked
   - Too loose = bad data commits
3. **Test with current data:** `python scraper/quality_gate.py --detailed`
4. **Document rationale** in HANDOVER.md

### Pattern 3: Debugging Nested JSON

**The Problem:** API structure is deeply nested

**Solution Pattern:**
```python
# Check raw structure first
import json
data = json.load(open('data/raw/residential_rent.json'))
first = data[0]

# Trace the path
print(list(first.keys()))  # Top level
print(list(first.get('property', {}).keys()))  # Nested
print(list(first.get('property', {}).get('location', {}).keys()))  # Deep nested
```

**Common Paths:**
- `property.id` (not `id`)
- `property.price.value` (not `price.value`)
- `property.location.coordinates.lat` (not `location.lat`)

## Common Issues & Solutions

| Problem | Solution | Reference |
|---------|----------|-----------|
| Empty CSV values | Check nested `property` object in cleaner.py | Line 251-254 |
| Missing coordinates | Check `location.coordinates.lat/lon` | Line 300-301 |
| Quality gate fails | Read quality_report.json, check thresholds | `data/latest/` |
| Pipeline timeout | Check API rate limiting, workers count | pf_scraper.py |
| GitHub Actions fails | Check workflow logs in Actions tab | `.github/workflows/` |
| Wrong data extracted | Verify raw JSON structure hasn't changed | `data/raw/*.json` |

## Current Status

**🟢 Timing Study Phase (June 2-9, 2026)**

**Active:**
- Timing study running every 4 hours
- Tracks 6 time windows to find optimal scrape time
- Data collection in `data/timing_study/`

**Paused:**
- Daily scrape (will resume after June 9)

**Quality:** 100% (24,622 listings)

**Next Steps:**
- June 9: Analyze timing study results
- June 9: Update daily scrape to optimal time
- June 9: Resume normal daily operations

## Git Workflow

**Branch Strategy:** Master-only (currently)

**Commit Message Format:**
```
fix: one-line description
feat: one-line description
docs: one-line description
```

**Example:**
```
fix: nested property object extraction in cleaner
docs: add quality gate system documentation
```

**Before Pushing:**
1. ✅ Code works locally
2. ✅ Quality gate passes
3. ✅ HANDOVER.md updated
4. ✅ Tested affected functionality

**Auto-Updates:**
- GitHub Actions automatically logs to HANDOVER.md
- Quality gate status in commit messages
- No manual action needed for pipeline runs

## Testing Approach

**Manual Verification Required:**

**After extraction changes:**
1. Run cleaner: `python scraper/cleaner.py`
2. Check sample: `head data/latest/residential_rent.csv`
3. Verify quality: `python scraper/quality_gate.py --detailed`

**After quality threshold changes:**
1. Test with current data
2. Verify expected pass/fail
3. Check if threshold realistic

**After workflow changes:**
1. Push to GitHub
2. Monitor Actions tab
3. Check workflow run logs

**No automated tests exist** - manual verification is current standard.

## External Resources

- **PropertyFinder Bahrain:** https://www.propertyfinder.bh
- **Repository:** https://github.com/bader1919/pf-pipeline
- **Power BI Docs:** https://docs.microsoft.com/power-bi
- **GitHub Actions Docs:** https://docs.github.com/actions

## Getting Help

**If stuck:**
1. Check HANDOVER.md change log for similar issues
2. Read quality report for violation details
3. Verify raw JSON structure
4. Test extraction step-by-step

**Documentation Files:**
- `HANDOVER.md` - This file (complete project log)
- `CLAUDE.md` - Claude-specific guidance
- `TIMING_STUDY_README.md` - Timing study details

**Contact:**
- Owner: Bader
- Repository: bader1919/pf-pipeline
