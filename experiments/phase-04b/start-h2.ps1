$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot '../../src'
& python (Join-Path $PSScriptRoot 'run.py') H2 --execute --expected-rgb FF0000
Read-Host 'Опыт завершён. Нажмите Enter, чтобы закрыть окно'
