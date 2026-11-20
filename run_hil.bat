@echo off
setlocal enabledelayedexpansion

title Comprehensive 28-Point HIL Test Suite Runner - Physical Hardware
cd /d "%~dp0"

echo ========================================================
echo   Automated Hardware-in-the-Loop (HIL) Test Runner
echo   Physical Arduino Uno (1,000,000 Baud, 25.0 kSPS ADC)
echo   Comprehensive 28-Point Boundary Sweep
echo ========================================================
echo.

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "!VENV_PYTHON!" (
    echo [ERROR] Virtual environment not found at:
    echo "!VENV_PYTHON!"
    pause
    exit /b 1
)

set "PORT=COM14"
if not "%~1"=="" set "PORT=%~1"

echo Executing 28-Point Physical HIL Sweep on %PORT%...
"!VENV_PYTHON!" "%~dp0scripts\run_comprehensive_hil_sweep.py" %PORT%

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo   [SUCCESS] All 28 HIL Scenarios Completed Successfully!
    echo   Results dataset saved: hil_sweep_results.json
    echo ========================================================
) else (
    echo.
    echo [ERROR] One or more HIL scenarios failed. Error code: %ERRORLEVEL%
    pause
)
