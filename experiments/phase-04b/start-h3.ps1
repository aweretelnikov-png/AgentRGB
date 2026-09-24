param([Parameter(Mandatory=$true)][string]$ExpectedRgb)
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot '../../src'
& python (Join-Path $PSScriptRoot 'run.py') H3 --execute --expected-rgb $ExpectedRgb
Read-Host 'Опыт завершён. Нажмите Enter, чтобы закрыть окно'
