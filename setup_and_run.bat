@echo off
setlocal enabledelayedexpansion
title HR Intelligence Platform Setup

echo ============================================================
echo  Agentic HR Intelligence Platform - Setup ^& Launch
echo ============================================================
echo.

:: ── Locate Python (check common locations + ARM64 path) ───────
set PYTHON=
if exist "%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PYTHON=python
    )
)

if not defined PYTHON (
    echo [INFO] Python not found. Installing via winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] winget install failed. Please install Python 3.12 manually:
        echo         https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [OK] Python installed. Please CLOSE this window and run setup_and_run.bat again.
    echo      (PATH needs to refresh after Python install)
    pause
    exit /b 0
)

for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do set PYVER=%%v
echo [OK] Found %PYVER% at %PYTHON%
echo.

:: ── Move to script directory ──────────────────────────────────
cd /d "%~dp0"

:: ── Install dependencies ──────────────────────────────────────
echo [STEP 1/3] Installing Python packages...
"%PYTHON%" -m pip install --upgrade pip -q
:: Use --prefer-binary to avoid C compilation issues on ARM64 Windows
"%PYTHON%" -m pip install anthropic plotly python-dotenv --prefer-binary -q
"%PYTHON%" -m pip install pandas --only-binary=:all: -q
"%PYTHON%" -m pip install streamlit --no-deps -q
"%PYTHON%" -m pip install altair blinker cachetools click gitpython requests rich tenacity toml tornado watchdog pydeck --prefer-binary -q
"%PYTHON%" -m pip install "protobuf>=3.20,<7" --only-binary=:all: -q
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Some packages may have issues, but continuing...
)
echo [OK] Packages installed.
echo.

:: ── Set up database ───────────────────────────────────────────
echo [STEP 2/3] Setting up SQLite database...
if exist "hr_data.db" (
    echo [OK] hr_data.db already exists, skipping.
) else (
    "%PYTHON%" setup_db.py
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Database setup failed. Make sure WA_Fn-UseC_-HR-Employee-Attrition.csv
        echo         is in C:\Users\bhavy\Downloads\
        pause
        exit /b 1
    )
)
echo.

:: ── Set up .env ───────────────────────────────────────────────
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [INFO] Created .env file. You can add your API key there, or enter it in the app sidebar.
)

:: ── Launch Streamlit ──────────────────────────────────────────
echo [STEP 3/3] Launching HR Intelligence Platform...
echo.
echo ============================================================
echo  App will open at: http://localhost:8501
echo  Press Ctrl+C to stop the server
echo ============================================================
echo.

"%PYTHON%" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false

pause
