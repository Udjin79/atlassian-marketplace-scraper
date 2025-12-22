#!/usr/bin/env python
"""
Run smoke tests for Atlassian Marketplace Scraper.

Usage:
    python run_smoke_tests.py
    python run_smoke_tests.py --verbose
    python run_smoke_tests.py --quick  # Skip slow tests
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from tests.test_smoke import run_smoke_tests


def main():
    """Main entry point for smoke tests."""
    parser = argparse.ArgumentParser(description='Run smoke tests')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--quick', '-q', action='store_true',
                       help='Skip slow tests')
    args = parser.parse_args()
    
    print("=" * 70)
    print("SMOKE TESTS - Atlassian Marketplace Scraper")
    print("=" * 70)
    print()
    print("Smoke tests verify that basic functionality works")
    print("and the system is not broken.")
    print()
    
    if args.quick:
        print("Running quick tests only (skipping slow tests)...")
        print()
    
    result = run_smoke_tests()
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"\n{test}:")
            print(traceback)
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"\n{test}:")
            print(traceback)
    
    if result.wasSuccessful():
        print("\n✓ All smoke tests passed!")
        return 0
    else:
        print("\n✗ Some smoke tests failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())

