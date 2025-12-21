# QuickStart Guide

## Current State
✅ **Fully implemented and ready to use**
✅ **All 60+ files created**
✅ **Flask template issue fixed**

## Location
```
/mnt/g/GitLab Repositories/Personal/Experiments/AtlassianMarketplaceScraper/
```

## Setup (First Time Only)

```bash
cd "/mnt/g/GitLab Repositories/Personal/Experiments/AtlassianMarketplaceScraper"

# 1. Activate virtual environment
source /home/udjin/.virtualenvs/Experiments/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (optional - may work without credentials for public API)
cp .env.example .env
# Edit .env if you have Atlassian credentials
```

## Usage (3-Step Process)

```bash
# Step 1: Scrape all apps (5-10 minutes)
python run_scraper.py

# Step 2: Scrape versions (1-2 hours)
python run_version_scraper.py

# Step 3: Download binaries (varies)
python run_downloader.py

# Step 4: View in browser
python app.py
# Open: http://localhost:5000
```

## Quick Test (Single Product)

```bash
# Test with one product first
python run_scraper.py
# Press Ctrl+C after first product completes

python run_version_scraper.py
python app.py
```

## Files Created

- ✅ Core: 13 Python modules (API, scrapers, models, utils, config)
- ✅ Web: 5 HTML templates + CSS + JS + Flask app
- ✅ CLI: 3 command-line scripts
- ✅ Docs: README.md + SESSION_STATE.md + QUICKSTART.md + .env.example

## Key Commands

```bash
# Resume interrupted scraping
python run_scraper.py --resume

# Download specific product only
python run_downloader.py jira

# Check API without browser
curl http://localhost:5000/api/stats
```

## What You'll Get

- **Apps**: All Server/DC apps from 5 products
- **Versions**: Last 1 year, Server/DC only
- **Binaries**: JAR/OBR files downloaded to `data/binaries/`
- **Metadata**: JSON files in `data/metadata/`
- **Web UI**: Browse, search, filter, download

## Troubleshooting

**No apps scraped?**
- Check internet connection
- Try without credentials first (public API)
- Check `logs/scraper.log`

**Flask template error?**
- ✅ Already fixed in app.py

**Download failures?**
- Check `logs/failed_downloads.log`
- Check disk space
- Re-run `python run_downloader.py`

## Status: READY TO USE 🚀
