#!/usr/bin/env python
"""Download plugin descriptions with images and videos from Atlassian Marketplace."""

import sys
import io
import argparse

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from scraper.description_downloader import DescriptionDownloader
from scraper.metadata_store import MetadataStore
from utils.logger import setup_logging

setup_logging()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download plugin descriptions with images and videos"
    )
    parser.add_argument(
        '--addon-key',
        help='Download description for specific addon key'
    )
    parser.add_argument(
        '--download-media',
        action='store_true',
        default=True,
        help='Download media files (images/videos)'
    )
    parser.add_argument(
        '--no-media',
        dest='download_media',
        action='store_false',
        help='Skip media download'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of apps to process'
    )
    parser.add_argument(
        '--use-api',
        action='store_true',
        help='Use API-based description instead of full HTML page'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Atlassian Marketplace Description Downloader")
    print("=" * 60)

    store = MetadataStore()
    downloader = DescriptionDownloader(metadata_store=store)

    if args.addon_key:
        # Download for specific app
        print(f"\nDownloading description for: {args.addon_key}")
        
        # Get app from database to get marketplace_url
        app = store.get_app_by_key(args.addon_key)
        marketplace_url = None
        if app:
            # Handle marketplace_url - can be string or dict
            marketplace_url_raw = app.get('marketplace_url')
            if marketplace_url_raw:
                if isinstance(marketplace_url_raw, dict):
                    marketplace_url = marketplace_url_raw.get('href', '')
                elif isinstance(marketplace_url_raw, str):
                    marketplace_url = marketplace_url_raw.strip()
        
        # If marketplace_url is empty, construct it
        if not marketplace_url:
            marketplace_url = f"https://marketplace.atlassian.com/apps/{args.addon_key}?hosting=datacenter&tab=overview"
            print(f"Constructed marketplace URL: {marketplace_url}")
        
        # Always use download_description - it handles both full_page and API
        # If marketplace_url is provided and not use_api, it will download full_page + API
        # If use_api is True, it will only download API description
        json_path, html_path = downloader.download_description(
            args.addon_key,
            download_media=args.download_media,
            marketplace_url=marketplace_url if not args.use_api else None
        )
        
        if json_path or html_path:
            print(f"[OK] Description saved:")
            if json_path:
                print(f"  JSON: {json_path}")
            if html_path:
                print(f"  HTML: {html_path}")
        else:
            print(f"[ERROR] Failed to download description for {args.addon_key}")
            sys.exit(1)
    else:
        # Download for all apps
        print(f"\nDownloading descriptions for all apps...")
        if args.limit:
            print(f"Limit: {args.limit} apps")
        print(f"Download media: {args.download_media}")
        print(f"Use full HTML page: {not args.use_api}")
        print()

        downloader.download_all_descriptions(
            download_media=args.download_media,
            limit=args.limit,
            use_full_page=not args.use_api
        )

    print("\n✔ Description download completed!")


if __name__ == '__main__':
    main()

