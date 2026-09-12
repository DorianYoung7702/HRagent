# 强制停止本机 HR Agent API（Ctrl+C 无效或端口被占用时使用）
param(
    [int]$Port = 8001
)

. "$PSScriptRoot\_port_utils.ps1"
Stop-HrAgentOnPort -Port $Port | Out-Null
