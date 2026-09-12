# Allow inbound TCP for LAN HR access (requires Administrator)
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_encoding.ps1"

$Port = 8001
$RuleName = "Yungia HR Agent TCP $Port"

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "防火墙规则已存在: $RuleName" -ForegroundColor Yellow
} else {
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    Write-Host "已添加防火墙入站规则: TCP $Port" -ForegroundColor Green
}

. "$PSScriptRoot\print_lan_urls.ps1" -Port $Port
