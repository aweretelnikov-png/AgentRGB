"""Read-only F75 identity probe for H5 preparation; never sends Direct frames."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response


def probe(backend, directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "changing_hid_writes": 0, "read_requests": 0, "status": "pending"}
    handle = None
    try:
        device = select_device(backend.enumerate())
        handle = backend.open(device.path)
        opened = backend.describe(handle, device.path)
        ids = backend.feature_report_ids(handle)
        result["identity"] = {
            "vid": f"{opened.vid:04X}", "pid": f"{opened.pid:04X}",
            "collection": "MI_01/COL06" if matches(opened) else "mismatch",
            "usage_page": f"{opened.usage_page:04X}",
            "usage": f"{opened.usage:04X}",
            "feature_bytes": opened.feature_bytes,
            "feature_report_ids": [f"{item:02X}" for item in sorted(ids)],
            "path_sha256": hashlib.sha256(opened.path.lower().encode("utf-16le")).hexdigest(),
        }
        if not matches(opened) or opened.path.lower() != device.path.lower() or 6 not in ids:
            raise RuntimeError("interface_or_report_id_mismatch")
        backend.set_feature(handle, read_request(0x82))
        result["read_requests"] = 1
        raw = backend.get_feature(handle, 6, 520)
        (directory / "model-82.bin").write_bytes(raw)  # Raw before validation.
        result["model_response_sha256"] = hashlib.sha256(raw).hexdigest()
        result["model"] = f"{raw[8]:02X}" if len(raw) > 8 else None
        result["psd"] = raw[12:14].hex().upper() if len(raw) >= 14 else None
        validate_response(raw, 0x82)
        result["status"] = "identity_confirmed"
    except Exception as error:
        result["status"] = "stopped_on_mismatch"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if handle is not None:
            try:
                backend.close(handle)
                result["handle_closed"] = True
            except Exception as error:
                result["handle_closed"] = False
                result["close_error"] = type(error).__name__
                result["status"] = "close_failed"
        (directory / "identity.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
