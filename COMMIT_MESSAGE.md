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

## Technical Changes

### Files Modified
- `scraper/download_manager.py`: Added detailed stats, caching, folder breakdown
- `scraper/marketplace_api.py`: Added credential rotation support
- `scraper/marketplace_api_v3.py`: Added credential rotation support
- `scraper/description_downloader.py`: Added documentation URL extraction from HTML
- `utils/credentials.py`: Added multi-account support and CredentialsRotator
- `web/routes.py`: Added storage details route, updated credentials API
- `web/templates/index.html`: Added storage breakdown widget with lazy loading
- `web/templates/descriptions_list.html`: Added documentation button
- `web/templates/manage.html`: Updated credentials management UI
- `web/templates/base.html`: Added Storage navigation link
- `web/templates/storage_details.html`: New page for detailed storage statistics

### API Changes
- `MarketplaceAPI.__init__()`: Added `use_rotation` and `rotator` parameters
- `MarketplaceAPI._make_request()`: Added automatic credential rotation on 429
- `MarketplaceAPIv3.__init__()`: Added `use_rotation` and `rotator` parameters
- `DownloadManager.get_storage_stats()`: Added `use_cache` parameter
- `DownloadManager.get_detailed_storage_stats()`: Added `use_cache` and `max_folders` parameters
- `DownloadManager.invalidate_storage_cache()`: New method for cache invalidation
- `DescriptionDownloader._download_api_description()`: Added `marketplace_url` and `documentation_url` parameters
- `DescriptionDownloader._extract_documentation_url_from_html()`: New method

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

## Related Issues
- Improves page load performance for web interface
- Enables parallel scraping with multiple accounts
- Adds vendor documentation links to plugin descriptions
```

