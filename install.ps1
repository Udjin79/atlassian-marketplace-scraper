# PowerShell script for installing Atlassian Marketplace Scraper on Windows
# Run: .\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Atlassian Marketplace Scraper - Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found! Install Python 3.8+ from python.org" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host ""
Write-Host "[2/4] Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "[OK] Virtual environment already exists" -ForegroundColor Green
} else {
    python -m venv venv
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Virtual environment created" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
}

# Install dependencies
Write-Host ""
Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    & "venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[ERROR] requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Install Playwright browser
Write-Host ""
Write-Host "[4/5] Installing Playwright browser (Chromium)..." -ForegroundColor Yellow
& "venv\Scripts\python.exe" -m playwright install chromium
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Playwright Chromium installed" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Failed to install Playwright browser" -ForegroundColor Yellow
    Write-Host "  You can install it manually later with: playwright install chromium" -ForegroundColor Yellow
}

# Create .env file
Write-Host ""
Write-Host "[5/5] Configuring..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Write-Host "[WARNING] .env file already exists, skipping creation" -ForegroundColor Yellow
    Write-Host "  Edit .env manually if needed" -ForegroundColor Yellow
} else {
    # Generate SECRET_KEY
    try {
        $secretKey = & "venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))" 2>$null
        if (-not $secretKey -or $secretKey -eq "") {
            throw "Failed to generate"
        }
        $secretKey = $secretKey.Trim()
    } catch {
        $secretKey = "dev-secret-key-change-in-production-use-random-string"
    }
    
    # Create .env file
    $envContent = @"
# Atlassian Marketplace API Credentials
MARKETPLACE_USERNAME=maxpowertexas1986@gmail.com
MARKETPLACE_API_TOKEN=ATATT3xFfGF0aDF3jnpXPlwQYz1_0suIGIsEAJBTZcLCpcZNnbr6vjk-BYPpLugB3yxZcfk5eHhVfliWJwc-z4JIXz01lC9-HGOvzWX4TAPZVVmtr1aEgR2tSvB7OpudZaQEkCpquUEgnIkEAG84F6bhpx5MZGFOFEMg1t-Ey6kx86tYu8AGeCk=9DF81475

# Storage Configuration
USE_SQLITE=True

# Metadata on drive I:
METADATA_DIR=I:\marketplace\metadata
DATABASE_PATH=I:\marketplace\marketplace.db

# Binary files distributed across drives:
# Jira -> H:\
BINARIES_DIR_JIRA=H:\marketplace-binaries\jira
# Confluence -> K:\
BINARIES_DIR_CONFLUENCE=K:\marketplace-binaries\confluence
# Bitbucket -> V:\
BINARIES_DIR_BITBUCKET=V:\marketplace-binaries\bitbucket
# Bamboo -> W:\
BINARIES_DIR_BAMBOO=W:\marketplace-binaries\bamboo
# Crowd -> F:\
BINARIES_DIR_CROWD=F:\marketplace-binaries\crowd

# Base path (used as fallback)
BINARIES_BASE_DIR=H:\marketplace-binaries

# Descriptions (plugin descriptions with images/videos)
# If not set, defaults to METADATA_DIR/descriptions
# DESCRIPTIONS_DIR=K:\marketplace-descriptions

# Logs on drive I:
LOGS_DIR=I:\marketplace\logs

# Flask Settings
FLASK_PORT=5000
FLASK_DEBUG=True
SECRET_KEY=$secretKey

# Scraper Settings
SCRAPER_BATCH_SIZE=50
SCRAPER_REQUEST_DELAY=0.5
VERSION_AGE_LIMIT_DAYS=365
MAX_CONCURRENT_DOWNLOADS=3
MAX_VERSION_SCRAPER_WORKERS=10
MAX_RETRY_ATTEMPTS=3

# Logging
LOG_LEVEL=INFO
"@
    
    [System.IO.File]::WriteAllText((Join-Path $PWD ".env"), $envContent, [System.Text.Encoding]::UTF8)
    Write-Host "[OK] .env file created with basic settings" -ForegroundColor Green
    Write-Host "  [OK] SECRET_KEY automatically generated" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[OK] Installation completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Activate virtual environment: venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "2. Run scraper: python run_scraper.py" -ForegroundColor White
Write-Host ""
Write-Host "To generate new SECRET_KEY:" -ForegroundColor Yellow
Write-Host "  python -c `"import secrets; print(secrets.token_hex(32))`"" -ForegroundColor White
Write-Host ""
