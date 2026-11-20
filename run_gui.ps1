<#
.SYNOPSIS
    Launches the Arduino Uno ADC Oscilloscope GUI.
.EXAMPLE
    .\run_gui.ps1
.EXAMPLE
    .\run_gui.ps1 -Port COM14
.EXAMPLE
    .\run_gui.ps1 -Sim
#>

[CmdletBinding()]
param (
    [string]$Port = "",
    [int]$Baud = 1000000,
    [switch]$Sim
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Python virtual environment not found at: $PythonExe" -ForegroundColor Red
    Write-Host "Please initialize the environment with: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

$Arguments = @("main.py")

if ($Sim) {
    $Arguments += "--sim"
} elseif ($Port) {
    $Arguments += "--port"
    $Arguments += $Port
    $Arguments += "--baud"
    $Arguments += $Baud
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       Arduino Uno ADC DAQ & Oscilloscope (25 kSPS)    " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Starting GUI..." -ForegroundColor Green

& $PythonExe $Arguments
