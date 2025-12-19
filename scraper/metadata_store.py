"""Metadata storage and retrieval using JSON files or SQLite database."""

import json
import os
from typing import List, Dict, Optional
from config import settings
from models.app import App
from models.version import Version
from utils.logger import get_logger

logger = get_logger('scraper')


class MetadataStoreJSON:
    """Handles storage and retrieval of app and version metadata."""

    def __init__(self):
        """Initialize metadata store."""
        self.apps_file = settings.APPS_JSON_PATH
        self.versions_dir = settings.VERSIONS_DIR

        # Ensure directories exist
        os.makedirs(os.path.dirname(self.apps_file), exist_ok=True)
        os.makedirs(self.versions_dir, exist_ok=True)

        # Initialize apps file if it doesn't exist
        if not os.path.exists(self.apps_file):
            self._write_json(self.apps_file, [])

    def _read_json(self, file_path):
        """Read JSON file safely."""
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return None
        except Exception as e:
            logger.error(f"Error reading {file_path}: {str(e)}")
            return None

    def _write_json(self, file_path, data):
        """Write JSON file safely."""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error writing {file_path}: {str(e)}")
            return False

    def save_app(self, app: App):
        """
        Save or update an app.

        Args:
            app: App instance to save
        """
        apps = self._read_json(self.apps_file) or []

        # Check if app already exists
        existing_index = None
        for i, existing_app in enumerate(apps):
            if existing_app.get('addon_key') == app.addon_key:
                existing_index = i
                break

        app_dict = app.to_dict()

        if existing_index is not None:
            # Update existing app
            apps[existing_index] = app_dict
            logger.debug(f"Updated app: {app.addon_key}")
        else:
            # Add new app
            apps.append(app_dict)
            logger.debug(f"Added new app: {app.addon_key}")

        self._write_json(self.apps_file, apps)

    def save_apps_batch(self, apps: List[App]):
        """
        Save multiple apps at once (more efficient).

        Args:
            apps: List of App instances
        """
        existing_apps = self._read_json(self.apps_file) or []
        existing_keys = {app.get('addon_key'): i for i, app in enumerate(existing_apps)}

        for app in apps:
            app_dict = app.to_dict()
            if app.addon_key in existing_keys:
                # Update existing
                existing_apps[existing_keys[app.addon_key]] = app_dict
            else:
                # Add new
                existing_apps.append(app_dict)

        self._write_json(self.apps_file, existing_apps)
        logger.info(f"Saved batch of {len(apps)} apps")

    def get_all_apps(self, filters: Optional[Dict] = None,
                     limit: Optional[int] = None,
                     offset: Optional[int] = 0) -> List[Dict]:
        """
        Get all apps with optional filtering and pagination.

        Args:
            filters: Optional filters (product, search, hosting)
            limit: Maximum apps to return (for pagination)
            offset: Number of apps to skip (for pagination)

        Returns:
            List of app dictionaries
        """
        apps = self._read_json(self.apps_file) or []

        if not filters:
            filtered = apps
        else:
            filtered = apps

            # Filter by product
            if 'product' in filters and filters['product']:
                filtered = [app for app in filtered
                           if filters['product'] in app.get('products', [])]

            # Filter by search query (name, vendor, key)
            if 'search' in filters and filters['search']:
                query = filters['search'].lower()
                filtered = [app for app in filtered
                           if query in app.get('name', '').lower()
                           or query in app.get('vendor', '').lower()
                           or query in app.get('addon_key', '').lower()]

            # Filter by hosting
            if 'hosting' in filters and filters['hosting']:
                filtered = [app for app in filtered
                           if filters['hosting'] in app.get('hosting', [])]

        # Apply pagination if specified
        if limit is not None:
            end_idx = offset + limit
            return filtered[offset:end_idx]

        return filtered

    def get_app_by_key(self, addon_key: str) -> Optional[Dict]:
        """
        Get a specific app by its key.

        Args:
            addon_key: The app's unique key

        Returns:
            App dictionary or None
        """
        apps = self._read_json(self.apps_file) or []

        for app in apps:
            if app.get('addon_key') == addon_key:
                return app

        return None

    def save_versions(self, addon_key: str, versions: List[Version]):
        """
        Save versions for an app.

        Args:
            addon_key: The app's unique key
            versions: List of Version instances
        """
        file_path = os.path.join(self.versions_dir, f"{addon_key}_versions.json")
        versions_data = [v.to_dict() for v in versions]

        self._write_json(file_path, versions_data)
        logger.debug(f"Saved {len(versions)} versions for {addon_key}")

        # Update app's total_versions count
        app = self.get_app_by_key(addon_key)
        if app:
            app['total_versions'] = len(versions)
            self.save_app(App.from_dict(app))

    def get_app_versions(self, addon_key: str) -> List[Dict]:
        """
        Get all versions for an app.

        Args:
            addon_key: The app's unique key

        Returns:
            List of version dictionaries
        """
        file_path = os.path.join(self.versions_dir, f"{addon_key}_versions.json")
        return self._read_json(file_path) or []

    def update_version_download_status(self, addon_key: str, version_id: str,
                                      downloaded: bool, file_path: Optional[str] = None):
        """
        Update download status for a specific version.

        Args:
            addon_key: The app's unique key
            version_id: The version ID
            downloaded: Whether the file has been downloaded
            file_path: Local file path (if downloaded)
        """
        versions = self.get_app_versions(addon_key)

        for version in versions:
            if str(version.get('version_id')) == str(version_id):
                version['downloaded'] = downloaded
                if file_path:
                    version['file_path'] = file_path
                    from datetime import datetime
                    version['download_date'] = datetime.now().isoformat()
                break

        file_path_versions = os.path.join(self.versions_dir, f"{addon_key}_versions.json")
        self._write_json(file_path_versions, versions)

    def get_apps_count(self, filters: Optional[Dict] = None) -> int:
        """
        Get total number of apps (optionally filtered).

        Args:
            filters: Optional filters (product, search, hosting)

        Returns:
            Count of apps
        """
        if filters:
            # Use get_all_apps to apply filters, then count
            apps = self.get_all_apps(filters)
            return len(apps)
        else:
            # Fast path: just count all apps
            apps = self._read_json(self.apps_file) or []
            return len(apps)

    def get_total_versions_count(self) -> int:
        """Get total number of versions across all apps."""
        total = 0
        for file_name in os.listdir(self.versions_dir):
            if file_name.endswith('_versions.json'):
                file_path = os.path.join(self.versions_dir, file_name)
                versions = self._read_json(file_path) or []
                total += len(versions)
        return total

    def get_downloaded_versions_count(self) -> int:
        """Get count of downloaded versions."""
        count = 0
        for file_name in os.listdir(self.versions_dir):
            if file_name.endswith('_versions.json'):
                file_path = os.path.join(self.versions_dir, file_name)
                versions = self._read_json(file_path) or []
                count += sum(1 for v in versions if v.get('downloaded', False))
        return count

    def search_apps(self, query: str, product: Optional[str] = None) -> List[Dict]:
        """
        Search apps by query string.

        Args:
            query: Search query
            product: Optional product filter

        Returns:
            List of matching app dictionaries
        """
        filters = {'search': query}
        if product:
            filters['product'] = product

        return self.get_all_apps(filters)


# Feature flag: Use SQLite or JSON storage
if settings.USE_SQLITE:
    from scraper.metadata_store_sqlite import MetadataStoreSQLite as MetadataStore
    logger.info("Using SQLite database for metadata storage")
else:
    MetadataStore = MetadataStoreJSON
    logger.info("Using JSON files for metadata storage")
