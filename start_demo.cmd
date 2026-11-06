@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 (
    py -3 app.py --open
    goto finished
)
python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 (
    python app.py --open
    goto finished
)
echo Python 3.10 or later is required. Install Python, then run this launcher again.
:finished
echo.
pause
