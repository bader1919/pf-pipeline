# PropertyFinder BH — Market Intelligence Pipeline

Daily automated scrape of all PropertyFinder Bahrain listings.
Tracks every new listing, removal (sold/rented), and price change over time.

## What it does

Every day at 02:00 UTC the pipeline:

1. **Scrapes** 6 categories via dynamic subcategory discovery + location drill-down — residential rent, residential sale, commercial rent, commercial sale, new projects, agents (~25–30k total records)
2. **Cleans** every field into flat CSVs (nothing dropped)
3. **Compares** today vs yesterday and records what changed

## Output files (committed to this repo)

| File | Description |
|---|---|
| `data/latest/all_listings.csv` | Full current snapshot — every active listing today |
| `data/latest/residential_rent.csv` | By category |
| `data/latest/residential_sale.csv` | By category |
| `data/latest/commercial_rent.csv` | By category |
| `data/latest/commercial_sale.csv` | By category |
| `data/latest/new_projects.csv` | By category |
| `data/latest/agents.csv` | By category |
| `data/changes/all_changes.csv` | **Cumulative change log** — demand intelligence |
| `data/changes/YYYY-MM-DD.csv` | Daily delta only |

## Power BI setup

Connect Power BI to this private repo using a Personal Access Token (PAT):

1. In GitHub → Settings → Developer Settings → Personal access tokens → Fine-grained tokens
2. Create token: scope = **Contents: Read** on this repo only
3. In Power BI Desktop → Get Data → Web → Advanced
4. URL: `https://raw.githubusercontent.com/YOUR_USERNAME/REPO_NAME/main/data/latest/all_listings.csv`
5. Add header: `Authorization` = `token YOUR_PAT`
6. Repeat for `data/changes/all_changes.csv`

## Demand analysis with `all_changes.csv`

| `change_type` | What it means |
|---|---|
| `new` | Listing appeared — new supply entering market |
| `removed` | Listing gone — likely sold or rented (demand absorbed) |
| `price_changed` | Price moved — market pressure signal |

Key fields for analysis:
- `days_on_market` — how long the listing was active before removal
- `price_delta` / `price_delta_pct` — direction and size of price movement
- `community` / `area` — geographic demand concentration
- `category` — rent vs sale, residential vs commercial

## Repo setup (one-time)

```bash
# 1. Clone / create this as a private repo on GitHub
git clone https://github.com/YOUR_USERNAME/pf-pipeline.git
cd pf-pipeline

# 2. No secrets needed — GITHUB_TOKEN is automatic in Actions

# 3. Enable GitHub Actions in repo settings (should be on by default)

# 4. First run: go to Actions tab → Daily Property Scrape → Run workflow
```

The first run will have no `previous/` snapshot so all listings are recorded as `new`.
From the second run onward, daily diffs are tracked.

## Local run

```bash
pip install -r scraper/requirements.txt    # requests, beautifulsoup4
python scraper/pf_scraper.py    # ~10-15 min for full catalogue
python scraper/cleaner.py
python scraper/comparator.py
```
