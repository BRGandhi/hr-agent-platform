@echo off
setlocal enabledelayedexpansion
title HR Insights Platform Setup

echo ============================================================
echo  HR Insights Platform - Setup and Launch
echo ============================================================
echo.

set PYTHON=
if exist "%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 set PYTHON=python
)

if not defined PYTHON (
    echo [INFO] Python not found. Installing via winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] winget install failed. Install Python manually and rerun this script.
        pause
        exit /b 1
    )
    echo [OK] Python installed. Close this window and rerun setup_and_run.bat.
    pause
    exit /b 0
)

for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do set PYVER=%%v
echo [OK] Found %PYVER% at %PYTHON%
echo.

cd /d "%~dp0"

echo [STEP 1/4] Installing Python packages...
"%PYTHON%" -m pip install --upgrade pip -q
"%PYTHON%" -m pip install -r requirements.txt --prefer-binary -q
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Package installation failed.
    pause
    exit /b 1
)
echo [OK] Packages installed.
echo.

echo [STEP 2/4] Ensuring hr_data.db exists...
if exist "hr_data.db" (
    echo [OK] hr_data.db already exists.
) else (
    "%PYTHON%" setup_db.py
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Database setup failed. Ensure the HR CSV is available.
        pause
        exit /b 1
    )
)
echo.

echo [STEP 3/4] Ensuring .env exists...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [OK] Created .env. Update it if you want a specific provider or API key.
) else (
    echo [OK] .env already exists.
)
echo.

echo [STEP 4/4] Launching HR Insights Platform...
echo.
echo ============================================================
echo  App will open at: http://localhost:8000
echo  Press Ctrl+C to stop the server
echo ============================================================
echo.

"%PYTHON%" -m uvicorn server:app --host 127.0.0.1 --port 8000

pause
