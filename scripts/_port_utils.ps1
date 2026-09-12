# port utils

# Default local API port for HR Agent console + uvicorn
$DefaultHrAgentPort = 8001

function Get-PortListenerProcessIds {
    param([int]$Port = $DefaultHrAgentPort)
    $pids = @()
    try {
        $pids = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
    }
    return @($pids | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

function Test-PortListening {
    param([int]$Port = $DefaultHrAgentPort)
    return (Get-PortListenerProcessIds -Port $Port).Count -gt 0
}

function Get-ProcessBrief {
    param([int]$ProcId)
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction Stop
        $name = Split-Path -Leaf $p.ExecutablePath
        $cmd = ($p.CommandLine -replace '\s+', ' ').Trim()
        if ($cmd.Length -gt 120) { $cmd = $cmd.Substring(0, 117) + '...' }
        return [PSCustomObject]@{
            ProcessId = $ProcId
            Name      = $name
            Command   = $cmd
        }
    } catch {
        return [PSCustomObject]@{
            ProcessId = $ProcId
            Name      = "pid:$ProcId"
            Command   = ''
        }
    }
}

function Stop-ProcessTree {
    param([int]$ProcId)
    if ($ProcId -le 0) { return @() }
    $stopped = @()
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcId" -ErrorAction SilentlyContinue |
        ForEach-Object { $stopped += Stop-ProcessTree $_.ProcessId }
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
    if ($?) { $stopped += $ProcId }
    return $stopped
}

function Stop-HrAgentOnPort {
    param(
        [int]$Port = $DefaultHrAgentPort,
        [switch]$Quiet
    )
    . "$PSScriptRoot\_encoding.ps1"
    $stopped = @()
    foreach ($procId in (Get-PortListenerProcessIds -Port $Port)) {
        $stopped += Stop-ProcessTree $procId
    }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'uvicorn\s+apps\.api\.main|apps\.api\.main:app' } |
        ForEach-Object { $stopped += Stop-ProcessTree $_.ProcessId }

    $stopped = @($stopped | Select-Object -Unique)
    if (-not $Quiet) {
        if ($stopped.Count -gt 0) {
            Write-Host "已停止 $($stopped.Count) 个 API 进程 (端口 $Port)。" -ForegroundColor Green
        } else {
            Write-Host "端口 $Port 上未发现 HR Agent API。" -ForegroundColor DarkGray
        }
    }
    return $stopped
}

function Get-AvailablePort {
    param(
        [int]$StartPort = $DefaultHrAgentPort,
        [int]$MaxAttempts = 50
    )
    for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
        $candidate = $StartPort + $offset
        if (-not (Test-PortListening -Port $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Resolve-HrAgentPort {
    param(
        [int]$PreferredPort = $DefaultHrAgentPort,
        [int]$MaxAttempts = 50
    )
    if (-not (Test-PortListening -Port $PreferredPort)) {
        return $PreferredPort
    }

    Write-Host "端口 $PreferredPort 已被占用:" -ForegroundColor Yellow
    foreach ($procId in (Get-PortListenerProcessIds -Port $PreferredPort)) {
        $info = Get-ProcessBrief $procId
        Write-Host "  PID $($info.ProcessId) $($info.Name)" -ForegroundColor DarkYellow
        if ($info.Command) {
            Write-Host "    $($info.Command)" -ForegroundColor DarkGray
        }
    }

    $maxPort = $PreferredPort + $MaxAttempts - 1
    $alt = Get-AvailablePort -StartPort ($PreferredPort + 1) -MaxAttempts ($MaxAttempts - 1)
    if ($null -eq $alt) {
        Write-Host "在 $PreferredPort 到 $maxPort 范围内无可用端口。" -ForegroundColor Red
        return $null
    }

    Write-Host "自动改用端口 $alt" -ForegroundColor Green
    return $alt
}

function Save-RuntimeApiPort {
    param(
        [int]$Port,
        [string]$ProjectRoot
    )
    $dir = Join-Path $ProjectRoot '.runtime'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -Path (Join-Path $dir 'api_port.txt') -Value $Port -Encoding ascii
}

function Get-RuntimeApiPort {
    param(
        [string]$ProjectRoot,
        [int]$DefaultPort = $DefaultHrAgentPort
    )
    $path = Join-Path $ProjectRoot '.runtime\api_port.txt'
    if (-not (Test-Path $path)) { return $DefaultPort }
    $raw = (Get-Content $path -Raw -ErrorAction SilentlyContinue).Trim()
    if ($raw -match '^\d+$') { return [int]$raw }
    return $DefaultPort
}
