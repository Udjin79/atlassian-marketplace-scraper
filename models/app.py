"""Data model for Atlassian Marketplace apps."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class App:
    """Represents an Atlassian Marketplace app."""

    addon_key: str
    name: str
    vendor: str
    description: str
    logo_url: Optional[str] = None
    marketplace_url: Optional[str] = None
    products: List[str] = field(default_factory=list)
    hosting: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    total_versions: int = 0
    scraped_at: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Create App instance from dictionary."""
        return cls(**data)

    @classmethod
    def from_api_response(cls, api_data, product=None, hosting_type=None):
        """
        Create App instance from Marketplace API response.

        Args:
            api_data: API response dictionary
            product: Product context from search (e.g., 'jira', 'confluence')
            hosting_type: Hosting context from search (e.g., 'server', 'datacenter')
        """
        # Extract products (prefer API data, fallback to search context)
        products = []
        if 'application' in api_data:
            if isinstance(api_data['application'], list):
                products = api_data['application']
            else:
                products = [api_data['application']]
        elif product:
            # API doesn't return this field, use search context
            products = [product]

        # Extract hosting types (prefer API data, fallback to search context)
        hosting = []
        if 'hosting' in api_data:
            if isinstance(api_data['hosting'], list):
                hosting = api_data['hosting']
            else:
                hosting = [api_data['hosting']]
        elif hosting_type:
            # API doesn't return this field, use search context
            # Server hosting often includes datacenter as well
            hosting = ['server', 'datacenter'] if hosting_type == 'server' else [hosting_type]

        # Extract vendor name from embedded data or direct field
        vendor = ''
        if '_embedded' in api_data and 'vendor' in api_data['_embedded']:
            # Vendor info in embedded object
            vendor_data = api_data['_embedded']['vendor']
            vendor = vendor_data.get('name', '')
        elif 'vendor' in api_data:
            # Direct vendor field (rare)
            if isinstance(api_data['vendor'], dict):
                vendor = api_data['vendor'].get('name', '')
            else:
                vendor = api_data['vendor']

        # Extract categories from embedded data
        categories = []
        if '_embedded' in api_data and 'categories' in api_data['_embedded']:
            # Categories in embedded object
            categories = [cat.get('name', '') for cat in api_data['_embedded']['categories'] if cat.get('name')]
        elif 'categories' in api_data:
            # Direct categories field
            categories = [cat.get('name', cat) if isinstance(cat, dict) else cat
                         for cat in api_data['categories']]

        # Extract marketplace URL and ensure it's absolute
        marketplace_url = None
        if '_links' in api_data and 'alternate' in api_data['_links']:
            alternate = api_data['_links']['alternate']
            if isinstance(alternate, dict):
                marketplace_url = alternate.get('href', '')
            else:
                marketplace_url = alternate

            # Convert relative URL to absolute
            if marketplace_url and marketplace_url.startswith('/'):
                marketplace_url = f'https://marketplace.atlassian.com{marketplace_url}'

        return cls(
            addon_key=api_data.get('key', ''),
            name=api_data.get('name', ''),
            vendor=vendor,
            description=api_data.get('summary', ''),
            logo_url=api_data.get('logoUrl') or api_data.get('logo', {}).get('url'),
            marketplace_url=marketplace_url,
            products=products,
            hosting=hosting,
            categories=categories,
            last_updated=api_data.get('lastUpdated'),
            total_versions=0,
            scraped_at=datetime.now().isoformat()
        )
