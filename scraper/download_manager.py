"""Download manager for app version binaries."""

import os
import requests
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

            # Create save directory
            save_dir = os.path.join(
                settings.BINARIES_DIR,
                product,
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

    def get_storage_stats(self) -> Dict:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage stats
        """
        total_size = 0
        file_count = 0

        for root, dirs, files in os.walk(settings.BINARIES_DIR):
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

        return {
            'total_bytes': total_size,
            'total_mb': round(size_mb, 2),
            'total_gb': round(size_gb, 2),
            'file_count': file_count
        }
