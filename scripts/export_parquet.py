"""
Export the raw archive to Parquet: one file per category per day.

  data/raw_archive/YYYY-MM-DD/*.json.gz  ->  data/parquet/<category>/YYYY-MM-DD.parquet

Every cleaner column is kept as text (exactly what the CSV holds) plus
snapshot_date. Days already exported are skipped, so the same command does
the nightly export and the full backfill. Partial scrapes (< MIN_ROWS
listings) are skipped -- the raw archive still has them.

Query with DuckDB, e.g.:
  SELECT snapshot_date, count(*) FROM 'data/parquet/residential_rent/*.parquet' GROUP BY 1;

Usage:
  python scripts/export_parquet.py            # every archive day not yet exported
  python scripts/export_parquet.py --redo 2026-09-25
"""

import argparse
import gzip
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import cleaner  # noqa: E402

ARCHIVE = Path("data/raw_archive")
OUT = Path("data/parquet")
CATEGORIES = ["residential_rent", "residential_sale", "commercial_rent",
              "commercial_sale", "new_projects"]
MIN_ROWS = 20_000


def clean_day(day_dir: Path, work: Path) -> Path:
    raw, out = work / "raw", work / "latest"
    for d in (raw, out):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    for gz in day_dir.glob("*.json.gz"):
        with gzip.open(gz, "rb") as src, open(raw / gz.name[:-3], "wb") as dst:
            shutil.copyfileobj(src, dst)
    cleaner.RAW_DIR, cleaner.OUT_DIR = str(raw), str(out)
    cleaner.main()
    return out


def export_day(day: str, csv_dir: Path, con) -> bool:
    csvs = {c: csv_dir / f"{c}.csv" for c in CATEGORIES if (csv_dir / f"{c}.csv").exists()}
    total = sum(con.execute(f"SELECT count(*) FROM read_csv('{p}', all_varchar=true)").fetchone()[0]
                for p in csvs.values())
    if total < MIN_ROWS:
        print(f"SKIP {day}: {total} listings < {MIN_ROWS} (partial scrape)")
        return False
    for cat, path in csvs.items():
        dest = OUT / cat / f"{day}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"""
            COPY (SELECT DATE '{day}' AS snapshot_date, *
                  FROM read_csv('{path}', all_varchar=true, header=true))
            TO '{dest}' (FORMAT parquet, COMPRESSION zstd)""")
    print(f"{day}: {total} listings, {len(csvs)} categories")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", nargs="*", default=[], help="days to re-export even if present")
    args = ap.parse_args()

    done = {p.stem for p in (OUT / "residential_rent").glob("*.parquet")}
    days = sorted(p for p in ARCHIVE.iterdir()
                  if p.is_dir() and (p.name not in done or p.name in args.redo))
    print(f"{len(days)} archive day(s) to export")

    con = duckdb.connect()
    exported = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        for day in days:
            if export_day(day.name, clean_day(day, Path(tmp)), con):
                exported += 1
            else:
                skipped += 1
    print(f"\nexport done: {exported} day(s) exported, {skipped} skipped")


if __name__ == "__main__":
    main()
