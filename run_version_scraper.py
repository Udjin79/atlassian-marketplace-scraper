#!/usr/bin/env python
"""CLI script to run the version scraper."""

import sys

# Fix encoding for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        # Fallback for older Python versions
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from scraper.version_scraper import VersionScraper
from scraper.metadata_store import MetadataStore
from config import settings
from utils.logger import setup_logging


def main():
    """Run the version scraper."""
    setup_logging()

    # Check for credentials
    if not settings.MARKETPLACE_USERNAME or not settings.MARKETPLACE_API_TOKEN:
        print("[ERROR] Error: Marketplace credentials not configured")
        print("Please set MARKETPLACE_USERNAME and MARKETPLACE_API_TOKEN in .env file")
        return 1

    print("=" * 60)
    print("Atlassian Marketplace Version Scraper")
    print("=" * 60)
    print()

    # Initialize components
    store = MetadataStore()
    scraper = VersionScraper(store=store)

    # Check if apps exist
    apps_count = store.get_apps_count()
    if apps_count == 0:
        print("[ERROR] Error: No apps found in metadata store")
        print()
        print("[INFO] Workflow steps:")
        print("   1. [*] Collect apps:        python run_scraper.py  <-- Run this first")
        print("   2. [*] Collect versions:    python run_version_scraper.py")
        print("   3. [*] Download binaries:  python run_downloader.py")
        print()
        print("   -> Run: python run_scraper.py")
        return 1

    print(f"[INFO] Found {apps_count} apps in metadata store")
    print(f"[*] Scraping versions (filtering: last {settings.VERSION_AGE_LIMIT_DAYS} days, Server/DC only)...")
    print()

    # Run version scraper with parallel processing
    max_workers = settings.MAX_VERSION_SCRAPER_WORKERS
    print(f"[*] Using {max_workers} parallel workers for faster scraping")

    try:
        scraper.scrape_all_app_versions(
            filter_date=True,
            filter_hosting=True,
            max_workers=max_workers
        )

        print("\n[OK] Version scraping completed successfully!")
        scraper.get_versions_summary()
        print()
        print("[INFO] Next step:")
        print("   -> Download binaries: python run_downloader.py")
        print("   -> Or download specific product: python run_downloader.py jira")
        return 0

    except KeyboardInterrupt:
        print("\n\n[WARNING] Scraping interrupted by user")
        return 1

    except Exception as e:
        print(f"\n[ERROR] Error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
