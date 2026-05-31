"""
PropertyFinder Bahrain — data cleaner.
Reads raw JSON from data/raw/, maps every field to the exact same
column schema as the n8n pf_listings table (117 columns).
Outputs per-category CSVs + combined all_listings.csv to data/latest/.
"""

import csv
import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR  = os.path.join(BASE_DIR, "data", "raw")
OUT_DIR  = os.path.join(BASE_DIR, "data", "latest")

CATEGORIES = [
    ("residential_rent",  "2", "Residential", "rent"),
    ("residential_sale",  "1", "Residential", "sale"),
    ("commercial_rent",   "4", "Commercial",  "rent"),
    ("commercial_sale",   "3", "Commercial",  "sale"),
]

# Exact column order — matches n8n pf_listings table (minus n8n-internal id/createdAt/updatedAt)
COLUMNS = [
    "listing_id", "pf_id", "title", "description",
    "property_type", "property_type_id", "category_id", "category_name", "offering_type",
    "bedrooms", "bedrooms_value", "bathrooms", "bathrooms_value", "rooms", "rooms_value",
    "completion_status", "furnished", "utilities_price_type",
    "listed_date", "last_refreshed_at", "rental_availability_date", "age",
    "share_url", "share_url_translated", "video_id", "view_360",
    "plot_size", "images_count", "zone_name", "agent_license_no", "payment_methods",
    "price_value", "price_currency", "price_period", "price_is_hidden",
    "price_per_area_price", "price_per_area_unit", "price_per_area_plot", "mortgage_cashback",
    "size_value", "size_unit",
    "location_id", "location_full_name", "latitude", "longitude",
    "location_slug", "location_type", "location_name", "location_path_name",
    "region_id", "region_name", "region_slug",
    "area_id", "area_name", "area_slug",
    "agent_id", "agent_image", "agent_is_super_agent", "agent_name", "agent_email",
    "agent_slug", "agent_whatsapp_response_time", "agent_total_properties",
    "agent_position", "agent_years_experience", "agent_transactions_count", "agent_languages",
    "contact_phone", "contact_whatsapp", "contact_email",
    "broker_id", "broker_name", "broker_address", "broker_email", "broker_phone",
    "broker_slug", "broker_total_properties", "broker_license_number",
    "broker_is_exclusive", "broker_total_agents", "broker_total_super_agents",
    "rera_number", "rera_authority_name", "rera_permit_url",
    "is_verified", "is_direct_from_developer", "is_new_construction", "is_available",
    "is_featured", "is_premium", "is_new_insert", "is_community_expert",
    "is_cts", "is_exclusive", "is_broker_project_property", "is_smart_ad",
    "is_spotlight_listing", "is_claimed_by_agent", "is_under_offer_by_competitor",
    "is_pf_exclusive", "is_fhm", "is_great_value", "is_high_demand", "is_luxe",
    "listing_level", "listing_level_label", "lead_value", "qs",
    "amenity_codes", "amenity_names", "image_url_first", "has_price_trends",
    "scraped_at", "detail_scraped_at",
]


def s(val, default=""):
    """Safe string — return empty string for None/NaN."""
    if val is None:
        return default
    if isinstance(val, float) and val != val:
        return default
    return val


def get(d, *keys, default=""):
    """Nested safe-get: get(obj, 'a', 'b', 'c') = obj.a.b.c"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return s(cur, default)


def pipe_list(items, key=None):
    """Join list items with | separator. If key given, extract that key from each dict."""
    if not items:
        return ""
    parts = []
    for item in items:
        if isinstance(item, dict):
            parts.append(str(item.get(key, "") or "") if key else str(item))
        else:
            parts.append(str(item))
    return "|".join(x for x in parts if x)


def flatten_listing(p: dict, category_id: str, category_name: str, scraped_at: str) -> dict:
    """
    Map a raw PropertyFinder API listing object to the exact 114-column schema.
    Handles the actual API format where price/size are top-level scalars,
    agent/broker are strings with detail objects in agentInfo/brokerInfo,
    location comes from locationTree + coordinates, and images are plain URL strings.
    """

    # ── Agent ────────────────────────────────────────────────────────────────
    # API returns agent as a plain string name; details live in agentInfo
    agent_info = p.get("agentInfo") or {}
    if not agent_info and isinstance(p.get("agent"), dict):
        agent_info = p.get("agent")  # fallback: older format where agent was a dict

    agent_langs = agent_info.get("languages") or []
    if isinstance(agent_langs, list):
        agent_langs_str = pipe_list(agent_langs, key="name") or pipe_list(agent_langs)
    else:
        agent_langs_str = s(agent_langs)

    # ── Broker ───────────────────────────────────────────────────────────────
    # API returns broker as a plain string name; details live in brokerInfo/clientInfo
    broker_info = p.get("brokerInfo") or p.get("clientInfo") or {}
    if not broker_info and isinstance(p.get("broker"), dict):
        broker_info = p.get("broker")  # fallback: older format

    # ── Price ────────────────────────────────────────────────────────────────
    # API returns price as a top-level int/float; older format used a dict
    raw_price = p.get("price")
    if isinstance(raw_price, dict):
        price_value   = s(raw_price.get("value") or raw_price.get("amount"))
        price_currency = s(raw_price.get("currency"), "BHD")
        price_period  = s(raw_price.get("period"))
        price_hidden  = raw_price.get("isHidden") or raw_price.get("onRequest")
        price_pa      = raw_price.get("perArea") or raw_price.get("pricePerArea") or {}
        ppa_price     = s(price_pa.get("price") or price_pa.get("value")) if isinstance(price_pa, dict) else s(price_pa)
        ppa_unit      = s(price_pa.get("unit")) if isinstance(price_pa, dict) else ""
        ppa_plot      = s(raw_price.get("perAreaPlot") or raw_price.get("pricePerAreaPlot"))
    else:
        price_value   = s(raw_price)
        price_currency = s(p.get("priceCurrency"), "BHD")
        price_period  = s(p.get("priceDuration"))
        price_hidden  = None
        ppa_price     = ""
        ppa_unit      = ""
        ppa_plot      = ""

    # ── Size ─────────────────────────────────────────────────────────────────
    # API returns size as a top-level int/float + sizeUnit; older format used a dict
    raw_size = p.get("size")
    if isinstance(raw_size, dict):
        size_value = s(raw_size.get("value") or raw_size.get("size"))
        size_unit  = s(raw_size.get("unit"), "sqm")
    else:
        size_value = s(raw_size or p.get("area"))
        size_unit  = s(p.get("sizeUnit"), "sqm")

    # ── Location ─────────────────────────────────────────────────────────────
    # API returns locationTree (array) + coordinates (dict) + displayAddress
    loc_tree   = p.get("locationTree") or []
    coords     = p.get("coordinates") or {}
    loc_old    = p.get("location") or {}  # fallback for older API format

    region_node = next((n for n in loc_tree if n.get("type") == "REGION"), {})
    area_node   = next((n for n in loc_tree if n.get("type") == "AREA"), {})

    # Prefer locationTree; fall back to nested location object
    region_id   = s(region_node.get("id")   or loc_old.get("region", {}).get("id"))
    region_name = s(region_node.get("name") or loc_old.get("region", {}).get("name"))
    region_slug = s(region_node.get("slug") or loc_old.get("region", {}).get("slug"))
    area_id     = s(area_node.get("id")     or loc_old.get("area", {}).get("id"))
    area_name   = s(area_node.get("name")   or loc_old.get("area", {}).get("name"))
    area_slug   = s(area_node.get("slug")   or loc_old.get("area", {}).get("slug"))

    loc_full    = (s(p.get("displayAddress"))
                   or s(loc_old.get("fullName"))
                   or s(loc_old.get("name")))
    latitude    = s(coords.get("latitude")  or loc_old.get("lat") or loc_old.get("latitude"))
    longitude   = s(coords.get("longitude") or loc_old.get("lng") or loc_old.get("longitude"))

    # location_name: the most granular named place (building > area > communityName)
    location_name = (s(p.get("buildingName"))
                     or area_name
                     or s(p.get("communityName")))

    # ── Images ───────────────────────────────────────────────────────────────
    # API returns images as plain URL strings; older format used dicts
    photos = p.get("photos") or p.get("images") or []
    images_count = len(photos)
    image_url_first = ""
    if photos:
        first = photos[0]
        image_url_first = s(first if isinstance(first, str)
                            else (first.get("urlMedium") or first.get("url") or first.get("src")))

    # ── Amenities ────────────────────────────────────────────────────────────
    # API returns amenities as code strings ["CP"], features as name strings ["Covered Parking"]
    raw_amenities = p.get("amenities") or []
    raw_features  = p.get("features")  or []
    if raw_amenities and isinstance(raw_amenities[0], dict):
        amenity_codes = pipe_list(raw_amenities, key="code") or pipe_list(raw_amenities, key="id")
        amenity_names = pipe_list(raw_amenities, key="name") or pipe_list(raw_amenities, key="label")
    else:
        amenity_codes = pipe_list(raw_amenities)
        amenity_names = pipe_list(raw_features) or pipe_list(raw_amenities)

    # ── Property type ────────────────────────────────────────────────────────
    prop_type = p.get("propertyType") or {}
    if isinstance(prop_type, dict):
        prop_type_name = s(prop_type.get("name") or prop_type.get("label"))
        prop_type_id   = s(prop_type.get("id"))
    else:
        prop_type_name = s(prop_type)
        prop_type_id   = s(p.get("propertyTypeId"))

    # ── Offering type ────────────────────────────────────────────────────────
    offering = (s(p.get("offeringType"))
                or s(p.get("type"))
                or s(p.get("listingType"))
                or s(p.get("priceDuration")))

    # ── Contacts ─────────────────────────────────────────────────────────────
    contacts = p.get("contactOptions") or p.get("contacts") or []

    def extract_contact(contacts_list, ctype):
        for c in contacts_list:
            if isinstance(c, dict):
                if ctype in (c.get("type") or "").lower():
                    return s(c.get("value") or c.get("number") or c.get("url"))
        return ""

    contact_phone    = (s(p.get("agentPhone"))    or s(p.get("contactPhone"))
                        or extract_contact(contacts, "phone"))
    contact_whatsapp = (s(p.get("agentWhatsapp")) or s(p.get("contactWhatsapp"))
                        or extract_contact(contacts, "whatsapp"))
    contact_email    = (s(p.get("agentEmail"))    or s(p.get("contactEmail"))
                        or extract_contact(contacts, "email"))

    # ── IDs ──────────────────────────────────────────────────────────────────
    # listing_id = numeric site ID; pf_id = internal hash ID
    listing_id = s(p.get("id"))
    pf_id      = s(p.get("listingId") or p.get("id"))

    # ── Payment methods ──────────────────────────────────────────────────────
    pm = p.get("paymentMethod") or p.get("paymentMethods") or []
    payment_methods = pipe_list(pm, key="name") if pm and isinstance(pm[0], dict) else pipe_list(pm)

    # ── Boolean helper ───────────────────────────────────────────────────────
    def b(val):
        if val is None:
            return ""
        return str(bool(val)).lower()

    return {
        "listing_id":                  listing_id,
        "pf_id":                       pf_id,
        "title":                       s(p.get("title") or p.get("name")),
        "description":                 s(p.get("description") or "")[:2000],
        "property_type":               prop_type_name,
        "property_type_id":            prop_type_id,
        "category_id":                 category_id,
        "category_name":               category_name,
        "offering_type":               offering,
        "bedrooms":                    s(p.get("bedrooms") or p.get("bedsMin") or p.get("beds")),
        "bedrooms_value":              s(p.get("bedroomsValue") or p.get("bedroomsLabel") or p.get("bedrooms")),
        "bathrooms":                   s(p.get("bathrooms") or p.get("bathsMin") or p.get("baths")),
        "bathrooms_value":             s(p.get("bathroomsValue") or p.get("bathroomsLabel") or p.get("bathrooms")),
        "rooms":                       s(p.get("rooms") or p.get("roomsMin")),
        "rooms_value":                 s(p.get("roomsValue") or p.get("roomsLabel") or p.get("rooms")),
        "completion_status":           s(p.get("completionStatus")),
        "furnished":                   s(p.get("furnished") or p.get("furnishing") or p.get("furnishingStatus")),
        "utilities_price_type":        s(p.get("utilitiesPriceType")),
        "listed_date":                 s(p.get("addedOn") or p.get("listedDate") or p.get("createdAt") or p.get("publishedAt")),
        "last_refreshed_at":           s(p.get("lastRefreshedAt") or p.get("updatedAt")),
        "rental_availability_date":    s(p.get("rentalAvailabilityDate")),
        "age":                         s(p.get("age")),
        "share_url":                   s(p.get("url") or p.get("shareUrl")),
        "share_url_translated":        s(p.get("shareUrlTranslated")),
        "video_id":                    s(p.get("videoId") or p.get("video")),
        "view_360":                    s(p.get("view360") or p.get("virtualTourUrl")),
        "plot_size":                   s(p.get("plotSize") or get(p.get("plotArea") or {}, "size")),
        "images_count":                images_count,
        "zone_name":                   s(p.get("zoneName")),
        "agent_license_no":            s(agent_info.get("licenseNo") or agent_info.get("license")),
        "payment_methods":             payment_methods,
        "price_value":                 price_value,
        "price_currency":              price_currency,
        "price_period":                price_period,
        "price_is_hidden":             b(price_hidden),
        "price_per_area_price":        ppa_price,
        "price_per_area_unit":         ppa_unit,
        "price_per_area_plot":         ppa_plot,
        "mortgage_cashback":           s(p.get("mortgageCashback")),
        "size_value":                  size_value,
        "size_unit":                   size_unit,
        "location_id":                 s(area_node.get("id") or loc_old.get("id")),
        "location_full_name":          loc_full,
        "latitude":                    latitude,
        "longitude":                   longitude,
        "location_slug":               s(area_node.get("slug") or loc_old.get("slug")),
        "location_type":               s(area_node.get("type") or loc_old.get("type")),
        "location_name":               location_name,
        "location_path_name":          s(loc_old.get("pathName") or loc_old.get("path")),
        "region_id":                   region_id,
        "region_name":                 region_name,
        "region_slug":                 region_slug,
        "area_id":                     area_id,
        "area_name":                   area_name,
        "area_slug":                   area_slug,
        "agent_id":                    s(agent_info.get("id")),
        "agent_image":                 s(agent_info.get("image") or agent_info.get("photo")),
        "agent_is_super_agent":        b(agent_info.get("is_super_agent") or agent_info.get("isSuperAgent")),
        "agent_name":                  s(agent_info.get("name") or p.get("agent") or p.get("contactName")),
        "agent_email":                 s(agent_info.get("email") or p.get("agentEmail")),
        "agent_slug":                  s(agent_info.get("slug")),
        "agent_whatsapp_response_time":s(agent_info.get("whatsappResponseTime")),
        "agent_total_properties":      s(agent_info.get("totalProperties")),
        "agent_position":              s(agent_info.get("position")),
        "agent_years_experience":      s(agent_info.get("yearsExperience") or agent_info.get("experience")),
        "agent_transactions_count":    s(agent_info.get("transactionsCount") or agent_info.get("transactions")),
        "agent_languages":             agent_langs_str,
        "contact_phone":               contact_phone,
        "contact_whatsapp":            contact_whatsapp,
        "contact_email":               contact_email,
        "broker_id":                   s(broker_info.get("id")),
        "broker_name":                 s(broker_info.get("name") or p.get("broker")),
        "broker_address":              s(broker_info.get("address")),
        "broker_email":                s(broker_info.get("email")),
        "broker_phone":                s(broker_info.get("phone")),
        "broker_slug":                 s(broker_info.get("slug")),
        "broker_total_properties":     s(broker_info.get("totalProperties")),
        "broker_license_number":       s(broker_info.get("licenseNumber") or broker_info.get("license")),
        "broker_is_exclusive":         b(p.get("isExclusive")),
        "broker_total_agents":         s(broker_info.get("totalAgents")),
        "broker_total_super_agents":   s(broker_info.get("totalSuperAgents")),
        "rera_number":                 s(p.get("rera") or p.get("reraNumber") or p.get("permitNumber")),
        "rera_authority_name":         s(p.get("reraAuthorityName")),
        "rera_permit_url":             s(p.get("reraPermitUrl") or p.get("dldPermit")),
        "is_verified":                 b(p.get("isVerified") or p.get("verified")),
        "is_direct_from_developer":    b(p.get("isDirectFromDeveloper")),
        "is_new_construction":         b(p.get("isNewConstruction")),
        "is_available":                b(p.get("isAvailable")),
        "is_featured":                 b(p.get("isFeatured") or p.get("featured")),
        "is_premium":                  b(p.get("isPremium") or p.get("premium")),
        "is_new_insert":               b(p.get("isNewInsert")),
        "is_community_expert":         b(p.get("isCommunityExpert")),
        "is_cts":                      b(p.get("isCts")),
        "is_exclusive":                b(p.get("isExclusive")),
        "is_broker_project_property":  b(p.get("isBrokerProjectProperty")),
        "is_smart_ad":                 b(p.get("isSmartAd") or p.get("listingLevelLabel") == "smart_ad"),
        "is_spotlight_listing":        b(p.get("isSpotlightListing")),
        "is_claimed_by_agent":         b(p.get("isClaimedByAgent")),
        "is_under_offer_by_competitor":b(p.get("isUnderOfferByCompetitor")),
        "is_pf_exclusive":             b(p.get("isPfExclusive")),
        "is_fhm":                      b(p.get("isFhm")),
        "is_great_value":              b(p.get("isGreatValue")),
        "is_high_demand":              b(p.get("isHighDemand")),
        "is_luxe":                     b(p.get("isLuxe")),
        "listing_level":               s(p.get("listingLevel")),
        "listing_level_label":         s(p.get("listingLevelLabel")),
        "lead_value":                  s(p.get("leadValue")),
        "qs":                          s(p.get("qs")),
        "amenity_codes":               amenity_codes,
        "amenity_names":               amenity_names,
        "image_url_first":             image_url_first,
        "has_price_trends":            b(p.get("hasPriceTrends")),
        "scraped_at":                  scraped_at,
        "detail_scraped_at":           "",
    }


def write_csv(rows: list, path: str):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            scraped_at = json.load(f).get("scraped_at", datetime.now(timezone.utc).isoformat())
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()

    print(f"Cleaning snapshot: {scraped_at}\n")

    all_rows = []

    for (cat_name, cat_id, cat_label, _) in CATEGORIES:
        raw_path = os.path.join(RAW_DIR, f"{cat_name}.json")
        if not os.path.exists(raw_path):
            print(f"  [SKIP] {cat_name} — raw file not found")
            continue

        with open(raw_path, encoding="utf-8") as f:
            records = json.load(f)

        rows = [flatten_listing(r, cat_id, cat_label, scraped_at) for r in records]
        out_path = os.path.join(OUT_DIR, f"{cat_name}.csv")
        write_csv(rows, out_path)
        print(f"  {cat_name}: {len(rows)} rows -> {out_path}")
        all_rows.extend(rows)

    combined_path = os.path.join(OUT_DIR, "all_listings.csv")
    write_csv(all_rows, combined_path)
    print(f"\nTotal: {len(all_rows)} listings -> {combined_path}")


if __name__ == "__main__":
    main()
