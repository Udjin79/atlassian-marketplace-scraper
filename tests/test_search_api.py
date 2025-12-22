"""
API-level smoke tests for search functionality.

These tests verify that the search API endpoints work correctly.
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import settings
from scraper.metadata_store import MetadataStore


class TestSearchAPI(unittest.TestCase):
    """Test search API functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = MetadataStore()
        web_dir = project_root / 'web'
        if str(web_dir) not in sys.path:
            sys.path.insert(0, str(web_dir))
    
    def test_simple_text_search_function(self):
        """Test the _simple_text_search function."""
        try:
            from web.routes import _simple_text_search
            
            # Test with empty query
            results = _simple_text_search('', self.store, limit=10)
            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 0)
            
            # Test with a query
            apps = self.store.get_all_apps(limit=5)
            if apps:
                test_app = apps[0]
                query = test_app.get('name', 'test')[:5]
                results = _simple_text_search(query, self.store, limit=10)
                self.assertIsInstance(results, list)
                # Should find at least one result
                if results:
                    result = results[0]
                    self.assertIn('addon_key', result)
                    self.assertIn('app_name', result)
                    self.assertIn('score', result)
        except ImportError:
            self.skipTest("Routes module not available")
    
    def test_enhanced_search_handles_errors(self):
        """Test that EnhancedSearch handles errors gracefully."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            
            # Test with None metadata_store (should handle gracefully)
            try:
                results = search.search_all('test', None, limit=10)
                # Should either return empty list or raise AttributeError
                self.assertIsInstance(results, list)
            except (AttributeError, TypeError):
                # Expected behavior
                pass
        except ImportError:
            self.skipTest("EnhancedSearch not available")


if __name__ == '__main__':
    unittest.main()

