#!/usr/bin/env python
"""CLI script to run the app scraper."""

import sys
from scraper.app_scraper import AppScraper
from scraper.marketplace_api import MarketplaceAPI
from scraper.metadata_store import MetadataStore
from config import settings
from utils.logger import setup_logging


def main():
    """Run the app scraper."""
    setup_logging()

    # Check for credentials
    if not settings.MARKETPLACE_USERNAME or not settings.MARKETPLACE_API_TOKEN:
        print("❌ Error: Marketplace credentials not configured")
        print("Please set MARKETPLACE_USERNAME and MARKETPLACE_API_TOKEN in .env file")
        print("See .env.example for template")
        return 1

    print("=" * 60)
    print("Atlassian Marketplace App Scraper")
    print("=" * 60)
    print()

    # Initialize components
    api = MarketplaceAPI()
    store = MetadataStore()
    scraper = AppScraper(api, store)

    # Check for command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()

        if command == '--help' or command == '-h':
            print("Usage: python run_scraper.py [--resume]")
            print()
            print("Options:")
            print("  --resume    Resume from last checkpoint")
            print("  --help      Show this help message")
            return 0

        elif command == '--resume':
            print("📌 Resuming from checkpoint...")
            scraper.scrape_all_products(resume=True)
            return 0

    # Run scraper
    try:
        scraper.scrape_all_products(resume=True)
        print("\n✅ App scraping completed successfully!")
        print(f"\n📊 Total apps: {store.get_apps_count()}")
        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️ Scraping interrupted by user")
        print("💾 Progress saved to checkpoint")
        print("   Run again with --resume to continue")
        return 1

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
