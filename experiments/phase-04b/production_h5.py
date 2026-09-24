"""Prepared, finite H5 through the production AulaF75Output; no CLI or import-time I/O.

Physical execution requires separate approval. The injected backend is the only
way this module can reach HID, and the wrapper enforces a 240-frame ceiling.
"""
from datetime import datetime, timezone
import hashlib
import threading
import time

from agentrgb.outputs.aula_f75 import AulaF75Output, direct_frame, read_request
from agentrgb.protocol import validate
from agentrgb.state import Core

FRAME_LIMIT = 240
MAX_ACTIVE_SECONDS = 12.0
STAGES = (
    ("run_started", "working", 3.0),
    ("run_waiting", "waiting", 3.0),
    ("run_resumed", "working", 3.0),
    ("run_ended", "completed", 2.05),
)
PLANNED_ACTIVE_SECONDS = sum(duration for _, _, duration in STAGES)


class BudgetedHid:
    """Delegates the production gate but admits only 0x82 reads and Direct frames."""

    def __init__(self, backend, frame_limit=FRAME_LIMIT):
        self.backend = backend
        self.frame_limit = frame_limit
        self.read_requests = 0
        self.frame_attempts = 0
        self.frame_successes = 0
        self.frame_colors = []
        self.frame_times = []
        self.writer_threads = set()
        self.identity_raw = None

    def enumerate(self):
        return self.backend.enumerate()

    def open(self, path):
        return self.backend.open(path)

    def describe(self, handle, path):
        return self.backend.describe(handle, path)

    def feature_report_ids(self, handle):
        return self.backend.feature_report_ids(handle)

    def get_feature(self, handle, report_id, length):
        raw = self.backend.get_feature(handle, report_id, length)
        if self.read_requests == 1 and self.identity_raw is None:
            self.identity_raw = bytes(raw)
        return raw

    def close(self, handle):
        return self.backend.close(handle)

    def set_feature(self, handle, report):
        if report == read_request(0x82):
            if self.read_requests:
                raise RuntimeError("identity_retry_forbidden")
            self.read_requests += 1
            return self.backend.set_feature(handle, report)
        if len(report) != 520 or report[:2] != b"\x06\x08":
            raise RuntimeError("forbidden_h5_report")
        rgb = tuple(report[8:11])
        if report != direct_frame(rgb):
            raise RuntimeError("invalid_h5_direct_frame")
        if self.frame_attempts >= self.frame_limit:
            raise RuntimeError("h5_frame_budget_exhausted")
        self.frame_attempts += 1
        self.frame_colors.append(rgb)
        self.frame_times.append(time.monotonic())
        self.writer_threads.add(threading.get_ident())
        self.backend.set_feature(handle, report)
        self.frame_successes += 1


def synthetic_event(kind):
    return validate({
        "schema_version": 1, "source": "pi", "source_instance_id": "h5-synthetic",
        "session_id": "h5-session", "run_id": "h5-run",
        "event_id": "h5-" + kind, "kind": kind,
        "timestamp": "2026-09-23T00:00:00Z",
        "metadata": {"outcome": "completed"} if kind == "run_ended" else {},
    })


def run_h5(backend, *, clock=time.monotonic, sleep=time.sleep):
    """One bounded synthetic Core cycle; never instantiates physical HID itself."""
    audited = BudgetedHid(backend)
    output = AulaF75Output(audited)
    core = Core(output, clock=clock)
    result = {
        "status": "pending", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "planned_active_seconds": PLANNED_ACTIVE_SECONDS,
        "max_active_seconds": MAX_ACTIVE_SECONDS, "max_direct_frames": FRAME_LIMIT,
        "states": [], "forbidden_reports_sent": 0,
    }
    started = clock()
    deadline = started
    try:
        for kind, state, duration in STAGES:
            if clock() - started >= MAX_ACTIVE_SECONDS:
                raise RuntimeError("h5_runtime_limit")
            if audited.frame_attempts >= FRAME_LIMIT:
                raise RuntimeError("h5_frame_limit")
            core.apply(synthetic_event(kind))
            if output.handle is None or output.last_error:
                raise RuntimeError("h5_output_unavailable")
            result["states"].append(state)
            deadline += duration
            sleep(max(0.0, deadline - clock()))
            if clock() - started > MAX_ACTIVE_SECONDS:
                raise RuntimeError("h5_runtime_limit")
            if output.last_error:
                raise RuntimeError("h5_heartbeat_failed")
        core.tick()  # completed expires; aggregate idle releases the output.
        if core.visible != "idle":
            raise RuntimeError("h5_idle_not_reached")
        if output.last_error:
            raise RuntimeError("h5_release_failed")
        result["status"] = "cycle_complete_visual_observation_pending"
    except Exception as error:
        result["status"] = "stopped_on_deviation"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        core.close()
        result["elapsed_seconds"] = clock() - started
        result["read_requests"] = audited.read_requests
        result["direct_frame_attempts"] = audited.frame_attempts
        result["direct_frame_successes"] = audited.frame_successes
        result["worker_thread_count"] = len(audited.writer_threads)
        result["first_frame_monotonic"] = audited.frame_times[0] if audited.frame_times else None
        result["last_frame_monotonic"] = audited.frame_times[-1] if audited.frame_times else None
        result["identity_model"] = (f"{audited.identity_raw[8]:02X}"
                                    if audited.identity_raw and len(audited.identity_raw) > 8 else None)
        result["identity_psd"] = (audited.identity_raw[12:14].hex().upper()
                                  if audited.identity_raw and len(audited.identity_raw) >= 14 else None)
        result["identity_sha256"] = (hashlib.sha256(audited.identity_raw).hexdigest()
                                     if audited.identity_raw is not None else None)
        result["frame_colors"] = [f"{r:02X}{g:02X}{b:02X}"
                                  for r, g, b in audited.frame_colors]
        result["last_error"] = output.last_error
        result["handle_closed"] = output.handle is None and output.last_error != "close_failed"
        result["worker_stopped"] = output._worker is None
    return result
