@echo off
setlocal enabledelayedexpansion

title SiL Test Suite Runner - Standards Compliance
cd /d "%~dp0"

echo ========================================================
echo   Software-in-the-Loop (SiL) Standards Verification
echo   IEEE 181-2011 ^| IEEE 1057 ^| IEC 60469 ^| ISO 16750-2
echo ========================================================
echo.

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "!VENV_PYTHON!" (
    echo [ERROR] Virtual environment not found at:
    echo "!VENV_PYTHON!"
    echo Please run: python -m venv .venv ^& .\.venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

echo Executing all 15 SiL Test Scenarios...
"!VENV_PYTHON!" "%~dp0run_sil_suite.py"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo   [SUCCESS] All SiL Scenarios Passed (100%% Compliance)!
    echo ========================================================
) else (
    echo.
    echo [ERROR] One or more SiL scenarios failed. Error code: %ERRORLEVEL%
    pause
)
