"""
Regression test for the cleaner: run one REAL archived listing (live
__NEXT_DATA__ nested format) through flatten_listing and assert every
critical field comes out populated.

This exact test would have caught every cleaner bug this project has had
(empty columns June 2026; 0% listed_date/area_name/agent_id July 2026).

Run: pytest tests/
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
from cleaner import flatten_listing, COLUMNS  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "live_listing.json")

CRITICAL_FIELDS = [
    "listing_id", "pf_id", "title", "price_value", "price_currency",
    "latitude", "longitude", "region_name", "area_name",
    "property_type", "offering_type", "listed_date",
    "agent_id", "agent_name", "contact_phone", "share_url",
]


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        rec = json.load(f)
    return rec["property"]


def test_critical_fields_populated():
    row = flatten_listing(load_fixture(), "commercial_sale", "Commercial Sale",
                          "2026-06-09T20:00:00+00:00")
    empty = [c for c in CRITICAL_FIELDS if not str(row.get(c, "")).strip()]
    assert not empty, f"Critical fields came out EMPTY from a real listing: {empty}"


def test_row_matches_schema():
    row = flatten_listing(load_fixture(), "commercial_sale", "Commercial Sale",
                          "2026-06-09T20:00:00+00:00")
    missing = [c for c in COLUMNS if c not in row]
    assert not missing, f"flatten_listing missing schema columns: {missing}"


def test_boolean_false_not_dropped():
    """False must serialize as 'false', never as '' (the or-chain bug)."""
    p = load_fixture()
    p["is_verified"] = False
    row = flatten_listing(p, "commercial_sale", "Commercial Sale",
                          "2026-06-09T20:00:00+00:00")
    assert row["is_verified"] == "false", (
        f"is_verified=False became {row['is_verified']!r} -- boolean False is being dropped"
    )
