# 查找真实 Python（跳过 Windows Store 占位符 python.exe）

function Test-RealPythonExe {
    param([string]$PythonPath)

    if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    $normalized = $PythonPath.Replace('/', '\').ToLowerInvariant()
    if ($normalized -match '\\windowsapps\\') {
        return $false
    }

    try {
        $out = & $PythonPath -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        $line = ($out | Select-Object -Last 1).ToString().Trim()
        return ($line -match '^\d+\s+\d+$')
    } catch {
        return $false
    }
}

function Get-ProjectPythonPath {
    param([string]$ProjectRoot)

    $candidates = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "venv\Scripts\python.exe")
    )

    foreach ($ver in @("313", "312", "311", "310")) {
        $candidates += @(
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$ver\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$ver-32\python.exe"),
            "C:\Program Files\Python$ver\python.exe",
            "C:\Program Files (x86)\Python$ver-32\python.exe"
        )
    }

    foreach ($base in @(
        (Join-Path $env:USERPROFILE "anaconda3"),
        (Join-Path $env:USERPROFILE "miniconda3"),
        (Join-Path $env:USERPROFILE "miniforge3"),
        (Join-Path $env:USERPROFILE "mambaforge"),
        "C:\ProgramData\anaconda3",
        "C:\ProgramData\miniconda3",
        "C:\ProgramData\miniforge3",
        "C:\ProgramData\mambaforge"
    )) {
        $candidates += (Join-Path $base "python.exe")
    }

    foreach ($candidate in $candidates) {
        if (Test-RealPythonExe $candidate) {
            return $candidate
        }
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd -and -not ($pyCmd.Source.ToLowerInvariant() -match '\\windowsapps\\')) {
        foreach ($ver in @("-3.13", "-3.12", "-3.11", "-3")) {
            try {
                $resolved = & $pyCmd.Source $ver -c "import sys; print(sys.executable)" 2>$null
                $resolved = ($resolved | Select-Object -Last 1).ToString().Trim()
                if (Test-RealPythonExe $resolved) {
                    return $resolved
                }
            } catch {
            }
        }
    }

    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and (Test-RealPythonExe $cmd.Source)) {
            return $cmd.Source
        }
    }

    return $null
}

function Get-PythonInstallHint {
    return @(
        "未找到可用的 Python 3.11+。请按以下步骤操作：",
        "  1. 安装 Python: https://www.python.org/downloads/",
        "     安装时勾选「Add python.exe to PATH」",
        "  2. 关闭 Windows 假 Python 别名：",
        "     设置 → 应用 → 高级应用设置 → 应用执行别名",
        "     关闭「python.exe」和「python3.exe」两个开关",
        "  3. 按 docs/DEPLOYMENT.md 创建 .venv 并安装依赖",
        "  4. 运行: .\scripts\start_console_prod.ps1"
    ) -join "`n"
}

function Invoke-ProjectPython {
    param(
        [string]$ProjectRoot,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    $py = Get-ProjectPythonPath $ProjectRoot
    if (-not $py) {
        Write-Host (Get-PythonInstallHint) -ForegroundColor Red
        exit 1
    }
    & $py @Args
    exit $LASTEXITCODE
}

function Test-PythonModule {
    param(
        [string]$PythonPath,
        [string]$ModuleName
    )
    if (-not (Test-RealPythonExe $PythonPath)) { return $false }
    try {
        & $PythonPath -c "import $ModuleName" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}
