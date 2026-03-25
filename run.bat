@echo off
setlocal

:: HR Insights Platform launcher
set PYTHON=
if exist "%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 set PYTHON=python
)

if not defined PYTHON (
    echo [ERROR] Python not found. Install Python 3.10 or newer.
    pause
    exit /b 1
)

cd /d "%~dp0"

if not exist "hr_data.db" (
    echo [SETUP] hr_data.db not found. Running setup_db.py...
    "%PYTHON%" setup_db.py
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Database setup failed.
        pause
        exit /b 1
    )
)

echo.
echo  HR Insights Platform
echo  Open http://localhost:8000 in your browser
echo  Press Ctrl+C to stop.
echo.

"%PYTHON%" -m uvicorn server:app --host 127.0.0.1 --port 8000

pause
