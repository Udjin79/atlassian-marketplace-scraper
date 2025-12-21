#!/usr/bin/env python
"""Download plugin descriptions with images and videos from Atlassian Marketplace."""

import sys
import io
import argparse
import time
from datetime import datetime

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
        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"Downloading description for: {args.addon_key}")
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        sys.stdout.flush()  # Force output to console
        
        # Get app from database to get marketplace_url
        print("[1/6] Getting app information from database...")
        sys.stdout.flush()
        app = store.get_app_by_key(args.addon_key)
        marketplace_url = None
        if app:
            print(f"  ✓ App found: {app.get('name', 'Unknown')}")
            sys.stdout.flush()
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
            print(f"  ⚠ Marketplace URL not found, constructed: {marketplace_url}")
        else:
            print(f"  ✓ Marketplace URL: {marketplace_url}")
        sys.stdout.flush()
        
        print(f"\n[2/6] Starting download process...")
        print(f"  - Download media: {'Yes' if args.download_media else 'No'}")
        print(f"  - Hosting types: datacenter (preferred), server (if datacenter not available)")
        print(f"  - Method: {'Full page + API' if not args.use_api else 'API only'}")
        print()
        sys.stdout.flush()
        
        # Always use download_description - it handles both full_page and API
        # If marketplace_url is provided and not use_api, it will download full_page + API
        # If use_api is True, it will only download API description
        # By default, download for datacenter, server, and cloud
        try:
            json_path, html_path = downloader.download_description(
                args.addon_key,
                download_media=args.download_media,
                marketplace_url=marketplace_url if not args.use_api else None,
                download_all_hosting=True  # Download for datacenter, server, and cloud
            )
        except KeyboardInterrupt:
            print("\n\n[!] Download interrupted by user")
            elapsed_time = time.time() - start_time
            print(f"Elapsed time: {elapsed_time:.1f} seconds")
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERROR] Download failed: {str(e)}")
            elapsed_time = time.time() - start_time
            print(f"Elapsed time: {elapsed_time:.1f} seconds")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        elapsed_time = time.time() - start_time
        
        print(f"\n[3/6] Download completed in {elapsed_time:.1f} seconds")
        
        if json_path or html_path:
            print(f"\n[4/6] Files saved:")
            if json_path:
                file_size = json_path.stat().st_size if json_path.exists() else 0
                size_kb = file_size / 1024
                print(f"  ✓ JSON: {json_path}")
                print(f"    Size: {size_kb:.1f} KB")
            if html_path:
                file_size = html_path.stat().st_size if html_path.exists() else 0
                size_kb = file_size / 1024
                size_mb = file_size / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size_kb:.1f} KB"
                print(f"  ✓ HTML: {html_path}")
                print(f"    Size: {size_str}")
            
            # Check for assets directory
            if html_path:
                assets_dir = html_path.parent / 'assets'
                if assets_dir.exists():
                    assets_size = sum(f.stat().st_size for f in assets_dir.rglob('*') if f.is_file())
                    assets_mb = assets_size / (1024 * 1024)
                    assets_count = len(list(assets_dir.rglob('*')))
                    print(f"  ✓ Assets: {assets_dir}")
                    print(f"    Files: {assets_count}, Size: {assets_mb:.1f} MB")
            
            print(f"\n[5/6] Summary:")
            print(f"  ✓ Total time: {elapsed_time:.1f} seconds")
            print(f"  ✓ Status: Success")
            
            print(f"\n[6/6] Done!")
            print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"\n[ERROR] Failed to download description for {args.addon_key}")
            print(f"Elapsed time: {elapsed_time:.1f} seconds")
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

