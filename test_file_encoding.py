"""Test script to check file encoding and fix corrupted HTML file."""

import sys
import os
from pathlib import Path

# Test the corrupted file
corrupted_file = Path(r"C:\Users\thssc\atlassian-marketplace-scraper-master\com_onresolve_jira_groovy_groovyrunner\full_page\index.html")

if corrupted_file.exists():
    print(f"File exists: {corrupted_file}")
    print(f"File size: {corrupted_file.stat().st_size} bytes")
    
    # Read as binary
    with open(corrupted_file, 'rb') as f:
        raw_bytes = f.read(1000)  # First 1000 bytes
    
    print(f"\nFirst 100 bytes (hex):")
    print(raw_bytes[:100].hex())
    
    print(f"\nFirst 100 bytes (repr):")
    print(repr(raw_bytes[:100]))
    
    # Try different encodings
    print("\n=== Trying different encodings ===")
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'windows-1252', 'gbk', 'big5']
    
    for encoding in encodings:
        try:
            decoded = raw_bytes.decode(encoding)
            # Check if it looks like valid text
            if any(c.isprintable() or c in '\n\r\t' for c in decoded[:200]):
                print(f"\n{encoding}: SUCCESS")
                print(f"First 200 chars: {decoded[:200]}")
                break
        except Exception as e:
            print(f"{encoding}: FAILED - {e}")
    
    # Check if it's gzip compressed
    if raw_bytes[:2] == b'\x1f\x8b':
        print("\n!!! File appears to be gzip compressed!")
        import gzip
        try:
            decompressed = gzip.decompress(raw_bytes)
            print(f"Decompressed size: {len(decompressed)} bytes")
            print(f"First 200 chars after decompression: {decompressed[:200].decode('utf-8', errors='replace')}")
        except Exception as e:
            print(f"Decompression failed: {e}")
else:
    print(f"File not found: {corrupted_file}")

