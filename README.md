# PropertyFinder BH — Market Intelligence Pipeline

Daily automated scrape of all PropertyFinder Bahrain listings (~25-30k).
Tracks every new listing, removal (sold/rented), and price change over time.

**Live dashboard:** [bader1919.github.io/pf-pipeline/dashboard/](https://bader1919.github.io/pf-pipeline/dashboard/)

`master` is the live branch. `v1` is an archival snapshot from 2026-06-25 (pre `node_modules`/`.playwright-cli` cleanup) — not maintained.

## What it does

Every day at 20:00 UTC the pipeline:

1. **Scrapes** 6 categories via dynamic subcategory discovery — residential rent/sale, commercial rent/sale, new projects, agents
2. **Cleans** every field into flat 116-column CSVs (nothing dropped)
3. **Compares** today vs yesterday and records what changed
4. **Archives** raw JSON compressed to `data/raw_archive/`
5. **Updates** the dashboard at the link above

## Output files (committed to this repo)

| File | Description |
|---|---|
| `data/latest/all_listings.csv` | Full current snapshot — every active listing today |
| `data/latest/*.csv` | Per-category snapshots |
| `data/changes/all_changes.csv` | Cumulative change log — core demand intelligence |
| `data/changes/YYYY-MM-DD.csv` | Daily delta |
| `data/raw_archive/YYYY-MM-DD/` | Gzip-compressed raw JSON for re-processing |
| `dashboard/data.json` | Dashboard data (auto-generated) |

## Demand analysis with `all_changes.csv`

| `change_type` | What it means |
|---|---|
| `new` | Listing appeared — new supply entering market |
| `removed` | Listing gone — likely sold or rented (demand absorbed) |
| `price_changed` | Price moved — market pressure signal |

Key analysis fields: `days_on_market`, `price_delta`, `price_delta_pct`, `community`, `area_name`, `category_name`

## Power BI setup

Connect Power BI via GitHub raw URL + Personal Access Token:

1. GitHub → Settings → Developer Settings → Fine-grained tokens → Contents: Read (this repo)
2. Power BI → Get Data → Web → Advanced
3. URL: `https://raw.githubusercontent.com/bader1919/pf-pipeline/master/data/latest/all_listings.csv`
4. Header: `Authorization` = `token YOUR_PAT`

## Local run

```bash
pip install -r scraper/requirements.txt

python scraper/pf_scraper.py    # ~10-15 min
python scraper/cleaner.py
python scraper/comparator.py
python scraper/reporter.py
python scraper/quality_gate.py
python scripts/update_dashboard.py
```

## Re-clean from archive

If the cleaner logic changes, past data can be re-processed from the compressed archive:

```bash
DATE=2026-06-09
mkdir -p data/raw
for f in data/raw_archive/$DATE/*.json.gz; do
  gzip -d -c "$f" > "data/raw/$(basename $f .gz)"
done
python scraper/cleaner.py
```
