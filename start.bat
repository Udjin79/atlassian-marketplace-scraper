@echo off
REM Batch script to check, install dependencies and run app.py
REM Run: start.bat

echo ========================================
echo Atlassian Marketplace Scraper - Launcher
echo ========================================
echo.

REM Check Python
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python 3.8+ from python.org
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python found: %PYTHON_VERSION%

REM Check/create virtual environment
echo.
echo [2/5] Checking virtual environment...
if exist "venv" (
    echo [OK] Virtual environment found
) else (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found!
    pause
    exit /b 1
)

REM Check/install dependencies
echo.
echo [3/5] Checking dependencies...
set VENV_PYTHON=venv\Scripts\python.exe
set VENV_PIP=venv\Scripts\pip.exe

REM Check if pip is installed
if not exist "%VENV_PIP%" (
    echo [INFO] Installing pip...
    "%VENV_PYTHON%" -m ensurepip --upgrade
)

REM Check if packages are installed (check flask as indicator)
"%VENV_PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies from requirements.txt...
    "%VENV_PYTHON%" -m pip install --upgrade pip --quiet
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
) else (
    echo [OK] Dependencies already installed
)

REM Check Playwright browser (optional)
echo.
echo [4/5] Checking Playwright browser...
"%VENV_PYTHON%" -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch()" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Playwright browser not installed
    echo   Installing Playwright Chromium (this may take a few minutes)...
    "%VENV_PYTHON%" -m playwright install chromium
    if errorlevel 1 (
        echo [WARNING] Failed to install Playwright browser
        echo   You can install it manually later with: venv\Scripts\python.exe -m playwright install chromium
    ) else (
        echo [OK] Playwright Chromium installed
    )
) else (
    echo [OK] Playwright browser found
)

REM Check .env file
echo.
echo [5/5] Checking configuration...
if exist ".env" (
    echo [OK] Configuration file (.env) found
) else (
    echo [WARNING] .env file not found
    echo   Run install.ps1 first to create .env file, or create it manually
    echo   The application will use default settings
)

REM Launch application
echo.
echo ========================================
echo Starting Flask application...
echo ========================================
echo.
echo Web interface will be available at: http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

REM Run app.py using venv Python
"%VENV_PYTHON%" app.py

REM If we get here, the app has stopped
echo.
echo Application stopped.
pause

