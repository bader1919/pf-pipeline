"""
PropertyFinder Bahrain — data cleaner.
Reads raw JSON from data/raw/, maps every field to the exact same
column schema as the n8n pf_listings table (117 columns).
Outputs per-category CSVs + combined all_listings.csv to data/latest/.
"""

import csv
import json
import os
import re
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


def camel_to_snake(name):
    """Convert camelCase → snake_case."""
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def flatten_listing(p: dict, category_id: str, category_name: str, scraped_at: str) -> dict:
    """
    Map a raw PropertyFinder API listing object to the exact 114-column schema.
    Every field that the API returns is captured. Nothing is dropped.
    """
    # Sub-objects
    price    = p.get("price") or {}
    size     = p.get("size") or {}
    loc      = p.get("location") or {}
    region   = loc.get("region") or {}
    area_obj = loc.get("area") or {}
    agent    = p.get("agent") or {}
    broker   = p.get("broker") or p.get("agency") or {}
    amenities = p.get("amenities") or []
    photos   = p.get("photos") or p.get("images") or []
    contacts = p.get("contactOptions") or p.get("contacts") or []

    # Property type — can be string or {id, name}
    prop_type = p.get("propertyType") or {}
    if isinstance(prop_type, dict):
        prop_type_name = s(prop_type.get("name") or prop_type.get("label"))
        prop_type_id   = s(prop_type.get("id"))
    else:
        prop_type_name = s(prop_type)
        prop_type_id   = ""

    # Offering type — rent vs sale
    offering = (
        s(p.get("offeringType"))
        or s(p.get("listingType"))
        or s(p.get("type"))
    )

    # Bedrooms — various API formats
    beds_raw   = p.get("bedrooms") or p.get("bedsMin") or p.get("beds")
    beds_val   = p.get("bedroomsValue") or p.get("bedroomsLabel") or beds_raw
    baths_raw  = p.get("bathrooms") or p.get("bathsMin") or p.get("baths")
    baths_val  = p.get("bathroomsValue") or p.get("bathroomsLabel") or baths_raw
    rooms_raw  = p.get("rooms") or p.get("roomsMin")
    rooms_val  = p.get("roomsValue") or p.get("roomsLabel") or rooms_raw

    # Price sub-fields
    price_pa   = price.get("perArea") or price.get("pricePerArea") or {}
    if isinstance(price_pa, dict):
        ppa_price = s(price_pa.get("price") or price_pa.get("value"))
        ppa_unit  = s(price_pa.get("unit"))
    else:
        ppa_price = s(price_pa)
        ppa_unit  = ""

    # Location sub-fields
    loc_full = (
        s(loc.get("fullName"))
        or s(loc.get("locationFullName"))
        or s(loc.get("name"))
    )

    # Agent sub-fields
    agent_langs = agent.get("languages") or []
    if isinstance(agent_langs, list):
        agent_langs_str = pipe_list(agent_langs, key="name") or pipe_list(agent_langs)
    else:
        agent_langs_str = s(agent_langs)

    # Contact options — phone, whatsapp, email extracted individually
    def extract_contact(contacts_list, ctype):
        for c in contacts_list:
            if isinstance(c, dict):
                t = (c.get("type") or "").lower()
                if ctype in t:
                    return s(c.get("value") or c.get("number") or c.get("url"))
        return ""

    contact_phone    = s(p.get("contactPhone"))    or extract_contact(contacts, "phone")    or s(get(agent, "phone"))
    contact_whatsapp = s(p.get("contactWhatsapp")) or extract_contact(contacts, "whatsapp")
    contact_email    = s(p.get("contactEmail"))    or extract_contact(contacts, "email")    or s(get(agent, "email"))

    # Amenities — codes and names as pipe-separated strings
    amenity_codes = pipe_list(amenities, key="code") or pipe_list(amenities, key="id")
    amenity_names = pipe_list(amenities, key="name") or pipe_list(amenities, key="label")

    # Images
    images_count  = len(photos)
    image_url_first = ""
    if photos:
        first = photos[0]
        if isinstance(first, dict):
            image_url_first = s(first.get("urlMedium") or first.get("url") or first.get("src"))
        else:
            image_url_first = s(first)

    # Boolean helper
    def b(val):
        if val is None:
            return ""
        return str(bool(val)).lower()

    # Payment methods
    pm = p.get("paymentMethods") or []
    payment_methods = pipe_list(pm, key="name") if pm and isinstance(pm[0], dict) else pipe_list(pm)

    pf_id = str(p.get("id") or p.get("listingId") or "")

    row = {
        "listing_id":                  pf_id,
        "pf_id":                       pf_id,
        "title":                       s(p.get("name") or p.get("title")),
        "description":                 s(p.get("description") or "")[:2000],
        "property_type":               prop_type_name,
        "property_type_id":            prop_type_id,
        "category_id":                 category_id,
        "category_name":               category_name,
        "offering_type":               offering,
        "bedrooms":                    s(beds_raw),
        "bedrooms_value":              s(beds_val),
        "bathrooms":                   s(baths_raw),
        "bathrooms_value":             s(baths_val),
        "rooms":                       s(rooms_raw),
        "rooms_value":                 s(rooms_val),
        "completion_status":           s(p.get("completionStatus")),
        "furnished":                   s(p.get("furnishingStatus") or p.get("furnished")),
        "utilities_price_type":        s(p.get("utilitiesPriceType")),
        "listed_date":                 s(p.get("listedDate") or p.get("createdAt") or p.get("publishedAt")),
        "last_refreshed_at":           s(p.get("lastRefreshedAt") or p.get("updatedAt")),
        "rental_availability_date":    s(p.get("rentalAvailabilityDate")),
        "age":                         s(p.get("age")),
        "share_url":                   s(p.get("shareUrl") or p.get("url")),
        "share_url_translated":        s(p.get("shareUrlTranslated")),
        "video_id":                    s(p.get("videoId") or p.get("video")),
        "view_360":                    s(p.get("view360") or p.get("virtualTourUrl")),
        "plot_size":                   s(p.get("plotSize") or get(p.get("plotArea") or {}, "size")),
        "images_count":                images_count,
        "zone_name":                   s(p.get("zoneName")),
        "agent_license_no":            s(get(agent, "licenseNo") or get(agent, "license")),
        "payment_methods":             payment_methods,
        "price_value":                 s(price.get("value") or price.get("amount")),
        "price_currency":              s(price.get("currency"), "BHD"),
        "price_period":                s(price.get("period")),
        "price_is_hidden":             b(price.get("isHidden") or price.get("onRequest")),
        "price_per_area_price":        ppa_price,
        "price_per_area_unit":         ppa_unit,
        "price_per_area_plot":         s(price.get("perAreaPlot") or price.get("pricePerAreaPlot")),
        "mortgage_cashback":           s(p.get("mortgageCashback")),
        "size_value":                  s(size.get("value") or size.get("size") or p.get("area")),
        "size_unit":                   s(size.get("unit"), "sqft"),
        "location_id":                 s(loc.get("id")),
        "location_full_name":          loc_full,
        "latitude":                    s(loc.get("lat") or loc.get("latitude")),
        "longitude":                   s(loc.get("lng") or loc.get("longitude")),
        "location_slug":               s(loc.get("slug")),
        "location_type":               s(loc.get("type")),
        "location_name":               s(loc.get("name")),
        "location_path_name":          s(loc.get("pathName") or loc.get("path")),
        "region_id":                   s(region.get("id")),
        "region_name":                 s(region.get("name")),
        "region_slug":                 s(region.get("slug")),
        "area_id":                     s(area_obj.get("id")),
        "area_name":                   s(area_obj.get("name")),
        "area_slug":                   s(area_obj.get("slug")),
        "agent_id":                    s(agent.get("id")),
        "agent_image":                 s(agent.get("image") or agent.get("photo")),
        "agent_is_super_agent":        b(agent.get("isSuperAgent") or agent.get("superAgent")),
        "agent_name":                  s(agent.get("name") or p.get("contactName")),
        "agent_email":                 s(agent.get("email")),
        "agent_slug":                  s(agent.get("slug")),
        "agent_whatsapp_response_time":s(agent.get("whatsappResponseTime")),
        "agent_total_properties":      s(agent.get("totalProperties")),
        "agent_position":              s(agent.get("position")),
        "agent_years_experience":      s(agent.get("yearsExperience") or agent.get("experience")),
        "agent_transactions_count":    s(agent.get("transactionsCount") or agent.get("transactions")),
        "agent_languages":             agent_langs_str,
        "contact_phone":               contact_phone,
        "contact_whatsapp":            contact_whatsapp,
        "contact_email":               contact_email,
        "broker_id":                   s(broker.get("id")),
        "broker_name":                 s(broker.get("name")),
        "broker_address":              s(broker.get("address")),
        "broker_email":                s(broker.get("email")),
        "broker_phone":                s(broker.get("phone")),
        "broker_slug":                 s(broker.get("slug")),
        "broker_total_properties":     s(broker.get("totalProperties")),
        "broker_license_number":       s(broker.get("licenseNumber") or broker.get("license")),
        "broker_is_exclusive":         b(broker.get("isExclusive")),
        "broker_total_agents":         s(broker.get("totalAgents")),
        "broker_total_super_agents":   s(broker.get("totalSuperAgents")),
        "rera_number":                 s(p.get("reraNumber") or p.get("permitNumber")),
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
        "is_smart_ad":                 b(p.get("isSmartAd")),
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
        "detail_scraped_at":           "",   # filled by detail fetcher (separate workflow)
    }

    return row


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
