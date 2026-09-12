# Liepin LPT demo - visible browser runs in THIS terminal
. "$PSScriptRoot\_encoding.ps1"

Set-Location $PSScriptRoot\..

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env - please set DEEPSEEK_API_KEY"
    exit 1
}

$env:PYTHONPATH = (Get-Location).Path
$env:BROWSER_HEADLESS = "false"

try {
    $null = Invoke-RestMethod -Uri "http://localhost:8001/health" -TimeoutSec 3
} catch {
    Write-Host "API not running. Start it first in another terminal:"
    Write-Host "  .\scripts\start_api.ps1"
    exit 1
}

Write-Host "Starting visible browser demo..."
python scripts/run_liepin_demo.py
exit $LASTEXITCODE
