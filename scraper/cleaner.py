"""
PropertyFinder Bahrain -- data cleaner.
Reads raw JSON from data/raw/, maps every field to the exact same
column schema as the n8n pf_listings table (117 columns).
Outputs per-category CSVs + combined all_listings.csv to data/latest/.

Handles 6 category types:
  - residential_rent / residential_sale / commercial_rent / commercial_sale:
    standard listings with nested 'property' sub-object
  - new_projects: project objects (different structure, mapped to project CSV)
  - agents: skipped if records are not dicts (raw key names from API)
"""

import csv
import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR  = os.path.join(BASE_DIR, "data", "raw")
OUT_DIR  = os.path.join(BASE_DIR, "data", "latest")

# Listing categories that use the standard 114-column schema
LISTING_CATEGORIES = {"residential_rent", "residential_sale", "commercial_rent", "commercial_sale"}

def discover_categories() -> list:
    """
    Read whatever JSON files the scraper saved -- no hardcoding.
    Returns list of category name strings.
    """
    if not os.path.exists(RAW_DIR):
        return []
    return [
        f[:-5]  # strip .json
        for f in os.listdir(RAW_DIR)
        if f.endswith(".json") and f != "manifest.json"
    ]

# Exact column order -- matches n8n pf_listings table (minus n8n-internal id/createdAt/updatedAt)
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
    "community", "sub_community",
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

# Column schema for new_projects (different structure from listings)
PROJECT_COLUMNS = [
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
    "community", "sub_community",
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
    # Project-specific extra columns (appended after the standard schema)
    "developer_id", "developer_name", "developer_logo_url",
    "construction_phase", "delivery_date", "down_payment_percentage",
    "hotness_level", "starting_price", "min_resale_price",
    "stock_availability", "payment_plans", "property_types_list",
    "price_range_min", "price_range_max", "sales_phase", "weight_ranking",
]


def s(val, default=""):
    """Safe string -- return empty string for None/NaN."""
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
    Every field that the API returns is captured. Nothing is dropped.

    Real API shape (confirmed from raw data):
      - price: flat int (not a dict)
      - priceCurrency, priceDuration: separate top-level fields
      - size: flat int; sizeUnit: separate field
      - coordinates: top-level dict with latitude/longitude keys
      - agent: string (display name); agentInfo: dict with id/name/email/etc.
      - broker: string (display name); brokerInfo: dict with id/name/phone/etc.
      - addedOn: listed date (not listedDate)
      - agentPhone/agentWhatsapp/agentEmail: top-level contact fields
      - amenities: list of short code strings; features: list of human-readable strings
      - locationTree: list of {id, name, type} dicts for region/area hierarchy
    """
    # Boolean helper
    def b(val):
        if val is None:
            return ""
        return str(bool(val)).lower()

    # --- Price ---
    # Real API: price is a flat int; priceCurrency and priceDuration are separate
    price_raw = p.get("price") or p.get("propertyValue")
    if isinstance(price_raw, dict):
        # Old nested format fallback
        price_value    = s(price_raw.get("value") or price_raw.get("amount"))
        price_currency = s(price_raw.get("currency"), "BHD")
        price_period   = s(price_raw.get("period"))
        price_is_hidden= b(price_raw.get("isHidden") or price_raw.get("onRequest"))
        ppa_price      = s((price_raw.get("perArea") or {}).get("price"))
        ppa_unit       = s((price_raw.get("perArea") or {}).get("unit"))
        ppa_plot       = s(price_raw.get("perAreaPlot"))
    else:
        price_value    = s(price_raw)
        price_currency = s(p.get("priceCurrency"), "BHD")
        price_period   = s(p.get("priceDuration"))
        price_is_hidden= ""
        ppa_price      = ""
        ppa_unit       = ""
        ppa_plot       = ""

    # --- Size ---
    # Real API: size is a flat int; sizeUnit is separate
    size_raw = p.get("size") or p.get("area")
    if isinstance(size_raw, dict):
        size_value = s(size_raw.get("value") or size_raw.get("size"))
        size_unit  = s(size_raw.get("unit"), "sqm")
    else:
        size_value = s(size_raw)
        size_unit  = s(p.get("sizeUnit") or p.get("sizeMin", "").split(" ")[-1] if p.get("sizeMin") else "", "sqm")

    # --- Coordinates ---
    # Real API: top-level coordinates dict with latitude/longitude keys
    coords = p.get("coordinates") or {}
    if coords:
        lat = s(coords.get("latitude") or coords.get("lat"))
        lon = s(coords.get("longitude") or coords.get("lng") or coords.get("lon"))
    else:
        loc = p.get("location") or {}
        loc_coords = loc.get("coordinates") or {}
        lat = s(loc_coords.get("lat") or loc_coords.get("latitude") or loc.get("lat") or loc.get("latitude"))
        lon = s(loc_coords.get("lon") or loc_coords.get("lng") or loc_coords.get("longitude") or loc.get("lng") or loc.get("longitude"))

    # --- Location ---
    # Real API: displayAddress at top level; locationTree list for region/area hierarchy
    loc = p.get("location") or {}
    loc_full = (
        s(p.get("displayAddress"))
        or s(loc.get("fullName"))
        or s(loc.get("locationFullName"))
        or s(loc.get("name"))
    )

    region_id = region_name = region_slug = ""
    area_id = area_name = area_slug = ""
    community = sub_community = ""

    # PF uses two parallel location hierarchies:
    #   Standard:  REGION → AREA (→ AREA sub-area)
    #   Community: REGION → COMMUNITY (level 1) → COMMUNITY (level 2)
    # We map level-1 COMMUNITY as area when no AREA node exists,
    # and always capture COMMUNITY names in community/sub_community columns.
    loc_tree = p.get("locationTree") or []
    community_nodes = []
    for node in loc_tree:
        ntype = (node.get("type") or "").upper()
        level = str(node.get("level", ""))
        if ntype == "REGION":
            region_id   = s(node.get("id"))
            region_name = s(node.get("name"))
            region_slug = s(node.get("slug") or node.get("slug_en"))
        elif ntype == "AREA":
            area_id   = s(node.get("id"))
            area_name = s(node.get("name"))
            area_slug = s(node.get("slug") or node.get("slug_en"))
        elif ntype == "COMMUNITY":
            community_nodes.append(node)

    # Map COMMUNITY nodes → community / sub_community columns
    if community_nodes:
        community     = s(community_nodes[0].get("name"))
        sub_community = s(community_nodes[1].get("name")) if len(community_nodes) > 1 else ""
        # If no AREA node, treat the first COMMUNITY level as the area equivalent
        if not area_name:
            area_id   = s(community_nodes[0].get("id"))
            area_name = community
            area_slug = s(community_nodes[0].get("slug") or community_nodes[0].get("slug_en"))

    # Fallbacks from old nested location structure (pre-flat API)
    if not region_name:
        r = loc.get("region") or {}
        if isinstance(r, dict):
            region_id, region_name, region_slug = s(r.get("id")), s(r.get("name")), s(r.get("slug"))
    if not area_name:
        a = loc.get("area") or {}
        if isinstance(a, dict):
            area_id, area_name, area_slug = s(a.get("id")), s(a.get("name")), s(a.get("slug"))
    if not community:
        community = s(p.get("community") or p.get("communityName"))

    # --- Agent ---
    # Real API: agent = string display name; agentInfo = dict with full details
    agent_info = p.get("agentInfo") or {}
    if not isinstance(agent_info, dict):
        agent_info = {}
    agent_str = p.get("agent") or ""   # string display name (fallback if agentInfo absent)

    agent_langs_raw = agent_info.get("languages") or []
    if isinstance(agent_langs_raw, list):
        agent_langs_str = pipe_list(agent_langs_raw, key="name") or pipe_list(agent_langs_raw)
    else:
        agent_langs_str = s(agent_langs_raw)

    # --- Broker ---
    # Real API: broker = string display name; brokerInfo = dict with full details
    broker_info = p.get("brokerInfo") or p.get("clientInfo") or {}
    if not isinstance(broker_info, dict):
        broker_info = {}
    # Fallback: old nested broker/agency dict
    if not broker_info:
        broker_info = p.get("broker") if isinstance(p.get("broker"), dict) else {}
        if not broker_info:
            broker_info = p.get("agency") if isinstance(p.get("agency"), dict) else {}

    # --- Contact ---
    contact_phone    = s(p.get("agentPhone") or p.get("contactPhone") or agent_info.get("phone"))
    contact_whatsapp = s(p.get("agentWhatsapp") or p.get("contactWhatsapp"))
    contact_email    = s(p.get("agentEmail") or p.get("contactEmail") or agent_info.get("email"))

    # --- Property type ---
    prop_type = p.get("propertyType") or {}
    if isinstance(prop_type, dict):
        prop_type_name = s(prop_type.get("name") or prop_type.get("label"))
        prop_type_id   = s(prop_type.get("id"))
    else:
        prop_type_name = s(prop_type)
        prop_type_id   = s(p.get("propertyTypeId"))

    # --- Offering type ---
    offering = (
        s(p.get("offeringType"))
        or s(p.get("priceDuration"))
        or s(p.get("listingType"))
        or s(p.get("type"))
    )

    # --- Bedrooms / Bathrooms ---
    beds_raw  = p.get("bedrooms") or p.get("bedsMin") or p.get("beds")
    beds_val  = p.get("bedroomsValue") or p.get("bedroomsLabel") or beds_raw
    baths_raw = p.get("bathrooms") or p.get("bathsMin") or p.get("baths")
    baths_val = p.get("bathroomsValue") or p.get("bathroomsLabel") or baths_raw
    rooms_raw = p.get("rooms") or p.get("roomsMin")
    rooms_val = p.get("roomsValue") or p.get("roomsLabel") or rooms_raw

    # --- Amenities ---
    # Real API: amenities = list of short code strings e.g. ["CP","LB"]
    #           features  = list of human-readable strings e.g. ["Covered Parking"]
    amenities = p.get("amenities") or []
    features  = p.get("features") or []
    if amenities and isinstance(amenities[0], dict):
        amenity_codes = pipe_list(amenities, key="code") or pipe_list(amenities, key="id")
        amenity_names = pipe_list(amenities, key="name") or pipe_list(amenities, key="label")
    else:
        amenity_codes = pipe_list(amenities)
        amenity_names = pipe_list(features) if features else pipe_list(amenities)

    # --- Images ---
    photos = p.get("photos") or p.get("images") or []
    images_count = len(photos)
    image_url_first = ""
    if photos:
        first = photos[0]
        if isinstance(first, dict):
            image_url_first = s(first.get("urlMedium") or first.get("url") or first.get("src"))
        else:
            image_url_first = s(first)

    # --- Payment methods ---
    pm = p.get("paymentMethods") or p.get("paymentMethod") or []
    payment_methods = pipe_list(pm, key="name") if (pm and isinstance(pm[0], dict)) else pipe_list(pm)

    # --- Listed date ---
    listed_date = s(
        p.get("addedOn")
        or p.get("listedDate")
        or p.get("createdAt")
        or p.get("publishedAt")
    )

    # --- Listing ID ---
    if p.get("listing_type") == "property" and isinstance(p.get("property"), dict):
        pf_id = str(p.get("property", {}).get("id") or "")
    else:
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
        "furnished":                   s(p.get("furnishingStatus") or p.get("furnished") or p.get("furnishing")),
        "utilities_price_type":        s(p.get("utilitiesPriceType")),
        "listed_date":                 listed_date,
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
        "agent_license_no":            s(agent_info.get("licenseNo") or agent_info.get("license")),
        "payment_methods":             payment_methods,
        "price_value":                 price_value,
        "price_currency":              price_currency,
        "price_period":                price_period,
        "price_is_hidden":             price_is_hidden,
        "price_per_area_price":        ppa_price,
        "price_per_area_unit":         ppa_unit,
        "price_per_area_plot":         ppa_plot,
        "mortgage_cashback":           s(p.get("mortgageCashback")),
        "size_value":                  size_value,
        "size_unit":                   size_unit,
        "location_id":                 s(loc.get("id")),
        "location_full_name":          loc_full,
        "latitude":                    lat,
        "longitude":                   lon,
        "location_slug":               s(loc.get("slug")),
        "location_type":               s(loc.get("type")),
        "location_name":               s(loc.get("name") or area_name),
        "location_path_name":          s(loc.get("pathName") or loc.get("path") or loc_full),
        "region_id":                   region_id,
        "region_name":                 region_name,
        "region_slug":                 region_slug,
        "area_id":                     area_id,
        "area_name":                   area_name,
        "area_slug":                   area_slug,
        "community":                   community,
        "sub_community":               sub_community,
        "agent_id":                    s(agent_info.get("id")),
        "agent_image":                 s(agent_info.get("image") or agent_info.get("photo")),
        "agent_is_super_agent":        b(agent_info.get("is_super_agent") or agent_info.get("isSuperAgent")),
        "agent_name":                  s(agent_info.get("name") or agent_str or p.get("contactName")),
        "agent_email":                 s(agent_info.get("email") or contact_email),
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
        "broker_name":                 s(broker_info.get("name")),
        "broker_address":              s(broker_info.get("address")),
        "broker_email":                s(broker_info.get("email")),
        "broker_phone":                s(broker_info.get("phone")),
        "broker_slug":                 s(broker_info.get("slug")),
        "broker_total_properties":     s(broker_info.get("totalProperties")),
        "broker_license_number":       s(broker_info.get("licenseNumber") or broker_info.get("license")),
        "broker_is_exclusive":         b(broker_info.get("isExclusive")),
        "broker_total_agents":         s(broker_info.get("totalAgents")),
        "broker_total_super_agents":   s(broker_info.get("totalSuperAgents")),
        "rera_number":                 s(p.get("reraNumber") or p.get("rera") or p.get("permitNumber")),
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
        "is_smart_ad":                 b(p.get("isSmartAd") or (p.get("listingLevelLabel") == "smart_ad")),
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


def flatten_project(proj: dict, scraped_at: str) -> dict:
    """
    Map a raw PropertyFinder API new_project object to the project column schema.
    Projects have a fundamentally different structure from listings (developer,
    paymentPlans, startingPrice, etc.) but are mapped into the same column layout
    where possible, with extra project-specific columns appended.
    """
    # Location -- nested as {id, fullName, coordinates: {lat, lon}}
    loc = proj.get("location") or {}
    coords = loc.get("coordinates") or {}

    # Parse fullName: "Governorate, Area, Community"
    loc_parts = [p.strip() for p in (loc.get("fullName") or "").split(",")]
    region_name = loc_parts[0] if len(loc_parts) >= 1 else ""
    area_name   = loc_parts[1] if len(loc_parts) >= 2 else ""
    locality    = loc_parts[2] if len(loc_parts) >= 3 else ""

    # Developer
    developer = proj.get("developer") or {}

    # Amenities -- list of {id, name}
    amenities = proj.get("amenities") or []
    amenity_codes = pipe_list(amenities, key="id")
    amenity_names = pipe_list(amenities, key="name")

    # Images -- list of URL strings
    images = proj.get("images") or []
    images_count = len(images)
    image_url_first = s(images[0]) if images else ""

    # Bedrooms -- list of strings like ["1", "2", "3"]
    bedrooms_list = proj.get("bedrooms") or []
    bedrooms_str = "|".join(str(b) for b in bedrooms_list) if bedrooms_list else ""

    # Property types -- list of strings like ["apartment", "villa"]
    prop_types_list = proj.get("propertyTypes") or []
    prop_types_str = "|".join(str(t) for t in prop_types_list) if prop_types_list else ""

    # Payment plans -- list of strings like ["10/90", "10/40/50"]
    payment_plans_list = proj.get("paymentPlans") or []
    payment_plans_str = "|".join(str(p) for p in payment_plans_list) if payment_plans_list else ""

    # Price range
    price_range = proj.get("priceRange") or {}

    # Completion status from construction phase
    completion = s(proj.get("constructionPhase"))

    # Boolean helper
    def b(val):
        if val is None:
            return ""
        return str(bool(val)).lower()

    pf_id = str(proj.get("id") or "")

    row = {
        # Standard columns (mapped from project data)
        "listing_id":                  pf_id,
        "pf_id":                       pf_id,
        "title":                       s(proj.get("title")),
        "description":                 "",
        "property_type":               prop_types_str,
        "property_type_id":            "",
        "category_id":                 "new_projects",
        "category_name":               "New Projects",
        "offering_type":               "sale",
        "bedrooms":                    bedrooms_str,
        "bedrooms_value":              bedrooms_str,
        "bathrooms":                   "",
        "bathrooms_value":             "",
        "rooms":                       "",
        "rooms_value":                 "",
        "completion_status":           completion,
        "furnished":                   "",
        "utilities_price_type":        "",
        "listed_date":                 "",
        "last_refreshed_at":           s(proj.get("deliveryDate")),
        "rental_availability_date":    "",
        "age":                         "",
        "share_url":                   s(proj.get("shareUrl")),
        "share_url_translated":        "",
        "video_id":                    "",
        "view_360":                    "",
        "plot_size":                   "",
        "images_count":                images_count,
        "zone_name":                   "",
        "agent_license_no":            "",
        "payment_methods":             payment_plans_str,
        "price_value":                 s(proj.get("startingPrice")),
        "price_currency":              "BHD",
        "price_period":                "",
        "price_is_hidden":             b(proj.get("startingPrice") is None or proj.get("startingPrice") == 0),
        "price_per_area_price":        "",
        "price_per_area_unit":         "",
        "price_per_area_plot":         "",
        "mortgage_cashback":           "",
        "size_value":                  "",
        "size_unit":                   "",
        "location_id":                 s(loc.get("id")),
        "location_full_name":          s(loc.get("fullName")),
        "latitude":                    s(coords.get("lat")),
        "longitude":                   s(coords.get("lng") or coords.get("lon")),
        "location_slug":               "",
        "location_type":               "",
        "location_name":               locality or area_name,
        "location_path_name":          s(loc.get("fullName")),
        "region_id":                   "",
        "region_name":                 region_name,
        "region_slug":                 "",
        "area_id":                     "",
        "area_name":                   area_name,
        "area_slug":                   "",
        "agent_id":                    "",
        "agent_image":                 s(developer.get("logoUrl")),
        "agent_is_super_agent":        "",
        "agent_name":                  s(developer.get("name")),
        "agent_email":                 "",
        "agent_slug":                  "",
        "agent_whatsapp_response_time":"",
        "agent_total_properties":      "",
        "agent_position":              "",
        "agent_years_experience":      "",
        "agent_transactions_count":    "",
        "agent_languages":             "",
        "contact_phone":               "",
        "contact_whatsapp":            "",
        "contact_email":               "",
        "broker_id":                   s(developer.get("id")),
        "broker_name":                 s(developer.get("name")),
        "broker_address":              "",
        "broker_email":                "",
        "broker_phone":                "",
        "broker_slug":                 "",
        "broker_total_properties":     "",
        "broker_license_number":       "",
        "broker_is_exclusive":         "",
        "broker_total_agents":         "",
        "broker_total_super_agents":   "",
        "rera_number":                 "",
        "rera_authority_name":         "",
        "rera_permit_url":             "",
        "is_verified":                 "",
        "is_direct_from_developer":    "true",
        "is_new_construction":         b(completion in ("under_construction", "not_started")),
        "is_available":                b(proj.get("stockAvailability") != "sold_out"),
        "is_featured":                 "",
        "is_premium":                  "",
        "is_new_insert":               "",
        "is_community_expert":         "",
        "is_cts":                      "",
        "is_exclusive":                "",
        "is_broker_project_property":  "",
        "is_smart_ad":                 "",
        "is_spotlight_listing":        "",
        "is_claimed_by_agent":         "",
        "is_under_offer_by_competitor":"",
        "is_pf_exclusive":             "",
        "is_fhm":                      "",
        "is_great_value":              "",
        "is_high_demand":              "",
        "is_luxe":                     "",
        "listing_level":               "",
        "listing_level_label":         "",
        "lead_value":                  "",
        "qs":                          s(proj.get("hotnessLevel")),
        "amenity_codes":               amenity_codes,
        "amenity_names":               amenity_names,
        "image_url_first":             image_url_first,
        "has_price_trends":            "",
        "scraped_at":                  scraped_at,
        "detail_scraped_at":           "",
        # Project-specific extra columns
        "developer_id":                s(developer.get("id")),
        "developer_name":              s(developer.get("name")),
        "developer_logo_url":          s(developer.get("logoUrl")),
        "construction_phase":          completion,
        "delivery_date":               s(proj.get("deliveryDate")),
        "down_payment_percentage":     s(proj.get("downPaymentPercentage")),
        "hotness_level":               s(proj.get("hotnessLevel")),
        "starting_price":              s(proj.get("startingPrice")),
        "min_resale_price":            s(proj.get("minResalePrice")),
        "stock_availability":          s(proj.get("stockAvailability")),
        "payment_plans":               payment_plans_str,
        "property_types_list":         prop_types_str,
        "price_range_min":             s(price_range.get("min")),
        "price_range_max":             s(price_range.get("max")),
        "sales_phase":                 s(proj.get("salesPhase")),
        "weight_ranking":              s(proj.get("weightRanking")),
    }

    return row


def write_csv(rows: list, path: str, columns: list = None):
    if not rows:
        return
    cols = columns or COLUMNS
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def is_valid_listing_record(rec) -> bool:
    """Check if a record is a valid listing dict (not a string, not None)."""
    return isinstance(rec, dict)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            scraped_at = json.load(f).get("scraped_at", datetime.now(timezone.utc).isoformat())
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()

    categories = discover_categories()
    print(f"Categories found in raw/: {categories}\n")
    print(f"Cleaning snapshot: {scraped_at}\n")

    all_rows = []

    for cat_name in categories:
        raw_path = os.path.join(RAW_DIR, f"{cat_name}.json")

        with open(raw_path, encoding="utf-8") as f:
            records = json.load(f)

        if not records:
            print(f"  {cat_name}: 0 records (empty file) -- skipped")
            continue

        # --- Handle non-listing categories ---
        if cat_name == "agents":
            # Agents may be strings (API key names) or dicts -- filter to dicts only
            valid_records = [r for r in records if isinstance(r, dict)]
            if not valid_records:
                print(f"  {cat_name}: {len(records)} records, but none are dicts -- skipped (non-listing category)")
                continue
            print(f"  WARNING: {cat_name}: {len(valid_records)} valid dict records out of {len(records)} total. "
                  f"Agent records are not listings -- writing minimal CSV.")
            rows = []
            for r in valid_records:
                pf_id = str(r.get("id") or "")
                row = {col: "" for col in COLUMNS}
                row["listing_id"] = pf_id
                row["pf_id"] = pf_id
                row["title"] = s(r.get("name") or "")
                row["category_id"] = "agents"
                row["category_name"] = "Agents"
                row["scraped_at"] = scraped_at
                rows.append(row)
            out_path = os.path.join(OUT_DIR, f"{cat_name}.csv")
            write_csv(rows, out_path)
            print(f"  {cat_name}: {len(rows)} rows -> {out_path}")
            # Do NOT add agent rows to all_listings -- they are not listings
            continue

        if cat_name == "new_projects":
            # Projects have a different structure -- use flatten_project
            valid_records = [r for r in records if isinstance(r, dict)]
            if not valid_records:
                print(f"  {cat_name}: {len(records)} records, but none are dicts -- skipped")
                continue
            rows = [flatten_project(proj, scraped_at) for proj in valid_records]
            out_path = os.path.join(OUT_DIR, f"{cat_name}.csv")
            write_csv(rows, out_path, columns=PROJECT_COLUMNS)
            print(f"  {cat_name}: {len(rows)} rows -> {out_path}")
            # Add to all_rows so they appear in all_listings.csv (standard columns only)
            all_rows.extend(rows)
            continue

        # --- Standard listing categories ---
        # Filter out non-dict records defensively
        valid_records = [r for r in records if isinstance(r, dict)]
        skipped = len(records) - len(valid_records)
        if skipped > 0:
            print(f"  WARNING: {cat_name}: skipped {skipped} non-dict records out of {len(records)}")

        if not valid_records:
            print(f"  {cat_name}: no valid dict records -- skipped")
            continue

        # Derive category_id and label from first record if available,
        # otherwise use the filename as label
        first = valid_records[0]
        cat_id    = str(first.get("categoryId") or first.get("category_id") or "")
        cat_label = str(first.get("categoryName") or first.get("category_name") or cat_name)

        rows = []
        for r in valid_records:
            # Extract nested property data for listings with listing_type == "property"
            if r.get("listing_type") == "property" and isinstance(r.get("property"), dict):
                property_data = r.get("property")
                # Preserve listing_type for downstream logic
                property_data["listing_type"] = r.get("listing_type")
                rows.append(flatten_listing(property_data, cat_id, cat_label, scraped_at))
            else:
                rows.append(flatten_listing(r, cat_id, cat_label, scraped_at))
        out_path = os.path.join(OUT_DIR, f"{cat_name}.csv")
        write_csv(rows, out_path)
        print(f"  {cat_name}: {len(rows)} rows -> {out_path}")
        all_rows.extend(rows)

    combined_path = os.path.join(OUT_DIR, "all_listings.csv")
    write_csv(all_rows, combined_path)
    print(f"\nTotal: {len(all_rows)} listings -> {combined_path}")


if __name__ == "__main__":
    main()
