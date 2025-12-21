#!/usr/bin/env python
"""Test script for save_marketplace_plugin_page function."""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.description_downloader import DescriptionDownloader
from config import settings
from utils.logger import setup_logging

def test_save_marketplace_page():
    """Test the save_marketplace_plugin_page function."""
    setup_logging()
    
    # Initialize downloader
    downloader = DescriptionDownloader()
    
    # Test data - example from JSON
    test_record = {
        "addon_key": "com.onresolve.jira.groovy.groovyrunner",
        "name": "ScriptRunner for Jira",
        "marketplace_url": {
            "href": "/apps/6820/scriptrunner-for-jira?tab=overview",
            "type": "text/html"
        }
    }
    
    addon_key = test_record["addon_key"]
    download_url = test_record["marketplace_url"]["href"]
    
    # Test 1: Playwright method with MHTML (RECOMMENDED - executes JS, captures full content)
    print("=" * 60)
    print("Test 1: Playwright method with MHTML (RECOMMENDED)")
    print("=" * 60)
    print("This method uses headless browser to execute JavaScript and capture fully rendered page")
    print("Output: Single MHTML file with all resources embedded")
    
    save_path_mhtml = Path(settings.DESCRIPTIONS_DIR) / "test" / "scriptrunner_playwright.mhtml"
    
    try:
        html_path = downloader.save_marketplace_page_with_playwright(
            download_url=download_url,
            save_path=save_path_mhtml,
            format="mhtml",
            wait_seconds=5,
            timeout=60
        )
        
        print(f"✓ Success!")
        print(f"  MHTML saved to: {html_path}")
        print(f"  File size: {html_path.stat().st_size} bytes")
        print(f"  NOTE: Open this file in a browser to view the fully rendered page")
        
    except ImportError as e:
        print(f"⚠ Playwright not installed: {str(e)}")
        print(f"  Install with: pip install playwright && playwright install chromium")
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Test 2: New method without media (removes scripts, works offline)
    print("\n" + "=" * 60)
    print("Test 2: Script removal method without media")
    print("=" * 60)
    print("This method removes all <script> tags to prevent SPA routing issues")
    
    save_path = Path(settings.DESCRIPTIONS_DIR) / "test" / "scriptrunner_no_media.html"
    
    try:
        html_path, assets_dir = downloader.save_marketplace_plugin_page(
            download_url=download_url,
            save_html_path=save_path,
            encoding="utf-8",
            download_media=False,
            timeout=30
        )
        
        print(f"✓ Success!")
        print(f"  HTML saved to: {html_path}")
        print(f"  Assets dir: {assets_dir}")
        print(f"  File size: {html_path.stat().st_size} bytes")
        
        # Check encoding and content
        with open(html_path, 'rb') as f:
            content = f.read()
            try:
                decoded = content.decode('utf-8')
                print(f"  ✓ File is valid UTF-8")
                print(f"  Contains DOCTYPE: {'<!DOCTYPE' in decoded[:200]}")
                print(f"  Scripts removed: {'<script' not in decoded}")
                print(f"  Contains plugin name: {'ScriptRunner' in decoded or 'scriptrunner' in decoded.lower()}")
                print(f"  First 200 chars: {decoded[:200]}...")
            except UnicodeDecodeError as e:
                print(f"  ✗ Encoding error: {e}")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Test 2: New method with media (RECOMMENDED - works offline with assets)
    print("\n" + "=" * 60)
    print("Test 2: New method with media (RECOMMENDED)")
    print("=" * 60)
    print("This method removes scripts AND downloads CSS/images for offline viewing")
    
    save_path_with_media = Path(settings.DESCRIPTIONS_DIR) / "test" / "scriptrunner_with_media.html"
    
    try:
        html_path, assets_dir = downloader.save_marketplace_plugin_page(
            download_url=download_url,
            save_html_path=save_path_with_media,
            encoding="utf-8",
            download_media=True,
            timeout=30
        )
        
        print(f"✓ Success!")
        print(f"  HTML saved to: {html_path}")
        print(f"  Assets dir: {assets_dir}")
        print(f"  File size: {html_path.stat().st_size} bytes")
        
        if assets_dir and assets_dir.exists():
            asset_files = list(assets_dir.glob("*"))
            print(f"  Assets downloaded: {len(asset_files)} files")
            for asset in asset_files[:10]:  # Show first 10
                print(f"    - {asset.name} ({asset.stat().st_size} bytes)")
            if len(asset_files) > 10:
                print(f"    ... and {len(asset_files) - 10} more")
        
        # Check encoding
        with open(html_path, 'rb') as f:
            content = f.read()
            try:
                decoded = content.decode('utf-8')
                print(f"  ✓ File is valid UTF-8")
                print(f"  Scripts removed: {'<script' not in decoded}")
                
                # Check if assets are referenced
                if assets_dir and assets_dir.name in decoded:
                    print(f"  ✓ Assets are referenced in HTML")
                
            except UnicodeDecodeError as e:
                print(f"  ✗ Encoding error: {e}")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Static API method (for comparison - uses REST API)
    print("\n" + "=" * 60)
    print("Test 4: Static API method (for comparison)")
    print("=" * 60)
    print("This method uses REST API to generate static HTML")
    
    save_path_static = Path(settings.DESCRIPTIONS_DIR) / "test" / "scriptrunner_static_api.html"
    
    try:
        html_path, assets_dir = downloader.save_marketplace_plugin_page_static(
            download_url=download_url,
            save_html_path=save_path_static,
            encoding="utf-8",
            download_media=False,
            addon_key=addon_key,
            timeout=30
        )
        
        print(f"✓ Success!")
        print(f"  HTML saved to: {html_path}")
        print(f"  File size: {html_path.stat().st_size} bytes")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)
    print("\nYou can now open the HTML files in a browser to verify they display correctly.")


if __name__ == '__main__':
    test_save_marketplace_page()

