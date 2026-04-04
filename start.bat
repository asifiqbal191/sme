@echo off
REM ================================================
REM  SME Order Tracker — Quick Start
REM  Launches FastAPI + ngrok tunnel
REM ================================================

echo.
echo  ============================================
echo   SME Order Tracker — Starting...
echo  ============================================
echo.

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo  [OK] Virtual environment activated
) else (
    echo  [!] No .venv found, using system Python
)

REM Install dependencies if needed
pip show pyngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo  [..] Installing pyngrok...
    pip install pyngrok>=7.1.0
)

echo.
echo  Starting FastAPI server + ngrok tunnel...
echo  Press Ctrl+C to stop
echo.

python start.py %*
