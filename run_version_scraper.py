#!/usr/bin/env python
"""CLI script to run the version scraper."""

import sys
from scraper.version_scraper import VersionScraper
from scraper.metadata_store import MetadataStore
from config import settings
from config.products import PRODUCT_LIST
from utils.logger import setup_logging


def main():
    """Run the version scraper."""
    setup_logging()

    # Check for credentials
    if not settings.MARKETPLACE_USERNAME or not settings.MARKETPLACE_API_TOKEN:
        print("❌ Error: Marketplace credentials not configured")
        print("Please set MARKETPLACE_USERNAME and MARKETPLACE_API_TOKEN in .env file")
        return 1

    print("=" * 60)
    print("Atlassian Marketplace Version Scraper")
    print("=" * 60)
    print()

    # Parse command line arguments
    product_filter = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg == '--help' or arg == '-h':
            print("Usage: python run_version_scraper.py [product]")
            print()
            print("Products:")
            for product in PRODUCT_LIST:
                print(f"  {product}")
            print()
            print("Examples:")
            print("  python run_version_scraper.py          # Scrape all products")
            print("  python run_version_scraper.py crowd    # Scrape Crowd apps only")
            return 0

        elif arg in PRODUCT_LIST:
            product_filter = arg
            print(f"🎯 Filtering by product: {product_filter}")
        else:
            print(f"❌ Error: Unknown product '{arg}'")
            print(f"   Valid products: {', '.join(PRODUCT_LIST)}")
            return 1

    # Initialize components
    store = MetadataStore()
    scraper = VersionScraper(store=store)

    # Get apps with optional product filter
    if product_filter:
        apps_count = store.get_apps_count({'product': product_filter})
    else:
        apps_count = store.get_apps_count()

    if apps_count == 0:
        if product_filter:
            print(f"❌ Error: No {product_filter} apps found in metadata store")
        else:
            print("❌ Error: No apps found in metadata store")
        print("   Run app scraper first: python run_scraper.py")
        return 1

    print(f"📦 Found {apps_count} apps")
    print(f"⏳ Scraping versions (filtering: last {settings.VERSION_AGE_LIMIT_DAYS} days, Server/DC only)...")
    print()

    # Run version scraper with parallel processing
    max_workers = settings.MAX_VERSION_SCRAPER_WORKERS
    print(f"⚡ Using {max_workers} parallel workers for faster scraping")

    try:
        scraper.scrape_all_app_versions(
            filter_date=True,
            filter_hosting=True,
            max_workers=max_workers,
            product_filter=product_filter
        )

        print("\n✅ Version scraping completed successfully!")
        scraper.get_versions_summary()
        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️ Scraping interrupted by user")
        return 1

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
