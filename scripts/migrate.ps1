# Database migration - always run from project root
. "$PSScriptRoot\_encoding.ps1"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-Host "Running alembic from: $ProjectRoot"
alembic upgrade head
