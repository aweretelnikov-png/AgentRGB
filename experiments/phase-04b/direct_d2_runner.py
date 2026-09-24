"""Finite D2 hardware runner: descriptor gate, fresh baseline, blue frames only.

No CLI, no import-time I/O, no enable/disable, no restore, no post-burst read.
The caller must obtain a separate visual observation before any post-read.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response
from descriptor_inspector import path_identity
from direct_mode_proto import (D2_FRAME_COUNT, D2_FRAME_INTERVAL_MS,
                               build_d2_burst_reports, build_uniform_frame)
from direct_d1_runner import BASELINE, BASELINE_FILES


def _now():
    return datetime.now(timezone.utc).isoformat()


def run_burst(backend, directory: Path, *, descriptor_probe, sleep=time.sleep) -> dict:
    """At most 40 report-06/command-08 writes after a strict fresh gate."""
    directory.mkdir(parents=True, exist_ok=False)
    blue = build_uniform_frame((0, 0, 255))
    (directory / "blue-frame.bin").write_bytes(blue)
    summary = {
        "status": "pending", "frame_limit": D2_FRAME_COUNT,
        "frame_interval_ms": D2_FRAME_INTERVAL_MS,
        "frame_sha256": hashlib.sha256(blue).hexdigest(),
        "read_requests": 0, "changing_write_attempts": 0,
        "changing_write_successes": 0, "direct_frames": 0,
        "enable_writes": 0, "disable_writes": 0,
        "config_writes": 0, "color_profile_writes": 0,
        "frame_events": [], "baseline": {},
    }
    handle = None
    try:
        device = select_device(backend.enumerate())
        descriptor = descriptor_probe(backend, device)
        if (descriptor["mi"], descriptor["col"], descriptor["vid"], descriptor["pid"],
                descriptor["usage_page"], descriptor["usage"], descriptor["feature_bytes"],
                descriptor["path_sha256"]) != (
                    "01", "06", "258A", "010C", "FF00", "0001", 520,
                    path_identity(device.path)["path_sha256"]):
            raise RuntimeError("descriptor_identity_mismatch")
        if "06" not in descriptor["feature_ids"]:
            raise RuntimeError("report_06_not_declared")
        summary["descriptor"] = {
            key: descriptor[key] for key in ("mi", "col", "vid", "pid",
                "usage_page", "usage", "feature_bytes", "feature_ids", "path_sha256")
        }

        handle = backend.open(device.path)
        opened = backend.describe(handle, device.path)
        if not matches(opened) or opened.path.lower() != device.path.lower():
            raise RuntimeError("opened_device_mismatch")
        summary["identity"] = {
            "vid": f"{opened.vid:04X}", "pid": f"{opened.pid:04X}",
            "collection": "MI_01/COL06",
            "usage": f"{opened.usage_page:04X}/{opened.usage:04X}",
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
                "matches_known_baseline": raw == expected,
            }
            if raw != expected:
                raise RuntimeError(f"baseline_{opcode:02X}_mismatch")
            current[opcode] = raw
        if (current[0x82][8], current[0x82][12:14], current[0x84][66:68],
                current[0x8A][29:32]) != (3, b"\x00\xcd", b"\x09\x37", b"\xff\x00\x00"):
            raise RuntimeError("baseline_fields_mismatch")

        reports = build_d2_burst_reports()
        if len(reports) != D2_FRAME_COUNT or any(report != blue for report in reports):
            raise RuntimeError("report_budget_mismatch")
        for index, report in enumerate(reports, start=1):
            event = {"frame": index, "timestamp_utc": _now(), "api_success": False}
            summary["changing_write_attempts"] += 1
            try:
                backend.set_feature(handle, report)
            except Exception as error:
                event["error"] = f"{type(error).__name__}: {error}"
                summary["frame_events"].append(event)
                raise
            event["api_success"] = True
            summary["frame_events"].append(event)
            summary["changing_write_successes"] += 1
            summary["direct_frames"] += 1
            if index < D2_FRAME_COUNT:
                sleep(D2_FRAME_INTERVAL_MS / 1000)
        summary["status"] = "burst_complete_wait_for_visual_observation"
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
        summary["finished_at_utc"] = _now()
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
