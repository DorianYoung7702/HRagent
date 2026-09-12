# Print LAN URLs for HR browser access (same WiFi)
param(
    [int]$Port = 8001
)

function Get-LanIPv4Addresses {
    $addrs = @()
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notmatch '^127\.' -and
                $_.IPAddress -notmatch '^169\.254\.' -and
                $_.PrefixOrigin -ne 'WellKnown'
            } |
            ForEach-Object { $_.IPAddress } |
            Sort-Object -Unique
    } catch {
        # Fallback when Get-NetIPAddress unavailable
        Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" -ErrorAction SilentlyContinue |
            ForEach-Object { $_.IPAddress } |
            Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notmatch '^127\.' } |
            Sort-Object -Unique
    }
    return $addrs
}

Write-Host ""
Write-Host "=== 网页访问地址（同 WiFi 的 HR 可直接打开）===" -ForegroundColor Cyan
Write-Host "  本机:     http://localhost:$Port" -ForegroundColor Green

$lan = @(Get-LanIPv4Addresses)
if ($lan.Count -eq 0) {
    Write-Host "  局域网:   (未检测到 IPv4，请 ipconfig 查看本机 IP)" -ForegroundColor Yellow
} else {
    foreach ($ip in $lan) {
        Write-Host "  局域网:   http://${ip}:$Port" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "说明: 猎聘浏览器自动化仍在本机运行，HR 仅通过网页配置任务并查看日志。" -ForegroundColor DarkGray
Write-Host "若其他设备无法打开，请以管理员运行: .\scripts\open_firewall_port.ps1" -ForegroundColor DarkGray
Write-Host ""
