"""Data model for app versions."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Version:
    """Represents a version of an Atlassian Marketplace app."""

    addon_key: str
    version_id: str
    version_name: str
    build_number: str
    release_date: str
    release_notes: str = ""
    summary: str = ""
    compatible_products: Dict[str, List[str]] = field(default_factory=dict)
    compatibility: Optional[str] = None  # e.g., "Confluence Server 10.0.1 - 10.0.3"
    hosting_type: str = ""
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_path: Optional[str] = None
    downloaded: bool = False
    download_date: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Create Version instance from dictionary."""
        return cls(**data)

    @classmethod
    def from_api_response(cls, addon_key, api_data):
        """Create Version instance from Marketplace API response."""
        # Extract version_id from self link (e.g., /versions/build/1007420)
        version_id = ''
        if '_links' in api_data and 'self' in api_data['_links']:
            self_link = api_data['_links']['self']
            if isinstance(self_link, dict):
                href = self_link.get('href', '')
            else:
                href = self_link

            # Extract version_id from path like /versions/build/1007420
            if '/versions/build/' in href:
                version_id = href.split('/versions/build/')[-1]
            elif '/versions/' in href:
                version_id = href.split('/versions/')[-1]

        # Fallback to 'id' field if available
        if not version_id:
            version_id = str(api_data.get('id', ''))

        # Last resort: use version name as ID (not ideal but prevents empty IDs)
        if not version_id:
            version_id = api_data.get('name', 'unknown')

        # Extract build number
        build_number = api_data.get('buildNumber', api_data.get('name', ''))

        # Extract release date from nested 'release.date' field
        release_date = ''
        if 'release' in api_data and isinstance(api_data['release'], dict):
            release_date = api_data['release'].get('date', '')
        # Fallback to old format if new format not found
        if not release_date:
            release_date = api_data.get('releaseDate', api_data.get('published', ''))

        # Extract hosting type from deployment object
        hosting_type = 'server'  # Default
        if 'deployment' in api_data and isinstance(api_data['deployment'], dict):
            deployment = api_data['deployment']
            # Check which hosting types are supported
            if deployment.get('dataCenter'):
                hosting_type = 'datacenter'
            elif deployment.get('server'):
                hosting_type = 'server'
            elif deployment.get('cloud'):
                hosting_type = 'cloud'
        elif 'hosting' in api_data:
            # Fallback to old format
            if isinstance(api_data['hosting'], list):
                hosting_type = api_data['hosting'][0] if api_data['hosting'] else 'server'
            else:
                hosting_type = api_data['hosting']

        # Extract compatible products/versions
        compatible_products = {}
        if 'compatibilities' in api_data:
            for compat in api_data['compatibilities']:
                if isinstance(compat, dict):
                    product = compat.get('application', 'unknown')
                    version_range = compat.get('version', '')
                    if product not in compatible_products:
                        compatible_products[product] = []
                    compatible_products[product].append(version_range)

        # Extract download URL from embedded artifact
        download_url = None
        if '_embedded' in api_data and 'artifact' in api_data['_embedded']:
            artifact_links = api_data['_embedded']['artifact'].get('_links', {})
            if 'binary' in artifact_links:
                binary_link = artifact_links['binary']
                if isinstance(binary_link, dict):
                    download_url = binary_link.get('href')
                else:
                    download_url = binary_link
        # Fallback to old format
        if not download_url and '_links' in api_data:
            binary_link = api_data['_links'].get('binary')
            if isinstance(binary_link, dict):
                download_url = binary_link.get('href')
            else:
                download_url = binary_link

        return cls(
            addon_key=addon_key,
            version_id=version_id,
            version_name=api_data.get('name', ''),
            build_number=build_number,
            release_date=release_date,
            release_notes=api_data.get('releaseNotes', ''),
            summary=api_data.get('summary', ''),
            compatible_products=compatible_products,
            compatibility=None,  # Will be filled by v3 API if available
            hosting_type=hosting_type,
            download_url=download_url,
            file_size=api_data.get('fileSize')
        )

    @classmethod
    def from_v3_api_response(cls, addon_key, api_data, compatibility_string=None):
        """
        Create Version instance from Marketplace API v3 response.

        Args:
            addon_key: The app's unique key
            api_data: v3 API response dictionary
            compatibility_string: Pre-formatted compatibility string

        Returns:
            Version instance
        """
        # Extract version ID from build number
        version_id = str(api_data.get('buildNumber', ''))

        # Extract release date
        release_date = ''
        if 'releaseDetails' in api_data and api_data['releaseDetails']:
            release_details = api_data['releaseDetails']
            released_at = release_details.get('releasedAt', '') if release_details else ''
            if released_at:
                # Convert ISO format to simple date
                release_date = released_at[:10]  # "2025-11-17T18:12:55.536Z" -> "2025-11-17"

        # Fallback to createdAt if releasedAt not available
        if not release_date and 'createdAt' in api_data and api_data['createdAt']:
            release_date = api_data['createdAt'][:10]

        # Extract release notes from changelog
        release_notes = ''
        summary = ''
        if 'changelog' in api_data and api_data['changelog']:
            changelog = api_data['changelog']
            release_notes = changelog.get('releaseNotes', '') if changelog else ''
            summary = changelog.get('releaseSummary', '') if changelog else ''

        # Extract download URL from artifact
        download_url = None
        if 'frameworkDetails' in api_data and api_data['frameworkDetails']:
            framework = api_data['frameworkDetails']
            if framework and 'attributes' in framework and framework['attributes']:
                artifact_id = framework['attributes'].get('artifactId')
                if artifact_id:
                    download_url = f'https://marketplace.atlassian.com/artifacts/{artifact_id}/download'

        return cls(
            addon_key=addon_key,
            version_id=version_id,
            version_name=api_data.get('versionNumber', ''),
            build_number=str(api_data.get('buildNumber', '')),
            release_date=release_date,
            release_notes=release_notes,
            summary=summary,
            compatible_products={},  # v3 API uses compatibility field instead
            compatibility=compatibility_string,
            hosting_type='',  # Set by caller based on appSoftwareId hosting type
            download_url=download_url,
            file_size=None  # Not provided in v3 API
        )
