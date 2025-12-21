"""Atlassian Marketplace API v3 client for version compatibility."""

import requests
from typing import List, Dict, Optional
from config import settings
from utils.logger import get_logger
from utils.credentials import get_credentials_rotator, CredentialsRotator

logger = get_logger('scraper')


class MarketplaceAPIv3:
    """Client for Atlassian Marketplace REST API v3."""

    def __init__(self, username=None, api_token=None, metadata_store=None, use_rotation=False, rotator: Optional[CredentialsRotator] = None):
        """
        Initialize the Marketplace API v3 client.

        Args:
            username: Atlassian account username (email) - if provided, uses this account
            api_token: API token from Atlassian - if provided, uses this token
            metadata_store: Optional MetadataStore instance for caching
            use_rotation: If True, uses credential rotation for parallel requests
            rotator: Optional CredentialsRotator instance (if None and use_rotation=True, uses global rotator)
        """
        self.use_rotation = use_rotation
        self.rotator = rotator or (get_credentials_rotator() if use_rotation else None)
        
        if username and api_token:
            # Use provided credentials
            self.username = username
            self.api_token = api_token
        elif use_rotation and self.rotator:
            # Use rotation - get next credentials
            creds = self.rotator.get_next()
            self.username = creds.get('username') if creds else settings.MARKETPLACE_USERNAME
            self.api_token = creds.get('api_token') if creds else settings.MARKETPLACE_API_TOKEN
        else:
            # Use settings/default
            self.username = username or settings.MARKETPLACE_USERNAME
            self.api_token = api_token or settings.MARKETPLACE_API_TOKEN
        
        self.session = requests.Session()

        if self.username and self.api_token:
            self.session.auth = (self.username, self.api_token)

        self.base_url = 'https://api.atlassian.com/marketplace/rest/3'

        # Database store for persistent caching
        self.metadata_store = metadata_store

        # In-memory cache for parent software versions (session-only)
        self._parent_software_cache = {}
    
    def rotate_credentials(self):
        """Rotate to next credentials if using rotation."""
        if self.use_rotation and self.rotator:
            creds = self.rotator.get_next()
            if creds:
                self.username = creds.get('username', '')
                self.api_token = creds.get('api_token', '')
                self.session.auth = (self.username, self.api_token)
                logger.debug(f"Rotated to credentials for: {self.username}")

    def get_app_software_ids(self, addon_key: str) -> List[Dict]:
        """
        Get appSoftwareIds for an addon_key.

        Args:
            addon_key: The app's unique key

        Returns:
            List of dicts with appSoftwareId and hosting type
        """
        url = f'{self.base_url}/app-software/app-key/{addon_key}'

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            # Ensure UTF-8 encoding for response
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get appSoftwareIds for {addon_key}: {str(e)}")
            return []

    def get_app_versions_v3(self, app_software_id: str, limit: int = 50) -> Dict:
        """
        Get versions for an appSoftwareId with compatibility information.

        Args:
            app_software_id: The app software UUID
            limit: Number of versions to fetch per request

        Returns:
            Dictionary with versions list and pagination links
        """
        url = f'{self.base_url}/app-software/{app_software_id}/versions'
        params = {'limit': limit}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            # Ensure UTF-8 encoding for response
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get versions for {app_software_id}: {str(e)}")
            return {'versions': [], 'totalCount': 0}

    def get_all_app_versions_v3(self, app_software_id: str) -> List[Dict]:
        """
        Get ALL versions for an appSoftwareId (handles pagination).

        Args:
            app_software_id: The app software UUID

        Returns:
            List of all version dictionaries
        """
        all_versions = []
        next_cursor = None

        while True:
            url = f'{self.base_url}/app-software/{app_software_id}/versions'
            params = {'limit': 50}

            if next_cursor:
                params['cursor'] = next_cursor

            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                # Ensure UTF-8 encoding for response
                if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                    response.encoding = 'utf-8'
                data = response.json()

                versions = data.get('versions', [])
                if not versions:
                    break

                all_versions.extend(versions)

                # Check for next page
                next_link = data.get('links', {}).get('next')
                if not next_link:
                    break

                # Extract cursor from next link
                if '?cursor=' in next_link:
                    next_cursor = next_link.split('?cursor=')[-1]
                else:
                    break

            except Exception as e:
                logger.error(f"Error fetching versions: {str(e)}")
                break

        logger.info(f"Retrieved {len(all_versions)} versions for {app_software_id}")
        return all_versions

    def get_parent_software_versions(self, parent_software_id: str) -> List[Dict]:
        """
        Get all versions for a parent software (e.g., 'jira', 'confluence').
        Fetches from API and saves to database for future use.

        Args:
            parent_software_id: Parent software identifier

        Returns:
            List of version dictionaries with buildNumber and versionNumber
        """
        # Check in-memory cache first
        if parent_software_id in self._parent_software_cache:
            return self._parent_software_cache[parent_software_id]

        url = f'{self.base_url}/parent-software/{parent_software_id}/versions'

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            # Ensure UTF-8 encoding for response
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            data = response.json()

            versions = data.get('versions', [])

            # Cache the result in memory
            self._parent_software_cache[parent_software_id] = versions

            # Save to database for persistent caching
            if self.metadata_store and versions:
                self.metadata_store.save_parent_software_versions_batch(parent_software_id, versions)

            logger.info(f"Cached {len(versions)} versions for {parent_software_id}")
            return versions

        except Exception as e:
            logger.error(f"Failed to get parent software versions for {parent_software_id}: {str(e)}")
            return []

    def get_version_by_build_number(self, parent_software_id: str, build_number: int) -> Optional[Dict]:
        """
        Get version information for a specific build number.
        Saves to database if metadata_store is available.

        Args:
            parent_software_id: Parent software identifier (e.g., 'confluence', 'jira')
            build_number: Build number to look up

        Returns:
            Version dictionary or None if not found
        """
        url = f'{self.base_url}/parent-software/{parent_software_id}/versions/build/{build_number}'

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            # Ensure UTF-8 encoding for response
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            version_data = response.json()

            # Save to database for future use
            if self.metadata_store and version_data:
                version_number = version_data.get('versionNumber')
                if version_number:
                    self.metadata_store.save_parent_software_version(
                        parent_software_id, build_number, version_number
                    )

            return version_data
        except Exception as e:
            logger.debug(f"Failed to get version for build {build_number}: {str(e)}")
            return None

    def get_version_string_from_build(self, parent_software_id: str, build_number: int) -> Optional[str]:
        """
        Convert build number to version string (e.g., 22972 -> "10.0.1").
        Uses database cache first, then API if needed.

        Args:
            parent_software_id: Parent software identifier
            build_number: Build number to look up

        Returns:
            Version string or None if not found
        """
        # 1. Check database first (persistent cache)
        if self.metadata_store:
            db_version = self.metadata_store.get_parent_software_version(parent_software_id, build_number)
            if db_version:
                return db_version

        # 2. Check in-memory cache
        if parent_software_id in self._parent_software_cache:
            versions = self._parent_software_cache[parent_software_id]
            for version in versions:
                if version.get('buildNumber') == build_number:
                    return version.get('versionNumber')

        # 3. Try fetching all versions (saves to DB)
        versions = self.get_parent_software_versions(parent_software_id)
        for version in versions:
            if version.get('buildNumber') == build_number:
                return version.get('versionNumber')

        # 4. Fallback: fetch specific build version (saves to DB)
        version_data = self.get_version_by_build_number(parent_software_id, build_number)
        if version_data:
            return version_data.get('versionNumber')

        return None

    def format_compatibility_string(self, compatibility: Dict, hosting_type: str = 'server') -> Optional[str]:
        """
        Format compatibility dict to human-readable string.

        Args:
            compatibility: Dict with parentSoftwareId, minBuildNumber, maxBuildNumber
            hosting_type: Hosting type (server, datacenter, cloud)

        Returns:
            Formatted string like "Confluence Data Center 10.0.1 - 10.0.3" or None
        """
        parent_id = compatibility.get('parentSoftwareId')
        min_build = compatibility.get('minBuildNumber')
        max_build = compatibility.get('maxBuildNumber')

        if not all([parent_id, min_build, max_build]):
            return None

        # Get version strings
        min_version = self.get_version_string_from_build(parent_id, min_build)
        max_version = self.get_version_string_from_build(parent_id, max_build)

        # Determine hosting name
        hosting_name = 'Data Center' if hosting_type == 'datacenter' else 'Server'

        if not min_version or not max_version:
            # Fallback to build numbers if version strings not found
            return f"{parent_id.title()} {hosting_name} {min_build} - {max_build}"

        # Capitalize product name
        product_name = parent_id.title()

        return f"{product_name} {hosting_name} {min_version} - {max_version}"
