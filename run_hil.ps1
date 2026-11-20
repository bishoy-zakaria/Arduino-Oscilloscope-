<#
.SYNOPSIS
    Automated Hardware-in-the-Loop (HIL) Test Runner for physical Arduino Uno.
.EXAMPLE
    .\run_hil.ps1
    .\run_hil.ps1 -Port COM14
#>

[CmdletBinding()]
param(
    [string]$Port = "COM14"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Virtual environment not found at: $PythonExe" -ForegroundColor Red
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Automated Hardware-in-the-Loop (HIL) Test Runner      " -ForegroundColor Cyan
Write-Host "  Target: Arduino Uno on $Port (1,000,000 Baud)         " -ForegroundColor Cyan
Write-Host "  Duration: 5.0 Seconds Per Scenario                    " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

& $PythonExe (Join-Path $ScriptDir "scripts\run_hil_test.py") $Port

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[SUCCESS] HIL Testing Completed!" -ForegroundColor Green
    $ReportPath = Join-Path $ScriptDir "hil_test_report.html"
    if (Test-Path $ReportPath) {
        Write-Host "Opening report: $ReportPath ..." -ForegroundColor Cyan
        Start-Process $ReportPath
    }
} else {
    Write-Host "`n[ERROR] HIL execution encountered errors." -ForegroundColor Red
    exit 1
}
