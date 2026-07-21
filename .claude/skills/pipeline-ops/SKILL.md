---
name: pipeline-ops
description: Operate, debug, and recover the PropertyFinder BH pipeline. Use when the user asks to check the run, fix the dashboard, investigate data gaps, re-clean an archived day, verify Neon, or diagnose a red GitHub Actions run.
---

# Pipeline Operations

Daily flow (all automatic, 20:00 UTC): scrape → clean → compare → report → quality gate → Postgres load (Supabase) → archive → commit → dashboard.

## Check health (in order)

1. **Dashboard data**: fetch `dashboard/data.json` from master — `status` field, `anomalies`, `field_fill_rates.gaps`, `actions_health`.
2. **Latest run**: `actions_list` on `daily_scrape.yml`. A red run = real problem now (hard gates added 2026-07-16); before that date red could be cosmetic.
3. **Supabase**: `SELECT COUNT(*), MAX(_scrape_date) FROM listings;` via Supabase MCP (project `ssfkjzskwoxhlczhasgo`) — confirm today's snapshot landed (~25k rows/day). Also check DB size vs the 500 MB free cap: `SELECT pg_size_pretty(pg_database_size(current_database()));` — full snapshots grow ~74 MB/day.

## Diagnose a bad scrape day

Symptom: quality gate CRITICAL `min_listings`, or dashboard total far below ~25k.
- Read the run log's Discovery section. `Found 0 sub-links` = PF changed HTML again → the price-split fallback should have kicked in (`falling back to price-range splitting`). If even price split failed (`pf/pt params not honored`), PF changed query params — inspect a live search URL's `__NEXT_DATA__` and update `split_by_price()` in `scraper/pf_scraper.py`.
- The scraper exits 1 below 60% of site-reported totals — that is intentional, not a crash.

## Diagnose empty/low fill-rate columns

- Compare against the "Known permanent gaps" list in CLAUDE.md first — most gaps are by design.
- A CORE field (listed_date, area_name, agent_id, property_type, contact_*) dropping to ~0% means the API shape changed. Decompress that day's `data/raw_archive/` file, inspect one record's real keys, fix `flatten_listing` in `scraper/cleaner.py`, extend `tests/test_cleaner.py`, then re-clean + re-load (recipe below).
- Remember the two formats (live nested snake_case under `property` vs flat camelCase) and the traps: `location_tree` (underscore), boolean False dying in `or`-chains (use `bk()`), literal `'none'` strings in numeric columns (loader's `safe_cast` handles).

## Re-clean + re-load any past day (idempotent)

```bash
DATE=YYYY-MM-DD
mkdir -p data/raw
for f in data/raw_archive/$DATE/*.json.gz; do gzip -d -c "$f" > "data/raw/$(basename $f .gz)"; done
python scraper/cleaner.py
SUPABASE_DB_URL=<secret> python scripts/load_to_db.py   # ON CONFLICT DO NOTHING — safe
```

## Changing loader/schema/scraper code

Open a PR touching `scraper/`, `scripts/`, or `tests/` — CI runs pytest. For loader/schema changes, test locally against a scratch Postgres (postgresql-16 + postgis are installable in the sandbox) before merging; Supabase free tier has no DB branching.

Schema contract: `COLUMNS` (116) order/names must not change without updating Supabase + Power BI + dashboard FIELD_GROUPS.

## Manual triggers

- Full pipeline: `actions_run_trigger` → `daily_scrape.yml` on master
- Dashboard only: `update_dashboard.yml`
- Both are safe to re-run; every write path is idempotent.

## User context

The owner (Bader) is not a git user — never ask them to run git commands; do the work and report outcomes plainly. They care about: no silent failures, data preserved for future AI/market analysis, and the dashboard telling the truth.
