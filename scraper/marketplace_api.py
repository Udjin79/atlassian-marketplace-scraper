"""Atlassian Marketplace API client."""

import requests
import time
from typing import List, Dict, Optional
from config import settings
from utils.rate_limiter import RateLimiter
from utils.logger import get_logger
from utils.credentials import get_credentials_rotator, CredentialsRotator

logger = get_logger('scraper')


class MarketplaceAPI:
    """Client for interacting with Atlassian Marketplace REST API."""

    def __init__(self, username=None, api_token=None, use_rotation=False, rotator: Optional[CredentialsRotator] = None):
        """
        Initialize the Marketplace API client.

        Args:
            username: Atlassian account username (email) - if provided, uses this account
            api_token: API token from Atlassian - if provided, uses this token
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

        # Set up authentication if credentials provided
        if self.username and self.api_token:
            self.session.auth = (self.username, self.api_token)

        self.rate_limiter = RateLimiter(delay=settings.SCRAPER_REQUEST_DELAY)
        self.base_url_v2 = settings.MARKETPLACE_API_V2
        self.download_base_url = settings.MARKETPLACE_BASE_URL
    
    def rotate_credentials(self):
        """Rotate to next credentials if using rotation."""
        if self.use_rotation and self.rotator:
            creds = self.rotator.get_next()
            if creds:
                self.username = creds.get('username', '')
                self.api_token = creds.get('api_token', '')
                self.session.auth = (self.username, self.api_token)
                logger.debug(f"Rotated to credentials for: {self.username}")

    def _make_request(self, url, params=None, retry_count=0, rotate_on_429=True):
        """
        Make HTTP request with retry logic and rate limiting.

        Args:
            url: Request URL
            params: Query parameters
            retry_count: Current retry attempt
            rotate_on_429: If True, rotate credentials on 429 (rate limit) errors

        Returns:
            Response JSON data

        Raises:
            requests.exceptions.RequestException: On request failure after retries
        """
        self.rate_limiter.wait_if_needed()

        try:
            response = self.session.get(url, params=params, timeout=30)

            # Adjust rate limiting based on response status
            self.rate_limiter.adaptive_delay(response.status_code)

            response.raise_for_status()
            # Ensure UTF-8 encoding for response
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0

            # Rotate credentials on 429 if using rotation
            if status_code == 429 and rotate_on_429 and self.use_rotation and self.rotator:
                logger.warning(f"Rate limited (429), rotating credentials...")
                self.rotate_credentials()
                if retry_count < settings.MAX_RETRY_ATTEMPTS:
                    wait_time = 2 ** retry_count
                    time.sleep(wait_time)
                    return self._make_request(url, params, retry_count + 1, rotate_on_429=False)

            if status_code == 429 or status_code >= 500:
                # Retry on rate limit or server errors
                if retry_count < settings.MAX_RETRY_ATTEMPTS:
                    wait_time = 2 ** retry_count  # Exponential backoff
                    logger.warning(f"HTTP {status_code} error, retrying in {wait_time}s... (attempt {retry_count + 1}/{settings.MAX_RETRY_ATTEMPTS})")
                    time.sleep(wait_time)
                    return self._make_request(url, params, retry_count + 1, rotate_on_429)

            logger.error(f"HTTP error for {url}: {str(e)}")
            raise

        except requests.exceptions.RequestException as e:
            if retry_count < settings.MAX_RETRY_ATTEMPTS:
                wait_time = 2 ** retry_count
                logger.warning(f"Request error, retrying in {wait_time}s... (attempt {retry_count + 1}/{settings.MAX_RETRY_ATTEMPTS})")
                time.sleep(wait_time)
                return self._make_request(url, params, retry_count + 1, rotate_on_429)

            logger.error(f"Request failed for {url}: {str(e)}")
            raise

    def search_apps(self, hosting='server', application=None, offset=0, limit=50, cost=None):
        """
        Search for apps in the Marketplace.

        Args:
            hosting: Hosting type filter ('server', 'datacenter', 'cloud')
            application: Product filter ('jira', 'confluence', etc.)
            offset: Pagination offset
            limit: Number of results per page (max 100)
            cost: Pricing filter ('free', 'paid')

        Returns:
            Dictionary with 'embedded' containing app list and '_links' for pagination
        """
        url = f"{self.base_url_v2}/addons"
        params = {
            'offset': offset,
            'limit': min(limit, 100)  # API max is 100
        }

        if hosting:
            params['hosting'] = hosting
        if application:
            params['application'] = application
        if cost:
            params['cost'] = cost

        logger.info(f"Searching apps: hosting={hosting}, application={application}, offset={offset}, limit={limit}")

        try:
            data = self._make_request(url, params)
            return data
        except Exception as e:
            logger.error(f"Failed to search apps: {str(e)}")
            return {'_embedded': {'addons': []}}

    def get_app_details(self, addon_key, with_version=True):
        """
        Get detailed information about a specific app.

        Args:
            addon_key: The app's unique key
            with_version: Include latest version information

        Returns:
            Dictionary containing app details
        """
        url = f"{self.base_url_v2}/addons/{addon_key}"
        params = {}

        if with_version:
            params['withVersion'] = 'true'

        logger.debug(f"Fetching app details for: {addon_key}")

        try:
            return self._make_request(url, params)
        except Exception as e:
            logger.error(f"Failed to get app details for {addon_key}: {str(e)}")
            return None

    def get_app_versions(self, addon_key, offset=0, limit=50):
        """
        Get version list for an app.

        Args:
            addon_key: The app's unique key
            offset: Pagination offset
            limit: Number of results per page

        Returns:
            Dictionary with '_embedded' containing version list
        """
        url = f"{self.base_url_v2}/addons/{addon_key}/versions"
        params = {
            'offset': offset,
            'limit': min(limit, 100)
        }

        logger.debug(f"Fetching versions for {addon_key}: offset={offset}, limit={limit}")

        try:
            return self._make_request(url, params)
        except Exception as e:
            logger.error(f"Failed to get versions for {addon_key}: {str(e)}")
            return {'_embedded': {'versions': []}}

    def get_all_app_versions(self, addon_key):
        """
        Get ALL versions for an app (handles pagination automatically).

        Args:
            addon_key: The app's unique key

        Returns:
            List of all version dictionaries
        """
        all_versions = []
        offset = 0
        limit = 100

        while True:
            data = self.get_app_versions(addon_key, offset=offset, limit=limit)

            if not data or '_embedded' not in data:
                break

            versions = data['_embedded'].get('versions', [])
            if not versions:
                break

            all_versions.extend(versions)

            # Check if there are more pages
            links = data.get('_links', {})
            if 'next' not in links:
                break

            offset += len(versions)

        logger.info(f"Retrieved {len(all_versions)} total versions for {addon_key}")
        return all_versions

    def get_download_url(self, addon_key, version_id=None, build_number=None):
        """
        Construct download URL for an app version.

        Args:
            addon_key: The app's unique key
            version_id: Version ID (if known)
            build_number: Build number (alternative to version_id)

        Returns:
            Download URL string
        """
        # Try to use version_id first
        if version_id:
            return f"{self.download_base_url}/download/apps/{addon_key}/version/{version_id}"

        # Fallback to build number pattern (less reliable)
        if build_number:
            return f"{self.download_base_url}/download/apps/{addon_key}/version/{build_number}"

        logger.warning(f"Cannot construct download URL for {addon_key}: no version_id or build_number provided")
        return None

    def download_binary(self, url, save_path, progress_callback=None):
        """
        Download binary file from URL with streaming.

        Args:
            url: Download URL
            save_path: Local file path to save to
            progress_callback: Optional callback function(downloaded_bytes, total_bytes)

        Returns:
            True if successful, False otherwise
        """
        try:
            self.rate_limiter.wait_if_needed()

            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            with open(save_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback:
                            progress_callback(downloaded, total_size)

            logger.info(f"Downloaded {downloaded} bytes to {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download from {url}: {str(e)}")
            return False
