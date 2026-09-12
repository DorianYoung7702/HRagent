# 生产/网页模式：构建前端 + 启动 API（单端口，支持局域网 HR 访问）
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_encoding.ps1"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== HRagent 控制台 - 本机网页模式 ===" -ForegroundColor Cyan

$consoleDir = Join-Path $Root "apps\console-web"
Push-Location $consoleDir
if (-not (Test-Path "node_modules")) {
    Write-Host "安装前端依赖..." -ForegroundColor Yellow
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
}
Write-Host "构建前端..." -ForegroundColor Yellow
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
Pop-Location

& "$Root\scripts\start_api.ps1"
