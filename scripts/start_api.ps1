# Start FastAPI - visible browser demo runs in this process
param(
    [switch]$Reload,
    [int]$Port = 8001,
    [string]$ListenHost = "127.0.0.1",
    [switch]$SkipLanPrint
)

. "$PSScriptRoot\_encoding.ps1"
. "$PSScriptRoot\_resolve_python.ps1"
. "$PSScriptRoot\_port_utils.ps1"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env - please set DEEPSEEK_API_KEY"
}

$py = Get-ProjectPythonPath $Root
if (-not $py) {
    Write-Host "未找到 Python / .venv。请先: python -m venv .venv  然后  .\.venv\Scripts\python.exe -m pip install -e ." -ForegroundColor Red
    exit 1
}

$Port = Resolve-HrAgentPort -PreferredPort $Port
if ($null -eq $Port) {
    exit 1
}

Save-RuntimeApiPort -Port $Port -ProjectRoot $Root

$env:PYTHONPATH = (Get-Location).Path
$env:BROWSER_HEADLESS = "false"
$env:API_PORT = "$Port"
$env:API_BASE_URL = "http://localhost:$Port"

Write-Host "Python: $py" -ForegroundColor DarkGray

if (-not $SkipLanPrint -and $ListenHost -ne "127.0.0.1") {
    . "$PSScriptRoot\print_lan_urls.ps1" -Port $Port
}

$uvicornArgs = @(
    "-m", "uvicorn", "apps.api.main:app",
    "--host", $ListenHost,
    "--port", "$Port"
)
if ($Reload) {
    $uvicornArgs += "--reload"
    # 抓取/初筛会频繁写 DB 与 browser profile；若被 watch 会不断 reload 并打断 Playwright 任务
    $reloadExcludes = @(
        "data/*",
        "apps/console-web/dist/*",
        "apps/console-web/node_modules/*",
        "**/*.db",
        "**/*.db-*",
        "**/browser_profiles/**"
    )
    foreach ($pattern in $reloadExcludes) {
        $uvicornArgs += "--reload-exclude"
        $uvicornArgs += $pattern
    }
    Write-Host "开发模式: --reload 已开启（已排除 data/、dist、browser_profiles）" -ForegroundColor DarkYellow
}
Write-Host "Ctrl+C 可退出；强制停止请运行: .\scripts\stop_api.ps1" -ForegroundColor DarkGray
Write-Host "正在启动服务 (http://${ListenHost}:$Port) ..." -ForegroundColor Yellow

try {
    & $py @uvicornArgs
    exit $LASTEXITCODE
} finally {
    Write-Host "`nAPI 进程已结束。" -ForegroundColor DarkGray
}
