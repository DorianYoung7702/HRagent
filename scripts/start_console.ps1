# 启动HRagent AI 筛选控制台（API + Vite 前端）
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_encoding.ps1"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== HRagent AI 筛选简历系统 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "终端 1: 启动 API (http://localhost:8001) ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$Root\scripts\start_api.ps1", "-Reload"

Start-Sleep -Seconds 4

$consoleDir = Join-Path $Root "apps\console-web"
if (-not (Test-Path (Join-Path $consoleDir "node_modules"))) {
    Write-Host "安装前端依赖..." -ForegroundColor Yellow
    Push-Location $consoleDir
    npm install
    Pop-Location
}

Write-Host "终端 2: 启动前端 (http://localhost:5173) ..." -ForegroundColor Yellow
Write-Host "请在浏览器打开: http://localhost:5173" -ForegroundColor Green
Push-Location $consoleDir
npm run dev
