"""
Postgres loader for the PropertyFinder pipeline (works with Supabase, Neon,
or any Postgres).

History-efficient design: instead of appending a full 27k-row copy of the
market every day (~74 MB/day), each snapshot is diffed against what the
database already holds and only what changed is stored (~1-2 MB/day).
Every day of history stays reconstructable.

Tables
  listings         one row per listing (pf_id): every CSV column + geom, as of
                   the listing's latest content change (rewritten only when a
                   tracked field changes, so the wide table doesn't bloat)
  listing_status   one narrow row per listing: first_seen_date, last_seen_date,
                   is_active (the only thing touched for every listing daily)
  listing_changes  one row per changed field per listing per day (old -> new).
                   field '_status' records market events:
                     NULL -> active       new listing
                     active -> removed    disappeared from the site
                     removed -> active    re-listed
  daily_stats      per day x category x area: active/new/removed counts + prices
  load_runs        one row per loaded snapshot day (audit trail + ordering guard)
Views (security_invoker): active_listings, price_history, market_events

Snapshots must be loaded in date order (the diff is against the current
state). Re-loading an already-loaded day is a no-op; loading a day older than
the newest loaded day is refused. Snapshots below MIN_ROWS are refused so a
partial scrape can't fake thousands of "removed" events.

All tables have RLS enabled with no policies: the Supabase REST API (anon /
authenticated keys) sees nothing until a policy is added on purpose; the
direct Postgres connection used here is unaffected.

Connection string env var (first one set wins):
  SUPABASE_DB_URL  -> current primary (Supabase project pf-pipeline)
  NEON_DATABASE_URL -> legacy/fallback
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

DB_URL = os.environ.get("SUPABASE_DB_URL") or os.environ.get("NEON_DATABASE_URL")

# Same floor as quality_gate.py's min_listings.
MIN_ROWS = 20000

# Columns that change on (nearly) every listing every day -- logging them would
# cost more than the rest of the history combined. In `listings` they hold the
# value from the listing's latest content change.
IGNORE_CHANGES = {"pf_id", "scraped_at", "detail_scraped_at", "lead_value"}

# Column type map for listings -- everything not listed here is TEXT.
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


class SnapshotRejected(Exception):
    """The snapshot must not be loaded (too small, or older than the DB state)."""


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


def qlit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def ensure_schema(cur, cols):
    """Create tables/indexes/views. Returns True if PostGIS (geom column) is available."""
    cur.execute("SAVEPOINT postgis;")
    try:
        # Supabase keeps extensions in the `extensions` schema (on its search_path).
        cur.execute("SELECT to_regnamespace('extensions') IS NOT NULL;")
        schema = " SCHEMA extensions" if cur.fetchone()[0] else ""
        cur.execute(f"CREATE EXTENSION IF NOT EXISTS postgis{schema};")
        has_postgis = True
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT postgis;")
        has_postgis = False
        print("WARNING: PostGIS unavailable -- loading without geom column (lat/lon scalars still stored).")

    col_defs = ",\n            ".join(
        f"{qident(c)} {col_type(c)}" for c in cols if c != "pf_id")
    geom_def = "geom GEOMETRY(Point, 4326)," if has_postgis else ""
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS listings (
            pf_id TEXT NOT NULL,
            {col_defs},
            {geom_def}
            PRIMARY KEY (pf_id)
        );
    """)
    # New cleaner columns get added instead of breaking the load.
    for c in cols:
        cur.execute(f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {qident(c)} {col_type(c)};")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS listing_status (
            pf_id           TEXT PRIMARY KEY,
            first_seen_date DATE NOT NULL,
            last_seen_date  DATE NOT NULL,
            is_active       BOOLEAN NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listing_changes (
            id          BIGSERIAL PRIMARY KEY,
            pf_id       TEXT NOT NULL,
            change_date DATE NOT NULL,
            field       TEXT NOT NULL,
            old_value   TEXT,
            new_value   TEXT,
            UNIQUE (pf_id, change_date, field)
        );
        CREATE TABLE IF NOT EXISTS daily_stats (
            stat_date     DATE NOT NULL,
            category_name TEXT NOT NULL,
            area_name     TEXT NOT NULL,
            active_count  INTEGER NOT NULL,
            new_count     INTEGER NOT NULL,
            removed_count INTEGER NOT NULL,
            avg_price     NUMERIC,
            median_price  NUMERIC,
            PRIMARY KEY (stat_date, category_name, area_name)
        );
        CREATE TABLE IF NOT EXISTS load_runs (
            snapshot_date   DATE PRIMARY KEY,
            loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            snapshot_rows   INTEGER NOT NULL,
            new_listings    INTEGER NOT NULL,
            removed         INTEGER NOT NULL,
            relisted        INTEGER NOT NULL,
            changed_listings INTEGER NOT NULL,
            field_changes   INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_listings_cat_area ON listings (category_name, area_name);
        CREATE INDEX IF NOT EXISTS idx_status_active ON listing_status (is_active) WHERE is_active;
        CREATE INDEX IF NOT EXISTS idx_listings_agent ON listings (agent_id);
        CREATE INDEX IF NOT EXISTS idx_listings_broker ON listings (broker_id);
        CREATE INDEX IF NOT EXISTS idx_changes_date_field ON listing_changes (change_date, field);
        CREATE INDEX IF NOT EXISTS idx_changes_field_date ON listing_changes (field, change_date);

        ALTER TABLE listings        ENABLE ROW LEVEL SECURITY;
        ALTER TABLE listing_status  ENABLE ROW LEVEL SECURITY;
        ALTER TABLE listing_changes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE daily_stats     ENABLE ROW LEVEL SECURITY;
        ALTER TABLE load_runs       ENABLE ROW LEVEL SECURITY;

        CREATE OR REPLACE VIEW active_listings WITH (security_invoker = true) AS
            SELECT l.*, s.first_seen_date, s.last_seen_date
            FROM listings l JOIN listing_status s USING (pf_id)
            WHERE s.is_active;

        CREATE OR REPLACE VIEW price_history WITH (security_invoker = true) AS
            SELECT c.pf_id, c.change_date,
                   NULLIF(c.old_value, '')::NUMERIC AS price_prev,
                   NULLIF(c.new_value, '')::NUMERIC AS price_curr,
                   l.category_name, l.area_name, l.property_type, l.title
            FROM listing_changes c JOIN listings l USING (pf_id)
            WHERE c.field = 'price_value';

        CREATE OR REPLACE VIEW market_events WITH (security_invoker = true) AS
            SELECT c.pf_id, c.change_date,
                   CASE WHEN c.field = 'price_value' THEN 'price_changed'
                        WHEN c.old_value IS NULL THEN 'new'
                        WHEN c.new_value = 'removed' THEN 'removed'
                        ELSE 'relisted' END AS event_type,
                   CASE WHEN c.field = 'price_value' THEN NULLIF(c.old_value, '')::NUMERIC END AS price_prev,
                   CASE WHEN c.field = 'price_value' THEN NULLIF(c.new_value, '')::NUMERIC END AS price_curr,
                   l.category_name, l.area_name, l.property_type, l.title,
                   l.price_value, s.first_seen_date, s.last_seen_date
            FROM listing_changes c
            JOIN listings l USING (pf_id)
            JOIN listing_status s USING (pf_id)
            WHERE c.field IN ('_status', 'price_value');
    """)
    if has_postgis:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_listings_geom ON listings USING GIST (geom);")
    return has_postgis


def stage_snapshot(cur, path, cols):
    """COPY the CSV into a TEXT temp table, then a typed, de-duplicated _stage."""
    col_list = ", ".join(qident(c) for c in cols)
    temp_defs = ", ".join(f"{qident(c)} TEXT" for c in cols)
    cur.execute(f"CREATE TEMP TABLE _stage_raw ({temp_defs}) ON COMMIT DROP;")
    with open(path, encoding="utf-8-sig") as f:
        cur.copy_expert(
            f"COPY _stage_raw ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)", f
        )
    casts = ", ".join(f"{safe_cast(qident(c), col_type(c))} AS {qident(c)}" for c in cols)
    cur.execute(f"""
        CREATE TEMP TABLE _stage ON COMMIT DROP AS
        SELECT DISTINCT ON (pf_id) {casts}
        FROM _stage_raw
        WHERE NULLIF(TRIM(pf_id), '') IS NOT NULL
        ORDER BY pf_id;
        ALTER TABLE _stage ADD PRIMARY KEY (pf_id);
    """)
    cur.execute("SELECT COUNT(*), MIN(scraped_at)::DATE FROM _stage;")
    return cur.fetchone()


def load_snapshot(cur, path=ALL_LISTINGS) -> dict:
    """Diff one snapshot CSV against the DB and apply it. Returns run stats,
    or None if this day was already loaded."""
    cols = read_headers(path)
    cur.execute("SET LOCAL TIME ZONE 'UTC';")  # snapshot date = UTC date of scraped_at
    has_postgis = ensure_schema(cur, cols)

    rows, snap_date = stage_snapshot(cur, path, cols)
    if rows < MIN_ROWS:
        raise SnapshotRejected(f"{path}: {rows} listings < {MIN_ROWS} minimum -- partial scrape, not loaded")
    if snap_date is None:
        raise SnapshotRejected(f"{path}: no parseable scraped_at -- can't date the snapshot")

    cur.execute("SELECT MAX(snapshot_date), BOOL_OR(snapshot_date = %s) FROM load_runs;", (snap_date,))
    last_date, already = cur.fetchone()
    if already:
        return None
    if last_date and snap_date < last_date:
        raise SnapshotRejected(f"snapshot {snap_date} is older than latest loaded day {last_date} -- "
                               "snapshots must be loaded in date order")

    d = snap_date.isoformat()

    # 1. Field-level changes for listings we already know (before overwriting them).
    tracked = [c for c in cols if c not in IGNORE_CHANGES]
    values = ",\n                ".join(
        f"({qlit(c)}, l.{qident(c)}::TEXT, s.{qident(c)}::TEXT)" for c in tracked)
    cur.execute(f"""
        INSERT INTO listing_changes (pf_id, change_date, field, old_value, new_value)
        SELECT s.pf_id, %s, v.field, v.old_value, v.new_value
        FROM _stage s
        JOIN listings l USING (pf_id)
        CROSS JOIN LATERAL (VALUES
                {values}
        ) AS v(field, old_value, new_value)
        WHERE v.old_value IS DISTINCT FROM v.new_value
        ON CONFLICT DO NOTHING;
    """, (d,))
    field_changes = cur.rowcount
    cur.execute("SELECT COUNT(DISTINCT pf_id) FROM listing_changes WHERE change_date = %s AND field <> '_status';", (d,))
    changed_listings = cur.fetchone()[0]

    # 2. Market events: new, re-listed, removed.
    cur.execute("""
        INSERT INTO listing_changes (pf_id, change_date, field, old_value, new_value)
        SELECT s.pf_id, %s, '_status', NULL, 'active'
        FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM listing_status t WHERE t.pf_id = s.pf_id)
        ON CONFLICT DO NOTHING;
    """, (d,))
    new_listings = cur.rowcount
    cur.execute("""
        INSERT INTO listing_changes (pf_id, change_date, field, old_value, new_value)
        SELECT t.pf_id, %s, '_status', 'removed', 'active'
        FROM listing_status t JOIN _stage s USING (pf_id) WHERE NOT t.is_active
        ON CONFLICT DO NOTHING;
    """, (d,))
    relisted = cur.rowcount
    cur.execute("""
        INSERT INTO listing_changes (pf_id, change_date, field, old_value, new_value)
        SELECT t.pf_id, %s, '_status', 'active', 'removed'
        FROM listing_status t WHERE t.is_active
          AND NOT EXISTS (SELECT 1 FROM _stage s WHERE s.pf_id = t.pf_id)
        ON CONFLICT DO NOTHING;
    """, (d,))
    removed = cur.rowcount

    # 3. Write new listings and listings whose content changed today; bump
    #    presence for everything seen.
    col_list = ", ".join(qident(c) for c in cols)
    updates = ", ".join(f"{qident(c)} = EXCLUDED.{qident(c)}" for c in cols if c != "pf_id")
    geom_col, geom_expr, geom_upd = "", "", ""
    if has_postgis:
        geom_col = ", geom"
        geom_expr = (", CASE WHEN s.latitude IS NOT NULL AND s.longitude IS NOT NULL "
                     "THEN ST_SetSRID(ST_MakePoint(s.longitude, s.latitude), 4326) END")
        geom_upd = ", geom = EXCLUDED.geom"
    cur.execute(f"""
        INSERT INTO listings ({col_list}{geom_col})
        SELECT {", ".join("s." + qident(c) for c in cols)}{geom_expr}
        FROM _stage s
        WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.pf_id = s.pf_id)
           OR s.pf_id IN (SELECT pf_id FROM listing_changes
                          WHERE change_date = %s AND field <> '_status')
        ON CONFLICT (pf_id) DO UPDATE SET
            {updates}{geom_upd};
    """, (d,))
    cur.execute("""
        INSERT INTO listing_status (pf_id, first_seen_date, last_seen_date, is_active)
        SELECT pf_id, %s, %s, TRUE FROM _stage
        ON CONFLICT (pf_id) DO UPDATE SET
            last_seen_date = EXCLUDED.last_seen_date,
            is_active = TRUE;
    """, (d, d))
    cur.execute("UPDATE listing_status SET is_active = FALSE WHERE is_active AND last_seen_date < %s;", (d,))

    # 4. Daily aggregates (keeps an exact daily time series at ~KB/day).
    cur.execute("""
        INSERT INTO daily_stats (stat_date, category_name, area_name, active_count,
                                 new_count, removed_count, avg_price, median_price)
        WITH act AS (
            SELECT COALESCE(category_name, '(unknown)') AS category_name,
                   COALESCE(area_name, '(unknown)') AS area_name,
                   COUNT(*) AS n, AVG(price_value) AS avg_price,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_value) AS median_price
            FROM _stage GROUP BY 1, 2
        ), ev AS (
            SELECT COALESCE(l.category_name, '(unknown)') AS category_name,
                   COALESCE(l.area_name, '(unknown)') AS area_name,
                   COUNT(*) FILTER (WHERE c.new_value = 'active')  AS new_n,
                   COUNT(*) FILTER (WHERE c.new_value = 'removed') AS removed_n
            FROM listing_changes c JOIN listings l USING (pf_id)
            WHERE c.change_date = %s AND c.field = '_status'
            GROUP BY 1, 2
        )
        SELECT %s, category_name, area_name, COALESCE(act.n, 0), COALESCE(ev.new_n, 0),
               COALESCE(ev.removed_n, 0), ROUND(act.avg_price, 2), act.median_price::NUMERIC
        FROM act FULL JOIN ev USING (category_name, area_name)
        ON CONFLICT DO NOTHING;
    """, (d, d))

    stats = dict(snapshot_date=d, snapshot_rows=rows, new_listings=new_listings,
                 removed=removed, relisted=relisted, changed_listings=changed_listings,
                 field_changes=field_changes)
    cur.execute("""
        INSERT INTO load_runs (snapshot_date, snapshot_rows, new_listings, removed,
                               relisted, changed_listings, field_changes)
        VALUES (%(snapshot_date)s, %(snapshot_rows)s, %(new_listings)s, %(removed)s,
                %(relisted)s, %(changed_listings)s, %(field_changes)s);
    """, stats)
    return stats


def load_file(conn, path=ALL_LISTINGS):
    """Load one snapshot in its own transaction and print a one-line summary."""
    with conn:
        with conn.cursor() as cur:
            stats = load_snapshot(cur, path)
    if stats is None:
        print(f"{path}: day already loaded -- nothing to do")
    else:
        print("loaded {snapshot_date}: {snapshot_rows} listings | new {new_listings}, "
              "removed {removed}, relisted {relisted} | {changed_listings} listings changed "
              "({field_changes} field changes)".format(**stats))
    return stats


def main():
    if not DB_URL:
        print("SUPABASE_DB_URL / NEON_DATABASE_URL not set -- skipping DB load (fine locally).")
        sys.exit(0)

    if not ALL_LISTINGS.exists():
        print(f"ERROR: {ALL_LISTINGS} not found. Run the pipeline first.")
        sys.exit(1)

    conn = psycopg2.connect(DB_URL)
    try:
        load_file(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE is_active) FROM listing_status;")
            total, active = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM load_runs;")
            days = cur.fetchone()[0]
        print(f"listings table: {total} listings ({active} active) across {days} loaded day(s)")
    except SnapshotRejected as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
