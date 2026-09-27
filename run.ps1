# AgriMon Evolution 1 - Windows launcher. First run creates .venv and installs requirements.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}
if (-not (Test-Path ".env")) {
    Write-Warning "No .env file: copy .env.example to .env and set OPENAI_API_KEY. The app starts, but questions will fail at intent resolution."
}
.\.venv\Scripts\python.exe -m agrimon
