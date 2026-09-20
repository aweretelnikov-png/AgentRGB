param(
    [ValidateSet('detect', 'identify', 'read-config', 'read-color')]
    [string]$Command = 'detect',

    [switch]$AllowReadCommands
)

$ErrorActionPreference = 'Stop'

if (-not ('AgentRgb.AulaF75.HidNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace AgentRgb.AulaF75
{
    public sealed class HidInterfaceInfo
    {
        public string Path { get; set; }
        public ushort VendorId { get; set; }
        public ushort ProductId { get; set; }
        public ushort VersionNumber { get; set; }
        public ushort UsagePage { get; set; }
        public ushort Usage { get; set; }
        public ushort InputReportBytes { get; set; }
        public ushort OutputReportBytes { get; set; }
        public ushort FeatureReportBytes { get; set; }
    }

    public static class HidNative
    {
        private const uint DigcfPresent = 0x00000002;
        private const uint DigcfDeviceInterface = 0x00000010;
        private const uint FileShareRead = 0x00000001;
        private const uint FileShareWrite = 0x00000002;
        private const uint OpenExisting = 3;
        private const uint GenericRead = 0x80000000;
        private const uint GenericWrite = 0x40000000;

        [StructLayout(LayoutKind.Sequential)]
        private struct SpDeviceInterfaceData
        {
            public int Size;
            public Guid InterfaceClassGuid;
            public int Flags;
            public UIntPtr Reserved;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct HiddAttributes
        {
            public int Size;
            public ushort VendorId;
            public ushort ProductId;
            public ushort VersionNumber;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct HidpCaps
        {
            public ushort Usage;
            public ushort UsagePage;
            public ushort InputReportByteLength;
            public ushort OutputReportByteLength;
            public ushort FeatureReportByteLength;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 17)]
            public ushort[] Reserved;
            public ushort NumberLinkCollectionNodes;
            public ushort NumberInputButtonCaps;
            public ushort NumberInputValueCaps;
            public ushort NumberInputDataIndices;
            public ushort NumberOutputButtonCaps;
            public ushort NumberOutputValueCaps;
            public ushort NumberOutputDataIndices;
            public ushort NumberFeatureButtonCaps;
            public ushort NumberFeatureValueCaps;
            public ushort NumberFeatureDataIndices;
        }

        [DllImport("hid.dll")]
        private static extern void HidD_GetHidGuid(out Guid hidGuid);

        [DllImport("hid.dll", SetLastError = true)]
        private static extern bool HidD_GetAttributes(SafeFileHandle device, ref HiddAttributes attributes);

        [DllImport("hid.dll", SetLastError = true)]
        private static extern bool HidD_GetPreparsedData(SafeFileHandle device, out IntPtr preparsedData);

        [DllImport("hid.dll")]
        private static extern bool HidD_FreePreparsedData(IntPtr preparsedData);

        [DllImport("hid.dll")]
        private static extern int HidP_GetCaps(IntPtr preparsedData, ref HidpCaps capabilities);

        [DllImport("hid.dll", SetLastError = true)]
        private static extern bool HidD_SetFeature(SafeFileHandle device, byte[] reportBuffer, int reportBufferLength);

        [DllImport("hid.dll", SetLastError = true)]
        private static extern bool HidD_GetFeature(SafeFileHandle device, byte[] reportBuffer, int reportBufferLength);

        [DllImport("setupapi.dll", SetLastError = true)]
        private static extern IntPtr SetupDiGetClassDevs(ref Guid classGuid, IntPtr enumerator, IntPtr parent, uint flags);

        [DllImport("setupapi.dll", SetLastError = true)]
        private static extern bool SetupDiEnumDeviceInterfaces(IntPtr deviceInfoSet, IntPtr deviceInfoData,
            ref Guid interfaceClassGuid, int memberIndex, ref SpDeviceInterfaceData deviceInterfaceData);

        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetupDiGetDeviceInterfaceDetail(IntPtr deviceInfoSet,
            ref SpDeviceInterfaceData deviceInterfaceData, IntPtr deviceInterfaceDetailData,
            int deviceInterfaceDetailDataSize, out int requiredSize, IntPtr deviceInfoData);

        [DllImport("setupapi.dll")]
        private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(string fileName, uint desiredAccess, uint shareMode,
            IntPtr securityAttributes, uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

        public static HidInterfaceInfo[] Enumerate(ushort vendorId, ushort productId)
        {
            Guid hidGuid;
            HidD_GetHidGuid(out hidGuid);
            IntPtr set = SetupDiGetClassDevs(ref hidGuid, IntPtr.Zero, IntPtr.Zero, DigcfPresent | DigcfDeviceInterface);
            if (set == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());

            var result = new List<HidInterfaceInfo>();
            try
            {
                for (int index = 0; ; index++)
                {
                    var interfaceData = new SpDeviceInterfaceData { Size = Marshal.SizeOf(typeof(SpDeviceInterfaceData)) };
                    if (!SetupDiEnumDeviceInterfaces(set, IntPtr.Zero, ref hidGuid, index, ref interfaceData))
                    {
                        if (Marshal.GetLastWin32Error() == 259) break;
                        throw new Win32Exception(Marshal.GetLastWin32Error());
                    }

                    int required;
                    SetupDiGetDeviceInterfaceDetail(set, ref interfaceData, IntPtr.Zero, 0, out required, IntPtr.Zero);
                    IntPtr detail = Marshal.AllocHGlobal(required);
                    try
                    {
                        Marshal.WriteInt32(detail, IntPtr.Size == 8 ? 8 : 6);
                        if (!SetupDiGetDeviceInterfaceDetail(set, ref interfaceData, detail, required, out required, IntPtr.Zero))
                            throw new Win32Exception(Marshal.GetLastWin32Error());

                        string path = Marshal.PtrToStringUni(IntPtr.Add(detail, 4));
                        using (var handle = CreateFile(path, 0, FileShareRead | FileShareWrite, IntPtr.Zero,
                            OpenExisting, 0, IntPtr.Zero))
                        {
                            if (handle.IsInvalid) continue;
                            var attributes = new HiddAttributes { Size = Marshal.SizeOf(typeof(HiddAttributes)) };
                            if (!HidD_GetAttributes(handle, ref attributes)) continue;
                            if (attributes.VendorId != vendorId || attributes.ProductId != productId) continue;

                            IntPtr preparsed;
                            if (!HidD_GetPreparsedData(handle, out preparsed)) continue;
                            try
                            {
                                var caps = new HidpCaps { Reserved = new ushort[17] };
                                if (HidP_GetCaps(preparsed, ref caps) < 0) continue;
                                result.Add(new HidInterfaceInfo {
                                    Path = path,
                                    VendorId = attributes.VendorId,
                                    ProductId = attributes.ProductId,
                                    VersionNumber = attributes.VersionNumber,
                                    UsagePage = caps.UsagePage,
                                    Usage = caps.Usage,
                                    InputReportBytes = caps.InputReportByteLength,
                                    OutputReportBytes = caps.OutputReportByteLength,
                                    FeatureReportBytes = caps.FeatureReportByteLength
                                });
                            }
                            finally { HidD_FreePreparsedData(preparsed); }
                        }
                    }
                    finally { Marshal.FreeHGlobal(detail); }
                }
            }
            finally { SetupDiDestroyDeviceInfoList(set); }
            return result.ToArray();
        }

        public static byte[] FeatureRead(string path, byte command, ushort payloadLength, int featureReportBytes)
        {
            using (var handle = CreateFile(path, GenericRead | GenericWrite, FileShareRead | FileShareWrite,
                IntPtr.Zero, OpenExisting, 0, IntPtr.Zero))
            {
                if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot open HID interface");
                var request = new byte[featureReportBytes];
                request[0] = 0x06;
                request[1] = command;
                request[2] = 0x01;
                request[4] = 0x01;
                request[6] = (byte)(payloadLength & 0xFF);
                request[7] = (byte)(payloadLength >> 8);
                if (!HidD_SetFeature(handle, request, request.Length))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "SET_FEATURE read request failed");

                var response = new byte[featureReportBytes];
                response[0] = 0x06;
                if (!HidD_GetFeature(handle, response, response.Length))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "GET_FEATURE failed");
                return response;
            }
        }
    }
}
'@
}

$interfaces = [AgentRgb.AulaF75.HidNative]::Enumerate(0x258A, 0x010C)
$interfaces | Select-Object Path,
    @{Name='VID:PID'; Expression={ '{0:X4}:{1:X4}' -f $_.VendorId, $_.ProductId }},
    @{Name='Version'; Expression={ '{0:X4}' -f $_.VersionNumber }},
    @{Name='UsagePage'; Expression={ '0x{0:X4}' -f $_.UsagePage }},
    @{Name='Usage'; Expression={ '0x{0:X4}' -f $_.Usage }},
    InputReportBytes, OutputReportBytes, FeatureReportBytes |
    Format-List

if ($Command -eq 'detect') {
    return
}

if (-not $AllowReadCommands) {
    throw 'identify/read are locked. Re-run with -AllowReadCommands only after explicit user approval.'
}

$candidates = @($interfaces | Where-Object {
    $_.UsagePage -in @(0xFF00, 0xFF13) -and $_.FeatureReportBytes -ge 8
})

if ($candidates.Count -ne 1) {
    throw "Expected exactly one vendor-defined feature interface, found $($candidates.Count). Stop and inspect detect output."
}

$device = $candidates[0]

function Format-Hex([byte[]]$Bytes, [int]$Count) {
    (($Bytes | Select-Object -First $Count | ForEach-Object { '{0:X2}' -f $_ }) -join ' ')
}

function Save-RawResponse([string]$Name, [byte[]]$Bytes) {
    $resultsDirectory = Join-Path $PSScriptRoot 'results'
    [System.IO.Directory]::CreateDirectory($resultsDirectory) | Out-Null
    [System.IO.File]::WriteAllBytes((Join-Path $resultsDirectory "$Name.bin"), $Bytes)
    [System.IO.File]::WriteAllText(
        (Join-Path $resultsDirectory "$Name.hex"),
        ((Format-Hex $Bytes $Bytes.Length) + [Environment]::NewLine))
}

if ($Command -eq 'read-config') {
    $configResponse = [AgentRgb.AulaF75.HidNative]::FeatureRead(
        $device.Path, 0x84, 0x0080, $device.FeatureReportBytes)
    Save-RawResponse 'config-response' $configResponse
    $configPayload = $configResponse[8..135]
    $effectId = $configPayload[18]
    $parameterOffset = 64 + (2 * $effectId)
    $brightness = if ($parameterOffset -lt $configPayload.Length) { $configPayload[$parameterOffset] } else { $null }
    $speedFlags = if (($parameterOffset + 1) -lt $configPayload.Length) { $configPayload[$parameterOffset + 1] } else { $null }
    [PSCustomObject]@{
        EffectId = $effectId
        Brightness = $brightness
        Speed = if ($null -ne $speedFlags) { $speedFlags -shr 4 } else { $null }
        Flags = if ($null -ne $speedFlags) { '0x{0:X1}' -f ($speedFlags -band 0x0F) } else { $null }
        ColorMode = if ($null -eq $speedFlags) { 'unknown' } elseif (($speedFlags -band 0x0F) -eq 0x07) { 'colorful' } elseif (($speedFlags -band 0x0F) -eq 0x00) { 'single' } else { 'palette/unknown' }
        RawFirst136 = Format-Hex $configResponse 136
    } | Format-List
    return
}

if ($Command -eq 'read-color') {
    $colorResponse = [AgentRgb.AulaF75.HidNative]::FeatureRead(
        $device.Path, 0x8A, 0x0200, $device.FeatureReportBytes)
    Save-RawResponse 'color-response' $colorResponse
    $colorPayload = $colorResponse[8..($colorResponse.Length - 1)]
    [PSCustomObject]@{
        PrimaryRgb = if ($colorPayload.Length -ge 32) { '#{0:X2}{1:X2}{2:X2}' -f $colorPayload[29], $colorPayload[30], $colorPayload[31] } else { $null }
        Terminator = if ($colorResponse.Length -gt 0x203) { '{0:X2} {1:X2}' -f $colorResponse[0x202], $colorResponse[0x203] } else { $null }
        Raw = Format-Hex $colorResponse $colorResponse.Length
    } | Format-List
    return
}

$modelResponse = [AgentRgb.AulaF75.HidNative]::FeatureRead(
    $device.Path, 0x82, 0x0006, $device.FeatureReportBytes)
Save-RawResponse 'model-response-full' $modelResponse

$modelId = $modelResponse[8]
[PSCustomObject]@{
    ModelId = '0x{0:X2}' -f $modelId
    Model = if ($modelId -eq 0x03) { 'AULA F75' } else { 'unknown' }
    Raw = Format-Hex $modelResponse 14
} | Format-List
