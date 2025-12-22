# PowerShell script to check, install dependencies and run app.py
# Run: .\start.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Atlassian Marketplace Scraper - Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found! Install Python 3.8+ from python.org" -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    pause
    exit 1
}

# Check/create virtual environment
Write-Host ""
Write-Host "[2/5] Checking virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "[OK] Virtual environment found" -ForegroundColor Green
} else {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        pause
        exit 1
    }
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
}

# Check if requirements.txt exists
if (-not (Test-Path "requirements.txt")) {
    Write-Host "[ERROR] requirements.txt not found!" -ForegroundColor Red
    pause
    exit 1
}

# Check/install dependencies
Write-Host ""
Write-Host "[3/5] Checking dependencies..." -ForegroundColor Yellow
$venvPython = "venv\Scripts\python.exe"
$venvPip = "venv\Scripts\pip.exe"

# Check if pip is installed
if (-not (Test-Path $venvPip)) {
    Write-Host "[INFO] Installing pip..." -ForegroundColor Yellow
    & $venvPython -m ensurepip --upgrade
}

# Check if packages are installed
$needsInstall = $false
try {
    & $venvPython -c "import flask" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $needsInstall = $true
    }
} catch {
    $needsInstall = $true
}

if ($needsInstall) {
    Write-Host "[INFO] Installing dependencies from requirements.txt..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
        pause
        exit 1
    }
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "[OK] Dependencies already installed" -ForegroundColor Green
}

# Check Playwright browser (optional, but recommended)
Write-Host ""
Write-Host "[4/5] Checking Playwright browser..." -ForegroundColor Yellow
try {
    & $venvPython -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch()" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright browser not installed"
    }
    Write-Host "[OK] Playwright browser found" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Playwright browser not installed" -ForegroundColor Yellow
    Write-Host "  Installing Playwright Chromium (this may take a few minutes)..." -ForegroundColor Yellow
    & $venvPython -m playwright install chromium
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Playwright Chromium installed" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Failed to install Playwright browser" -ForegroundColor Yellow
        Write-Host "  You can install it manually later with: venv\Scripts\python.exe -m playwright install chromium" -ForegroundColor Yellow
    }
}

# Check .env file
Write-Host ""
Write-Host "[5/5] Checking configuration..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Write-Host "[OK] Configuration file (.env) found" -ForegroundColor Green
} else {
    Write-Host "[WARNING] .env file not found" -ForegroundColor Yellow
    Write-Host "  Run install.ps1 first to create .env file, or create it manually" -ForegroundColor Yellow
    Write-Host "  The application will use default settings" -ForegroundColor Yellow
}

# Launch application
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Flask application..." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Web interface will be available at: http://localhost:5000" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Run app.py using venv Python
& $venvPython app.py

# If we get here, the app has stopped
Write-Host ""
Write-Host "Application stopped." -ForegroundColor Yellow
pause

