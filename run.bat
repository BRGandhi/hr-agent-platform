@echo off
:: Direct launcher using ARM64 Python path
set PYTHON=C:\Users\bhavy\AppData\Local\Programs\Python\Python312-arm64\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] Python not found at %PYTHON%
    echo Please run setup_and_run.bat first to install Python.
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

echo Starting HR Intelligence Platform at http://localhost:8501
echo Press Ctrl+C to stop.
echo.
"%PYTHON%" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false
pause
