# Read-only опыт 03O. Не сохраняет полные command lines, пути или environment.
param([Parameter(Mandatory=$true)][string]$OutputFile)
$ErrorActionPreference = 'Stop'
$all = @(Get-CimInstance -Query 'SELECT ProcessId,ParentProcessId,Name FROM Win32_Process')
$roots = @($all | Where-Object { $_.Name -match '^(codex|chatgpt)\.exe$' })
$ids = [Collections.Generic.HashSet[uint32]]::new()
foreach ($item in $roots) { [void]$ids.Add([uint32]$item.ProcessId) }
do {
    $changed = $false
    foreach ($item in $all) {
        if ($ids.Contains([uint32]$item.ParentProcessId)) {
            if ($ids.Add([uint32]$item.ProcessId)) { $changed = $true }
        }
    }
} while ($changed)
$processes = @()
foreach ($item in $all | Where-Object { $ids.Contains([uint32]$_.ProcessId) }) {
    $record = [ordered]@{ pid=$item.ProcessId; parent_pid=$item.ParentProcessId; name=$item.Name }
    if ($item.Name -match '^(codex|chatgpt)\.exe$') {
        $detail = Get-CimInstance -Query ("SELECT CommandLine,ExecutablePath FROM Win32_Process WHERE ProcessId=" + $item.ProcessId)
        $line = $detail.CommandLine
        $record['command_line_available'] = ($null -ne $line)
        $record['app_server'] = [bool]($line -match '(?:^|\s)app-server(?:\s|$)')
        $record['proxy'] = [bool]($line -match '(?:^|\s)proxy(?:\s|$)')
        $record['daemon'] = [bool]($line -match '(?:^|\s)daemon(?:\s|$)')
        $record['stdio_flag'] = [bool]($line -match '(?:^|\s)--stdio(?:\s|$)')
        $record['listen_flag'] = [bool]($line -match '(?:^|\s)--listen(?:\s|=)')
        $record['remote_flag'] = [bool]($line -match '(?:^|\s)--remote(?:\s|=)')
        $record['sock_flag'] = [bool]($line -match '(?:^|\s)--sock(?:\s|=)')
        $record['ws_auth_flag'] = [bool]($line -match '(?:^|\s)--ws-(auth|token-file|token-sha256|shared-secret-file)(?:\s|=)')
        $record['electron_type'] = $null
        if ($line -match '--type=(renderer|gpu-process|utility|crashpad-handler)\b') {
            $record['electron_type'] = $Matches[1]
        }
        $record['listen_kind'] = $null
        # Не сохранять query, path, credentials или произвольные значения флагов.
        if ($line -match '--listen(?:\s+|=)"?(stdio://|off)(?:"|\s|$)') {
            $record['listen_kind'] = $Matches[1]
        } elseif ($line -match '--listen(?:\s+|=)"?(ws://(?:127\.0\.0\.1|\[::1\]):[0-9]+)(?:"|\s|$)') {
            $record['listen_kind'] = $Matches[1]
        } elseif ($line -match '--listen(?:\s+|=)"?unix://') {
            $record['listen_kind'] = 'unix://<path omitted>'
        }
        if ($detail.ExecutablePath) {
            $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($detail.ExecutablePath)
            $record['product_version'] = $version.ProductVersion
            $record['product_name'] = $version.ProductName
        }
    }
    $processes += [pscustomobject]$record
}
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $ids.Contains([uint32]$_.OwningProcess) } | ForEach-Object {
    [pscustomobject]@{ pid=$_.OwningProcess; address=$_.LocalAddress; port=$_.LocalPort }
})
$pipeNames = @([IO.Directory]::GetFiles('\\.\pipe\') | ForEach-Object { $_.Substring(9) } | Where-Object { $_ -match '(?i)codex|chatgpt|openai' })
$pipes = @($pipeNames | ForEach-Object {
    # Семейство имени достаточно для отчёта; ownership перечисление pipe не даёт.
    $family = [regex]::Replace($_, '[0-9a-fA-F]{8,}(?:-[0-9a-fA-F-]+)?', '<id>')
    [pscustomobject]@{ name=$family; ownership='not established' }
})
$result = [ordered]@{
    timestamp=[DateTime]::UtcNow.ToString('o'); processes=$processes;
    tcp_listeners=$listeners; named_pipes=$pipes
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputFile -Encoding utf8
$result | ConvertTo-Json -Depth 8
