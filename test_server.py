#!/usr/bin/env python
"""Simple script to test if Flask server is running."""

import requests
import sys
from config import settings

def test_server():
    """Test if Flask server is accessible."""
    url = f"http://localhost:{settings.FLASK_PORT}"
    
    print(f"Testing server at {url}...")
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            print(f"✓ Server is running and responding!")
            print(f"  Status code: {response.status_code}")
            return 0
        else:
            print(f"✗ Server responded with status code: {response.status_code}")
            return 1
    except requests.exceptions.ConnectionError:
        print(f"✗ Cannot connect to server at {url}")
        print("\nPossible reasons:")
        print("1. Server is not running - run: python app.py")
        print("2. Port is different - check FLASK_PORT in .env")
        print("3. Firewall is blocking the connection")
        return 1
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(test_server())

