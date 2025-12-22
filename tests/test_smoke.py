"""
Smoke tests for Atlassian Marketplace Scraper.

Smoke tests verify that basic functionality works and the system is not broken.
These tests should run quickly and cover critical paths.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import settings
from scraper.metadata_store import MetadataStore
from scraper.download_manager import DownloadManager
from utils.logger import get_logger

logger = get_logger('tests')


class TestMetadataStore(unittest.TestCase):
    """Test MetadataStore basic functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = MetadataStore()
    
    def test_store_initialization(self):
        """Test that MetadataStore can be initialized."""
        self.assertIsNotNone(self.store)
    
    def test_get_apps_count(self):
        """Test getting apps count."""
        count = self.store.get_apps_count()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)
    
    def test_get_all_apps(self):
        """Test getting all apps."""
        apps = self.store.get_all_apps(limit=10)
        self.assertIsInstance(apps, list)
        # If there are apps, check structure
        if apps:
            app = apps[0]
            self.assertIn('addon_key', app)
            self.assertIn('name', app)
    
    def test_get_app_by_key(self):
        """Test getting app by key."""
        apps = self.store.get_all_apps(limit=1)
        if apps:
            addon_key = apps[0].get('addon_key')
            if addon_key:
                app = self.store.get_app_by_key(addon_key)
                self.assertIsNotNone(app)
                self.assertEqual(app.get('addon_key'), addon_key)


class TestDownloadManager(unittest.TestCase):
    """Test DownloadManager basic functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.download_mgr = DownloadManager(MetadataStore())
    
    def test_manager_initialization(self):
        """Test that DownloadManager can be initialized."""
        self.assertIsNotNone(self.download_mgr)
    
    def test_get_storage_stats(self):
        """Test getting storage statistics."""
        stats = self.download_mgr.get_storage_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn('file_count', stats)
        self.assertIn('total_bytes', stats)
        self.assertIsInstance(stats['file_count'], int)
        self.assertGreaterEqual(stats['file_count'], 0)
    
    def test_get_detailed_storage_stats(self):
        """Test getting detailed storage statistics."""
        stats = self.download_mgr.get_detailed_storage_stats(max_folders=10)
        self.assertIsInstance(stats, dict)
        self.assertIn('total', stats)
        self.assertIn('categories', stats)
        self.assertIn('by_disk', stats)


class TestSearchFunctionality(unittest.TestCase):
    """Test search functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = MetadataStore()
        # Add web directory to path for imports
        web_dir = project_root / 'web'
        if str(web_dir) not in sys.path:
            sys.path.insert(0, str(web_dir))
    
    def test_enhanced_search_import(self):
        """Test that EnhancedSearch can be imported."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            self.assertIsNotNone(search)
        except ImportError as e:
            self.fail(f"Failed to import EnhancedSearch: {e}")
    
    def test_enhanced_search_basic(self):
        """Test basic enhanced search functionality."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            # Test with empty query
            results = search.search_all('', self.store, limit=10)
            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 0)
            
            # Test with a simple query (if there are apps)
            apps = self.store.get_all_apps(limit=1)
            if apps and apps[0].get('name'):
                test_query = apps[0]['name'][:5]  # First 5 chars of app name
                results = search.search_all(test_query, self.store, limit=10)
                self.assertIsInstance(results, list)
                # Should find at least one result
                if results:
                    result = results[0]
                    self.assertIn('addon_key', result)
                    self.assertIn('app_name', result)
                    self.assertIn('score', result)
        except ImportError:
            self.skipTest("EnhancedSearch not available")
    
    def test_whoosh_search_import(self):
        """Test that WhooshSearchIndex can be imported."""
        try:
            from search_index_whoosh import WhooshSearchIndex
            search = WhooshSearchIndex()
            self.assertIsNotNone(search)
        except ImportError as e:
            self.skipTest(f"Whoosh not available: {e}")
    
    def test_whoosh_search_needs_rebuild(self):
        """Test Whoosh index rebuild check."""
        try:
            from search_index_whoosh import WhooshSearchIndex
            search = WhooshSearchIndex()
            needs_rebuild = search.needs_rebuild()
            self.assertIsInstance(needs_rebuild, bool)
        except ImportError:
            self.skipTest("Whoosh not available")


class TestFileSystem(unittest.TestCase):
    """Test file system paths and directories."""
    
    def test_descriptions_dir_exists(self):
        """Test that descriptions directory path is valid."""
        desc_dir = Path(settings.DESCRIPTIONS_DIR)
        # Directory should exist or be creatable
        self.assertTrue(desc_dir.parent.exists() or desc_dir.exists())
    
    def test_metadata_dir_exists(self):
        """Test that metadata directory path is valid."""
        metadata_dir = Path(settings.METADATA_DIR)
        self.assertTrue(metadata_dir.parent.exists() or metadata_dir.exists())
    
    def test_binaries_base_dir_exists(self):
        """Test that binaries base directory path is valid."""
        binaries_dir = Path(settings.BINARIES_BASE_DIR)
        self.assertTrue(binaries_dir.parent.exists() or binaries_dir.exists())


class TestSettings(unittest.TestCase):
    """Test settings configuration."""
    
    def test_settings_loaded(self):
        """Test that settings are loaded."""
        self.assertIsNotNone(settings.DESCRIPTIONS_DIR)
        self.assertIsNotNone(settings.METADATA_DIR)
        self.assertIsNotNone(settings.BINARIES_BASE_DIR)
    
    def test_settings_paths_are_strings(self):
        """Test that path settings are strings."""
        self.assertIsInstance(settings.DESCRIPTIONS_DIR, str)
        self.assertIsInstance(settings.METADATA_DIR, str)
        self.assertIsInstance(settings.BINARIES_BASE_DIR, str)


class TestSearchEnhancedDetailed(unittest.TestCase):
    """Detailed tests for EnhancedSearch."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = MetadataStore()
        web_dir = project_root / 'web'
        if str(web_dir) not in sys.path:
            sys.path.insert(0, str(web_dir))
    
    def test_search_in_app_names(self):
        """Test searching in app names."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            
            # Get a real app name
            apps = self.store.get_all_apps(limit=5)
            if not apps:
                self.skipTest("No apps in database")
            
            # Search for first word of first app name
            test_app = apps[0]
            app_name = test_app.get('name', '')
            if app_name:
                query = app_name.split()[0] if ' ' in app_name else app_name[:5]
                results = search.search_all(query, self.store, limit=10)
                
                # Should find at least the app we searched for
                found_keys = [r['addon_key'] for r in results]
                self.assertIn(test_app['addon_key'], found_keys)
        except ImportError:
            self.skipTest("EnhancedSearch not available")
    
    def test_search_in_vendors(self):
        """Test searching in vendor names."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            
            apps = self.store.get_all_apps(limit=5)
            if not apps:
                self.skipTest("No apps in database")
            
            # Search for vendor name
            test_app = apps[0]
            vendor = test_app.get('vendor', '')
            if vendor:
                query = vendor.split()[0] if ' ' in vendor else vendor[:5]
                results = search.search_all(query, self.store, limit=10)
                
                # Should find at least one result
                self.assertGreater(len(results), 0)
        except ImportError:
            self.skipTest("EnhancedSearch not available")
    
    def test_search_empty_query(self):
        """Test that empty query returns no results."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            results = search.search_all('', self.store, limit=10)
            self.assertEqual(len(results), 0)
            
            results = search.search_all('   ', self.store, limit=10)
            self.assertEqual(len(results), 0)
        except ImportError:
            self.skipTest("EnhancedSearch not available")
    
    def test_search_results_structure(self):
        """Test that search results have correct structure."""
        try:
            from search_enhanced import EnhancedSearch
            search = EnhancedSearch()
            
            apps = self.store.get_all_apps(limit=1)
            if not apps:
                self.skipTest("No apps in database")
            
            # Search for something that should match
            query = apps[0].get('name', 'test')[:3]
            results = search.search_all(query, self.store, limit=5)
            
            if results:
                result = results[0]
                required_fields = ['addon_key', 'app_name', 'vendor', 'score', 'match_type']
                for field in required_fields:
                    self.assertIn(field, result, f"Result missing field: {field}")
                
                # Check types
                self.assertIsInstance(result['addon_key'], str)
                self.assertIsInstance(result['app_name'], str)
                self.assertIsInstance(result['score'], (int, float))
                self.assertGreaterEqual(result['score'], 0)
        except ImportError:
            self.skipTest("EnhancedSearch not available")


class TestStorageStats(unittest.TestCase):
    """Test storage statistics functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store = MetadataStore()
        self.download_mgr = DownloadManager(self.store)
    
    def test_storage_stats_structure(self):
        """Test that storage stats have correct structure."""
        stats = self.download_mgr.get_storage_stats()
        
        required_fields = ['total_bytes', 'total_mb', 'total_gb', 'file_count']
        for field in required_fields:
            self.assertIn(field, stats, f"Stats missing field: {field}")
    
    def test_detailed_storage_stats_structure(self):
        """Test that detailed storage stats have correct structure."""
        stats = self.download_mgr.get_detailed_storage_stats(max_folders=5)
        
        required_keys = ['total', 'categories', 'by_disk']
        for key in required_keys:
            self.assertIn(key, stats, f"Detailed stats missing key: {key}")
        
        # Check total structure
        total = stats['total']
        self.assertIn('bytes', total)
        self.assertIn('mb', total)
        self.assertIn('gb', total)
        self.assertIn('file_count', total)
        
        # Check categories structure
        categories = stats['categories']
        self.assertIsInstance(categories, dict)
        for category_name, category_data in categories.items():
            self.assertIn('bytes', category_data)
            self.assertIn('file_count', category_data)
            self.assertIn('folders', category_data)
            self.assertIsInstance(category_data['folders'], list)


def run_smoke_tests():
    """Run all smoke tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestMetadataStore,
        TestDownloadManager,
        TestSearchFunctionality,
        TestFileSystem,
        TestSettings,
        TestSearchEnhancedDetailed,
        TestStorageStats
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == '__main__':
    print("=" * 70)
    print("SMOKE TESTS - Atlassian Marketplace Scraper")
    print("=" * 70)
    print()
    
    result = run_smoke_tests()
    
    print()
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)
    
    if result.wasSuccessful():
        print("✓ All smoke tests passed!")
        sys.exit(0)
    else:
        print("✗ Some smoke tests failed!")
        sys.exit(1)

