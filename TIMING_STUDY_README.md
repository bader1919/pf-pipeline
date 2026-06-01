# Timing Study - Finding Optimal Scrape Time

**Started:** June 2, 2026
**Duration:** 7 days
**Frequency:** Every 4 hours (6 runs per day)

## Purpose

We need to find the optimal time to scrape PropertyFinder Bahrain to capture the most daily changes. Currently, we scrape at 02:00 UTC (5:00 AM Bahrain), but we have no confirmation this is the best time.

## How It Works

### Time Windows (4-hour intervals)
- **00-04 UTC** (3:00 AM - 7:00 AM Bahrain) - Early morning
- **04-08 UTC** (7:00 AM - 11:00 AM Bahrain) - Morning business hours
- **08-12 UTC** (11:00 AM - 3:00 PM Bahrain) - Midday
- **12-16 UTC** (3:00 PM - 7:00 PM Bahrain) - Afternoon
- **16-20 UTC** (7:00 PM - 11:00 PM Bahrain) - Evening
- **20-24 UTC** (11:00 PM - 3:00 AM Bahrain) - Late night

### Data Collected Per Run
- New listings count
- Removed listings count
- Price changes count
- Total listings count
- Net change (new - removed)
- Timestamp metadata

## Expected Results

After 7 days (42 runs total), we'll have:

1. **Activity patterns by time window**
   - Which 4-hour window shows most activity
   - When new listings typically appear
   - When removed listings occur
   - Price change patterns

2. **Optimal scraping time**
   - Time window with highest total activity
   - Recommended daily scrape schedule
   - Bahrain time vs UTC time

## Current Status

**Data being collected in:** `data/timing_study/`

**Files generated:**
- `daily_log.jsonl` - All run records
- `snapshot_*.json` - Individual run snapshots
- `weekly_analysis.json` - Compiled analysis after 7 days

## How to Check Progress

### View Latest Run
```bash
# Check the most recent timing study run
tail -1 data/timing_study/daily_log.jsonl | python -m json.tool
```

### View Current Analysis
```bash
# Run analysis at any time (even before 7 days)
python scraper/timing_analysis.py --analyze-only
```

### Generate Weekly Report
```bash
# After 7 days, generate final report
python scraper/timing_analysis.py --weekly-report
```

## Post-Study Actions

### After 7 Days (June 9, 2026):

1. **Analyze results**
   ```bash
   python scraper/timing_analysis.py --weekly-report
   ```

2. **Review recommendations**
   - Check `data/timing_study/weekly_analysis.json`
   - Identify optimal time window
   - Note recommendation in `data/timing_study/weekly_report.md`

3. **Update daily scrape schedule**
   - Edit `.github/workflows/daily_scrape.yml`
   - Uncomment schedule line with optimal time
   - Push to GitHub

4. **Disable timing study**
   - Disable or delete `.github/workflows/timing_study.yml`
   - Optional: Archive timing study data

## Example Output

```
[TIME WINDOW ANALYSIS]

  [WINNER] 08-12 UTC:
    Runs: 7
    Avg New Listings: 15.3
    Avg Removed Listings: 8.2
    Avg Price Changes: 45.6
    Total Activity: 69.1

[RECOMMENDATION]
  Recommended daily scrape time: 10:00 UTC (1:00 PM Bahrain)
  Reason: This window shows highest activity with 15.3 new listings
  and 8.2 removed listings on average.
```

## Notes

- **Study runs independently** of daily scrape
- **Both workflows** can run simultaneously (disabled daily for now)
- **No data loss** - all runs go to same `data/` directories
- **Automatic tracking** - every run is timestamped and logged
- **GitHub Actions summary** - see results in workflow runs

## Questions?

- **Q:** What if the optimal time is the middle of the night?
- **A:** We'll pick the best business hours alternative (8 AM - 8 PM Bahrain)

- **Q:** What if all windows show similar activity?
- **A:** We'll choose 10:00 UTC (1 PM Bahrain) - middle of business day

- **Q:** Can we extend the study beyond 7 days?
- **A:** Yes - just let it run longer. More data = better patterns.
