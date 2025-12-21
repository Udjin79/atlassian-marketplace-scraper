"""Test script to check description downloader paths and encoding."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings
from scraper.description_downloader import DescriptionDownloader

print("=== Configuration ===")
print(f"DESCRIPTIONS_DIR: {settings.DESCRIPTIONS_DIR}")
print(f"METADATA_DIR: {settings.METADATA_DIR}")
print(f"BASE_DIR: {settings.BASE_DIR if hasattr(settings, 'BASE_DIR') else 'N/A'}")

print("\n=== DescriptionDownloader ===")
downloader = DescriptionDownloader()
print(f"downloader.descriptions_dir: {downloader.descriptions_dir}")
print(f"Expected path for com.onresolve.jira.groovy.groovyrunner:")
print(f"  {os.path.join(downloader.descriptions_dir, 'com_onresolve_jira_groovy_groovyrunner', 'full_page', 'index.html')}")

print("\n=== Checking existing file ===")
existing_file = r"C:\Users\thssc\atlassian-marketplace-scraper-master\com_onresolve_jira_groovy_groovyrunner\full_page\index.html"
if os.path.exists(existing_file):
    print(f"Existing file found: {existing_file}")
    print(f"File size: {os.path.getsize(existing_file)} bytes")
    
    # Try to read and check encoding
    try:
        with open(existing_file, 'rb') as f:
            raw_bytes = f.read(1000)  # Read first 1000 bytes
        print(f"First 100 bytes (hex): {raw_bytes[:100].hex()}")
        
        # Try UTF-8
        try:
            content_utf8 = raw_bytes.decode('utf-8')
            print("✓ File can be decoded as UTF-8")
            print(f"First 200 chars: {content_utf8[:200]}")
        except UnicodeDecodeError as e:
            print(f"✗ Cannot decode as UTF-8: {e}")
            
        # Try to detect encoding
        try:
            import chardet
            detected = chardet.detect(raw_bytes)
            print(f"Detected encoding: {detected}")
        except ImportError:
            print("chardet not available")
    except Exception as e:
        print(f"Error reading file: {e}")
else:
    print(f"File not found: {existing_file}")

