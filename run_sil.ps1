<#
.SYNOPSIS
    Runs the Software-in-the-Loop (SiL) Standards Testing Suite and opens the report.
.EXAMPLE
    .\run_sil.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Virtual environment not found at: $PythonExe" -ForegroundColor Red
    Write-Host "Please initialize: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Software-in-the-Loop (SiL) Standards Verification     " -ForegroundColor Cyan
Write-Host "  IEEE 181-2011 | IEEE 1057 | IEC 60469 | ISO 16750-2   " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Executing all 13 SiL Test Scenarios..." -ForegroundColor Green

& $PythonExe (Join-Path $ScriptDir "scripts\generate_sil_report.py")

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[SUCCESS] All SiL Scenarios Passed 100%!" -ForegroundColor Green
    $ReportPath = Join-Path $ScriptDir "sil_test_report.html"
    if (Test-Path $ReportPath) {
        Write-Host "Opening report: $ReportPath ..." -ForegroundColor Cyan
        Start-Process $ReportPath
    }
} else {
    Write-Host "`n[FAIL] Test execution encountered errors." -ForegroundColor Red
    exit 1
}
