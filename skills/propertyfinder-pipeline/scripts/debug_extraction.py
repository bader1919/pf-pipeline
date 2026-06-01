#!/usr/bin/env python3
"""
PropertyFinder Pipeline - Debug Extraction Helper

Traces JSON structure to find the correct extraction path for nested fields.
Usage: python debug_extraction.py [category]
Example: python debug_extraction.py residential_rent
"""

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"


def trace_structure(obj, path="", max_depth=5, current_depth=0):
    """Recursively trace JSON structure and print paths."""
    if current_depth >= max_depth:
        return

    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key
            value_type = type(value).__name__

            print(f"{current_path} [{value_type}]")

            # Recurse into nested structures
            if isinstance(value, (dict, list)) and current_depth < max_depth:
                trace_structure(value, current_path, max_depth, current_depth + 1)

    elif isinstance(obj, list) and len(obj) > 0:
        # Trace first item of list
        current_path = f"{path}[0]" if path else "[0]"
        print(f"{current_path} [array with {len(obj)} items]")
        trace_structure(obj[0], current_path, max_depth, current_depth)


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_extraction.py <category>")
        print("Available categories:")
        for f in os.listdir(RAW_DIR):
            if f.endswith('.json') and f != 'manifest.json':
                print(f"  - {f[:-5]}")
        sys.exit(1)

    category = sys.argv[1]
    raw_file = RAW_DIR / f"{category}.json"

    if not raw_file.exists():
        print(f"Error: {raw_file} does not exist")
        sys.exit(1)

    print(f"Tracing structure for: {category}")
    print("=" * 60)
    print()

    # Load and parse
    with open(raw_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not data:
        print("No data found in file")
        sys.exit(1)

    # Trace first record
    print("Structure of first record:")
    print("-" * 60)
    trace_structure(data[0])

    print()
    print("=" * 60)
    print("Common extraction patterns:")
    print("=" * 60)
    print()

    # Show common patterns
    first = data[0]

    # Check for listing_type wrapper
    if 'listing_type' in first:
        print("✓ Detected listing_type wrapper")
        if first.get('listing_type') == 'property':
            print("  → Use p.get('property', {}) to access property data")

    # Check for nested objects
    if 'property' in first:
        print("✓ Detected nested 'property' object")
        prop = first.get('property', {})

        if 'price' in prop:
            print("  → Price path: property.price.value")

        if 'location' in prop:
            print("  → Location path: property.location.full_name")

            if 'coordinates' in prop.get('location', {}):
                print("  → Coordinates path: property.location.coordinates.lat/lon")

    print()
    print("Use these paths in cleaner.py flatten_listing() function")


if __name__ == "__main__":
    main()
