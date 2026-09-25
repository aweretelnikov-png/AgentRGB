"""Проверка identity AULA F75 без изменения RGB и пользовательского профиля."""
import os

from .aula_f75 import AulaError, REPORT_BYTES, matches, read_request, validate_response
from .windows_hid import WindowsHid


def check_f75() -> int:
    if os.name != "nt":
        print("AULA F75: unsupported platform")
        return 1

    handle = None
    status = "identity read failed"
    try:
        backend = WindowsHid()
        candidates = [device for device in backend.enumerate() if matches(device)]
        if not candidates:
            status = "not found"
        elif len(candidates) > 1:
            status = "ambiguous"
        else:
            device = candidates[0]
            handle = backend.open(device.path)
            opened = backend.describe(handle, device.path)
            if not matches(opened) or opened.path.lower() != device.path.lower():
                raise AulaError("opened_device_mismatch")
            if 6 not in backend.feature_report_ids(handle):
                raise AulaError("feature_report_id_missing")
            # Служебный SetFeature запрашивает identity; RGB/profile не меняется.
            backend.set_feature(handle, read_request(0x82))
            validate_response(backend.get_feature(handle, 6, REPORT_BYTES), 0x82)
            status = "ready"
    except Exception:
        # Текст transport exception может содержать приватный Windows HID path.
        status = "identity read failed"
    finally:
        if handle is not None:
            try:
                backend.close(handle)
            except Exception:
                status = "identity read failed"

    print(f"AULA F75: {status}")
    if status == "ready":
        print("Check: identity read")
        print("VID/PID: 258A:010C; collection: MI_01/COL06; usage: FF00/0001")
        print("FeatureReportByteLength: 520; report ID: 06")
        print("Model: 03")
        print("PSD: 00CD")
        return 0
    return 1
