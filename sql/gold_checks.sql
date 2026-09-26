-- =============================================================================
-- Validation checks for the gold star schema (sql/gold_star_schema.sql).
-- Read-only. Run after applying the schema:
--   psql "$DB_URL" -f sql/gold_checks.sql
-- Section 1 returns one row per check with pass = true/false; every row must
-- pass. Sections 2-3 are for eyeballing (price sanity, query timings).
-- =============================================================================

-- JIT compilation of these many-view plans costs seconds (up to minutes for
-- the big check query) and buys nothing at this data size.
SET jit = off;

\echo '== 1. Integrity checks (every row must have pass = t) =='

WITH checks AS (
    -- 1a. dimension keys unique and non-NULL -------------------------------
    SELECT 'dim_date key unique/not null' AS check_name,
           COUNT(*) - COUNT(DISTINCT date_key) + COUNT(*) FILTER (WHERE date_key IS NULL) AS bad
    FROM gold.dim_date
    UNION ALL SELECT 'dim_area key unique/not null',
           COUNT(*) - COUNT(DISTINCT area_key) + COUNT(*) FILTER (WHERE area_key IS NULL) FROM gold.dim_area
    UNION ALL SELECT 'dim_location key unique/not null',
           COUNT(*) - COUNT(DISTINCT location_key) + COUNT(*) FILTER (WHERE location_key IS NULL) FROM gold.dim_location
    UNION ALL SELECT 'dim_category key unique/not null',
           COUNT(*) - COUNT(DISTINCT category_key) + COUNT(*) FILTER (WHERE category_key IS NULL) FROM gold.dim_category
    UNION ALL SELECT 'dim_property_type key unique/not null',
           COUNT(*) - COUNT(DISTINCT property_type_key) + COUNT(*) FILTER (WHERE property_type_key IS NULL) FROM gold.dim_property_type
    UNION ALL SELECT 'dim_agent key unique/not null',
           COUNT(*) - COUNT(DISTINCT agent_key) + COUNT(*) FILTER (WHERE agent_key IS NULL) FROM gold.dim_agent
    UNION ALL SELECT 'dim_broker key unique/not null',
           COUNT(*) - COUNT(DISTINCT broker_key) + COUNT(*) FILTER (WHERE broker_key IS NULL) FROM gold.dim_broker
    UNION ALL SELECT 'dim_listing key unique/not null',
           COUNT(*) - COUNT(DISTINCT pf_id) + COUNT(*) FILTER (WHERE pf_id IS NULL) FROM gold.dim_listing

    -- 1b. every dimension has its Unknown member ----------------------------
    UNION ALL SELECT 'unknown members present (8 dims)',
           8 - ( (SELECT COUNT(*) FROM gold.dim_date          WHERE date_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_area          WHERE area_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_location      WHERE location_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_category      WHERE category_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_property_type WHERE property_type_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_agent         WHERE agent_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_broker        WHERE broker_key = -1)
               + (SELECT COUNT(*) FROM gold.dim_listing       WHERE pf_id = '(unknown)'))

    -- 1c. orphan FKs (fact/dim -> dim), incl. NULL FKs ----------------------
    UNION ALL SELECT 'fact_listing_current -> dim_listing orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_listing d USING (pf_id) WHERE d.pf_id IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_date (snapshot) orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_date d ON d.date_key = f.snapshot_date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_date (listed) orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_date d ON d.date_key = f.listed_date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_date (first_seen) orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_date d ON d.date_key = f.first_seen_date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_location orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_location d USING (location_key) WHERE d.location_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_area orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_area d USING (area_key) WHERE d.area_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_category orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_category d USING (category_key) WHERE d.category_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_property_type orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_property_type d USING (property_type_key) WHERE d.property_type_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_agent orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_agent d USING (agent_key) WHERE d.agent_key IS NULL
    UNION ALL SELECT 'fact_listing_current -> dim_broker orphans', COUNT(*)
    FROM gold.fact_listing_current f LEFT JOIN gold.dim_broker d USING (broker_key) WHERE d.broker_key IS NULL

    UNION ALL SELECT 'fact_market_event -> dim_listing orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_listing d USING (pf_id) WHERE d.pf_id IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_date orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_date d ON d.date_key = f.event_date_key WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_location orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_location d USING (location_key) WHERE d.location_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_area orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_area d USING (area_key) WHERE d.area_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_category orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_category d USING (category_key) WHERE d.category_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_property_type orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_property_type d USING (property_type_key) WHERE d.property_type_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_agent orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_agent d USING (agent_key) WHERE d.agent_key IS NULL
    UNION ALL SELECT 'fact_market_event -> dim_broker orphans', COUNT(*)
    FROM gold.fact_market_event f LEFT JOIN gold.dim_broker d USING (broker_key) WHERE d.broker_key IS NULL

    UNION ALL SELECT 'fact_daily_market -> dim_date orphans', COUNT(*)
    FROM gold.fact_daily_market f LEFT JOIN gold.dim_date d USING (date_key) WHERE d.date_key IS NULL
    UNION ALL SELECT 'fact_daily_market -> dim_area orphans', COUNT(*)
    FROM gold.fact_daily_market f LEFT JOIN gold.dim_area d USING (area_key) WHERE d.area_key IS NULL
    UNION ALL SELECT 'fact_daily_market -> dim_category orphans', COUNT(*)
    FROM gold.fact_daily_market f LEFT JOIN gold.dim_category d USING (category_key) WHERE d.category_key IS NULL

    UNION ALL SELECT 'dim_listing -> dim_location/area/category/ptype/agent/broker orphans', COUNT(*)
    FROM gold.dim_listing f
    LEFT JOIN gold.dim_location lo      ON lo.location_key = f.location_key
    LEFT JOIN gold.dim_area ar          ON ar.area_key = f.area_key
    LEFT JOIN gold.dim_category ca      ON ca.category_key = f.category_key
    LEFT JOIN gold.dim_property_type pt ON pt.property_type_key = f.property_type_key
    LEFT JOIN gold.dim_agent ag         ON ag.agent_key = f.agent_key
    LEFT JOIN gold.dim_broker br        ON br.broker_key = f.broker_key
    WHERE lo.location_key IS NULL OR ar.area_key IS NULL OR ca.category_key IS NULL
       OR pt.property_type_key IS NULL OR ag.agent_key IS NULL OR br.broker_key IS NULL
    UNION ALL SELECT 'dim_location -> dim_area orphans', COUNT(*)
    FROM gold.dim_location f LEFT JOIN gold.dim_area d USING (area_key) WHERE d.area_key IS NULL
    UNION ALL SELECT 'dim_agent -> dim_broker orphans', COUNT(*)
    FROM gold.dim_agent f LEFT JOIN gold.dim_broker d USING (broker_key) WHERE d.broker_key IS NULL

    -- 1d. reconciliation with Silver ----------------------------------------
    UNION ALL SELECT 'fact_listing_current rows = active listing_status rows',
           ABS((SELECT COUNT(*) FROM gold.fact_listing_current)
             - (SELECT COUNT(*) FROM public.listing_status WHERE is_active))
    UNION ALL SELECT 'fact_listing_current pf_id unique',
           (SELECT COUNT(*) - COUNT(DISTINCT pf_id) FROM gold.fact_listing_current)
    UNION ALL SELECT 'dim_listing rows = listings rows + unknown',
           ABS((SELECT COUNT(*) FROM gold.dim_listing) - (SELECT COUNT(*) + 1 FROM public.listings))
    UNION ALL SELECT 'fact_market_event counts per type = listing_changes', COUNT(*)
    FROM (
        SELECT event_type, COUNT(*) AS n FROM gold.fact_market_event GROUP BY 1
    ) g FULL JOIN (
        SELECT CASE WHEN field = 'price_value' THEN 'price_changed'
                    WHEN old_value IS NULL THEN 'new'
                    WHEN new_value = 'removed' THEN 'removed'
                    ELSE 'relisted' END AS event_type, COUNT(*) AS n
        FROM public.listing_changes WHERE field IN ('_status', 'price_value') GROUP BY 1
    ) s USING (event_type)
    WHERE g.n IS DISTINCT FROM s.n
    UNION ALL SELECT 'fact_market_event new/removed/relisted per day = load_runs', COUNT(*)
    FROM (
        SELECT event_date AS d,
               COUNT(*) FILTER (WHERE event_type = 'new')      AS new_n,
               COUNT(*) FILTER (WHERE event_type = 'removed')  AS rem_n,
               COUNT(*) FILTER (WHERE event_type = 'relisted') AS rel_n
        FROM gold.fact_market_event GROUP BY 1
    ) g FULL JOIN (
        SELECT snapshot_date AS d, new_listings AS new_n, removed AS rem_n, relisted AS rel_n
        FROM public.load_runs
    ) r USING (d)
    WHERE (g.new_n, g.rem_n, g.rel_n) IS DISTINCT FROM (r.new_n, r.rem_n, r.rel_n)
    UNION ALL SELECT 'fact_daily_market sums = daily_stats sums',
           (SELECT COUNT(*) FROM (
                SELECT SUM(active_count), SUM(new_count), SUM(removed_count), COUNT(*) FROM gold.fact_daily_market
                EXCEPT
                SELECT SUM(active_count), SUM(new_count), SUM(removed_count), COUNT(*) FROM public.daily_stats) x)
    UNION ALL SELECT 'fact_daily_market active per day = load_runs.snapshot_rows', COUNT(*)
    FROM (SELECT date_key, SUM(active_count) AS n FROM gold.fact_daily_market GROUP BY 1) g
    FULL JOIN (SELECT to_char(snapshot_date, 'YYYYMMDD')::INT AS date_key, snapshot_rows AS n FROM public.load_runs) r
    USING (date_key) WHERE g.n IS DISTINCT FROM r.n

    -- 1e. no PII columns / free text in any gold view ------------------------
    UNION ALL SELECT 'gold view definitions reference no PII columns', COUNT(*)
    FROM pg_views v
    WHERE v.schemaname = 'gold'
      AND v.definition ~* '(agent_email|agent_image|contact_phone|contact_whatsapp|contact_email|broker_email|broker_phone|broker_address|description)'
    UNION ALL SELECT 'gold view columns include no PII columns', COUNT(*)
    FROM information_schema.columns c
    WHERE c.table_schema = 'gold'
      AND c.column_name IN ('agent_email', 'agent_image', 'contact_phone', 'contact_whatsapp',
                            'contact_email', 'broker_email', 'broker_phone', 'broker_address', 'description')

    -- 1f. security: views are security_invoker, no grants to PUBLIC/anon/authenticated
    UNION ALL SELECT 'all gold views are security_invoker', COUNT(*)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'gold' AND c.relkind = 'v'
      AND NOT COALESCE('security_invoker=true' = ANY (c.reloptions), FALSE)
    UNION ALL SELECT 'gold relations are views only (no tables/matviews)', COUNT(*)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'gold' AND c.relkind NOT IN ('v')
    UNION ALL SELECT 'no gold privileges for PUBLIC/anon/authenticated', COUNT(*)
    FROM (
        SELECT grantee FROM information_schema.role_table_grants
        WHERE table_schema = 'gold' AND grantee IN ('PUBLIC', 'anon', 'authenticated')
        UNION ALL
        -- has_*_privilege accepts 'public' for the PUBLIC pseudo-role
        SELECT r FROM unnest(ARRAY['public', 'anon', 'authenticated']) AS r
        WHERE CASE WHEN r = 'public' OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)
                   THEN has_schema_privilege(r, 'gold', 'USAGE') ELSE FALSE END
    ) x
    UNION ALL SELECT 'PUBLIC has no USAGE on schema gold', COUNT(*)
    FROM pg_namespace n, aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a
    WHERE n.nspname = 'gold' AND a.grantee = 0
)
SELECT check_name, bad, bad = 0 AS pass FROM checks;

\echo '== 2. Price sanity per category (current snapshot) =='

SELECT c.category_name,
       COUNT(*)                                                                   AS listings,
       MIN(f.monthly_price)                                                       AS min_monthly,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.monthly_price)::NUMERIC(12,2) AS med_monthly,
       MAX(f.monthly_price)                                                       AS max_monthly,
       MIN(f.price_per_sqm)                                                       AS min_ppsqm,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_per_sqm)::NUMERIC(12,2) AS med_ppsqm,
       MAX(f.price_per_sqm)                                                       AS max_ppsqm,
       COUNT(*) FILTER (WHERE f.price_per_sqm IS NULL)                            AS ppsqm_null,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.days_on_market)              AS med_days_on_market
FROM gold.fact_listing_current f
JOIN gold.dim_category c USING (category_key)
GROUP BY 1 ORDER BY 1;

\echo '== 2b. Event price-change sanity =='

SELECT COUNT(*) AS price_changes,
       MIN(price_change_pct) AS min_pct,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_change_pct) AS med_pct,
       MAX(price_change_pct) AS max_pct,
       COUNT(*) FILTER (WHERE price_at_event IS NULL) AS no_price_at_event
FROM gold.fact_market_event WHERE event_type = 'price_changed';

\echo '== 3. Timings of typical queries =='

\timing on
-- Rent per sqm by area (current)
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON, TIMING OFF)
SELECT a.region_name, a.area_name, COUNT(*), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.price_per_sqm)
FROM gold.fact_listing_current f
JOIN gold.dim_area a USING (area_key)
JOIN gold.dim_category c USING (category_key)
WHERE c.offering = 'rent'
GROUP BY 1, 2;

-- Weekly market events by segment
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON, TIMING OFF)
SELECT d.iso_year, d.iso_week, c.segment, e.event_type, SUM(e.event_count)
FROM gold.fact_market_event e
JOIN gold.dim_date d ON d.date_key = e.event_date_key
JOIN gold.dim_category c USING (category_key)
GROUP BY 1, 2, 3, 4;

-- Daily active inventory by region
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON, TIMING OFF)
SELECT d.date, a.region_name, SUM(f.active_count)
FROM gold.fact_daily_market f
JOIN gold.dim_date d USING (date_key)
JOIN gold.dim_area a USING (area_key)
GROUP BY 1, 2;

-- Top agents by active listings
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON, TIMING OFF)
SELECT ag.agent_name, b.broker_name, COUNT(*)
FROM gold.fact_listing_current f
JOIN gold.dim_agent ag USING (agent_key)
JOIN gold.dim_broker b ON b.broker_key = ag.broker_key
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;

-- Single-listing drill-down (price history of one listing)
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON, TIMING OFF)
SELECT event_date, event_type, price_prev, price_curr, price_change_pct, price_at_event
FROM gold.fact_market_event
WHERE pf_id = (SELECT pf_id FROM public.listing_changes WHERE field = 'price_value' LIMIT 1);
\timing off
