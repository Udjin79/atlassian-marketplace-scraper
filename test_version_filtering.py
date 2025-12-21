#!/usr/bin/env python
"""Test script to debug version filtering for a specific app."""

from scraper.marketplace_api import MarketplaceAPI
from scraper.version_scraper import VersionScraper
from scraper.metadata_store import MetadataStore
import logging

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test with "Admin Toolbox for Jira"
addon_key = 'com.valiantys.jira.admin-toolbox'

print(f"\n{'='*80}")
print(f"Testing version filtering for: {addon_key}")
print(f"{'='*80}\n")

# Initialize scraper
scraper = VersionScraper()

# Scrape versions with detailed logging
print("Fetching and filtering versions...\n")
versions = scraper.scrape_app_versions(
    addon_key,
    filter_date=True,
    filter_hosting=True
)

print(f"\n{'='*80}")
print(f"RESULT: Found {len(versions)} versions after filtering")
print(f"{'='*80}\n")

if versions:
    print("Version details:")
    for i, v in enumerate(versions[:10], 1):
        print(f"{i}. {v.version_name} - Released: {v.release_date} - Hosting: {v.hosting_type}")
else:
    print("No versions found after filtering!")
    print("\nThis means either:")
    print("  1. API returned no versions")
    print("  2. All versions were filtered out by hosting type filter")
    print("  3. All versions were filtered out by date filter")
    print("\nCheck the DEBUG logs above to see which filter removed the versions.")
