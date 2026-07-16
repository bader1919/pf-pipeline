"""
Neon Postgres loader for the PropertyFinder pipeline.

Appends today's snapshot (data/latest/all_listings.csv) into the `listings`
table (one row per listing per day) and upserts market events from
data/changes/all_changes.csv into the `changes` table.

Idempotent: UNIQUE constraints + ON CONFLICT DO NOTHING mean re-runs never
duplicate rows. Creates tables/indexes on first run.

Requires NEON_DATABASE_URL env var (Neon connection string).
In pull requests, CI points this at an isolated Neon branch (see neon_branch_preview.yml).
"""

import csv
import os
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

ALL_LISTINGS = Path("data/latest/all_listings.csv")
ALL_CHANGES  = Path("data/changes/all_changes.csv")

DB_URL = os.environ.get("NEON_DATABASE_URL")

# Column type map for listings — everything not listed here is TEXT.
NUMERIC_COLS = {
    "plot_size", "size_value", "price_value", "price_per_area_price",
    "price_per_area_plot", "lead_value", "qs",
}
SMALLINT_COLS = {
    "bedrooms_value", "bathrooms_value", "rooms_value", "images_count",
}
DOUBLE_COLS = {"latitude", "longitude"}
BOOLEAN_COLS = {
    "price_is_hidden", "agent_is_super_agent", "broker_is_exclusive",
    "is_verified", "is_direct_from_developer", "is_new_construction",
    "is_available", "is_featured", "is_premium", "is_new_insert",
    "is_community_expert", "is_cts", "is_exclusive",
    "is_broker_project_property", "is_smart_ad", "is_spotlight_listing",
    "is_claimed_by_agent", "is_under_offer_by_competitor", "is_pf_exclusive",
    "is_fhm", "is_great_value", "is_high_demand", "is_luxe",
}
TIMESTAMPTZ_COLS = {"listed_date", "last_refreshed_at", "scraped_at", "detail_scraped_at"}

CHANGES_NUMERIC = {"price_prev", "price_curr", "price_delta", "price_delta_pct", "area_size"}
CHANGES_DOUBLE = {"latitude", "longitude"}
CHANGES_INT = {"days_on_market"}
CHANGES_TS = {"first_seen_at", "last_seen_at", "scraped_at"}


def col_type(col: str) -> str:
    if col in NUMERIC_COLS:
        return "NUMERIC"
    if col in SMALLINT_COLS:
        return "SMALLINT"
    if col in DOUBLE_COLS:
        return "DOUBLE PRECISION"
    if col in BOOLEAN_COLS:
        return "BOOLEAN"
    if col in TIMESTAMPTZ_COLS:
        return "TIMESTAMPTZ"
    return "TEXT"


def changes_col_type(col: str) -> str:
    if col in CHANGES_NUMERIC:
        return "NUMERIC"
    if col in CHANGES_DOUBLE:
        return "DOUBLE PRECISION"
    if col in CHANGES_INT:
        return "INTEGER"
    if col in CHANGES_TS:
        return "TIMESTAMPTZ"
    if col == "change_date":
        return "DATE"
    return "TEXT"


def safe_cast(col_sql: str, target_type: str) -> str:
    """
    SQL expression that casts a TEXT staging column to target_type, turning
    anything unparseable ('', 'none', 'N/A', junk) into NULL instead of
    aborting the whole load.
    """
    if target_type == "TEXT":
        return f"NULLIF({col_sql}, '')"
    if target_type in ("NUMERIC", "SMALLINT", "INTEGER", "DOUBLE PRECISION"):
        return (f"CASE WHEN {col_sql} ~ '^\\s*-?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?\\s*$' "
                f"THEN {col_sql}::{target_type} END")
    if target_type == "BOOLEAN":
        return (f"CASE WHEN LOWER(TRIM({col_sql})) IN ('true','t','1','yes') THEN TRUE "
                f"WHEN LOWER(TRIM({col_sql})) IN ('false','f','0','no') THEN FALSE END")
    if target_type in ("TIMESTAMPTZ", "DATE"):
        return (f"CASE WHEN {col_sql} ~ '^\\s*[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
                f"THEN {col_sql}::{target_type} END")
    return f"NULLIF({col_sql}, '')::{target_type}"


def read_headers(path: Path) -> list:
    with open(path, encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def qident(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def ensure_schema(cur, listing_cols, change_cols):
    """Create tables/indexes. Returns True if PostGIS (geom column) is available."""
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        has_postgis = True
    except psycopg2.Error:
        cur.connection.rollback()
        has_postgis = False
        print("WARNING: PostGIS unavailable -- loading without geom column (lat/lon scalars still stored).")

    geom_def = "geom GEOMETRY(Point, 4326)," if has_postgis else ""
    listing_defs = ",\n        ".join(f"{qident(c)} {col_type(c)}" for c in listing_cols)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS listings (
            _id BIGSERIAL PRIMARY KEY,
            _scrape_date DATE NOT NULL,
            {listing_defs},
            {geom_def}
            UNIQUE (pf_id, _scrape_date)
        );
    """)

    change_defs = ",\n        ".join(f"{qident(c)} {changes_col_type(c)}" for c in change_cols)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS changes (
            _id BIGSERIAL PRIMARY KEY,
            {change_defs},
            UNIQUE (listing_id, change_date, change_type)
        );
    """)

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_listings_date_cat ON listings (_scrape_date, category_name);",
        "CREATE INDEX IF NOT EXISTS idx_listings_area_date ON listings (area_name, _scrape_date);",
        "CREATE INDEX IF NOT EXISTS idx_listings_pfid_date ON listings (pf_id, _scrape_date);",
        "CREATE INDEX IF NOT EXISTS idx_listings_agent ON listings (agent_id);",
        "CREATE INDEX IF NOT EXISTS idx_listings_broker ON listings (broker_id);",
        "CREATE INDEX IF NOT EXISTS idx_listings_price ON listings (price_value) WHERE price_value IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_changes_date_type ON changes (change_date, change_type);",
        "CREATE INDEX IF NOT EXISTS idx_changes_area ON changes (area, change_type);",
        "CREATE INDEX IF NOT EXISTS idx_changes_listing ON changes (listing_id);",
    ]
    if has_postgis:
        indexes.append("CREATE INDEX IF NOT EXISTS idx_listings_geom ON listings USING GIST (geom);")
    for idx in indexes:
        cur.execute(idx)

    return has_postgis


def load_listings(cur, cols, has_postgis=True) -> tuple:
    """COPY the CSV into a temp table (all TEXT), then typed insert with geom."""
    col_list = ", ".join(qident(c) for c in cols)
    temp_defs = ", ".join(f"{qident(c)} TEXT" for c in cols)

    cur.execute(f"CREATE TEMP TABLE _stage_listings ({temp_defs}) ON COMMIT DROP;")

    with open(ALL_LISTINGS, encoding="utf-8-sig") as f:
        cur.copy_expert(
            f"COPY _stage_listings ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)", f
        )
    cur.execute("SELECT COUNT(*) FROM _stage_listings;")
    staged = cur.fetchone()[0]

    # Typed select: cast each column; empty string → NULL
    casts = []
    for c in cols:
        casts.append(safe_cast(qident(c), col_type(c)))
    cast_list = ", ".join(casts)

    lat_ok = safe_cast("latitude", "DOUBLE PRECISION")
    lon_ok = safe_cast("longitude", "DOUBLE PRECISION")
    if has_postgis:
        geom_col = ", geom"
        geom_expr = f""",
            CASE
                WHEN ({lat_ok}) IS NOT NULL AND ({lon_ok}) IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint({lon_ok}, {lat_ok}), 4326)
            END"""
    else:
        geom_col = ""
        geom_expr = ""

    scrape_date = safe_cast("scraped_at", "TIMESTAMPTZ")
    cur.execute(f"""
        INSERT INTO listings (_scrape_date, {col_list}{geom_col})
        SELECT
            COALESCE(({scrape_date})::DATE, CURRENT_DATE),
            {cast_list}{geom_expr}
        FROM _stage_listings
        ON CONFLICT (pf_id, _scrape_date) DO NOTHING;
    """)
    return staged, cur.rowcount


def load_changes(cur, cols) -> tuple:
    col_list = ", ".join(qident(c) for c in cols)
    temp_defs = ", ".join(f"{qident(c)} TEXT" for c in cols)

    cur.execute(f"CREATE TEMP TABLE _stage_changes ({temp_defs}) ON COMMIT DROP;")

    with open(ALL_CHANGES, encoding="utf-8-sig") as f:
        cur.copy_expert(
            f"COPY _stage_changes ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)", f
        )
    cur.execute("SELECT COUNT(*) FROM _stage_changes;")
    staged = cur.fetchone()[0]

    cast_list = ", ".join(safe_cast(qident(c), changes_col_type(c)) for c in cols)

    cur.execute(f"""
        INSERT INTO changes ({col_list})
        SELECT {cast_list}
        FROM _stage_changes
        ON CONFLICT (listing_id, change_date, change_type) DO NOTHING;
    """)
    return staged, cur.rowcount


def main():
    if not DB_URL:
        print("NEON_DATABASE_URL not set -- skipping Neon load (this is fine locally).")
        sys.exit(0)

    if not ALL_LISTINGS.exists():
        print(f"ERROR: {ALL_LISTINGS} not found. Run the pipeline first.")
        sys.exit(1)

    listing_cols = read_headers(ALL_LISTINGS)
    change_cols = read_headers(ALL_CHANGES) if ALL_CHANGES.exists() else []

    conn = psycopg2.connect(DB_URL)
    try:
        with conn:
            with conn.cursor() as cur:
                has_postgis = ensure_schema(cur, listing_cols, change_cols or ["change_date", "change_type", "listing_id"])

                staged, inserted = load_listings(cur, listing_cols, has_postgis)
                print(f"listings: {staged} staged, {inserted} inserted, {staged - inserted} already present")

                if change_cols:
                    staged_c, inserted_c = load_changes(cur, change_cols)
                    print(f"changes:  {staged_c} staged, {inserted_c} inserted, {staged_c - inserted_c} already present")

                cur.execute("SELECT COUNT(*), COUNT(DISTINCT _scrape_date) FROM listings;")
                total, days = cur.fetchone()
                print(f"listings table now holds {total} rows across {days} snapshot day(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
