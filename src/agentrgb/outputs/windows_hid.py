"""Минимальные ctypes bindings Windows HID для AULA, без протокола RGB."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os

LOG = logging.getLogger("agentrgb.hid")


@dataclass(frozen=True)
class Interface:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    feature_bytes: int


class GUID(C.Structure):
    _fields_ = [("data1", W.DWORD), ("data2", W.WORD), ("data3", W.WORD), ("data4", C.c_ubyte * 8)]


class InterfaceData(C.Structure):
    _fields_ = [("size", W.DWORD), ("guid", GUID), ("flags", W.DWORD), ("reserved", C.c_size_t)]


class Attributes(C.Structure):
    _fields_ = [("size", W.DWORD), ("vid", W.WORD), ("pid", W.WORD), ("version", W.WORD)]


class Caps(C.Structure):
    _fields_ = [("usage", W.WORD), ("usage_page", W.WORD), ("input_bytes", W.WORD),
                ("output_bytes", W.WORD), ("feature_bytes", W.WORD), ("reserved", W.WORD * 17),
                ("counts", W.WORD * 10)]


class FeatureCaps(C.Structure):
    """HIDP_VALUE_CAPS/HIDP_BUTTON_CAPS: both 72 bytes, ReportID at byte 2."""
    _fields_ = [("raw", C.c_ubyte * 72)]


class WindowsHid:
    def __init__(self, diagnostic_sink=None):
        if os.name != "nt":
            raise OSError("windows_required")
        self.diagnostic_sink = diagnostic_sink
        self.get_sequence = 0
        self.last_get_diagnostic = None
        self.requests = {}
        self.hid = C.WinDLL("hid", use_last_error=True)
        self.setup = C.WinDLL("setupapi", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        # Указывать типы обязательно: HANDLE/указатели нельзя усекать на x64.
        signatures = [
            (self.hid, "HidD_GetHidGuid", [C.POINTER(GUID)], None),
            (self.hid, "HidD_GetAttributes", [W.HANDLE, C.POINTER(Attributes)], C.c_ubyte),
            (self.hid, "HidD_GetPreparsedData", [W.HANDLE, C.POINTER(C.c_void_p)], C.c_ubyte),
            (self.hid, "HidD_FreePreparsedData", [C.c_void_p], C.c_ubyte),
            (self.hid, "HidP_GetCaps", [C.c_void_p, C.POINTER(Caps)], C.c_long),
            (self.hid, "HidP_GetValueCaps", [C.c_int, C.c_void_p, C.POINTER(W.WORD), C.c_void_p], C.c_long),
            (self.hid, "HidP_GetButtonCaps", [C.c_int, C.c_void_p, C.POINTER(W.WORD), C.c_void_p], C.c_long),
            (self.hid, "HidD_SetFeature", [W.HANDLE, C.c_void_p, W.ULONG], C.c_ubyte),
            (self.hid, "HidD_GetFeature", [W.HANDLE, C.c_void_p, W.ULONG], C.c_ubyte),
            (self.setup, "SetupDiGetClassDevsW", [C.POINTER(GUID), W.LPCWSTR, W.HWND, W.DWORD], W.HANDLE),
            (self.setup, "SetupDiEnumDeviceInterfaces", [W.HANDLE, C.c_void_p, C.POINTER(GUID), W.DWORD, C.POINTER(InterfaceData)], W.BOOL),
            (self.setup, "SetupDiGetDeviceInterfaceDetailW", [W.HANDLE, C.POINTER(InterfaceData), C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            (self.setup, "SetupDiDestroyDeviceInfoList", [W.HANDLE], W.BOOL),
            (self.kernel, "CreateFileW", [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
            (self.kernel, "CloseHandle", [W.HANDLE], W.BOOL),
        ]
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result

    @staticmethod
    def check(success):
        if not success:
            raise C.WinError(C.get_last_error())

    def open(self, path, access=0xC0000000):
        handle = self.kernel.CreateFileW(path, access, 3, None, 3, 0, None)
        if handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        return handle

    def close(self, handle):
        try:
            self.check(self.kernel.CloseHandle(handle))
        finally:
            self.requests.pop(handle, None)

    def describe(self, handle, path):
        attributes = Attributes(size=C.sizeof(Attributes))
        self.check(self.hid.HidD_GetAttributes(handle, C.byref(attributes)))
        preparsed = C.c_void_p()
        self.check(self.hid.HidD_GetPreparsedData(handle, C.byref(preparsed)))
        try:
            caps = Caps()
            if self.hid.HidP_GetCaps(preparsed, C.byref(caps)) != 0x00110000:
                raise OSError("hid_caps_failed")
            return Interface(path, attributes.vid, attributes.pid, caps.usage_page, caps.usage, caps.feature_bytes)
        finally:
            self.hid.HidD_FreePreparsedData(preparsed)

    def feature_report_ids(self, handle):
        """Read declared feature IDs from the opened collection's HIDP caps."""
        preparsed = C.c_void_p()
        self.check(self.hid.HidD_GetPreparsedData(handle, C.byref(preparsed)))
        try:
            caps = Caps()
            if self.hid.HidP_GetCaps(preparsed, C.byref(caps)) & 0xFFFFFFFF != 0x00110000:
                raise OSError("hid_caps_failed")
            report_ids = set()
            for index, function in ((8, self.hid.HidP_GetValueCaps),
                                    (7, self.hid.HidP_GetButtonCaps)):
                count = caps.counts[index]
                if count > 4096:
                    raise OSError("excessive_feature_caps")
                if not count:
                    continue
                entries = (FeatureCaps * count)()
                actual = W.WORD(count)
                status = function(2, C.cast(entries, C.c_void_p), C.byref(actual), preparsed)
                if status & 0xFFFFFFFF != 0x00110000 or actual.value > count:
                    raise OSError("hid_feature_caps_failed")
                report_ids.update(entries[i].raw[2] for i in range(actual.value))
            return frozenset(report_ids)
        finally:
            self.hid.HidD_FreePreparsedData(preparsed)

    def enumerate(self):
        guid = GUID()
        self.hid.HidD_GetHidGuid(C.byref(guid))
        device_set = self.setup.SetupDiGetClassDevsW(C.byref(guid), None, None, 0x12)
        if device_set == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        result = []
        try:
            index = 0
            while True:
                info = InterfaceData(size=C.sizeof(InterfaceData))
                if not self.setup.SetupDiEnumDeviceInterfaces(device_set, None, C.byref(guid), index, C.byref(info)):
                    if C.get_last_error() == 259:
                        break
                    raise C.WinError(C.get_last_error())
                index += 1
                needed = W.DWORD()
                self.setup.SetupDiGetDeviceInterfaceDetailW(device_set, C.byref(info), None, 0, C.byref(needed), None)
                if not needed.value:
                    raise OSError("hid_detail_size_failed")
                detail = C.create_string_buffer(needed.value)
                C.cast(detail, C.POINTER(W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
                self.check(self.setup.SetupDiGetDeviceInterfaceDetailW(device_set, C.byref(info), detail, needed, C.byref(needed), None))
                path = C.wstring_at(C.addressof(detail) + 4)
                # Не открывать интерфейсы других устройств даже для описания.
                if "vid_258a&pid_010c" not in path.lower():
                    continue
                handle = self.open(path, access=0)
                try:
                    result.append(self.describe(handle, path))
                finally:
                    self.close(handle)
        finally:
            self.setup.SetupDiDestroyDeviceInfoList(device_set)
        return result

    def set_feature(self, handle, report):
        buffer = (C.c_ubyte * len(report)).from_buffer_copy(report)
        self.requests.pop(handle, None)
        self.check(self.hid.HidD_SetFeature(handle, buffer, len(report)))
        self.requests[handle] = bytes(buffer)

    def get_feature(self, handle, report_id, length):
        buffer = (C.c_ubyte * length)()
        buffer[0] = report_id
        success = bool(self.hid.HidD_GetFeature(handle, buffer, length))
        # Считать ошибку немедленно, до логирования и любых других WinAPI calls.
        error = C.get_last_error() if not success else None
        raw = bytes(buffer)
        request = self.requests.pop(handle, None)
        self.get_sequence += 1
        record = dict(sequence=self.get_sequence, timestamp=datetime.now(timezone.utc).isoformat(),
                      requested_opcode=request[1] if request and len(request) >= 2 else None,
                      request_header_hex=request[:8].hex(" ") if request else None,
                      api_success=success, buffer_size=length, initial_report_id=report_id,
                      first32_hex=raw[:32].hex(" "), terminator_hex=raw[0x202:0x204].hex(" "))
        if not success:
            record["get_last_error"] = error
        self.last_get_diagnostic = record
        LOG.debug("HID get sequence=%d success=%s first16=%s", self.get_sequence, success, raw[:16].hex(" "))
        # Экспериментальный sink сохраняет даже API failure/невалидный response.
        # В production sink отсутствует; полный report не логируется и не пишется на диск.
        if self.diagnostic_sink is not None:
            self.diagnostic_sink({**record, "raw_response": raw, "raw_request": request})
        if not success:
            raise C.WinError(error)
        return raw
