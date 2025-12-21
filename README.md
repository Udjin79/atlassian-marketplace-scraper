# Atlassian Marketplace Scraper

A Python-based service to scrape the Atlassian Marketplace for Server/Data Center apps and versions, download binaries, and provide a web interface for browsing the collected data.

The stable release line is maintained in the `stable` branch.

## Features

- **Complete Marketplace Scraping**: Scrapes all apps across Jira, Confluence, Bitbucket, Bamboo, and Crowd
- **Version Filtering**: Filters versions released in the last year, Server/Data Center hosting only
- **Binary Downloads**: Downloads JAR/OBR files with resume capability
- **Web Interface**: Flask-based UI for browsing apps and versions
- **Checkpoint/Resume**: Robust checkpoint system for interrupted scraping
- **Concurrent Downloads**: Multi-threaded downloads with configurable concurrency
- **Metadata Storage**: SQLite database for apps and versions

## Architecture

```
AtlassianMarketplaceScraper/
├── app.py                      # Flask web application
├── run_scraper.py              # CLI: Scrape apps
├── run_version_scraper.py      # CLI: Scrape versions
├── run_downloader.py           # CLI: Download binaries
├── run_reindex.py              # CLI: Reindex storage
├── config/                     # Configuration
├── scraper/                    # Core scraping logic
│   ├── marketplace_api.py      # API client
│   ├── app_scraper.py          # App discovery
│   ├── version_scraper.py      # Version fetching
│   ├── download_manager.py     # Binary downloads
│   ├── metadata_store.py       # Data persistence
│   └── filters.py              # Date/hosting filters
├── models/                     # Data models
├── utils/                      # Utilities (logger, rate limiter, checkpoint)
├── web/                        # Flask web interface
│   ├── routes.py               # HTTP routes
│   ├── templates/              # HTML templates
│   └── static/                 # CSS/JS assets
└── data/                       # Downloaded data
    ├── metadata/               # SQLite metadata + checkpoints
    └── binaries/               # JAR/OBR files
```

## Installation

### Prerequisites

- Python 3.8+
- Atlassian Marketplace credentials (optional for public API)

### Setup

1. **Clone or navigate to the directory:**
   ```bash
   cd AtlassianMarketplaceScraper
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials (optional for public data)
   ```
5. **Create basic folders (optional; created automatically on first run):**
   ```bash
   mkdir -p data/metadata/versions data/metadata/checkpoints data/binaries logs
   ```

## Docker Deployment

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Quick Start

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials (optional for public data)
   ```

2. **Build and start the web interface:**
   ```bash
   docker-compose up -d web
   ```

   Access at http://localhost:5000

### Running Scraper Scripts

The scraper scripts use Docker profiles to avoid auto-starting:

```bash
# Step 1: Scrape apps
docker-compose run --rm scraper

# Step 2: Scrape versions (all products)
docker-compose run --rm version-scraper

# Step 2 (alternative): Scrape versions for specific product
docker-compose run --rm version-scraper python run_version_scraper.py crowd

# Step 3: Download binaries (all products)
docker-compose run --rm downloader

# Download specific product
docker-compose run --rm downloader python run_downloader.py jira

# Reindex storage (sync metadata with actual files on disk)
docker-compose run --rm web python run_reindex.py

# Reindex and clean orphaned files
docker-compose run --rm web python run_reindex.py --clean-orphaned
```

**Note:** The downloader automatically runs reindexing before starting downloads.

### Data Persistence

Data and logs are automatically persisted via Docker volumes:
- `./data/metadata` - Apps and versions metadata
- `./data/binaries` - Downloaded JAR/OBR files (or custom path via `BINARIES_PATH`)
- `./logs` - Application logs

### Using External Drive for Binaries

Binaries can be stored on a separate drive or shared storage (useful for large datasets):

1. **Set the path in .env:**
   ```bash
   # For local external drive
   BINARIES_PATH=/mnt/external-drive/atlassian-binaries

   # For network share
   BINARIES_PATH=/mnt/nas/atlassian-binaries
   ```

2. **Ensure the directory exists and has proper permissions:**
   ```bash
   mkdir -p /mnt/external-drive/atlassian-binaries
   chmod 755 /mnt/external-drive/atlassian-binaries
   ```

3. **Start services normally:**
   ```bash
   docker-compose up -d web
   ```

The binaries will be downloaded to your specified path while metadata stays in `./data/metadata`.

### Docker Commands

```bash
# View logs
docker-compose logs -f web

# Stop services
docker-compose down

# Rebuild after code changes
docker-compose build

# Force rebuild (no cache) - use after updates to ensure all changes are applied
docker-compose build --no-cache

# Remove all data (destructive)
docker-compose down -v
```

**Important:** After pulling updates or modifying code, rebuild with `--no-cache` to ensure all changes are applied.

### Docker Architecture

- **web**: Flask application on port 5000 (always running)
- **scraper**: App scraping service (on-demand via `run`)
- **version-scraper**: Version scraping service (on-demand via `run`)
- **downloader**: Binary download service (on-demand via `run`)

All services share the same network and volumes for data consistency.

## Usage

### Step 1: Scrape Apps

Discover all apps from the Atlassian Marketplace:

```bash
python run_scraper.py
```

**Options:**
- `--resume`: Resume from last checkpoint after interruption

**Output:**
- Apps metadata saved to `data/metadata/marketplace.db`
- Progress automatically checkpointed every 100 apps

### Step 2: Scrape Versions

Fetch version history for all apps (configurable age limit, Server/DC only):

```bash
# Scrape all products
python run_version_scraper.py

# Scrape specific product only
python run_version_scraper.py crowd
python run_version_scraper.py jira
```

**Output:**
- Version metadata saved to `data/metadata/marketplace.db`
- Versions filtered by date (last 365 days) and hosting type

### Step 3: Download Binaries

Download JAR/OBR files for all versions:

```bash
# Download all products
python run_downloader.py

# Download specific product
python run_downloader.py jira
```

**Features:**
- Concurrent downloads (default: 3 parallel)
- Automatic retry on failure (max 3 attempts)
- Resume capability for interrupted downloads
- Files organized by: `data/binaries/{product}/{app_key}/{version}/`
- **Automatic reindexing** on start to sync metadata with actual files

### Storage Reindexing

If you manually add, remove, or move binary files, you can reindex the storage to sync metadata with actual files:

```bash
# Reindex storage (sync metadata with disk)
python run_reindex.py

# Reindex and remove orphaned files
python run_reindex.py --clean-orphaned
```

**What reindexing does:**
- Scans all versions marked as "downloaded" in metadata
- Verifies that files actually exist on disk
- Clears "downloaded" status for missing files
- Optionally removes files not tracked in metadata

**When to reindex:**
- After manually deleting binary files
- After moving the binaries directory
- When download statistics seem incorrect
- After restoring from backup

**Note:** The download script automatically runs reindexing before starting downloads.

### Step 4: Launch Web Interface

Browse collected apps and versions via web UI:

```bash
python app.py
```

**Access:** http://localhost:5000

**Features:**
- Dashboard with statistics
- App catalog with search and filtering
- Version details with download links
- REST API endpoints (`/api/*`)

## Configuration

Edit `.env` file to customize behavior:

```bash
# Marketplace Credentials (optional for public data)
MARKETPLACE_USERNAME=your-email@example.com
MARKETPLACE_API_TOKEN=your-api-token

# Scraper Settings
SCRAPER_BATCH_SIZE=50              # Apps per API request
SCRAPER_REQUEST_DELAY=0.5          # Seconds between requests
VERSION_AGE_LIMIT_DAYS=365         # Version date filter (days)
MAX_CONCURRENT_DOWNLOADS=3         # Parallel downloads
MAX_RETRY_ATTEMPTS=3               # Retry failed requests
MAX_VERSION_SCRAPER_WORKERS=10     # Parallel version scraper workers

# Storage Settings
# BINARIES_PATH=/path/to/storage  # Custom path for binaries (default: ./data/binaries)

# Flask Settings
FLASK_PORT=5000
FLASK_DEBUG=True
SECRET_KEY=your-secret-key

# Storage Backend
USE_SQLITE=True                   # True to use SQLite instead of JSON files
```

## API Endpoints

The web interface provides REST API endpoints:

- `GET /api/apps` - Get all apps (JSON)
- `GET /api/apps/<addon_key>` - Get app details
- `GET /api/stats` - Get statistics
- `GET /api/products` - Get product list
- `GET /download/<product>/<app_key>/<version_id>` - Download binary

## Data Storage

### Metadata

```
data/metadata/
├── marketplace.db              # Apps and versions
├── apps.json                   # All apps (array)
├── versions/                   # Versions per app
│   └── {app_key}_versions.json
└── checkpoints/                # Resume checkpoints
    └── scrape_checkpoint.pkl
```

### Binaries

```
data/binaries/
├── jira/
│   └── com.example.app/
│       └── 1.0.0/
│           └── com.example.app-1.0.0.jar
├── confluence/
├── bitbucket/
├── bamboo/
└── crowd/
```

## Logging

Logs are written to `logs/` directory:

- `scraper.log` - General scraping activity
- `download.log` - Download operations
- `failed_downloads.log` - Failed download errors

## Error Handling

- **API Rate Limiting**: Adaptive delay with exponential backoff
- **Network Failures**: Automatic retry with configurable attempts
- **Interrupted Scraping**: Checkpoint system for resume
- **Download Failures**: Logged to `failed_downloads.log` for retry

## Development

### Project Structure

- **config/**: Configuration and product definitions
- **scraper/**: Core scraping components
- **models/**: Data models (App, Version, DownloadStatus)
- **utils/**: Logging, rate limiting, checkpoint management
- **web/**: Flask application (routes, templates, static files)

## Notes

- First run creates `data/` and `logs/` automatically, but you can pre-create them if you prefer.
- Scraping and version collection can take hours for a full marketplace run.
- The web UI only shows data already collected by the scrapers.

### Key Patterns

- **Checkpoint/Resume**: Uses pickle for state persistence (pattern from `converter/main.py`)
- **Rate Limiting**: Adaptive delays based on HTTP response codes
- **Error Logging**: File-based logging with ERROR level for failures

## Troubleshooting

### No apps found
- Check internet connection
- Verify Marketplace API is accessible
- Check logs in `logs/scraper.log`

### Download failures (404 errors)
- **If you see 404 errors for download URLs**, the `app_id` field may not be populated
- **Solution:** Re-run the app scraper to populate `app_id` for all apps:
  ```bash
  docker-compose run --rm scraper  # or python run_scraper.py
  ```
- **Then rebuild Docker images** to ensure code changes are applied:
  ```bash
  docker-compose build --no-cache
  ```
- Check available disk space
- Review `logs/failed_downloads.log`
- Retry with `python run_downloader.py`

### Web interface errors
- Ensure scraping completed successfully
- Check `data/metadata/marketplace.db` exists
- Review Flask logs in console

## Performance

- **Apps scraping**: ~5-10 minutes for all products
- **Versions scraping**: ~1-2 hours (depends on total apps)
- **Binary downloads**: Varies by file sizes and network speed
- **Storage**: Expect 10-100 GB for full marketplace (all products, 1 year)

## License

This project is for personal/educational use. Respect Atlassian's Terms of Service when scraping their marketplace.
