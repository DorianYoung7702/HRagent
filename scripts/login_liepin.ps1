# Liepin LPT login - save browser profile
. "$PSScriptRoot\_encoding.ps1"
. "$PSScriptRoot\_resolve_python.ps1"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

$py = Get-ProjectPythonPath $Root
if (-not $py) {
    Write-Host "未找到 Python / .venv" -ForegroundColor Red
    exit 1
}

$env:BROWSER_HEADLESS = "false"
$env:PYTHONPATH = (Get-Location).Path

& $py scripts/login_liepin.py
