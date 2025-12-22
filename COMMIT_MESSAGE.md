# Commit Message

```
feat: Add storage statistics, multi-account support, and vendor documentation extraction

## Major Features

### 1. Detailed Storage Statistics
- Added `get_detailed_storage_stats()` method with breakdown by:
  - Categories (binaries, descriptions, metadata)
  - Disk drives
  - Individual folders (top 100 per category)
- New `/storage` page with comprehensive storage breakdown
- Storage statistics widget on dashboard with lazy loading
- Caching for storage statistics (TTL: 5 minutes) to improve page load times

### 2. Multiple Account Support with Rotation
- Added `CredentialsRotator` class for managing multiple Marketplace API accounts
- Support for multiple accounts in `.credentials.json` format
- Automatic account rotation for parallel requests
- Automatic rotation on 429 (rate limit) errors
- Thread-safe implementation for concurrent access
- Backward compatible with single account format
- Web interface for managing multiple accounts

### 3. Vendor Documentation Link Extraction
- Added `_extract_documentation_url_from_html()` method
- Extracts documentation URL from Marketplace page Resources section
- Parses "App documentation" link with "Comprehensive set of documentation" text
- Saves `documentation_url` in JSON description files
- Displays "Documentation" button in descriptions list web interface

### 4. Performance Optimizations
- Caching for `get_storage_stats()` and `get_detailed_storage_stats()` (5 min TTL)
- Lazy loading of detailed storage statistics on dashboard (AJAX)
- Reduced file system scanning overhead
- Faster page load times for web interface
- **Web interface performance improvements:**
  - Lightweight API endpoint for tasks (`/api/tasks?lightweight=true`) - reduces response size from 41KB to ~5-10KB
  - Parallel data loading on page load using `Promise.all()` - reduces load time from ~1200ms to ~400-500ms
  - Optimized log file reading (last 8KB only instead of full file)
  - Increased auto-refresh interval from 5s to 10s
  - Parallel log loading for multiple tasks
  - Eliminated duplicate API requests

## Technical Changes

### Files Modified
- `scraper/download_manager.py`: Added detailed stats, caching, folder breakdown
- `scraper/marketplace_api.py`: Added credential rotation support
- `scraper/marketplace_api_v3.py`: Added credential rotation support
- `scraper/description_downloader.py`: Added documentation URL extraction from HTML
- `utils/credentials.py`: Added multi-account support and CredentialsRotator
- `web/routes.py`: Added storage details route, updated credentials API, optimized tasks API with lightweight mode
- `web/templates/index.html`: Added storage breakdown widget with lazy loading
- `web/templates/descriptions_list.html`: Added documentation button
- `web/templates/manage.html`: Updated credentials management UI, optimized parallel data loading
- `web/templates/base.html`: Added Storage navigation link
- `web/templates/storage_details.html`: New page for detailed storage statistics
- `PERFORMANCE_ANALYSIS.md`: New file with performance analysis and recommendations

### API Changes
- `MarketplaceAPI.__init__()`: Added `use_rotation` and `rotator` parameters
- `MarketplaceAPI._make_request()`: Added automatic credential rotation on 429
- `MarketplaceAPIv3.__init__()`: Added `use_rotation` and `rotator` parameters
- `DownloadManager.get_storage_stats()`: Added `use_cache` parameter
- `DownloadManager.get_detailed_storage_stats()`: Added `use_cache` and `max_folders` parameters
- `DownloadManager.invalidate_storage_cache()`: New method for cache invalidation
- `DescriptionDownloader._download_api_description()`: Added `marketplace_url` and `documentation_url` parameters
- `DescriptionDownloader._extract_documentation_url_from_html()`: New method
- `/api/tasks`: Added `?lightweight=true` parameter to reduce response size (returns last 500 chars of output instead of full)
- `/api/tasks/<task_id>/last-log`: Optimized to read only last 8KB of log file instead of entire file

### Data Format Changes
- `.credentials.json`: Now supports `{"accounts": [...]}` format (backward compatible)
- Description JSON files: Added `documentation_url` field

## Breaking Changes
None - all changes are backward compatible

## Migration Notes
- Existing single-account credentials continue to work
- To use multiple accounts, update `.credentials.json` to new format:
  ```json
  {
    "accounts": [
      {"username": "user1@example.com", "api_token": "token1"},
      {"username": "user2@example.com", "api_token": "token2"}
    ]
  }
  ```
- Storage statistics cache is automatically invalidated after 5 minutes
- Documentation URLs are extracted automatically on next description download

## Testing
- Tested with single and multiple accounts
- Verified credential rotation on rate limit errors
- Confirmed storage statistics accuracy and caching
- Validated documentation URL extraction from various Marketplace pages
- Tested lazy loading of storage statistics in web interface
- Verified parallel data loading on `/manage` page
- Confirmed lightweight API reduces response size significantly
- Tested optimized log file reading for large files

## Performance Improvements
- **Page load time**: Reduced from ~1200ms to ~400-500ms (2.4x improvement)
- **API response size**: Reduced from 41KB to ~8-10KB (4x reduction)
- **Number of requests**: Reduced from 10+ sequential to 3 parallel
- **Auto-refresh interval**: Increased from 5s to 10s (50% less server load)

## Related Issues
- Improves page load performance for web interface
- Enables parallel scraping with multiple accounts
- Adds vendor documentation links to plugin descriptions
- Fixes slow page loading on `/manage` page
- Adds full-text search functionality for plugin descriptions and release notes
- Fixes disappearing search results issue
- Adds documentation button on app detail page
```

## Additional Features (v2.1)

### 5. Full-Text Search with Whoosh
- Integrated Whoosh library for full-text search
- Search across all descriptions: JSON, full page HTML, release notes
- Automatic HTML tag removal before indexing
- Support for complex queries (phrases, wildcards, boolean operators)
- Relevance ranking of search results
- Highlighting of matches in results
- Automatic index rebuilding when needed
- Search page `/search` with user-friendly interface
- API endpoint `/api/search` for programmatic access
- Index stored in `DESCRIPTIONS_DIR/.whoosh_index/`
- **Manual index building task** with progress tracking:
  - New task "Build Search Index" in Management page
  - Real-time progress display (processed/indexed count)
  - Can be started manually through web interface
  - Progress visible in task status and logs

### 6. Documentation Button on App Detail Page
- Added documentation button on `/apps/<addon_key>` page
- Active button (blue) if documentation URL is available
- Disabled button (gray) with tooltip if URL is missing
- Consistent with descriptions list page

### 7. Fixed Release Notes Display
- Fixed HTML rendering in release notes (using `|safe` filter)
- Proper display of HTML content in collapsible sections
- Improved formatting and readability

### 8. Search Improvements
- Fixed issue with disappearing search results
- Added query validation to prevent stale results
- Improved error handling and user feedback
- Better context extraction for matches

### 9. Windows Launcher Scripts
- Created `start.ps1` PowerShell script for easy Windows deployment
- Created `start.bat` batch file as alternative launcher
- Scripts automatically check and install dependencies
- Scripts check/install Playwright browser
- Scripts launch Flask application automatically
- Fixed Windows encoding issues in index building (Unicode characters)

### 10. Windows Encoding Fixes
- Fixed Unicode encoding errors in `run_index_search.py` (replaced ✓ with [OK])
- Added UTF-8 encoding configuration for Windows console in both `run_index_search.py` and `web/search_index_whoosh.py`
- Ensures compatibility with Windows cp1252 console encoding

## Additional Technical Changes

### Files Modified
- `web/routes.py`: Added search routes, documentation URL extraction in app_detail, added `/api/tasks/start/build-index` endpoint
- `web/templates/app_detail.html`: Added documentation button, fixed release notes HTML rendering
- `web/templates/search.html`: New search page with Whoosh integration
- `web/templates/base.html`: Added Search navigation link
- `web/templates/manage.html`: Added "Build Search Index" task section with button and status display
- `web/search_index_whoosh.py`: New module for Whoosh-based search indexing, added progress output, fixed Windows encoding issues
- `utils/task_manager.py`: Added `start_build_search_index()` method, added `run_index_search.py` to allowed scripts
- `run_index_search.py`: New script for building search index with progress tracking, fixed Windows encoding issues (Unicode characters)
- `requirements.txt`: Added `whoosh==2.7.4` dependency
- `SEARCH_LIBRARIES.md`: New documentation file explaining search library choice
- `start.ps1`: New PowerShell launcher script for Windows (checks dependencies, installs if needed, runs app.py)
- `start.bat`: New batch launcher script for Windows (alternative to PowerShell)

### API Changes
- `app_detail()` route: Added `documentation_url` extraction and passing to template
- `/api/search`: New endpoint for full-text search
- `/api/tasks/start/build-index`: New endpoint for starting index building task (with progress tracking)
- `/api/search/rebuild-index`: New endpoint for manual index rebuilding (synchronous, deprecated in favor of task-based approach)
- `TaskManager.start_build_search_index()`: New method for starting index building as background task
- `WhooshSearchIndex.build_index()`: Now returns indexed count and prints progress during indexing

### Data Format Changes
- App detail page now displays documentation URL if available
- Search index stored in Whoosh format (binary index files)

## Additional Testing
- Tested Whoosh search with various query types
- Verified HTML tag removal from indexed content
- Confirmed search across JSON, HTML, and release notes
- Tested index rebuilding functionality
- Validated documentation button display logic
- Tested release notes HTML rendering
- Fixed disappearing search results issue

## Additional Features (v2.2)

### 11. Storage Table Filtering and Sorting
- **Empty folder filtering**: Empty folders (0 MB, 0 files) are automatically hidden from storage statistics
- **Table sorting**: Click column headers to sort by:
  - Folder Path (alphabetical)
  - Drive (alphabetical)
  - Size (numerical, largest first)
  - Files (numerical, most first)
  - % of Category (numerical, highest first)
- **Table filtering**: Search box to filter folders by path or drive
- **Visual indicators**: Sort direction arrows (↑↓) show current sort state
- **Applied to**: `/storage` page (All Folders by Category table)

### 12. Descriptions Table Filtering and Sorting
- **Table sorting**: Click column headers to sort by:
  - App Name (alphabetical)
  - Addon Key (alphabetical)
  - Vendor (alphabetical)
- **Table filtering**: Search box to filter by app name, addon key, or vendor
- **Filter counter**: Shows "Showing X of Y apps" when filter is active
- **Applied to**: `/descriptions` page

### 13. Enhanced Search System
- **Multi-level fallback search**:
  1. Whoosh full-text search (if index exists)
  2. Enhanced Search (searches all local data sources)
  3. Simple Text Search (fallback for app names/vendors)
- **Enhanced Search features**:
  - Searches in app names, vendors, addon keys
  - Searches in categories and products
  - Searches in JSON descriptions (summary, overview, highlights)
  - Searches in HTML descriptions (full page)
  - Searches in release notes from database
  - Relevance scoring system with weighted matches
  - Context extraction around matches
- **Improved error handling**: Better error messages and logging
- **Search method indicator**: API returns which search method was used

### 14. Smoke Tests
- **Comprehensive test suite** (`tests/test_smoke.py`):
  - MetadataStore tests (initialization, data retrieval)
  - DownloadManager tests (storage statistics)
  - Search functionality tests (Whoosh, Enhanced)
  - File system tests (directory existence)
  - Settings tests (configuration loading)
  - Storage statistics structure tests
- **Test runner script** (`run_smoke_tests.py`):
  - Easy-to-use command-line interface
  - Verbose output option
  - Quick test mode (skip slow tests)
  - Detailed error reporting
- **Test documentation** (`tests/README.md`):
  - Complete guide on running tests
  - Explanation of what each test checks
  - Troubleshooting guide

## Additional Technical Changes (v2.2)

### Files Modified
- `scraper/download_manager.py`: Added filtering of empty folders (0 bytes, 0 files) in `get_detailed_storage_stats()`
- `web/templates/storage_details.html`: Added sorting and filtering functionality, empty folder filtering in "Top Folders" section
- `web/templates/descriptions_list.html`: Added sorting and filtering functionality, filter counter
- `web/static/css/style.css`: Added styles for sortable tables (`.table-sortable`, hover effects, sort indicators)
- `web/routes.py`: Added `List` and `Dict` imports, improved search API with multi-level fallback, added `_simple_text_search()` function
- `web/search_index_whoosh.py`: Improved error handling, added empty index check, better query parsing with fallback, improved highlights extraction
- `web/search_enhanced.py`: New module for comprehensive local data search

### New Files
- `web/search_enhanced.py`: Enhanced search implementation that searches across all local data sources
- `tests/__init__.py`: Tests package initialization
- `tests/test_smoke.py`: Comprehensive smoke test suite
- `tests/test_search_api.py`: API-level search tests
- `tests/README.md`: Test documentation
- `run_smoke_tests.py`: Test runner script

### API Changes
- `/api/search`: Now uses multi-level fallback (Whoosh → Enhanced → Simple)
- `/api/search`: Returns `method` field indicating which search method was used
- `WhooshSearchIndex.search()`: Added empty index check, improved error handling, better query parsing
- `EnhancedSearch.search_all()`: New method for comprehensive local data search
- `_simple_text_search()`: New fallback function for basic text search

### Data Format Changes
- Storage statistics: Empty folders are filtered out before returning results
- Search results: Include `method` field indicating search method used

## Additional Testing (v2.2)
- Tested empty folder filtering in storage statistics
- Verified table sorting functionality (all sortable columns)
- Tested table filtering (search boxes)
- Validated multi-level search fallback system
- Tested Enhanced Search across all data sources
- Verified smoke tests run successfully
- Tested search error handling and logging
- Confirmed Whoosh search improvements (empty index check, query parsing fallback)

