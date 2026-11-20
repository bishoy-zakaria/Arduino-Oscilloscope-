@echo off
setlocal enabledelayedexpansion

title Arduino Uno ADC Oscilloscope
cd /d "%~dp0"

echo ========================================================
echo        Arduino Uno ADC DAQ ^& Oscilloscope (25 kSPS)
echo ========================================================
echo.

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "!VENV_PYTHON!" (
    echo [ERROR] Virtual environment not found at:
    echo "!VENV_PYTHON!"
    echo.
    echo Please create the virtual environment first using:
    echo    python -m venv .venv
    echo    .\.venv\Scripts\pip.exe install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: If no arguments passed, launch main.py directly (auto-detects COM ports)
if "%~1"=="" (
    echo Launching Oscilloscope GUI...
    "!VENV_PYTHON!" "%~dp0main.py"
) else (
    echo Launching with arguments: %*
    "!VENV_PYTHON!" "%~dp0main.py" %*
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Application exited with error code: %ERRORLEVEL%
    pause
)
