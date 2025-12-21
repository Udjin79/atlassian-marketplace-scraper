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
        marketplace_url = app.get('marketplace_url') if app else None
        
        if marketplace_url and not args.use_api:
            # Download full HTML page
            print(f"Using full HTML page: {marketplace_url}")
            html_path = downloader.download_full_marketplace_page(
                marketplace_url,
                args.addon_key,
                download_assets=args.download_media
            )
            if html_path:
                print(f"[OK] Full page saved: {html_path}")
            else:
                print(f"[ERROR] Failed to download full page, trying API...")
                json_path, html_path = downloader.download_description(
                    args.addon_key,
                    download_media=args.download_media,
                    marketplace_url=marketplace_url
                )
                if json_path and html_path:
                    print(f"[OK] Description saved:")
                    print(f"  JSON: {json_path}")
                    print(f"  HTML: {html_path}")
                else:
                    print(f"[ERROR] Failed to download description for {args.addon_key}")
                    sys.exit(1)
        else:
            # Use API-based description
            json_path, html_path = downloader.download_description(
                args.addon_key,
                download_media=args.download_media,
                marketplace_url=marketplace_url
            )
            if json_path and html_path:
                print(f"[OK] Description saved:")
                print(f"  JSON: {json_path}")
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

