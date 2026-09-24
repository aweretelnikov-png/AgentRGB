$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'AgentRGB 04B-C1 — visual confirmation'
$env:PYTHONPATH = Join-Path $PSScriptRoot '../../src'
& python -u (Join-Path $PSScriptRoot 'c1.py') --execute
Read-Host 'C1 завершён. Нажмите Enter, чтобы закрыть окно'
