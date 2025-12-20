#!/usr/bin/env python
"""CLI script to reindex storage and sync metadata with actual files."""

import sys
from scraper.metadata_store import MetadataStore
from utils.storage_reindex import StorageReindexer
from utils.logger import setup_logging


def main():
    """Run storage reindexing."""
    setup_logging()

    print("=" * 60)
    print("Atlassian Marketplace Storage Reindexer")
    print("=" * 60)
    print()

    # Parse arguments
    clean_orphaned = False
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg == '--help' or arg == '-h':
            print("Usage: python run_reindex.py [--clean-orphaned]")
            print()
            print("This script reindexes the storage by:")
            print("  1. Scanning all versions marked as 'downloaded' in metadata")
            print("  2. Verifying that the actual files exist on disk")
            print("  3. Clearing 'downloaded' status for missing files")
            print()
            print("Options:")
            print("  --clean-orphaned    Also remove files not tracked in metadata")
            print()
            print("Examples:")
            print("  python run_reindex.py                # Reindex only")
            print("  python run_reindex.py --clean-orphaned  # Reindex and clean")
            return 0

        elif arg == '--clean-orphaned':
            clean_orphaned = True
        else:
            print(f"❌ Error: Unknown option '{arg}'")
            print("   Use --help for usage information")
            return 1

    # Initialize components
    store = MetadataStore()
    reindexer = StorageReindexer(store)

    # Run reindex
    try:
        print("🔄 Starting reindex process...")
        print()
        stats = reindexer.reindex(verbose=True)

        # Optionally clean orphaned files
        if clean_orphaned:
            print()
            print("🔍 Searching for orphaned files...")
            orphaned = reindexer.get_orphaned_files(verbose=True)

            if orphaned:
                total = sum(len(paths) for paths in orphaned.values())
                print()
                print(f"⚠️  Found {total} orphaned directories")
                print()

                # Ask for confirmation
                response = input("Remove orphaned files? (yes/no): ").strip().lower()

                if response in ['yes', 'y']:
                    print()
                    reindexer.clean_orphaned_files(orphaned, verbose=True)
                else:
                    print("❌ Cancelled - orphaned files not removed")
            else:
                print("✅ No orphaned files found")

        print()
        print("=" * 60)
        print("✅ Reindex complete!")
        print("=" * 60)

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️ Reindex interrupted by user")
        return 1

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
