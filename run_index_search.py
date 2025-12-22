"""Script to build search index for plugin descriptions and release notes."""

import sys
import os
from pathlib import Path

# Fix encoding for Windows console (cp1252 doesn't support Unicode)
if sys.platform == 'win32':
    try:
        # Try to set UTF-8 encoding for stdout/stderr
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        # Fallback: use ASCII-safe output
        pass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from scraper.metadata_store import MetadataStore
from web.search_index_whoosh import WhooshSearchIndex
from utils.logger import get_logger
from config import settings
from pathlib import Path

logger = get_logger('indexer')


def main():
    """Build search index."""
    print("=" * 60)
    print("Building Search Index")
    print("=" * 60)
    print()
    
    try:
        # Initialize components
        store = MetadataStore()
        search_index = WhooshSearchIndex()
        
        print("[1/2] Initializing search index...")
        sys.stdout.flush()
        
        # Build index with progress
        print("[2/2] Building index from descriptions and release notes...")
        print("This may take a few minutes depending on the number of plugins...")
        print()
        sys.stdout.flush()
        
        # Count total items for progress
        descriptions_dir = Path(settings.DESCRIPTIONS_DIR)
        total_items = 0
        if descriptions_dir.exists():
            total_items = len([item for item in descriptions_dir.iterdir() if item.is_dir()])
        
        print(f"Found {total_items} plugin directories to index")
        sys.stdout.flush()
        
        # Build index (will print progress internally)
        indexed_count = search_index.build_index(store)
        
        print()
        print("=" * 60)
        print(f"[OK] Search index built successfully! Indexed {indexed_count} plugins")
        print("=" * 60)
        print()
        print(f"Index location: {search_index.index_dir}")
        print()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n[!] Index building interrupted by user.")
        return 1
    except Exception as e:
        logger.error(f"Error building search index: {str(e)}", exc_info=True)
        print(f"\n\n[ERROR] Failed to build search index: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())

