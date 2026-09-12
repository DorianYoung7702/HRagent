# Local dev setup (SQLite, no Docker)
. "$PSScriptRoot\_encoding.ps1"
. "$PSScriptRoot\_resolve_python.ps1"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

$py = Get-ProjectPythonPath $ProjectRoot
if (-not $py) {
    Write-Host "未找到 Python / .venv" -ForegroundColor Red
    exit 1
}

Write-Host "=== Local SQLite mode (no Docker) ===" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path "data" | Out-Null

$aiosqlite = & $py -c "import importlib.util; print(1 if importlib.util.find_spec('aiosqlite') else 0)" 2>$null
if ($aiosqlite -ne "1") {
    Write-Host "Installing aiosqlite..."
    & $py -m pip install aiosqlite -i https://pypi.tuna.tsinghua.edu.cn/simple -q
}

$envFile = Join-Path $ProjectRoot ".env"
$exampleFile = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $exampleFile $envFile
}

$content = Get-Content $envFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
$sqliteUrl = "DATABASE_URL=sqlite+aiosqlite:///./data/recruiting.db"
if ($content -match "DATABASE_URL=") {
    $content = $content -replace "DATABASE_URL=.*", $sqliteUrl
} else {
    $content = "$sqliteUrl`r`n$content"
}
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($envFile, $content, $utf8NoBom)

Write-Host "DATABASE_URL -> sqlite+aiosqlite:///./data/recruiting.db"

& $py scripts/init_db.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Database init failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Local environment ready. Next steps:" -ForegroundColor Green
Write-Host "  1. Start API:  .\scripts\start_api.ps1" -ForegroundColor Cyan
Write-Host "  2. Run demo:   .\scripts\run_liepin_demo.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: SQLite mode skips Temporal/Redis. LPT fetch + AI screening demo works fine."
