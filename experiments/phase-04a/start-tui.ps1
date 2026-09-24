param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('B','C')]
    [string]$Scenario
)
$ErrorActionPreference = 'Stop'
$piCli = Join-Path $env:APPDATA 'npm/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
& node (Join-Path $PSScriptRoot 'run.mjs') $Scenario $piCli
Read-Host 'Опыт завершён. Нажмите Enter, чтобы закрыть окно'
