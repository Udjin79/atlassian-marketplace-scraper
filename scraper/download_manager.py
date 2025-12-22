"""Download manager for app version binaries."""

import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict
from tqdm import tqdm
from config import settings
from scraper.marketplace_api import MarketplaceAPI
from scraper.metadata_store import MetadataStore
from models.download import DownloadStatus
from utils.logger import get_logger

logger = get_logger('download')


class DownloadManager:
    """Manages downloading of app version binaries."""

    def __init__(self, api: Optional[MarketplaceAPI] = None,
                 store: Optional[MetadataStore] = None):
        """
        Initialize download manager.

        Args:
            api: MarketplaceAPI instance
            store: MetadataStore instance
        """
        self.api = api or MarketplaceAPI()
        self.store = store or MetadataStore()
        
        # Cache for storage statistics (TTL: 5 minutes)
        self._storage_stats_cache = None
        self._storage_stats_cache_time = 0
        self._storage_stats_cache_ttl = 300  # 5 minutes
        
        self._detailed_storage_stats_cache = None
        self._detailed_storage_stats_cache_time = 0
        self._detailed_storage_stats_cache_ttl = 300  # 5 minutes
        self.max_workers = settings.MAX_CONCURRENT_DOWNLOADS
        self.max_retries = settings.MAX_RETRY_ATTEMPTS

    def download_all_versions(self, product: Optional[str] = None):
        """
        Download all versions that haven't been downloaded yet.

        Args:
            product: Optional product filter
        """
        apps = self.store.get_all_apps()
        if product:
            apps = [app for app in apps if product in app.get('products', [])]

        if not apps:
            print("❌ No apps found")
            return

        print(f"🔄 Preparing to download versions for {len(apps)} apps...")

        # Collect all downloadable versions
        download_queue = []

        for app in apps:
            addon_key = app.get('addon_key')
            versions = self.store.get_app_versions(addon_key)

            for version in versions:
                if not version.get('downloaded', False):
                    # Determine product for this app
                    app_product = app.get('products', ['unknown'])[0]
                    download_queue.append({
                        'app': app,
                        'version': version,
                        'product': app_product
                    })

        if not download_queue:
            print("✅ All versions already downloaded!")
            return

        print(f"📦 {len(download_queue)} versions to download")
        print(f"🔧 Using {self.max_workers} concurrent downloads\n")

        # Download with thread pool
        completed = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all download tasks
            future_to_item = {
                executor.submit(
                    self._download_single_version,
                    item['app']['addon_key'],
                    item['version'],
                    item['product']
                ): item
                for item in download_queue
            }

            # Process completed downloads with progress bar
            with tqdm(total=len(download_queue), desc="Downloading", unit="file") as pbar:
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        success = future.result()
                        if success:
                            completed += 1
                        else:
                            failed += 1
                    except Exception as e:
                        logger.error(f"Download exception: {str(e)}")
                        failed += 1

                    pbar.update(1)

        print(f"\n✅ Download complete!")
        print(f"   Successfully downloaded: {completed}")
        print(f"   Failed: {failed}")

    def _download_single_version(self, addon_key: str, version: Dict,
                                 product: str) -> bool:
        """
        Download a single version binary.

        Args:
            addon_key: App key
            version: Version dictionary
            product: Product name for directory organization

        Returns:
            True if successful, False otherwise
        """
        version_id = version.get('version_id')
        version_name = version.get('version_name', version_id)

        # Create download status
        status = DownloadStatus(
            app_key=addon_key,
            version_id=str(version_id),
            status='pending'
        )

        try:
            # Construct download URL
            download_url = version.get('download_url')
            if not download_url:
                # Try to construct it
                download_url = self.api.get_download_url(addon_key, version_id)

            if not download_url:
                logger.error(f"No download URL for {addon_key} v{version_name}")
                return False

            # Create save directory using product-specific storage
            product_binaries_dir = settings.get_binaries_dir_for_product(product)
            save_dir = os.path.join(
                product_binaries_dir,
                addon_key,
                str(version_id)
            )
            os.makedirs(save_dir, exist_ok=True)

            # Determine file name
            file_name = version.get('file_name')
            if not file_name:
                # Extract from URL or use default
                file_name = f"{addon_key}-{version_id}.jar"

            file_path = os.path.join(save_dir, file_name)

            # Check if already exists
            if os.path.exists(file_path):
                logger.debug(f"File already exists: {file_path}")
                self.store.update_version_download_status(
                    addon_key, version_id, True, file_path
                )
                return True

            # Download with retries
            for attempt in range(self.max_retries):
                try:
                    status.mark_started()

                    response = requests.get(download_url, stream=True, timeout=60)
                    response.raise_for_status()

                    total_size = int(response.headers.get('content-length', 0))
                    status.total_bytes = total_size

                    # Download file
                    with open(file_path, 'wb') as f:
                        downloaded = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                status.downloaded_bytes = downloaded

                    # Verify file size
                    actual_size = os.path.getsize(file_path)
                    if total_size > 0 and actual_size != total_size:
                        raise Exception(f"File size mismatch: expected {total_size}, got {actual_size}")

                    # Mark as completed
                    status.mark_completed(file_path)
                    self.store.update_version_download_status(
                        addon_key, version_id, True, file_path
                    )

                    logger.info(f"Downloaded: {addon_key} v{version_name} ({actual_size} bytes)")
                    return True

                except Exception as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Download attempt {attempt + 1} failed for {addon_key} v{version_name}: {str(e)}")
                        # Clean up partial download
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        continue
                    else:
                        raise

        except Exception as e:
            error_msg = str(e)
            status.mark_failed(error_msg)
            logger.error(f"Failed to download {addon_key} v{version_name}: {error_msg}")
            return False

        return False

    def download_specific_version(self, addon_key: str, version_id: str):
        """
        Download a specific version.

        Args:
            addon_key: App key
            version_id: Version ID
        """
        # Get app and version info
        app = self.store.get_app_by_key(addon_key)
        if not app:
            print(f"❌ App not found: {addon_key}")
            return

        versions = self.store.get_app_versions(addon_key)
        version = None
        for v in versions:
            if str(v.get('version_id')) == str(version_id):
                version = v
                break

        if not version:
            print(f"❌ Version not found: {version_id}")
            return

        product = app.get('products', ['unknown'])[0]

        print(f"🔄 Downloading {addon_key} v{version.get('version_name')}...")

        success = self._download_single_version(addon_key, version, product)

        if success:
            print(f"✅ Download complete!")
        else:
            print(f"❌ Download failed")

    def get_storage_stats(self, use_cache: bool = True) -> Dict:
        """
        Get storage statistics from all product-specific directories.

        Args:
            use_cache: If True, use cached results if available and not expired

        Returns:
            Dictionary with storage stats
        """
        # Check cache
        if use_cache:
            current_time = time.time()
            if (self._storage_stats_cache is not None and 
                current_time - self._storage_stats_cache_time < self._storage_stats_cache_ttl):
                logger.debug("Returning cached storage stats")
                return self._storage_stats_cache
        
        total_size = 0
        file_count = 0
        
        # Get all directories to check (product-specific + base fallback)
        directories_to_check = set()
        
        # Add all product-specific directories
        for product_dir in settings.PRODUCT_STORAGE_MAP.values():
            if os.path.exists(product_dir):
                directories_to_check.add(product_dir)
        
        # Also check base directory as fallback
        if os.path.exists(settings.BINARIES_BASE_DIR):
            directories_to_check.add(settings.BINARIES_BASE_DIR)
        
        # If no product-specific dirs exist, check default
        if not directories_to_check and os.path.exists(settings.BINARIES_DIR):
            directories_to_check.add(settings.BINARIES_DIR)

        # Walk through all directories
        for directory in directories_to_check:
            if not os.path.exists(directory):
                continue
                
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                        file_count += 1
                    except OSError:
                        pass

        # Convert to human-readable format
        size_gb = total_size / (1024 ** 3)
        size_mb = total_size / (1024 ** 2)

        result = {
            'total_bytes': total_size,
            'total_mb': round(size_mb, 2),
            'total_gb': round(size_gb, 2),
            'file_count': file_count
        }
        
        # Update cache
        self._storage_stats_cache = result
        self._storage_stats_cache_time = time.time()
        
        return result
    
    def invalidate_storage_cache(self):
        """Invalidate storage statistics cache."""
        self._storage_stats_cache = None
        self._storage_stats_cache_time = 0
        self._detailed_storage_stats_cache = None
        self._detailed_storage_stats_cache_time = 0
        logger.debug("Storage statistics cache invalidated")
    
    def get_detailed_storage_stats(self, use_cache: bool = True, max_folders: int = 100) -> Dict:
        """
        Get detailed storage statistics with breakdown by category, disk, and individual folders.

        Args:
            use_cache: If True, use cached results if available and not expired
            max_folders: Maximum number of folders to track per category (for performance)

        Returns:
            Dictionary with detailed storage stats by category, disk, and folders
        """
        # Check cache
        if use_cache:
            current_time = time.time()
            if (self._detailed_storage_stats_cache is not None and 
                current_time - self._detailed_storage_stats_cache_time < self._detailed_storage_stats_cache_ttl):
                logger.debug("Returning cached detailed storage stats")
                return self._detailed_storage_stats_cache
        
        from pathlib import Path
        import os
        
        logger.info("Calculating detailed storage statistics (this may take a while)...")
        
        categories = {
            'binaries': {
                'paths': [],
                'size': 0,
                'file_count': 0,
                'by_disk': {},
                'folders': {}
            },
            'descriptions': {
                'paths': [],
                'size': 0,
                'file_count': 0,
                'by_disk': {},
                'folders': {}
            },
            'metadata': {
                'paths': [],
                'size': 0,
                'file_count': 0,
                'by_disk': {},
                'folders': {}
            }
        }
        
        # Add binaries directories
        for product_dir in settings.PRODUCT_STORAGE_MAP.values():
            if os.path.exists(product_dir):
                categories['binaries']['paths'].append(product_dir)
        if os.path.exists(settings.BINARIES_BASE_DIR):
            categories['binaries']['paths'].append(settings.BINARIES_BASE_DIR)
        if os.path.exists(settings.BINARIES_DIR):
            categories['binaries']['paths'].append(settings.BINARIES_DIR)
        
        # Add descriptions directory
        if os.path.exists(settings.DESCRIPTIONS_DIR):
            categories['descriptions']['paths'].append(settings.DESCRIPTIONS_DIR)
        
        # Add metadata directory
        if os.path.exists(settings.METADATA_DIR):
            categories['metadata']['paths'].append(settings.METADATA_DIR)
        
        # Calculate stats for each category
        for category, data in categories.items():
            for path in data['paths']:
                if not os.path.exists(path):
                    continue
                
                # Get disk drive
                drive = Path(path).anchor
                if drive not in data['by_disk']:
                    data['by_disk'][drive] = {'size': 0, 'file_count': 0}
                
                # Track individual folders
                path_str = str(path)
                if path_str not in data['folders']:
                    data['folders'][path_str] = {'size': 0, 'file_count': 0, 'drive': drive}
                
                # Walk through directory (limit depth for performance)
                folder_count = 0
                for root, dirs, files in os.walk(path):
                    # Calculate size for current directory
                    dir_size = 0
                    dir_file_count = 0
                    
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            file_size = os.path.getsize(file_path)
                            dir_size += file_size
                            dir_file_count += 1
                            data['size'] += file_size
                            data['file_count'] += 1
                            data['by_disk'][drive]['size'] += file_size
                            data['by_disk'][drive]['file_count'] += 1
                        except OSError:
                            pass
                    
                    # Store folder stats (only for top-level folders to avoid too much detail)
                    # Limit number of folders tracked for performance
                    if folder_count < max_folders:
                        if root == path or os.path.dirname(root) == path:
                            folder_key = os.path.basename(root) if root != path else os.path.basename(path)
                            if folder_key and folder_key not in ['.', '..']:
                                full_folder_path = root if root != path else path
                                if full_folder_path not in data['folders']:
                                    data['folders'][full_folder_path] = {
                                        'size': dir_size,
                                        'file_count': dir_file_count,
                                        'drive': drive
                                    }
                                    folder_count += 1
                                else:
                                    data['folders'][full_folder_path]['size'] += dir_size
                                    data['folders'][full_folder_path]['file_count'] += dir_file_count
        
        # Convert to human-readable format
        result = {
            'categories': {},
            'total': {
                'bytes': 0,
                'mb': 0,
                'gb': 0,
                'file_count': 0
            },
            'by_disk': {},
            'folders': {}
        }
        
        for category, data in categories.items():
            size_gb = data['size'] / (1024 ** 3)
            size_mb = data['size'] / (1024 ** 2)
            
            result['categories'][category] = {
                'bytes': data['size'],
                'mb': round(size_mb, 2),
                'gb': round(size_gb, 2),
                'file_count': data['file_count'],
                'by_disk': {},
                'folders': []
            }
            
            # Add by_disk breakdown
            for drive, disk_data in data['by_disk'].items():
                disk_size_gb = disk_data['size'] / (1024 ** 3)
                disk_size_mb = disk_data['size'] / (1024 ** 2)
                result['categories'][category]['by_disk'][drive] = {
                    'bytes': disk_data['size'],
                    'mb': round(disk_size_mb, 2),
                    'gb': round(disk_size_gb, 2),
                    'file_count': disk_data['file_count']
                }
                
                # Add to total by disk
                if drive not in result['by_disk']:
                    result['by_disk'][drive] = {'bytes': 0, 'mb': 0, 'gb': 0, 'file_count': 0}
                result['by_disk'][drive]['bytes'] += disk_data['size']
                result['by_disk'][drive]['file_count'] += disk_data['file_count']
            
            # Add folder breakdown (filter out empty folders)
            for folder_path, folder_data in data['folders'].items():
                # Skip empty folders (0 bytes and 0 files)
                if folder_data['size'] == 0 and folder_data['file_count'] == 0:
                    continue
                    
                folder_size_gb = folder_data['size'] / (1024 ** 3)
                folder_size_mb = folder_data['size'] / (1024 ** 2)
                result['categories'][category]['folders'].append({
                    'path': folder_path,
                    'name': os.path.basename(folder_path) or folder_path,
                    'bytes': folder_data['size'],
                    'mb': round(folder_size_mb, 2),
                    'gb': round(folder_size_gb, 2),
                    'file_count': folder_data['file_count'],
                    'drive': folder_data['drive']
                })
            
            # Sort folders by size (largest first)
            result['categories'][category]['folders'].sort(key=lambda x: x['bytes'], reverse=True)
            
            result['total']['bytes'] += data['size']
            result['total']['file_count'] += data['file_count']
        
        # Convert totals
        result['total']['gb'] = round(result['total']['bytes'] / (1024 ** 3), 2)
        result['total']['mb'] = round(result['total']['bytes'] / (1024 ** 2), 2)
        
        # Convert by_disk totals
        for drive in result['by_disk']:
            result['by_disk'][drive]['gb'] = round(result['by_disk'][drive]['bytes'] / (1024 ** 3), 2)
            result['by_disk'][drive]['mb'] = round(result['by_disk'][drive]['bytes'] / (1024 ** 2), 2)
        
        # Update cache
        self._detailed_storage_stats_cache = result
        self._detailed_storage_stats_cache_time = time.time()
        
        logger.info("Detailed storage statistics calculated successfully")
        return result