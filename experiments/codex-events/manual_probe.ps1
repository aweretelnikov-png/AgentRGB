# Открывать пользователю для проверки настоящего CLI UI, не перенаправлять вывод.
$ErrorActionPreference = 'Stop'
$probeFile = Join-Path $PSScriptRoot 'cli_probe.py'
$outputFile = Join-Path $PSScriptRoot '_local/hooks-manual.jsonl'
python $probeFile manual --output $outputFile
