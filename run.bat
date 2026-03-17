@echo off
:: HR Intelligence Platform launcher
:: Locate Python — try ARM64 path first, then fall back to PATH
set PYTHON=
if exist "%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 ( set PYTHON=python )
)

if not defined PYTHON (
    echo [ERROR] Python 3.12 not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)

cd /d "%~dp0"

if not exist "hr_data.db" (
    echo [SETUP] Database not found. Running setup_db.py...
    "%PYTHON%" setup_db.py
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Database setup failed.
        pause
        exit /b 1
    )
)

:: --- Choose frontend ---
set MODE=%1
if "%MODE%"=="streamlit" goto :streamlit
if "%MODE%"=="legacy"    goto :streamlit

:fastapi
echo.
echo  HR Intelligence Platform (JS/HTML frontend)
echo  Open http://localhost:8000 in your browser
echo  Press Ctrl+C to stop.
echo.
"%PYTHON%" server.py
goto :end

:streamlit
echo.
echo  HR Intelligence Platform (Streamlit frontend)
echo  Open http://localhost:8501 in your browser
echo  Press Ctrl+C to stop.
echo.
"%PYTHON%" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false

:end
pause
