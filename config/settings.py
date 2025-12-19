"""Configuration management using environment variables."""

import os
from decouple import config

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
METADATA_DIR = os.path.join(DATA_DIR, 'metadata')
BINARIES_DIR = os.path.join(DATA_DIR, 'binaries')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Marketplace API Credentials
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
DATABASE_PATH = os.path.join(METADATA_DIR, 'marketplace.db')

# Ensure directories exist
for directory in [METADATA_DIR, VERSIONS_DIR, CHECKPOINTS_DIR, BINARIES_DIR, LOGS_DIR]:
    os.makedirs(directory, exist_ok=True)
