# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r scraper/requirements.txt

# Run the 3-step pipeline locally (~45 min for full catalogue)
python scraper/pf_scraper.py      # Step 1: Scrape API → data/raw/
python scraper/cleaner.py          # Step 2: Raw JSON → CSVs in data/latest/
python scraper/comparator.py       # Step 3: Diff vs previous snapshot → data/changes/

# There are no tests in this repository.
```

## Architecture

This is a daily PropertyFinder Bahrain market intelligence pipeline. It scrapes ~25-30k real estate listings and tracks market changes over time.

**Data flow:** API → Raw JSON → Clean CSVs → Change tracking

Three sequential scripts in `scraper/`:

- **pf_scraper.py** — Hits the PropertyFinder API directly (not HTML parsing). Scrapes 4 listing categories: `residential_rent`, `residential_sale`, `commercial_rent`, `commercial_sale`. Handles pagination with 1.5s delay between requests. Writes raw JSON + a manifest to `data/raw/`.

- **cleaner.py** — Flattens nested JSON into a flat 114-column CSV schema matching a downstream n8n `pf_listings` table. Outputs per-category CSVs plus a combined `all_listings.csv` to `data/latest/`.

- **comparator.py** — Compares today's snapshot (`data/latest/`) against yesterday's (`data/previous/`). Tracks 3 change types: new listings, removed listings, price changes. Maintains cumulative history in `data/changes/all_changes.csv` and daily deltas in `data/changes/YYYY-MM-DD.csv`. Rotates snapshots for next comparison.

**Data directories:**

| Directory | Purpose |
|-----------|---------|
| `data/raw/` | Raw JSON from API (gitignored) |
| `data/latest/` | Today's cleaned CSV snapshots |
| `data/previous/` | Yesterday's snapshots (for diffing) |
| `data/changes/` | Cumulative + daily change logs |

## CI/CD

GitHub Actions workflow (`.github/workflows/daily_scrape.yml`) runs the full pipeline daily at 02:00 UTC with a 120-minute timeout. Steps: scrape → clean → compare → commit updated data back to the repo. Uses `GITHUB_TOKEN` automatically — no secrets required.

## Key Details

- No secrets or API keys needed (public API + `GITHUB_TOKEN` in Actions).
- The 114-column CSV schema is the contract between this pipeline and downstream consumers (Power BI, n8n).
- All data is preserved during cleaning — nothing is dropped.
- Designed for Power BI integration via GitHub raw CSV access.
