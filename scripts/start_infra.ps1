# Start infra (PostgreSQL + Redis + Temporal) - requires Docker
. "$PSScriptRoot\_encoding.ps1"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $ProjectRoot

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Host ""
    Write-Host "[WARN] Docker not found." -ForegroundColor Yellow
    Write-Host "For demo without Docker, use:" -ForegroundColor Yellow
    Write-Host "  .\scripts\setup_local.ps1" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "For full stack, install Docker Desktop:" -ForegroundColor Yellow
    Write-Host "  https://www.docker.com/products/docker-desktop/" -ForegroundColor Cyan
    Pop-Location
    exit 1
}

Push-Location (Join-Path $ProjectRoot "infra")
docker compose up -d postgres redis temporal temporal-ui
Pop-Location

Write-Host ""
Write-Host "Temporal UI: http://localhost:8080"
Write-Host "PostgreSQL: localhost:5432"
Write-Host ""
Write-Host "Then run migration from project root:"
Write-Host "  .\scripts\migrate.ps1" -ForegroundColor Cyan
Pop-Location
