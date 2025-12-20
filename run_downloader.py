#!/usr/bin/env python
"""CLI script to run the download manager."""

import sys
from scraper.download_manager import DownloadManager
from scraper.marketplace_api import MarketplaceAPI
from scraper.metadata_store import MetadataStore
from config.products import PRODUCT_LIST
from config import settings
from utils.logger import setup_logging


def main():
    """Run the download manager."""
    setup_logging()

    print("=" * 60)
    print("Atlassian Marketplace Binary Downloader")
    print("=" * 60)
    print()

    # Initialize components
    api = MarketplaceAPI()
    store = MetadataStore()
    downloader = DownloadManager(api, store)

    # Check if versions exist
    versions_count = store.get_total_versions_count()
    apps_count = store.get_apps_count()
    if versions_count == 0:
        print("❌ Error: No versions found in metadata store")
        print()
        print("📋 Workflow steps:")
        print("   1. ✅ Collect apps:        python run_scraper.py")
        print("   2. ⏳ Collect versions:    python run_version_scraper.py  <-- You are here")
        print("   3. ⏸️  Download binaries:  python run_downloader.py")
        print()
        if apps_count > 0:
            print(f"   ✓ Found {apps_count} apps - ready for version scraping")
            print("   → Run: python run_version_scraper.py")
        else:
            print("   → First run: python run_scraper.py")
        return 1

    # Parse command line arguments
    product_filter = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg == '--help' or arg == '-h':
            print("Usage: python run_downloader.py [product]")
            print()
            print("Products:")
            for product in PRODUCT_LIST:
                print(f"  {product}")
            print()
            print("Examples:")
            print("  python run_downloader.py          # Download all")
            print("  python run_downloader.py jira     # Download Jira apps only")
            return 0

        elif arg in PRODUCT_LIST:
            product_filter = arg
            print(f"🎯 Filtering by product: {product_filter}")
        else:
            print(f"❌ Error: Unknown product '{arg}'")
            print(f"   Valid products: {', '.join(PRODUCT_LIST)}")
            return 1

    print(f"📊 Total versions in metadata: {versions_count}")
    print(f"💾 Max concurrent downloads: {settings.MAX_CONCURRENT_DOWNLOADS}")
    print()

    # Run downloader
    try:
        downloader.download_all_versions(product=product_filter)

        # Show final stats
        storage_stats = downloader.get_storage_stats()
        print(f"\n💾 Storage used: {storage_stats['total_gb']:.2f} GB")
        print(f"📁 Total files: {storage_stats['file_count']}")

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️ Download interrupted by user")
        return 1

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
