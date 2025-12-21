"""Configuration management using environment variables."""

import os
from decouple import config

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Custom storage paths (can be set via environment variables)
# If not set, defaults to project directory
DATA_BASE_DIR = config('DATA_BASE_DIR', default=BASE_DIR)
DATA_DIR = os.path.join(DATA_BASE_DIR, 'data')
METADATA_DIR = config('METADATA_DIR', default=os.path.join(DATA_DIR, 'metadata'))
BINARIES_DIR = config('BINARIES_DIR', default=os.path.join(DATA_DIR, 'binaries'))
BINARIES_BASE_DIR = config('BINARIES_BASE_DIR', default=BINARIES_DIR)
LOGS_DIR = config('LOGS_DIR', default=os.path.join(BASE_DIR, 'logs'))
# Descriptions directory (can be set separately, defaults to METADATA_DIR/descriptions)
DESCRIPTIONS_DIR = config('DESCRIPTIONS_DIR', default=os.path.join(METADATA_DIR, 'descriptions'))

# Product-specific binary storage mapping
# Maps products to different drives for distributed storage
PRODUCT_STORAGE_MAP = {
    'jira': config('BINARIES_DIR_JIRA', default=os.path.join(BINARIES_BASE_DIR, 'jira')),
    'confluence': config('BINARIES_DIR_CONFLUENCE', default=os.path.join(BINARIES_BASE_DIR, 'confluence')),
    'bitbucket': config('BINARIES_DIR_BITBUCKET', default=os.path.join(BINARIES_BASE_DIR, 'bitbucket')),
    'bamboo': config('BINARIES_DIR_BAMBOO', default=os.path.join(BINARIES_BASE_DIR, 'bamboo')),
    'crowd': config('BINARIES_DIR_CROWD', default=os.path.join(BINARIES_BASE_DIR, 'crowd')),
}


def get_binaries_dir_for_product(product: str) -> str:
    """
    Get the storage directory for a specific product.
    
    Args:
        product: Product name (jira, confluence, bitbucket, bamboo, crowd)
        
    Returns:
        Path to the product's binary storage directory
    """
    product_lower = product.lower()
    if product_lower in PRODUCT_STORAGE_MAP:
        return PRODUCT_STORAGE_MAP[product_lower]
    # Fallback to default
    return os.path.join(BINARIES_BASE_DIR, product_lower)

# Marketplace API Credentials
# Try to load from credentials file first, then from env
try:
    from utils.credentials import get_credentials
    credentials = get_credentials()
    MARKETPLACE_USERNAME = config('MARKETPLACE_USERNAME', default=credentials.get('username', ''))
    MARKETPLACE_API_TOKEN = config('MARKETPLACE_API_TOKEN', default=credentials.get('api_token', ''))
except Exception:
    # Fallback to env only
    MARKETPLACE_USERNAME = config('MARKETPLACE_USERNAME', default='')
    MARKETPLACE_API_TOKEN = config('MARKETPLACE_API_TOKEN', default='')

# Scraper Settings
SCRAPER_BATCH_SIZE = config('SCRAPER_BATCH_SIZE', default=50, cast=int)
SCRAPER_REQUEST_DELAY = config('SCRAPER_REQUEST_DELAY', default=0.5, cast=float)
VERSION_AGE_LIMIT_DAYS = config('VERSION_AGE_LIMIT_DAYS', default=365, cast=int)
MAX_CONCURRENT_DOWNLOADS = config('MAX_CONCURRENT_DOWNLOADS', default=3, cast=int)
MAX_VERSION_SCRAPER_WORKERS = config('MAX_VERSION_SCRAPER_WORKERS', default=10, cast=int)
MAX_RETRY_ATTEMPTS = config('MAX_RETRY_ATTEMPTS', default=3, cast=int)

# Flask Settings
FLASK_DEBUG = config('FLASK_DEBUG', default=True, cast=bool)
FLASK_PORT = config('FLASK_PORT', default=5000, cast=int)
SECRET_KEY = config('SECRET_KEY', default='dev-secret-key-change-in-production')

# Logging Settings
LOG_LEVEL = config('LOG_LEVEL', default='INFO')

# API Endpoints
MARKETPLACE_BASE_URL = 'https://marketplace.atlassian.com'
MARKETPLACE_API_V2 = f'{MARKETPLACE_BASE_URL}/rest/2'
MARKETPLACE_API_V3 = 'https://api.atlassian.com/marketplace/rest/3'

# File paths
APPS_JSON_PATH = os.path.join(METADATA_DIR, 'apps.json')
VERSIONS_DIR = os.path.join(METADATA_DIR, 'versions')
CHECKPOINTS_DIR = os.path.join(METADATA_DIR, 'checkpoints')
CHECKPOINT_FILE = os.path.join(CHECKPOINTS_DIR, 'scrape_checkpoint.pkl')

# Database configuration
USE_SQLITE = config('USE_SQLITE', default=False, cast=bool)
DATABASE_PATH = config('DATABASE_PATH', default=os.path.join(METADATA_DIR, 'marketplace.db'))

# Ensure directories exist
for directory in [METADATA_DIR, VERSIONS_DIR, CHECKPOINTS_DIR, BINARIES_DIR, LOGS_DIR, DESCRIPTIONS_DIR]:
    os.makedirs(directory, exist_ok=True)

# Ensure product-specific binary directories exist
for product_dir in PRODUCT_STORAGE_MAP.values():
    os.makedirs(product_dir, exist_ok=True)
