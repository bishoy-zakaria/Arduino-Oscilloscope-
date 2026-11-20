@echo off
setlocal enabledelayedexpansion

title Python Virtual Environment Setup (.venv)
cd /d "%~dp0"

echo ==============================================================================
echo   ADC Study - Automated Python Virtual Environment (.venv) Setup
echo ==============================================================================
echo.

:: 1. Locate System Python
set "SYSTEM_PYTHON="

:: Check if 'python' is available and is Python 3
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable if sys.version_info[0] == 3 else '')"') do (
        set "SYSTEM_PYTHON=%%i"
    )
)

:: Fallback to Python Launcher 'py -3' if python not on PATH or not v3
if not defined SYSTEM_PYTHON (
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        for /f "tokens=*" %%i in ('py -3 -c "import sys; print(sys.executable)"') do (
            set "SYSTEM_PYTHON=%%i"
        )
    )
)

:: If still not found, alert user and exit
if not defined SYSTEM_PYTHON (
    echo [ERROR] Python 3 was not detected on your system PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [INFO] Found System Python: !SYSTEM_PYTHON!
for /f "tokens=*" %%v in ('"!SYSTEM_PYTHON!" --version') do echo [INFO] Python Version: %%v
echo.

:: 2. Create or Validate .venv
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if exist "%VENV_PYTHON%" (
    echo [INFO] Virtual environment already exists at:
    echo        "%VENV_DIR%"
    echo [INFO] Updating and verifying dependencies...
) else (
    echo [INFO] Creating new virtual environment at:
    echo        "%VENV_DIR%"
    "!SYSTEM_PYTHON!" -m venv "%VENV_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment. Error code: %ERRORLEVEL%
        pause
        exit /b %ERRORLEVEL%
    )
    echo [SUCCESS] Virtual environment created successfully.
)
echo.

:: 3. Upgrade pip
echo [INFO] Upgrading pip to latest version...
"!VENV_PYTHON!" -m pip install --upgrade pip --quiet
echo.

:: 4. Install dependencies from requirements.txt
if exist "%~dp0requirements.txt" (
    echo [INFO] Installing dependencies from requirements.txt...
    "!VENV_PIP!" install -r "%~dp0requirements.txt"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install packages from requirements.txt. Error code: %ERRORLEVEL%
        pause
        exit /b %ERRORLEVEL%
    )
) else (
    echo [WARNING] requirements.txt not found! Installing core packages manually...
    "!VENV_PIP!" install PyQt6 pyqtgraph pyserial numpy colorama
)
echo.

:: 5. Verify Package Import Integrity
echo [INFO] Verifying package import integrity...
"!VENV_PYTHON!" -c "import PyQt6.QtCore as qc, pyqtgraph, serial, numpy, colorama; print('  [OK] PyQt6:       v' + qc.PYQT_VERSION_STR); print('  [OK] PyQtGraph:   v' + pyqtgraph.__version__); print('  [OK] NumPy:       v' + numpy.__version__); print('  [OK] pySerial:    v' + serial.__version__); print('  [OK] Colorama:    v' + colorama.__version__)"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] One or more packages failed verification.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==============================================================================
echo   [SUCCESS] Environment setup is complete and fully verified!
echo ==============================================================================
echo.
echo Available Launchers:
echo   - run_gui.bat         : Launch 60 FPS PyQtGraph Oscilloscope Application
echo   - run_hil.bat [PORT]  : Run 28-Point Physical HIL Hardware Sweep (e.g. COM14)
echo   - run_sil.bat         : Run 15-Scenario SiL Standards Compliance Test Suite
echo   - run_dsp_report.bat  : Open Scientific Specification Paper in Browser
echo.
pause
