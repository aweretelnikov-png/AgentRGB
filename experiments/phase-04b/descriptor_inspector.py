"""Read-only Windows HID collection/capability inventory for the D1 failure.

This module never calls SetFeature, GetFeature, ReadFile, or WriteFile.
Device paths are transient and only their SHA-256 hashes leave the process.
"""

import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from agentrgb.outputs.windows_hid import Attributes, Caps, WindowsHid


HIDP_FEATURE = 2
HIDP_STATUS_SUCCESS = 0x00110000
MAX_CAPS = 4096


class ValueCaps(C.Structure):
    # hidpi.h HIDP_VALUE_CAPS. ReportID is at offset 2; full size is 72.
    _fields_ = [
        ("usage_page", W.WORD), ("report_id", C.c_ubyte), ("is_alias", C.c_ubyte),
        ("bit_field", W.WORD), ("link_collection", W.WORD),
        ("link_usage", W.WORD), ("link_usage_page", W.WORD),
        ("is_range", C.c_ubyte), ("is_string_range", C.c_ubyte),
        ("is_designator_range", C.c_ubyte), ("is_absolute", C.c_ubyte),
        ("has_null", C.c_ubyte), ("reserved", C.c_ubyte),
        ("bit_size", W.WORD), ("report_count", W.WORD),
        ("reserved2", W.WORD * 5), ("units_exp", W.ULONG),
        ("units", W.ULONG), ("logical_min", W.LONG),
        ("logical_max", W.LONG), ("physical_min", W.LONG),
        ("physical_max", W.LONG), ("range_or_not_range", C.c_ubyte * 16),
    ]


class ButtonCaps(C.Structure):
    # hidpi.h HIDP_BUTTON_CAPS. ReportID is at offset 2; full size is 72.
    _fields_ = [
        ("usage_page", W.WORD), ("report_id", C.c_ubyte), ("is_alias", C.c_ubyte),
        ("bit_field", W.WORD), ("link_collection", W.WORD),
        ("link_usage", W.WORD), ("link_usage_page", W.WORD),
        ("is_range", C.c_ubyte), ("is_string_range", C.c_ubyte),
        ("is_designator_range", C.c_ubyte), ("is_absolute", C.c_ubyte),
        ("report_count", W.WORD), ("reserved2", W.WORD),
        ("reserved", W.ULONG * 9), ("range_or_not_range", C.c_ubyte * 16),
    ]


def path_identity(path):
    """Return only collection labels and a stable hash, never the raw path."""
    lowered = path.lower()
    mi = re.search(r"&mi_([0-9a-f]{2})", lowered)
    col = re.search(r"&col([0-9a-f]{2})", lowered)
    return {
        "mi": mi.group(1).upper() if mi else None,
        "col": col.group(1).upper() if col else None,
        "path_sha256": hashlib.sha256(lowered.encode("utf-16le")).hexdigest(),
    }


def feature_ids(value_ids, button_ids):
    return sorted(set(value_ids) | set(button_ids))


def classification(collections):
    current = [row for row in collections if row["mi"] == "01" and row["col"] == "06"]
    all_ids = {int(report_id, 16) for row in collections for report_id in row["feature_ids"]}
    current_ids = {int(report_id, 16) for row in current for report_id in row["feature_ids"]}
    if not current:
        return "current_collection_missing"
    if 0x39 in current_ids and 0x3C in current_ids:
        return "enable_ids_in_current_collection"
    if 0x39 in all_ids or 0x3C in all_ids:
        return "enable_ids_in_other_collection_or_split"
    return "enable_ids_absent_from_all_collections"


def _caps_ids(hid, preparsed, count, structure, function_name):
    if not count:
        return []
    if count > MAX_CAPS:
        raise ValueError(f"excessive_{function_name}_count:{count}")
    values = (structure * count)()
    actual = W.WORD(count)
    status = getattr(hid, function_name)(HIDP_FEATURE, C.cast(values, C.c_void_p),
                                         C.byref(actual), preparsed)
    if status & 0xFFFFFFFF != HIDP_STATUS_SUCCESS:
        raise OSError(f"{function_name}_failed:{status & 0xFFFFFFFF:08X}")
    if actual.value > count:
        raise OSError(f"{function_name}_overflow")
    return [values[i].report_id for i in range(actual.value)]


def inspect_interface(backend, interface):
    handle = backend.open(interface.path, access=0)
    try:
        attrs = Attributes(size=C.sizeof(Attributes))
        backend.check(backend.hid.HidD_GetAttributes(handle, C.byref(attrs)))
        if (attrs.vid, attrs.pid) != (0x258A, 0x010C):
            raise OSError("vid_pid_changed_during_inspection")
        preparsed = C.c_void_p()
        backend.check(backend.hid.HidD_GetPreparsedData(handle, C.byref(preparsed)))
        try:
            caps = Caps()
            status = backend.hid.HidP_GetCaps(preparsed, C.byref(caps))
            if status & 0xFFFFFFFF != HIDP_STATUS_SUCCESS:
                raise OSError(f"HidP_GetCaps_failed:{status & 0xFFFFFFFF:08X}")
            value_ids = _caps_ids(backend.hid, preparsed, caps.counts[8], ValueCaps,
                                  "HidP_GetValueCaps")
            button_ids = _caps_ids(backend.hid, preparsed, caps.counts[7], ButtonCaps,
                                   "HidP_GetButtonCaps")
            return {
                **path_identity(interface.path), "vid": f"{attrs.vid:04X}",
                "pid": f"{attrs.pid:04X}", "usage_page": f"{caps.usage_page:04X}",
                "usage": f"{caps.usage:04X}", "input_bytes": caps.input_bytes,
                "output_bytes": caps.output_bytes, "feature_bytes": caps.feature_bytes,
                "number_feature_value_caps": caps.counts[8],
                "number_feature_button_caps": caps.counts[7],
                "value_feature_ids": [f"{item:02X}" for item in sorted(set(value_ids))],
                "button_feature_ids": [f"{item:02X}" for item in sorted(set(button_ids))],
                "feature_ids": [f"{item:02X}" for item in feature_ids(value_ids, button_ids)],
            }
        finally:
            backend.check(backend.hid.HidD_FreePreparsedData(preparsed))
    finally:
        backend.close(handle)


def inspect_all(backend):
    rows = [inspect_interface(backend, interface) for interface in backend.enumerate()]
    rows.sort(key=lambda row: (row["mi"] or "", row["col"] or "", row["path_sha256"]))
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "collection_count": len(rows), "collections": rows,
            "classification": classification(rows), "hid_write_attempts": 0}


def main():
    if C.sizeof(ValueCaps) != 72 or C.sizeof(ButtonCaps) != 72:
        raise OSError("unexpected_HIDP_caps_structure_layout")
    result = inspect_all(WindowsHid())
    output = Path(__file__).parent / "results" / "direct-d1-descriptor.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
