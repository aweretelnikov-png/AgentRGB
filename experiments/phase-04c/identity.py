"""Fresh F75 identity only: one 0x82 read request, no Direct or persistent commands."""
from datetime import datetime, timezone
import json

from agentrgb.outputs.aula_f75 import REPORT_BYTES, matches, read_request, select_device, validate_response
from agentrgb.outputs.windows_hid import WindowsHid


def main():
    backend = WindowsHid()
    handle = None
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "status": "pending", "direct_frames": 0, "mutating_writes": 0,
              "read_requests_82": 0}
    try:
        device = select_device(backend.enumerate())
        handle = backend.open(device.path)
        opened = backend.describe(handle, device.path)
        if not matches(opened) or opened.path.lower() != device.path.lower():
            raise RuntimeError("opened_identity_mismatch")
        ids = backend.feature_report_ids(handle)
        if 6 not in ids:
            raise RuntimeError("report_id_06_missing")
        backend.set_feature(handle, read_request(0x82))
        result["read_requests_82"] = 1
        raw = validate_response(backend.get_feature(handle, 6, REPORT_BYTES), 0x82)
        result["identity"] = {"vid": f"{opened.vid:04X}", "pid": f"{opened.pid:04X}",
                              "collection": "MI_01/COL06", "usage_page": f"{opened.usage_page:04X}",
                              "usage": f"{opened.usage:04X}", "feature_bytes": opened.feature_bytes,
                              "report_id": "06", "model": f"{raw[8]:02X}",
                              "psd": raw[12:14].hex().upper()}
        result["status"] = "read_only_identified"
    except Exception as error:
        result["status"] = "identity_failed"
        result["error_kind"] = type(error).__name__
    finally:
        if handle is not None:
            try:
                backend.close(handle)
                result["handle_closed"] = True
            except Exception:
                result["handle_closed"] = False
                result["status"] = "identity_failed"
        print(json.dumps(result), flush=True)
    return 0 if result["status"] == "read_only_identified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
