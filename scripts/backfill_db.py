"""
Backfill the database from the gzip raw archive (data/raw_archive/YYYY-MM-DD/).

For every archived day newer than the latest loaded day: decompress into a
temp dir, re-run the cleaner there, and load the snapshot with load_to_db.
Days are processed oldest-first (the loader diffs against current state).
Partial scrapes (< MIN_ROWS listings) are skipped, not loaded. Safe to
re-run: already-loaded days are skipped. Nothing in data/ is modified.

Usage:
  SUPABASE_DB_URL=... python scripts/backfill_db.py            # all pending days
  SUPABASE_DB_URL=... python scripts/backfill_db.py --until 2026-07-01
"""

import argparse
import gzip
import shutil
import sys
import tempfile
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import cleaner  # noqa: E402
import load_to_db  # noqa: E402

ARCHIVE = Path("data/raw_archive")


def latest_loaded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('load_runs') IS NOT NULL;")
        if not cur.fetchone()[0]:
            return None
        cur.execute("SELECT MAX(snapshot_date)::TEXT FROM load_runs;")
        return cur.fetchone()[0]


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
    return out / "all_listings.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", help="last archive day to load (YYYY-MM-DD), default: all")
    args = ap.parse_args()

    if not load_to_db.DB_URL:
        sys.exit("SUPABASE_DB_URL / NEON_DATABASE_URL not set.")

    conn = psycopg2.connect(load_to_db.DB_URL)
    last = latest_loaded(conn)
    days = sorted(p for p in ARCHIVE.iterdir() if p.is_dir()
                  and (last is None or p.name >= last)
                  and (args.until is None or p.name <= args.until))
    print(f"latest loaded day: {last or 'none'} -- {len(days)} archive day(s) to process")

    loaded = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        for day in days:
            print(f"\n=== {day.name} ===")
            csv_path = clean_day(day, Path(tmp))
            if not csv_path.exists():
                print(f"SKIP {day.name}: cleaner produced no all_listings.csv")
                skipped += 1
                continue
            try:
                if load_to_db.load_file(conn, csv_path):
                    loaded += 1
            except load_to_db.SnapshotRejected as e:
                print(f"SKIP {day.name}: {e}")
                skipped += 1
    conn.close()
    print(f"\nbackfill done: {loaded} day(s) loaded, {skipped} skipped")


if __name__ == "__main__":
    main()
