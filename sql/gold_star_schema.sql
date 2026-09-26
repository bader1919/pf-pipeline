-- =============================================================================
-- GOLD layer: star schema over the Silver tables written by scripts/load_to_db.py
--
--   Bronze  data/raw_archive/YYYY-MM-DD/*.json.gz    (raw API payloads, in git)
--   Silver  public.listings, listing_status, listing_changes, daily_stats,
--           load_runs                                 (diff-based history)
--   Gold    schema "gold": plain views only (dims + facts) -- no storage cost
--
-- Apply (idempotent, safe to re-run; the whole file is one transaction):
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f sql/gold_star_schema.sql
--
-- Requires the Silver tables to exist (run the loader once) and PostGIS
-- (listings.geom) -- both are true on Supabase.
--
-- Design rules
--   * Views only, all WITH (security_invoker = true): a caller sees gold rows
--     only if it can read the Silver tables itself (RLS on, no policies).
--   * No privileges for PUBLIC / anon / authenticated (revoked at the end of
--     every run), and "gold" is not a PostgREST-exposed schema: nothing is
--     visible through the Supabase REST API.
--   * No personal contact data: agent_email, agent_image, contact_phone,
--     contact_whatsapp, contact_email, broker_email, broker_phone,
--     broker_address and the free-text description are never selected.
--   * Keys are BIGINT (dim_listing: pf_id TEXT). Clean numeric natural ids are
--     used as-is (location_id, property_type_id, agent_id, broker_id); text
--     natural keys (area_name, category_name, UUID broker ids of developers,
--     multi-type project property types) use a deterministic 64-bit md5 hash.
--     date_key = YYYYMMDD. Every dimension has an Unknown member with key -1
--     so fact foreign keys are never NULL.
--   * Dates are UTC calendar dates (same convention as the loader's
--     snapshot_date).
--
-- Changing a view's column list: CREATE OR REPLACE VIEW can only append
-- columns. If a change renames/removes/reorders columns, add
--   DROP VIEW IF EXISTS gold.<view> CASCADE;
-- above its definition (dependent gold views are recreated further down in
-- this same file, so the run stays self-contained; re-grant any API role
-- afterwards).
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS gold;
COMMENT ON SCHEMA gold IS
  'Gold layer: star-schema views (dims + facts) over the Silver pipeline tables. Views only, security_invoker, no PII.';

-- -----------------------------------------------------------------------------
-- listing_base (internal building block, not for direct API use)
-- One row per pf_id with every surrogate key resolved once, so that the
-- dimensions and facts derived from it always agree on keys.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.listing_base WITH (security_invoker = true) AS
WITH pt_by_name AS (
    -- New-project rows carry property_type as lower-case text without an id
    -- ('apartment', 'villa'); map them onto PF's numeric id when the name matches.
    SELECT lower(property_type) AS pt_name, MIN(property_type_id::BIGINT) AS pt_id
    FROM public.listings
    WHERE property_type_id ~ '^[0-9]+$' AND property_type IS NOT NULL
    GROUP BY 1
)
SELECT
    l.pf_id,
    l.listing_id,
    -- keys ------------------------------------------------------------------
    CASE WHEN l.location_id ~ '^[0-9]+$' THEN l.location_id::BIGINT
         WHEN l.location_id IS NOT NULL
         THEN ('x' || left(md5(l.location_id), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS location_key,
    CASE WHEN l.area_name IS NOT NULL
         THEN ('x' || left(md5(l.area_name), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS area_key,
    CASE WHEN l.category_name IS NOT NULL
         THEN ('x' || left(md5(l.category_name), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS category_key,
    CASE WHEN l.property_type_id ~ '^[0-9]+$' THEN l.property_type_id::BIGINT
         WHEN pt.pt_id IS NOT NULL THEN pt.pt_id
         WHEN l.property_type IS NOT NULL
         THEN ('x' || left(md5(lower(l.property_type)), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS property_type_key,
    CASE WHEN l.agent_id ~ '^[0-9]+$' THEN l.agent_id::BIGINT
         WHEN l.agent_id IS NOT NULL
         THEN ('x' || left(md5(l.agent_id), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS agent_key,
    CASE WHEN l.broker_id ~ '^[0-9]+$' THEN l.broker_id::BIGINT
         WHEN l.broker_id IS NOT NULL
         THEN ('x' || left(md5(l.broker_id), 16))::BIT(64)::BIGINT
         ELSE -1 END                                             AS broker_key,
    -- status ----------------------------------------------------------------
    s.first_seen_date,
    s.last_seen_date,
    s.is_active,
    -- location --------------------------------------------------------------
    l.location_id, l.location_name, l.location_type, l.location_full_name,
    l.location_path_name, l.location_slug, l.community, l.sub_community,
    l.area_id, l.area_name, l.region_id, l.region_name,
    l.latitude, l.longitude, l.geom,
    -- category --------------------------------------------------------------
    l.category_id, l.category_name, l.offering_type,
    -- property type ---------------------------------------------------------
    l.property_type_id, l.property_type,
    -- agent / broker (no contact data) --------------------------------------
    l.agent_id, l.agent_name, l.agent_slug, l.agent_is_super_agent,
    l.agent_position, l.agent_languages, l.agent_years_experience,
    l.agent_total_properties, l.agent_transactions_count,
    l.agent_whatsapp_response_time,
    l.broker_id, l.broker_name, l.broker_slug, l.broker_is_exclusive,
    l.broker_license_number, l.broker_total_properties, l.broker_total_agents,
    l.broker_total_super_agents,
    -- listing attributes ----------------------------------------------------
    l.title, l.bedrooms, l.bedrooms_value, l.bathrooms, l.bathrooms_value,
    l.size_value, l.size_unit, l.plot_size, l.furnished, l.completion_status,
    -- PF uses 0001-01-01 as a "no date" sentinel on a few listings
    CASE WHEN l.listed_date >= '2000-01-01' THEN l.listed_date END AS listed_date,
    l.last_refreshed_at, l.share_url,
    l.price_value, l.price_currency, l.price_period, l.price_is_hidden,
    l.is_verified, l.is_featured, l.is_premium, l.is_exclusive,
    l.is_direct_from_developer, l.listing_level,
    l.scraped_at
FROM public.listings l
JOIN public.listing_status s USING (pf_id)
LEFT JOIN pt_by_name pt ON pt.pt_name = lower(l.property_type)
                       AND COALESCE(l.property_type_id, '') !~ '^[0-9]+$';

COMMENT ON VIEW gold.listing_base IS
  'Internal: one row per pf_id with all gold surrogate keys resolved. Building block for the dims/facts; APIs should read the dim_/fact_ views instead.';

-- -----------------------------------------------------------------------------
-- dim_date  (grain: calendar day; role-played by snapshot / event / listed /
-- first-seen dates). Range: earliest date in the data .. max(today, latest
-- date in the data) + 30 days, plus the Unknown row (-1).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_date WITH (security_invoker = true) AS
WITH bounds AS (
    SELECT LEAST(
               (SELECT MIN((listed_date AT TIME ZONE 'UTC')::DATE) FROM gold.listing_base),
               (SELECT MIN(first_seen_date) FROM public.listing_status),
               (SELECT MIN(change_date) FROM public.listing_changes),
               (SELECT MIN(stat_date) FROM public.daily_stats),
               current_date) AS d_min,
           GREATEST(
               (SELECT MAX((listed_date AT TIME ZONE 'UTC')::DATE) FROM gold.listing_base),
               (SELECT MAX(last_seen_date) FROM public.listing_status),
               current_date) + 30 AS d_max
), days AS (
    SELECT g::DATE AS d
    FROM bounds, generate_series(bounds.d_min, bounds.d_max, INTERVAL '1 day') AS g
)
SELECT to_char(d, 'YYYYMMDD')::INTEGER             AS date_key,
       d                                           AS date,
       EXTRACT(DAY FROM d)::SMALLINT               AS day,
       trim(to_char(d, 'Day'))                     AS day_name,
       EXTRACT(ISODOW FROM d)::SMALLINT            AS iso_day_of_week,
       EXTRACT(ISODOW FROM d) IN (5, 6)            AS is_weekend,
       EXTRACT(WEEK FROM d)::SMALLINT              AS iso_week,
       EXTRACT(ISOYEAR FROM d)::SMALLINT           AS iso_year,
       EXTRACT(MONTH FROM d)::SMALLINT             AS month,
       trim(to_char(d, 'Month'))                   AS month_name,
       EXTRACT(QUARTER FROM d)::SMALLINT           AS quarter,
       EXTRACT(YEAR FROM d)::SMALLINT              AS year,
       to_char(d, 'YYYY-MM')                       AS year_month
FROM days
UNION ALL
SELECT -1, NULL, NULL, 'Unknown', NULL, NULL, NULL, NULL, NULL, 'Unknown', NULL, NULL, 'Unknown';

COMMENT ON VIEW gold.dim_date IS
  'Calendar dimension, one row per day (UTC) from the earliest date in the data to today+30, plus Unknown (-1). Bahrain weekend = Friday & Saturday.';
COMMENT ON COLUMN gold.dim_date.date_key IS 'Surrogate key YYYYMMDD (e.g. 20260620); -1 = Unknown.';
COMMENT ON COLUMN gold.dim_date.is_weekend IS 'TRUE on Friday and Saturday (Bahrain weekend).';

-- -----------------------------------------------------------------------------
-- dim_area  (grain: area_name -- the level daily_stats is kept at)
-- Conformed roll-up of dim_location; used directly by fact_daily_market.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_area WITH (security_invoker = true) AS
WITH names AS (
    SELECT area_name FROM gold.listing_base WHERE area_name IS NOT NULL
    UNION
    SELECT area_name FROM public.daily_stats WHERE area_name <> '(unknown)'
), attrs AS (
    -- most frequent id/region per area name (new-project rows carry no ids)
    SELECT DISTINCT ON (area_name) area_name, area_id, region_id, region_name
    FROM gold.listing_base
    WHERE area_name IS NOT NULL
    GROUP BY area_name, area_id, region_id, region_name
    ORDER BY area_name, (area_id IS NULL), COUNT(*) DESC
)
SELECT ('x' || left(md5(n.area_name), 16))::BIT(64)::BIGINT AS area_key,
       a.area_id,
       n.area_name,
       a.region_id,
       COALESCE(a.region_name, 'Unknown')                   AS region_name
FROM names n
LEFT JOIN attrs a USING (area_name)
UNION ALL
SELECT -1, NULL, 'Unknown', NULL, 'Unknown';

COMMENT ON VIEW gold.dim_area IS
  'Area dimension (grain: area, ~100 rows) with its governorate/region. Conformed roll-up of dim_location; the grain of fact_daily_market. -1 = Unknown.';
COMMENT ON COLUMN gold.dim_area.area_key IS 'Deterministic key: 64-bit md5 hash of area_name; -1 = Unknown.';

-- -----------------------------------------------------------------------------
-- dim_location  (grain: PF location_id = leaf of the location tree:
-- area, or community / sub-community / tower inside an area)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_location WITH (security_invoker = true) AS
SELECT location_key, location_id, location_name, location_type, location_full_name,
       location_path_name, community, sub_community, area_key, area_id, area_name,
       region_id, region_name
FROM (
    SELECT DISTINCT ON (location_key)
           location_key, location_id, location_name, location_type, location_full_name,
           location_path_name, community, sub_community, area_key, area_id, area_name,
           region_id, region_name
    FROM gold.listing_base
    WHERE location_key <> -1
    -- prefer rows that carry the full tree (regular listings over new projects),
    -- then the most recently seen
    ORDER BY location_key, (location_type IS NULL), last_seen_date DESC, scraped_at DESC
) x
UNION ALL
SELECT -1, NULL, 'Unknown', NULL, NULL, NULL, NULL, NULL, -1, NULL, 'Unknown', NULL, 'Unknown';

COMMENT ON VIEW gold.dim_location IS
  'Location dimension (grain: PF location_id, the leaf of the location tree, ~160 rows). Carries community/sub_community and rolls up to dim_area via area_key. -1 = Unknown.';
COMMENT ON COLUMN gold.dim_location.location_key IS 'PF location_id as BIGINT; -1 = Unknown.';
COMMENT ON COLUMN gold.dim_location.area_key IS 'FK to gold.dim_area.';

-- -----------------------------------------------------------------------------
-- dim_category  (grain: category_name)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_category WITH (security_invoker = true) AS
WITH cats AS (
    SELECT DISTINCT ON (category_name) category_name, category_id, offering_type
    FROM gold.listing_base
    WHERE category_name IS NOT NULL
    ORDER BY category_name, last_seen_date DESC
), names AS (
    SELECT category_name FROM cats
    UNION
    SELECT category_name FROM public.daily_stats WHERE category_name <> '(unknown)'
)
SELECT ('x' || left(md5(n.category_name), 16))::BIT(64)::BIGINT AS category_key,
       c.category_id,
       n.category_name,
       CASE WHEN c.offering_type ILIKE '% for %' THEN c.offering_type
            ELSE n.category_name END                           AS category_label,
       CASE WHEN n.category_name ILIKE 'residential%' THEN 'residential'
            WHEN n.category_name ILIKE 'commercial%'  THEN 'commercial'
            WHEN n.category_name ILIKE '%project%'    THEN 'new_projects'
            ELSE 'other' END                                   AS segment,
       CASE WHEN n.category_name ILIKE '%rent%' THEN 'rent'
            WHEN n.category_name ILIKE '%sale%' OR n.category_name ILIKE '%project%' THEN 'sale'
            ELSE 'unknown' END                                 AS offering
FROM names n
LEFT JOIN cats c USING (category_name)
UNION ALL
SELECT -1, NULL, 'Unknown', 'Unknown', 'unknown', 'unknown';

COMMENT ON VIEW gold.dim_category IS
  'Listing category (residential_rent, residential_sale, commercial_rent, commercial_sale, New Projects) with segment (residential/commercial/new_projects) and offering (rent/sale). -1 = Unknown.';
COMMENT ON COLUMN gold.dim_category.category_key IS 'Deterministic key: 64-bit md5 hash of category_name; -1 = Unknown.';
COMMENT ON COLUMN gold.dim_category.offering IS 'rent or sale (new projects are sale).';

-- -----------------------------------------------------------------------------
-- dim_property_type  (grain: PF property_type_id; new-project multi-type
-- strings such as 'apartment|penthouse' get their own hashed member)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_property_type WITH (security_invoker = true) AS
SELECT property_type_key, property_type_id, property_type, is_multi_type
FROM (
    SELECT DISTINCT ON (property_type_key)
           property_type_key,
           CASE WHEN property_type_id ~ '^[0-9]+$' THEN property_type_id::INTEGER END AS property_type_id,
           property_type,
           property_type LIKE '%|%' AS is_multi_type
    FROM gold.listing_base
    WHERE property_type_key <> -1
    ORDER BY property_type_key, (property_type_id IS NULL), last_seen_date DESC
) x
UNION ALL
SELECT -1, NULL, 'Unknown', FALSE;

COMMENT ON VIEW gold.dim_property_type IS
  'Property type (Apartment, Villa, Land, Office Space, ...). Key = PF property_type_id; new-project text types without an id map by name, multi-type strings (a|b) get a hashed key. -1 = Unknown.';

-- -----------------------------------------------------------------------------
-- dim_broker  (grain: broker_id = agency, or developer for new projects)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_broker WITH (security_invoker = true) AS
SELECT broker_key, broker_id, broker_name, broker_slug, is_developer, broker_is_exclusive,
       broker_license_number, broker_total_properties, broker_total_agents,
       broker_total_super_agents
FROM (
    SELECT DISTINCT ON (broker_key)
           broker_key, broker_id, broker_name, broker_slug,
           NOT (broker_id ~ '^[0-9]+$')                                   AS is_developer,
           broker_is_exclusive, broker_license_number,
           CASE WHEN broker_total_properties   ~ '^[0-9]+$' THEN broker_total_properties::INTEGER END   AS broker_total_properties,
           CASE WHEN broker_total_agents       ~ '^[0-9]+$' THEN broker_total_agents::INTEGER END       AS broker_total_agents,
           CASE WHEN broker_total_super_agents ~ '^[0-9]+$' THEN broker_total_super_agents::INTEGER END AS broker_total_super_agents
    FROM gold.listing_base
    WHERE broker_key <> -1
    ORDER BY broker_key, last_seen_date DESC, scraped_at DESC
) x
UNION ALL
SELECT -1, NULL, 'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL;

COMMENT ON VIEW gold.dim_broker IS
  'Broker / agency (latest attributes). is_developer = TRUE for developer ids (UUIDs) that only appear on New Projects. No contact data (email/phone/address excluded). -1 = Unknown.';

-- -----------------------------------------------------------------------------
-- dim_agent  (grain: agent_id; latest attributes)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_agent WITH (security_invoker = true) AS
SELECT agent_key, agent_id, agent_name, agent_slug, is_super_agent, agent_position,
       agent_languages, years_experience, total_properties, transactions_count,
       whatsapp_response_time, broker_key, broker_id, broker_name
FROM (
    SELECT DISTINCT ON (agent_key)
           agent_key, agent_id, agent_name, agent_slug,
           agent_is_super_agent AS is_super_agent,
           agent_position, agent_languages,
           CASE WHEN agent_years_experience   ~ '^[0-9]+$' THEN agent_years_experience::INTEGER END   AS years_experience,
           CASE WHEN agent_total_properties   ~ '^[0-9]+$' THEN agent_total_properties::INTEGER END   AS total_properties,
           CASE WHEN agent_transactions_count ~ '^[0-9]+$' THEN agent_transactions_count::INTEGER END AS transactions_count,
           agent_whatsapp_response_time AS whatsapp_response_time,
           broker_key, broker_id, broker_name
    FROM gold.listing_base
    WHERE agent_key <> -1
    ORDER BY agent_key, last_seen_date DESC, scraped_at DESC
) x
UNION ALL
SELECT -1, NULL, 'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, -1, NULL, 'Unknown';

COMMENT ON VIEW gold.dim_agent IS
  'Agent (latest attributes of the most recently seen listing). Name, super-agent flag, languages, experience; broker_key = current agency. No contact data (email/image/phone excluded). -1 = Unknown.';
COMMENT ON COLUMN gold.dim_agent.broker_key IS 'FK to gold.dim_broker (agency of the agent''s most recently seen listing).';

-- -----------------------------------------------------------------------------
-- dim_listing  (grain: pf_id -- every listing ever seen, active or not)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.dim_listing WITH (security_invoker = true) AS
SELECT pf_id, listing_id, title,
       bedrooms_value, (bedrooms = 'studio' OR bedrooms_value = 0) AS is_studio,
       bathrooms_value, size_value, size_unit, furnished, completion_status,
       latitude, longitude, geom,
       (listed_date AT TIME ZONE 'UTC')::DATE AS listed_date,
       first_seen_date, last_seen_date, is_active, share_url,
       location_key, area_key, category_key, property_type_key, agent_key, broker_key
FROM gold.listing_base
UNION ALL
SELECT '(unknown)', NULL, 'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, FALSE, NULL, -1, -1, -1, -1, -1, -1;

COMMENT ON VIEW gold.dim_listing IS
  'Listing dimension, one row per pf_id ever seen (active or removed), attributes as of the latest content change, plus FKs to the other dims. pf_id ''(unknown)'' = Unknown member.';
COMMENT ON COLUMN gold.dim_listing.pf_id IS 'PropertyFinder listing id (natural key, TEXT).';
COMMENT ON COLUMN gold.dim_listing.first_seen_date IS 'First snapshot the pipeline saw the listing (left-censored at the first loaded day).';
COMMENT ON COLUMN gold.dim_listing.is_active IS 'TRUE when present in the latest loaded snapshot.';
COMMENT ON COLUMN gold.dim_listing.listed_date IS 'PF listed date (UTC); NULL when PF sends its 0001-01-01 sentinel.';
COMMENT ON COLUMN gold.dim_listing.bedrooms_value IS 'NULL for studios (see is_studio) and commercial listings.';

-- -----------------------------------------------------------------------------
-- fact_listing_current  (grain: one row per ACTIVE listing at the latest
-- loaded snapshot)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.fact_listing_current WITH (security_invoker = true) AS
WITH snap AS (
    SELECT MAX(snapshot_date) AS snapshot_date, MIN(snapshot_date) AS first_load_date
    FROM public.load_runs
), pc AS (
    SELECT pf_id, COUNT(*) AS price_change_count, MAX(change_date) AS last_price_change_date
    FROM public.listing_changes
    WHERE field = 'price_value'
    GROUP BY pf_id
), base AS (
    SELECT b.pf_id, b.location_key, b.area_key, b.category_key, b.property_type_key,
           b.agent_key, b.broker_key, b.listed_date, b.first_seen_date,
           b.price_value, b.price_period, b.price_is_hidden,
           -- same rule as gold.dim_category.offering
           CASE WHEN b.category_name ILIKE '%rent%' THEN 'rent' ELSE 'sale' END AS offering,
           CASE WHEN lower(b.size_unit) IN ('sqft', 'sq ft', 'ft2', 'sqf')
                THEN b.size_value * 0.09290304
                ELSE b.size_value END                          AS size_sqm_raw,
           CASE WHEN b.category_name ILIKE '%rent%' AND b.price_value > 0 THEN
                CASE lower(b.price_period)
                     WHEN 'monthly' THEN b.price_value
                     WHEN 'yearly'  THEN b.price_value / 12
                     WHEN 'weekly'  THEN b.price_value * 52 / 12
                     WHEN 'daily'   THEN b.price_value * 365 / 12
                END
           END                                                 AS monthly_price_raw
    FROM gold.listing_base b
    WHERE b.is_active
)
SELECT
    b.pf_id,
    to_char(snap.snapshot_date, 'YYYYMMDD')::INTEGER                      AS snapshot_date_key,
    b.location_key, b.area_key, b.category_key, b.property_type_key, b.agent_key, b.broker_key,
    COALESCE(to_char((b.listed_date AT TIME ZONE 'UTC')::DATE, 'YYYYMMDD')::INTEGER, -1) AS listed_date_key,
    to_char(b.first_seen_date, 'YYYYMMDD')::INTEGER                       AS first_seen_date_key,
    b.price_value,
    b.price_period,
    b.price_is_hidden,
    ROUND(b.monthly_price_raw, 2)                                         AS monthly_price,
    ROUND(b.size_sqm_raw, 2)                                              AS size_sqm,
    ROUND(CASE WHEN b.size_sqm_raw > 0 THEN
               CASE WHEN b.offering = 'rent' THEN b.monthly_price_raw
                    WHEN b.price_value > 0 THEN b.price_value END / b.size_sqm_raw
          END, 2)                                                         AS price_per_sqm,
    snap.snapshot_date - b.first_seen_date                                AS days_on_market,
    (b.first_seen_date = snap.first_load_date)                            AS days_on_market_censored,
    snap.snapshot_date - (b.listed_date AT TIME ZONE 'UTC')::DATE         AS days_since_listed,
    COALESCE(pc.price_change_count, 0)::INTEGER                           AS price_change_count,
    pc.last_price_change_date
FROM base b
CROSS JOIN snap
LEFT JOIN pc USING (pf_id);

COMMENT ON VIEW gold.fact_listing_current IS
  'Current market snapshot: one row per listing active in the latest loaded snapshot (load_runs), with prices normalised and time-on-market measures.';
COMMENT ON COLUMN gold.fact_listing_current.snapshot_date_key IS 'Latest load_runs.snapshot_date as YYYYMMDD.';
COMMENT ON COLUMN gold.fact_listing_current.monthly_price IS 'Rent normalised to BHD/month (yearly/12, weekly*52/12, daily*365/12); NULL for sale listings and for price 0.';
COMMENT ON COLUMN gold.fact_listing_current.size_sqm IS 'Size in square metres (sqft converted x0.09290304).';
COMMENT ON COLUMN gold.fact_listing_current.price_per_sqm IS 'Rent: monthly_price per sqm. Sale: price_value per sqm. NULL when size or price is missing/0.';
COMMENT ON COLUMN gold.fact_listing_current.days_on_market IS 'Snapshot date - first_seen_date (days tracked by the pipeline).';
COMMENT ON COLUMN gold.fact_listing_current.days_on_market_censored IS 'TRUE when first seen on the first loaded day: the listing may be older than days_on_market says.';
COMMENT ON COLUMN gold.fact_listing_current.days_since_listed IS 'Snapshot date - PF listed_date (PF can reset listed_date on refresh).';
COMMENT ON COLUMN gold.fact_listing_current.price_change_count IS 'Number of logged price changes over the listing''s tracked life.';

-- -----------------------------------------------------------------------------
-- fact_market_event  (grain: one row per listing per day per event:
-- new / removed / relisted / price_changed)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.fact_market_event WITH (security_invoker = true) AS
WITH ev AS (
    SELECT c.pf_id, c.change_date,
           CASE WHEN c.field = 'price_value' THEN 'price_changed'
                WHEN c.old_value IS NULL      THEN 'new'
                WHEN c.new_value = 'removed'  THEN 'removed'
                ELSE 'relisted' END                                          AS event_type,
           CASE WHEN c.field = 'price_value' AND c.old_value ~ '^-?[0-9]+\.?[0-9]*$'
                THEN c.old_value::NUMERIC END                                AS price_prev,
           CASE WHEN c.field = 'price_value' AND c.new_value ~ '^-?[0-9]+\.?[0-9]*$'
                THEN c.new_value::NUMERIC END                                AS price_curr
    FROM public.listing_changes c
    WHERE c.field IN ('_status', 'price_value')
)
SELECT
    e.pf_id,
    to_char(e.change_date, 'YYYYMMDD')::INTEGER                             AS event_date_key,
    e.change_date                                                           AS event_date,
    e.event_type,
    d.location_key, d.area_key, d.category_key, d.property_type_key, d.agent_key, d.broker_key,
    e.price_prev,
    e.price_curr,
    e.price_curr - e.price_prev                                             AS price_change,
    ROUND(100 * (e.price_curr - e.price_prev) / NULLIF(e.price_prev, 0), 2) AS price_change_pct,
    CASE WHEN e.event_type = 'price_changed' THEN e.price_curr
         ELSE COALESCE(
             -- price in force on the event day, rebuilt from the price log
             (SELECT CASE WHEN p.new_value ~ '^-?[0-9]+\.?[0-9]*$' THEN p.new_value::NUMERIC END
              FROM public.listing_changes p
              WHERE p.pf_id = e.pf_id AND p.field = 'price_value' AND p.change_date <= e.change_date
              ORDER BY p.change_date DESC LIMIT 1),
             (SELECT CASE WHEN p.old_value ~ '^-?[0-9]+\.?[0-9]*$' THEN p.old_value::NUMERIC END
              FROM public.listing_changes p
              WHERE p.pf_id = e.pf_id AND p.field = 'price_value' AND p.change_date > e.change_date
              ORDER BY p.change_date ASC LIMIT 1),
             d.price_value)
    END                                                                     AS price_at_event,
    1                                                                       AS event_count
FROM ev e
JOIN gold.listing_base d USING (pf_id);

COMMENT ON VIEW gold.fact_market_event IS
  'Market events from listing_changes: new, removed, relisted (field _status) and price_changed (field price_value). Dimension keys come from the listing''s current attributes.';
COMMENT ON COLUMN gold.fact_market_event.event_type IS 'new | removed | relisted | price_changed';
COMMENT ON COLUMN gold.fact_market_event.price_prev IS 'price_changed only: price before the change.';
COMMENT ON COLUMN gold.fact_market_event.price_curr IS 'price_changed only: price after the change.';
COMMENT ON COLUMN gold.fact_market_event.price_change_pct IS 'price_changed only: 100 * (curr - prev) / prev.';
COMMENT ON COLUMN gold.fact_market_event.price_at_event IS 'Listing price in force on the event day (rebuilt from the price log).';

-- -----------------------------------------------------------------------------
-- fact_daily_market  (grain: day x category x area, from daily_stats)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.fact_daily_market WITH (security_invoker = true) AS
SELECT to_char(s.stat_date, 'YYYYMMDD')::INTEGER AS date_key,
       CASE WHEN s.area_name = '(unknown)' THEN -1
            ELSE ('x' || left(md5(s.area_name), 16))::BIT(64)::BIGINT END     AS area_key,
       CASE WHEN s.category_name = '(unknown)' THEN -1
            ELSE ('x' || left(md5(s.category_name), 16))::BIT(64)::BIGINT END AS category_key,
       s.active_count,
       s.new_count,
       s.removed_count,
       s.avg_price,
       s.median_price
FROM public.daily_stats s;

COMMENT ON VIEW gold.fact_daily_market IS
  'Daily market time series (grain: day x category x area) from daily_stats: active/new/removed counts, avg/median asking price (raw price_value, BHD; rent = monthly).';
COMMENT ON COLUMN gold.fact_daily_market.avg_price IS 'Average price_value of active listings that day (not additive across rows).';
COMMENT ON COLUMN gold.fact_daily_market.median_price IS 'Median price_value of active listings that day (not additive across rows).';

-- -----------------------------------------------------------------------------
-- Privileges: nothing for PUBLIC / anon / authenticated (Supabase REST roles).
-- -----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA gold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA gold FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold REVOKE ALL ON TABLES FROM PUBLIC;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA gold FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA gold FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA gold REVOKE ALL ON TABLES FROM %I', r);
        END IF;
    END LOOP;
END $$;

COMMIT;
