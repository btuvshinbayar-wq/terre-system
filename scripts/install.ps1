# Terre System installer: creates .venv, installs packages, copies config
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "== Terre System install ==" -ForegroundColor Cyan
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.11+ from https://www.python.org (tick 'Add to PATH')." -ForegroundColor Red
    exit 1
}
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
if (-not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml }
New-Item -ItemType Directory -Force secrets, data | Out-Null
Write-Host ""
Write-Host "Done. Next: double-click start_terre.bat (demo mode)." -ForegroundColor Green
