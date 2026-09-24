"""D1 burst runner, deliberately without a CLI or a production integration.

This module is prepared for separate hardware authorization. Importing it does
not open a device. Tests inject FakeHid and a fake clock; no physical send occurs.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response
from direct_mode_proto import (D1_FRAME_COUNT, D1_FRAME_INTERVAL_MS,
                               build_d1_burst_reports, build_enable_reports,
                               build_uniform_frame)


BASELINE = Path(__file__).parent / "results" / "inspect-20260923T112656878991Z"
BASELINE_FILES = {
    0x82: "model-response.bin",
    0x84: "config-response.bin",
    0x8A: "color-response.bin",
}


def run_burst(backend, directory: Path, *, sleep=time.sleep) -> dict:
    """Read strict baseline, then at most 3 enable + 40 direct reports.

    Ends immediately after the final direct frame and closes the handle.
    No disable, restore, retry, final read, or physical transport is created here.
    """
    directory.mkdir(parents=True, exist_ok=False)
    summary = {
        "status": "pending", "source_commit": "879f155336d1a0fa002a4a72b2e0332fb4b274cd",
        "max_enable_writes": 3, "max_direct_frames": D1_FRAME_COUNT,
        "frame_interval_ms": D1_FRAME_INTERVAL_MS, "read_requests": 0,
        "changing_write_attempts": 0, "changing_write_successes": 0,
        "enable_writes": 0, "direct_frames": 0, "disable_writes": 0,
        "config_writes": 0, "color_profile_writes": 0, "baseline": {},
    }
    handle = None
    try:
        device = select_device(backend.enumerate())
        handle = backend.open(device.path)
        opened = backend.describe(handle, device.path)
        if not matches(opened) or opened.path.lower() != device.path.lower():
            raise RuntimeError("opened_device_mismatch")
        summary["identity"] = {
            "vid": f"{opened.vid:04X}", "pid": f"{opened.pid:04X}",
            "collection": "MI_01/COL06", "usage": f"{opened.usage_page:04X}/{opened.usage:04X}",
            "feature_bytes": opened.feature_bytes,
        }

        current = {}
        for opcode in (0x82, 0x84, 0x8A):
            backend.set_feature(handle, read_request(opcode))
            summary["read_requests"] += 1
            raw = backend.get_feature(handle, 0x06, 520)
            (directory / f"baseline-{opcode:02X}.bin").write_bytes(raw)
            validate_response(raw, opcode)
            expected = (BASELINE / BASELINE_FILES[opcode]).read_bytes()
            summary["baseline"][f"{opcode:02X}"] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "matches_power_baseline": raw == expected,
            }
            if raw != expected:
                raise RuntimeError(f"baseline_{opcode:02X}_mismatch")
            current[opcode] = raw
        if (current[0x82][8], current[0x82][12:14], current[0x84][66:68],
                current[0x8A][29:32]) != (3, b"\x00\xcd", b"\x09\x37", b"\xff\x00\x00"):
            raise RuntimeError("baseline_fields_mismatch")

        reports = build_d1_burst_reports()
        blue = build_uniform_frame((0, 0, 255))
        if (len(reports) != 3 + D1_FRAME_COUNT
                or reports[:3] != build_enable_reports()
                or any(report != blue for report in reports[3:])):
            raise RuntimeError("report_budget_mismatch")
        for index, report in enumerate(reports):
            summary["changing_write_attempts"] += 1
            backend.set_feature(handle, report)
            summary["changing_write_successes"] += 1
            if index < 3:
                summary["enable_writes"] += 1
                sleep(0.005)  # The pinned F75 WebHID implementation waits 5 ms.
            else:
                summary["direct_frames"] += 1
                if index + 1 < len(reports):
                    sleep(D1_FRAME_INTERVAL_MS / 1000)
        summary["status"] = "burst_complete_wait_for_timeout_observation"
    except Exception as error:
        summary["status"] = "stopped_on_deviation"
        summary["error"] = f"{type(error).__name__}: {error}"
    finally:
        if handle is not None:
            try:
                backend.close(handle)
                summary["handle_closed"] = True
            except Exception as error:
                summary["handle_closed"] = False
                summary["status"] = "stopped_on_deviation"
                summary["close_error"] = type(error).__name__
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
