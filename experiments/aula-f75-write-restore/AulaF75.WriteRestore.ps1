param(
    [ValidateSet('prepare', 'execute')]
    [string]$Command = 'prepare',

    [switch]$AcceptAbsoluteRgbOffset,

    [switch]$ExecuteAuthorized
)

$ErrorActionPreference = 'Stop'

$readOnlyScript = Join-Path $PSScriptRoot '..\aula-f75-readonly\AulaF75.ReadOnly.ps1'
$readOnlyResults = Join-Path $PSScriptRoot '..\aula-f75-readonly\results'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
$resultDirectory = Join-Path $PSScriptRoot "results\$timestamp"
[System.IO.Directory]::CreateDirectory($resultDirectory) | Out-Null

function Format-Hex([byte[]]$Bytes) {
    (($Bytes | ForEach-Object { '{0:X2}' -f $_ }) -join ' ')
}

function Save-Bytes([string]$BaseName, [byte[]]$Bytes) {
    $binaryPath = Join-Path $resultDirectory "$BaseName.bin"
    $hexPath = Join-Path $resultDirectory "$BaseName.hex"
    [System.IO.File]::WriteAllBytes($binaryPath, $Bytes)
    [System.IO.File]::WriteAllText($hexPath, (Format-Hex $Bytes) + [Environment]::NewLine)
}

function Copy-FreshResult([string]$SourceName, [string]$DestinationName) {
    $sourcePath = Join-Path $readOnlyResults $SourceName
    $destinationPath = Join-Path $resultDirectory $DestinationName
    [System.IO.File]::Copy($sourcePath, $destinationPath, $true)
}

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

# Load the independently maintained read-only diagnostic implementation and
# obtain three fresh responses. No write opcode is available in that script.
& $readOnlyScript -Command identify -AllowReadCommands | Out-Host
Copy-FreshResult 'model-response-full.bin' 'fresh-model-response.bin'
Copy-FreshResult 'model-response-full.hex' 'fresh-model-response.hex'

$interfaces = @([AgentRgb.AulaF75.HidNative]::Enumerate(0x258A, 0x010C))
$candidates = @($interfaces | Where-Object {
    $_.Path -match 'vid_258a&pid_010c&mi_01&col06' -and
    $_.UsagePage -eq 0xFF00 -and
    $_.Usage -eq 0x0001 -and
    $_.FeatureReportBytes -eq 520
})
if ($candidates.Count -ne 1) {
    throw "Safety check failed: expected one exact MI_01/COL06 candidate, found $($candidates.Count)."
}
$device = $candidates[0]

$model = [System.IO.File]::ReadAllBytes((Join-Path $resultDirectory 'fresh-model-response.bin'))
$semanticModelId = $model[8]
$psdHigh = $model[12]
$psdLow = $model[13]
if ($semanticModelId -ne 0x03 -or $psdHigh -ne 0x00 -or $psdLow -ne 0xCD) {
    throw ('Safety check failed: model={0:X2}, PSD={1:X2}{2:X2}.' -f $semanticModelId, $psdHigh, $psdLow)
}

& $readOnlyScript -Command read-config -AllowReadCommands | Out-Host
Copy-FreshResult 'config-response.bin' 'fresh-config-response.bin'
Copy-FreshResult 'config-response.hex' 'fresh-config-response.hex'

& $readOnlyScript -Command read-color -AllowReadCommands | Out-Host
Copy-FreshResult 'color-response.bin' 'fresh-color-response.bin'
Copy-FreshResult 'color-response.hex' 'fresh-color-response.hex'

$config = [System.IO.File]::ReadAllBytes((Join-Path $resultDirectory 'fresh-config-response.bin'))
$color = [System.IO.File]::ReadAllBytes((Join-Path $resultDirectory 'fresh-color-response.bin'))

if ($config.Length -ne 520 -or $color.Length -ne 520) {
    throw "Safety check failed: expected 520-byte responses."
}
if ($config[0] -ne 0x06 -or $config[1] -ne 0x84 -or $config[6] -ne 0x80 -or $config[7] -ne 0x00) {
    throw 'Safety check failed: unexpected config response header.'
}
if ($config[134] -ne 0x5A -or $config[135] -ne 0xA5) {
    throw 'Safety check failed: config terminator is not 5A A5.'
}
if ($color[0] -ne 0x06 -or $color[1] -ne 0x8A -or $color[7] -ne 0x02) {
    throw 'Safety check failed: unexpected color response header.'
}
if ($color[0x202] -ne 0x5A -or $color[0x203] -ne 0xA5) {
    throw 'Safety check failed: color terminator is not 5A A5.'
}

$effectId = $config[8 + 18]
$parameterOffset = 8 + 64 + (2 * $effectId)
$brightness = $config[$parameterOffset]
$speedFlags = $config[$parameterOffset + 1]
$speed = $speedFlags -shr 4
$flags = $speedFlags -band 0x0F

$absoluteRgb = $color[29..31]
$payloadRelativeRgb = $color[(8 + 29)..(8 + 31)]

$snapshot = [ordered]@{
    timestamp = $timestamp
    path = $device.Path
    vid = '0x258A'
    pid = '0x010C'
    usage_page = '0xFF00'
    usage = '0x0001'
    feature_report_bytes = 520
    semantic_model_id = '0x{0:X2}' -f $semanticModelId
    psd = '0x{0:X2}{1:X2}' -f $psdHigh, $psdLow
    effect_id = $effectId
    brightness = $brightness
    speed = $speed
    flags = '0x{0:X1}' -f $flags
    rgb_absolute_29_31 = '#{0:X2}{1:X2}{2:X2}' -f $absoluteRgb[0], $absoluteRgb[1], $absoluteRgb[2]
    rgb_payload_29_31 = '#{0:X2}{1:X2}{2:X2}' -f $payloadRelativeRgb[0], $payloadRelativeRgb[1], $payloadRelativeRgb[2]
}
[System.IO.File]::WriteAllText(
    (Join-Path $resultDirectory 'snapshot.json'),
    ($snapshot | ConvertTo-Json) + [Environment]::NewLine)

$hashLines = Get-ChildItem -LiteralPath $resultDirectory -File |
    Where-Object { $_.Name -ne 'sha256.txt' } |
    Sort-Object Name |
    ForEach-Object { '{0}  {1}' -f (Get-Sha256 $_.FullName), $_.Name }
[System.IO.File]::WriteAllLines((Join-Path $resultDirectory 'sha256.txt'), $hashLines)

$snapshot | Format-List

if ($effectId -ne 1 -or $brightness -ne 8 -or $speed -ne 3 -or $flags -ne 7) {
    throw 'Fresh config differs materially from the previous observation. No write report was prepared.'
}

if ((Format-Hex $absoluteRgb) -ne (Format-Hex $payloadRelativeRgb) -and -not $AcceptAbsoluteRgbOffset) {
    throw ('RGB offset ambiguity: absolute report [29..31]={0}, payload-relative [29..31]={1}. No write report was prepared.' -f
        (Format-Hex $absoluteRgb), (Format-Hex $payloadRelativeRgb))
}

# The report shape follows the field-tested MIT implementation: a new zeroed
# 520-byte request, not a mutated read response. AcceptAbsoluteRgbOffset records
# the explicit decision to prefer its absolute report offsets over the ambiguous
# wording in PROTOCOL.md. This command only creates files; it has no HID write API.
$changeReport = [byte[]]::new(520)
$changeReport[0] = 0x06
$changeReport[1] = 0x0A
$changeReport[7] = 0x02
$changeReport[29] = 0x00
$changeReport[30] = 0x00
$changeReport[31] = 0xFF
$changeReport[0x202] = 0x5A
$changeReport[0x203] = 0xA5
Save-Bytes 'prepared-change-report' $changeReport

$restoreReport = [byte[]]::new(520)
$restoreReport[0] = 0x06
$restoreReport[1] = 0x0A
$restoreReport[7] = 0x02
$restoreReport[29] = $absoluteRgb[0]
$restoreReport[30] = $absoluteRgb[1]
$restoreReport[31] = $absoluteRgb[2]
$restoreReport[0x202] = 0x5A
$restoreReport[0x203] = 0xA5
Save-Bytes 'prepared-restore-report' $restoreReport

$requestDiff = for ($index = 0; $index -lt 520; $index++) {
    if ($restoreReport[$index] -ne $changeReport[$index]) {
        '0x{0:X3}: restore {1:X2} -> change {2:X2}' -f $index, $restoreReport[$index], $changeReport[$index]
    }
}
[System.IO.File]::WriteAllLines((Join-Path $resultDirectory 'semantic-request-diff.txt'), $requestDiff)

$wireDiff = for ($index = 0; $index -lt 520; $index++) {
    if ($color[$index] -ne $changeReport[$index]) {
        '0x{0:X3}: read-response {1:X2} -> change-request {2:X2}' -f $index, $color[$index], $changeReport[$index]
    }
}
[System.IO.File]::WriteAllLines((Join-Path $resultDirectory 'read-response-vs-change-request-diff.txt'), $wireDiff)

$preparation = [ordered]@{
    source_rgb_offset = 'absolute report [29..31]'
    source_rgb = '#{0:X2}{1:X2}{2:X2}' -f $absoluteRgb[0], $absoluteRgb[1], $absoluteRgb[2]
    test_rgb = '#0000FF'
    report_length = 520
    report_id = '0x06'
    opcode = '0x0A'
    length_high_byte_at_7 = '0x02'
    terminator_offset = '0x202..0x203'
    terminator = '5A A5'
    normal_write_operations = 2
    hid_write_api_present = $false
}
[System.IO.File]::WriteAllText(
    (Join-Path $resultDirectory 'preparation.json'),
    ($preparation | ConvertTo-Json) + [Environment]::NewLine)

$hashLines = Get-ChildItem -LiteralPath $resultDirectory -File |
    Where-Object { $_.Name -ne 'sha256.txt' } |
    Sort-Object Name |
    ForEach-Object { '{0}  {1}' -f (Get-Sha256 $_.FullName), $_.Name }
[System.IO.File]::WriteAllLines((Join-Path $resultDirectory 'sha256.txt'), $hashLines)

Write-Host "Prepared reports in $resultDirectory. No write command was sent."

if ($Command -eq 'prepare') {
    return
}

if (-not $ExecuteAuthorized) {
    throw 'execute is locked. Pass -ExecuteAuthorized only after explicit user permission for the two 0x0A writes.'
}

if (-not ('AgentRgb.AulaF75.HidWriteNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace AgentRgb.AulaF75
{
    public static class HidWriteNative
    {
        private const uint GenericRead = 0x80000000;
        private const uint GenericWrite = 0x40000000;
        private const uint FileShareRead = 0x00000001;
        private const uint FileShareWrite = 0x00000002;
        private const uint OpenExisting = 3;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(string fileName, uint desiredAccess, uint shareMode,
            IntPtr securityAttributes, uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

        [DllImport("hid.dll", SetLastError = true)]
        private static extern bool HidD_SetFeature(SafeFileHandle device, byte[] reportBuffer, int reportBufferLength);

        public static void SendFeature(string path, byte[] report)
        {
            if (report == null || report.Length != 520 || report[0] != 0x06 || report[1] != 0x0A)
                throw new InvalidOperationException("Only a 520-byte report 0x06/opcode 0x0A is permitted.");

            using (var handle = CreateFile(path, GenericRead | GenericWrite, FileShareRead | FileShareWrite,
                IntPtr.Zero, OpenExisting, 0, IntPtr.Zero))
            {
                if (handle.IsInvalid)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot open exact HID interface for write");
                if (!HidD_SetFeature(handle, report, report.Length))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "HidD_SetFeature failed");
            }
        }
    }
}
'@
}

function Read-ColorAfterWrite([string]$BaseName) {
    $response = [AgentRgb.AulaF75.HidNative]::FeatureRead($device.Path, 0x8A, 0x0200, 520)
    Save-Bytes $BaseName $response
    return $response
}

function Read-ConfigAfterWrite([string]$BaseName) {
    $response = [AgentRgb.AulaF75.HidNative]::FeatureRead($device.Path, 0x84, 0x0080, 520)
    Save-Bytes $BaseName $response
    return $response
}

function Get-Differences([byte[]]$Left, [byte[]]$Right, [int[]]$IgnoredIndices = @()) {
    $ignored = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($index in $IgnoredIndices) { [void]$ignored.Add($index) }
    @(for ($index = 0; $index -lt $Left.Length; $index++) {
        if (-not $ignored.Contains($index) -and $Left[$index] -ne $Right[$index]) {
            [PSCustomObject]@{ Index=$index; Before=$Left[$index]; After=$Right[$index] }
        }
    })
}

$writeCount = 0
$changeSent = $false
$restoreSent = $false
$experimentError = $null

Write-Host 'DEVICE: AULA F75 / 258A:010C / MI_01/COL06'
Write-Host ('CURRENT: #{0:X2}{1:X2}{2:X2}' -f $absoluteRgb[0], $absoluteRgb[1], $absoluteRgb[2])
Write-Host 'CHANGE:  #0000FF'
Write-Host ('RESTORE: #{0:X2}{1:X2}{2:X2}' -f $absoluteRgb[0], $absoluteRgb[1], $absoluteRgb[2])
Write-Host 'WRITE COUNT: 2 maximum (change + restore)'
Write-Host ('RESULTS: {0}' -f $resultDirectory)

try {
    [AgentRgb.AulaF75.HidWriteNative]::SendFeature($device.Path, $changeReport)
    $writeCount++
    $changeSent = $true
    Write-Host 'CHANGE_WRITE_SENT: 1'

    $changeReadback = Read-ColorAfterWrite 'change-readback'
    $changeRgb = $changeReadback[29..31]
    Write-Host ('CHANGE_READBACK_RGB: #{0:X2}{1:X2}{2:X2}' -f $changeRgb[0], $changeRgb[1], $changeRgb[2])
    if ((Format-Hex $changeRgb) -ne '00 00 FF') {
        throw ('Change read-back mismatch: expected 00 00 FF, got {0}.' -f (Format-Hex $changeRgb))
    }

    $unexpectedChange = Get-Differences $color $changeReadback @(29, 30, 31)
    if ($unexpectedChange.Count -ne 0) {
        [System.IO.File]::WriteAllText(
            (Join-Path $resultDirectory 'unexpected-change-diff.json'),
            ($unexpectedChange | ConvertTo-Json) + [Environment]::NewLine)
        throw "Change read-back modified $($unexpectedChange.Count) bytes outside primary RGB."
    }

    $visualChange = Read-Host 'Type BLUE only if the keyboard is visibly blue; any other input triggers restore'
    if ($visualChange -cne 'BLUE') {
        throw 'Visual blue confirmation was not received.'
    }

    [AgentRgb.AulaF75.HidWriteNative]::SendFeature($device.Path, $restoreReport)
    $writeCount++
    $restoreSent = $true
    Write-Host 'RESTORE_WRITE_SENT: 1'

    $restoreColorReadback = Read-ColorAfterWrite 'restore-color-readback'
    $restoreConfigReadback = Read-ConfigAfterWrite 'restore-config-readback'
    $restoreRgb = $restoreColorReadback[29..31]
    $colorFullyEqual = [System.Linq.Enumerable]::SequenceEqual[byte]($color, $restoreColorReadback)
    $configFullyEqual = [System.Linq.Enumerable]::SequenceEqual[byte]($config, $restoreConfigReadback)
    Write-Host ('RESTORE_READBACK_RGB: #{0:X2}{1:X2}{2:X2}' -f $restoreRgb[0], $restoreRgb[1], $restoreRgb[2])
    Write-Host "RESTORE_COLOR_FULL_EQUAL: $colorFullyEqual"
    Write-Host "RESTORE_CONFIG_FULL_EQUAL: $configFullyEqual"
    if ((Format-Hex $restoreRgb) -ne (Format-Hex $absoluteRgb)) {
        throw ('Restore RGB mismatch: expected {0}, got {1}.' -f (Format-Hex $absoluteRgb), (Format-Hex $restoreRgb))
    }
    if (-not $configFullyEqual) {
        throw 'Config changed during color-only experiment.'
    }

    $visualRestore = Read-Host 'Type RESTORED only if the original visual state returned; no further writes will occur'
    if ($visualRestore -cne 'RESTORED') {
        throw 'Visual restoration was not confirmed.'
    }
}
catch {
    $experimentError = $_
    Write-Error $_ -ErrorAction Continue
}
finally {
    if ($changeSent -and -not $restoreSent) {
        try {
            Write-Host 'CONTROLLED_RESTORE_ATTEMPT: 1'
            [AgentRgb.AulaF75.HidWriteNative]::SendFeature($device.Path, $restoreReport)
            $writeCount++
            $restoreSent = $true
            $emergencyColor = Read-ColorAfterWrite 'controlled-restore-color-readback'
            $emergencyConfig = Read-ConfigAfterWrite 'controlled-restore-config-readback'
            Write-Host ('CONTROLLED_RESTORE_RGB: #{0:X2}{1:X2}{2:X2}' -f $emergencyColor[29], $emergencyColor[30], $emergencyColor[31])
            Write-Host ('CONTROLLED_RESTORE_CONFIG_EQUAL: {0}' -f [System.Linq.Enumerable]::SequenceEqual[byte]($config, $emergencyConfig))
        }
        catch {
            Write-Error "Controlled restore failed: $_" -ErrorAction Continue
        }
    }

    $final = [ordered]@{
        write_count = $writeCount
        change_sent = $changeSent
        restore_sent = $restoreSent
        error = if ($null -ne $experimentError) { $experimentError.ToString() } else { $null }
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $resultDirectory 'execution-summary.json'),
        ($final | ConvertTo-Json) + [Environment]::NewLine)
    Write-Host "FINAL_WRITE_COUNT: $writeCount"
}

if ($null -ne $experimentError) {
    throw $experimentError
}
