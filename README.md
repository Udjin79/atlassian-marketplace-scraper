# Atlassian Marketplace Scraper

A Python-based service to scrape the Atlassian Marketplace for Server/Data Center apps and versions, download binaries, and provide a web interface for browsing the collected data.

## Features

- **Complete Marketplace Scraping**: Scrapes all apps across Jira, Confluence, Bitbucket, Bamboo, and Crowd
- **Version Filtering**: Filters versions released in the last year, Server/Data Center hosting only
- **Binary Downloads**: Downloads JAR/OBR files with resume capability
- **Web Interface**: Flask-based UI for browsing apps and versions
- **Checkpoint/Resume**: Robust checkpoint system for interrupted scraping
- **Concurrent Downloads**: Multi-threaded downloads with configurable concurrency
- **Progress Tracking**: Real-time progress bars using tqdm
- **Metadata Storage**: JSON-based storage for apps and versions

## Architecture

```
AtlassianMarketplaceScraper/
├── app.py                      # Flask web application
├── run_scraper.py              # CLI: Scrape apps
├── run_version_scraper.py      # CLI: Scrape versions
├── run_downloader.py           # CLI: Download binaries
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
    ├── metadata/               # JSON metadata
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

## Usage

### Step 1: Scrape Apps

Discover all apps from the Atlassian Marketplace:

```bash
python run_scraper.py
```

**Options:**
- `--resume`: Resume from last checkpoint after interruption

**Output:**
- Apps metadata saved to `data/metadata/apps.json`
- Progress automatically checkpointed every 100 apps

### Step 2: Scrape Versions

Fetch version history for all apps (last 1 year, Server/DC only):

```bash
python run_version_scraper.py
```

**Output:**
- Version metadata saved to `data/metadata/versions/{app_key}_versions.json`
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

### Metadata (JSON)

```
data/metadata/
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
- **Progress Tracking**: tqdm progress bars for long operations
- **Rate Limiting**: Adaptive delays based on HTTP response codes
- **Error Logging**: File-based logging with ERROR level for failures

## Troubleshooting

### No apps found
- Check internet connection
- Verify Marketplace API is accessible
- Check logs in `logs/scraper.log`

### Download failures
- Check available disk space
- Review `logs/failed_downloads.log`
- Retry with `python run_downloader.py`

### Web interface errors
- Ensure scraping completed successfully
- Check `data/metadata/apps.json` exists
- Review Flask logs in console

## Performance

- **Apps scraping**: ~5-10 minutes for all products
- **Versions scraping**: ~1-2 hours (depends on total apps)
- **Binary downloads**: Varies by file sizes and network speed
- **Storage**: Expect 10-100 GB for full marketplace (all products, 1 year)

## License

This project is for personal/educational use. Respect Atlassian's Terms of Service when scraping their marketplace.
