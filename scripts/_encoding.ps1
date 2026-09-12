# Shared encoding setup for Windows PowerShell 5.x / Terminal
# Script files must be saved as UTF-8 WITH BOM so Chinese literals parse correctly.
try { chcp 65001 | Out-Null } catch {}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
