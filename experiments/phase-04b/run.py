"""Исторический стенд 04B: сохранён только безопасный read-only inspect.

H1–H4/D1 работали с прежним RGB-only adapter. После production config acquire
их старые лимиты и сценарии неприменимы; физические повторы здесь запрещены.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response
from agentrgb.outputs.windows_hid import WindowsHid


def save_get_diagnostic(directory, record):
    """Экспериментальный raw до валидации, также при неуспехе Windows API."""
    stem = f"get-{record['sequence']:03d}"
    raw = record["raw_response"]
    (directory / f"{stem}-response.bin").write_bytes(raw)
    if record["raw_request"] is not None:
        (directory / f"{stem}-request.bin").write_bytes(record["raw_request"])
    details = {key: value for key, value in record.items() if key not in ("raw_request", "raw_response")}
    details["response_file"] = f"{stem}-response.bin"
    details["rgb_29_31_hex"] = raw[29:32].hex(" ")
    details["sha256"] = hashlib.sha256(raw).hexdigest()
    (directory / f"{stem}.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")


def inspect(directory, backend):
    """Один fresh 0x82/0x84/0x8A, ни одного 0x04 или 0x0A."""
    directory.mkdir(parents=True, exist_ok=False)
    result = dict(scenario="inspect", python=platform.python_version(), platform=platform.system(),
                  status="pending", write_attempts=0, write_successes=0, reads={})
    handle = None
    try:
        device = select_device(backend.enumerate())
        handle = backend.open(device.path)
        opened = backend.describe(handle, device.path)
        if not matches(opened) or opened.path.lower() != device.path.lower():
            raise RuntimeError("opened_device_mismatch")
        result["identity"] = dict(vid=f"{opened.vid:04X}", pid=f"{opened.pid:04X}",
                                  collection="MI_01/COL06", usage_page=f"{opened.usage_page:04X}",
                                  usage=f"{opened.usage:04X}", feature_bytes=opened.feature_bytes,
                                  report_id="06")
        for name, opcode in (("model", 0x82), ("config", 0x84), ("color", 0x8A)):
            backend.set_feature(handle, read_request(opcode))
            raw = backend.get_feature(handle, 6, 520)
            (directory / f"{name}-response.bin").write_bytes(raw)
            validate_response(raw, opcode)
            result["reads"][name] = dict(opcode=f"{opcode:02X}", sha256=hashlib.sha256(raw).hexdigest())
            if name == "model":
                result["identity"].update(model=f"{raw[8]:02X}", psd=raw[12:14].hex().upper())
            elif name == "config":
                result["config_66_67"] = raw[66:68].hex().upper()
            else:
                result["original_rgb"] = raw[29:32].hex().upper()
        result["status"] = "read_only_identified"
    except Exception as error:
        result["status"] = "stopped_on_error"
        result["error"] = type(error).__name__
    finally:
        if handle is not None:
            try:
                backend.close(handle)
                result["handle_closed"] = True
            except Exception:
                result["handle_closed"] = False
                result["status"] = "stopped_on_error"
        (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="inspect",
                        choices=("inspect", "H1", "H2", "H3", "H4", "D1"))
    args = parser.parse_args()
    if args.scenario != "inspect":
        parser.error("legacy hardware scenarios retired; use a separately approved production test")
    directory = Path(__file__).parent / "results" / ("inspect-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backend = WindowsHid(diagnostic_sink=lambda record: save_get_diagnostic(directory, record))
    result = inspect(directory, backend)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "read_only_identified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
