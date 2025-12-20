"""Storage reindexing utility to sync metadata with actual files on disk."""

import os
from typing import Dict, Tuple, List
from tqdm import tqdm
from config import settings
from scraper.metadata_store import MetadataStore
from utils.logger import get_logger

logger = get_logger('storage_reindex')


class StorageReindexer:
    """Reindexes storage to sync metadata with actual files on disk."""

    def __init__(self, store: MetadataStore = None):
        """
        Initialize storage reindexer.

        Args:
            store: MetadataStore instance
        """
        self.store = store or MetadataStore()
        self.binaries_dir = settings.BINARIES_DIR

    def reindex(self, verbose: bool = True) -> Dict[str, int]:
        """
        Reindex storage by comparing metadata with actual files on disk.

        This will:
        - Mark versions as not downloaded if files are missing
        - Clear file_path for missing files
        - Update statistics

        Args:
            verbose: Whether to print progress information

        Returns:
            Dictionary with reindex statistics
        """
        if verbose:
            print("🔄 Starting storage reindex...")
            print(f"📁 Binaries directory: {self.binaries_dir}")

        stats = {
            'total_versions': 0,
            'marked_downloaded': 0,
            'files_verified': 0,
            'files_missing': 0,
            'metadata_cleared': 0
        }

        # Early exit: Check if there are any downloaded versions
        downloaded_count = self.store.get_downloaded_versions_count()
        if downloaded_count == 0:
            if verbose:
                print("✅ No downloaded versions found - nothing to reindex!")
            return stats

        if verbose:
            print(f"📊 Found {downloaded_count} versions marked as downloaded")
            print("🔍 Verifying files on disk...")

        # Get all apps
        apps = self.store.get_all_apps()

        # Collect updates to batch process
        updates_to_clear: List[tuple] = []

        # Use progress bar for better UX
        with tqdm(total=len(apps), desc="Processing apps", disable=not verbose) as pbar:
            for app in apps:
                addon_key = app.get('addon_key')
                versions = self.store.get_app_versions(addon_key)

                if not versions:
                    pbar.update(1)
                    continue

                for version in versions:
                    stats['total_versions'] += 1

                    # Check if version is marked as downloaded
                    if version.get('downloaded', False):
                        stats['marked_downloaded'] += 1

                        # Verify file exists
                        file_path = version.get('file_path')

                        if file_path and os.path.exists(file_path):
                            # File exists, all good
                            stats['files_verified'] += 1
                        else:
                            # File is missing, queue for update
                            version_name = version.get('version_name', version.get('version_id'))
                            logger.debug(f"Missing file for {addon_key} v{version_name}: {file_path}")

                            updates_to_clear.append((addon_key, version.get('version_id')))
                            stats['files_missing'] += 1

                pbar.update(1)

        # Batch update all missing files
        if updates_to_clear:
            if verbose:
                print(f"\n🔄 Clearing {len(updates_to_clear)} download records...")

            with tqdm(total=len(updates_to_clear), desc="Updating metadata", disable=not verbose) as pbar:
                for addon_key, version_id in updates_to_clear:
                    self.store.update_version_download_status(
                        addon_key,
                        version_id,
                        downloaded=False,
                        file_path=None
                    )
                    stats['metadata_cleared'] += 1
                    pbar.update(1)

        if verbose:
            print("\n✅ Reindex complete!")
            print(f"   Total versions: {stats['total_versions']}")
            print(f"   Marked as downloaded: {stats['marked_downloaded']}")
            print(f"   Files verified: {stats['files_verified']}")
            print(f"   Files missing: {stats['files_missing']}")
            print(f"   Metadata cleared: {stats['metadata_cleared']}")

        logger.info(f"Storage reindex completed: {stats}")

        return stats

    def verify_file_exists(self, addon_key: str, version_id: str, product: str) -> Tuple[bool, str]:
        """
        Verify if a file exists for a specific version.

        Args:
            addon_key: App key
            version_id: Version ID
            product: Product name

        Returns:
            Tuple of (exists, file_path)
        """
        # Construct expected directory
        version_dir = os.path.join(
            self.binaries_dir,
            product,
            addon_key,
            str(version_id)
        )

        if not os.path.exists(version_dir):
            return False, None

        # Check for any files in the directory
        files = [f for f in os.listdir(version_dir) if os.path.isfile(os.path.join(version_dir, f))]

        if files:
            # Return first file found
            file_path = os.path.join(version_dir, files[0])
            return True, file_path

        return False, None

    def get_orphaned_files(self, verbose: bool = False) -> Dict[str, list]:
        """
        Find files on disk that aren't tracked in metadata.

        Args:
            verbose: Whether to print progress information

        Returns:
            Dictionary mapping product -> list of orphaned file paths
        """
        if verbose:
            print("🔍 Scanning for orphaned files...")

        orphaned = {}

        if not os.path.exists(self.binaries_dir):
            return orphaned

        # Walk through binaries directory
        for product_name in os.listdir(self.binaries_dir):
            product_dir = os.path.join(self.binaries_dir, product_name)

            if not os.path.isdir(product_dir):
                continue

            for addon_key in os.listdir(product_dir):
                app_dir = os.path.join(product_dir, addon_key)

                if not os.path.isdir(app_dir):
                    continue

                # Check if this app exists in metadata
                app = self.store.get_app_by_key(addon_key)

                if not app:
                    # Entire app directory is orphaned
                    if product_name not in orphaned:
                        orphaned[product_name] = []
                    orphaned[product_name].append(app_dir)
                    continue

                # Check each version directory
                versions = self.store.get_app_versions(addon_key)
                version_ids = {str(v.get('version_id')) for v in versions}

                for version_id in os.listdir(app_dir):
                    version_dir = os.path.join(app_dir, version_id)

                    if not os.path.isdir(version_dir):
                        continue

                    # Check if this version exists in metadata
                    if version_id not in version_ids:
                        if product_name not in orphaned:
                            orphaned[product_name] = []
                        orphaned[product_name].append(version_dir)

        if verbose:
            total_orphaned = sum(len(files) for files in orphaned.values())
            print(f"   Found {total_orphaned} orphaned directories")

        return orphaned

    def clean_orphaned_files(self, orphaned: Dict[str, list], verbose: bool = True) -> int:
        """
        Remove orphaned files from disk.

        Args:
            orphaned: Dictionary from get_orphaned_files()
            verbose: Whether to print progress

        Returns:
            Number of directories removed
        """
        import shutil

        removed_count = 0

        for product, paths in orphaned.items():
            for path in paths:
                try:
                    if verbose:
                        print(f"🗑️  Removing: {path}")

                    shutil.rmtree(path)
                    removed_count += 1

                except Exception as e:
                    logger.error(f"Failed to remove {path}: {str(e)}")

        if verbose:
            print(f"\n✅ Removed {removed_count} orphaned directories")

        return removed_count
