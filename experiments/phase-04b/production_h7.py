"""Bounded H7 harness. Importing this module never opens HID or starts Core."""
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import socket
import threading
import time

from agentrgb.outputs.aula_f75 import AulaF75Output, matches
from agentrgb.server import EventServer
from agentrgb.state import Core
from production_h5 import BudgetedHid

FAULT_AFTER = 20
FRAME_LIMIT = 60
MAX_ACTIVE_SECONDS = 3.0


def run_h7(backend, directory: Path, *, port=8765, observe_seconds=4.0):
    """One Core/HTTP run with a software fault after 20 successful Direct frames."""
    if not 0 <= observe_seconds <= 5:
        raise ValueError("invalid_observation_duration")
    directory.mkdir(parents=True, exist_ok=False)
    timeline = []
    timeline_lock = threading.Lock()
    fault_triggered = threading.Event()

    def record(name, **details):
        with timeline_lock:
            timeline.append({"name": name, "monotonic": time.monotonic(),
                             "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                             **details})

    class AuditedHid(BudgetedHid):
        def __init__(self, wrapped):
            super().__init__(wrapped, frame_limit=FRAME_LIMIT)
            self.first_direct_started = None
            self.opens = 0
            self.close_count = 0
            self.interface = None
            self.report_ids = None

        def open(self, path):
            handle = super().open(path)
            self.opens += 1
            record("handle_opened")
            return handle

        def describe(self, handle, path):
            device = super().describe(handle, path)
            self.interface = {
                "vid": f"{device.vid:04X}", "pid": f"{device.pid:04X}",
                "collection": "MI_01/COL06" if matches(device) else "mismatch",
                "usage_page": f"{device.usage_page:04X}",
                "usage": f"{device.usage:04X}", "feature_bytes": device.feature_bytes,
            }
            return device

        def feature_report_ids(self, handle):
            ids = super().feature_report_ids(handle)
            self.report_ids = [f"{item:02X}" for item in sorted(ids)]
            return ids

        def set_feature(self, handle, report):
            direct = len(report) == 520 and report[:2] == b"\x06\x08"
            if direct:
                now = time.monotonic()
                if self.first_direct_started is None:
                    self.first_direct_started = now
                if now - self.first_direct_started >= MAX_ACTIVE_SECONDS:
                    record("active_deadline_rejected_frame")
                    raise RuntimeError("h7_active_deadline")  # Before Windows HID.
                record("frame_write_started", index=self.frame_attempts + 1)
            try:
                super().set_feature(handle, report)
            except Exception as error:
                record("report_error", kind=type(error).__name__, message=str(error))
                raise
            if direct:
                record("frame_write_succeeded", index=self.frame_successes)

        def close(self, handle):
            record("handle_close_started")
            try:
                super().close(handle)
            except Exception as error:
                record("handle_close_failed", kind=type(error).__name__)
                raise
            self.close_count += 1
            record("handle_closed")

    audited = AuditedHid(backend)

    class FaultOutput(AulaF75Output):
        def _after_direct_frame(self):
            if self.write_successes == FAULT_AFTER:
                record("software_fault_triggered", after_successes=self.write_successes)
                fault_triggered.set()
                raise RuntimeError("h7_controlled_software_fault")

    output = FaultOutput(audited)

    class TracedStopEvent(threading.Event):
        def set(self):
            if not self.is_set():
                record("worker_stop_requested")
            super().set()

    output._stop = TracedStopEvent()
    production_heartbeat = output._heartbeat

    def traced_heartbeat():
        try:
            production_heartbeat()
        finally:
            record("worker_ended")

    output._heartbeat = traced_heartbeat
    core = Core(output)
    server = None
    serving = None
    start_status = None
    safe_statuses = []
    core_alive_after_fault = False
    opens_before_safe_events = None
    frames_before_safe_events = None
    runner_error = None

    def post(address, kind, event_id):
        event = {
            "schema_version": 1, "source": "pi", "source_instance_id": "h7-synthetic",
            "session_id": "h7-session", "run_id": "h7-run", "event_id": event_id,
            "kind": kind, "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        }
        connection = http.client.HTTPConnection(*address, timeout=2)
        try:
            connection.request("POST", "/v1/events", json.dumps(event),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            response.read()
            record("core_event_processed", kind=kind, status=response.status)
            return response.status
        finally:
            connection.close()

    try:
        with EventServer(port, core) as server:
            record("listener_started", port=server.server_port)
            serving = threading.Thread(target=server.serve_forever,
                                       kwargs={"poll_interval": 0.01})
            serving.start()
            try:
                start_status = post(server.server_address, "run_started", "h7-start")
                if output._worker is None:
                    record("gate_stopped_before_frames", error=output.last_error)
                else:
                    worker = output._worker
                    deadline = (audited.first_direct_started or time.monotonic()) + MAX_ACTIVE_SECONDS
                    while not fault_triggered.is_set() and worker.is_alive():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        fault_triggered.wait(min(0.02, remaining))
                    if not fault_triggered.is_set():
                        record("fault_not_reached_before_deadline", error=output.last_error)
                        with server.lock:
                            core.close()
                    else:
                        worker.join(1)
                        if worker.is_alive() or output.handle is not None:
                            record("cleanup_incomplete_after_fault")
                        else:
                            opens_before_safe_events = audited.opens
                            frames_before_safe_events = audited.frame_successes
                            safe_statuses.append(post(server.server_address, "run_waiting", "h7-wait"))
                            safe_statuses.append(post(server.server_address, "run_resumed", "h7-resume"))
                            core_alive_after_fault = all(status == 200 for status in safe_statuses)
                            record("post_fault_core_checked", alive=core_alive_after_fault,
                                   opens=audited.opens, frames=audited.frame_successes)
                            threading.Event().wait(observe_seconds)
            finally:
                server.shutdown()
                serving.join(2)
                record("listener_stopped")
        record("listener_closed")
    except Exception as error:
        runner_error = f"{type(error).__name__}: {error}"
        record("runner_error", kind=type(error).__name__, message=str(error))
    finally:
        if server is not None:
            listener_closed = server.fileno() == -1
            port_number = server.server_port
        else:
            listener_closed = False
            port_number = port
        with socket.socket() as probe:
            probe.settimeout(0.2)
            listener_absent = probe.connect_ex(("127.0.0.1", port_number)) != 0

    if audited.identity_raw is not None:
        (directory / "model-82.bin").write_bytes(audited.identity_raw)
    fault_times = [item["monotonic"] for item in timeline
                   if item["name"] == "software_fault_triggered"]
    frame_starts = [item["monotonic"] for item in timeline
                    if item["name"] == "frame_write_started"]
    worker_ends = [item["monotonic"] for item in timeline
                   if item["name"] == "worker_ended"]
    closes = [item["monotonic"] for item in timeline
              if item["name"] == "handle_closed"]
    stops = [item["monotonic"] for item in timeline
             if item["name"] == "worker_stop_requested"]
    result = {
        "status": "pending_visual_confirmation", "fault_after": FAULT_AFTER,
        "max_active_seconds": MAX_ACTIVE_SECONDS, "frame_limit": FRAME_LIMIT,
        "identity": audited.interface, "feature_report_ids": audited.report_ids,
        "model": f"{audited.identity_raw[8]:02X}" if audited.identity_raw and len(audited.identity_raw) > 8 else None,
        "psd": audited.identity_raw[12:14].hex().upper() if audited.identity_raw and len(audited.identity_raw) >= 14 else None,
        "model_response_sha256": hashlib.sha256(audited.identity_raw).hexdigest() if audited.identity_raw is not None else None,
        "read_requests": audited.read_requests,
        "start_http_status": start_status, "safe_event_statuses": safe_statuses,
        "core_alive_after_fault": core_alive_after_fault,
        "frames": audited.frame_successes, "frame_attempts": audited.frame_attempts,
        "writer_thread_count": len(audited.writer_threads),
        "fault_triggered": bool(fault_times), "output_last_error": output.last_error,
        "active_duration_seconds": (fault_times[0] - audited.first_direct_started
                                    if fault_times and audited.first_direct_started is not None else None),
        "handle_open_count": audited.opens, "handle_close_count": audited.close_count,
        "worker_ended": bool(worker_ends),
        "writes_started_after_fault": sum(timepoint > fault_times[0] for timepoint in frame_starts) if fault_times else None,
        "writes_started_after_stop": sum(timepoint > stops[0] for timepoint in frame_starts) if stops else None,
        "no_reacquire_during_safe_events": (opens_before_safe_events == audited.opens
                                            if opens_before_safe_events is not None else None),
        "no_frames_during_safe_events": (frames_before_safe_events == audited.frame_successes
                                          if frames_before_safe_events is not None else None),
        "stop_before_handle_close": bool(stops and closes and max(stops) < min(closes)),
        "handle_close_before_worker_end": bool(worker_ends and closes and max(closes) < min(worker_ends)),
        "listener_closed_after_run": listener_closed,
        "listener_absent_after_run": listener_absent,
        "runner_error": runner_error, "timeline": timeline,
    }
    if not (start_status == 200 and audited.read_requests == 1
            and result["identity"] is not None and result["identity"]["collection"] == "MI_01/COL06"
            and result["feature_report_ids"] is not None and "06" in result["feature_report_ids"]
            and result["model"] == "03" and result["psd"] == "00CD"
            and audited.frame_successes == FAULT_AFTER
            and audited.frame_attempts == FAULT_AFTER
            and result["active_duration_seconds"] is not None
            and result["active_duration_seconds"] <= MAX_ACTIVE_SECONDS
            and len(audited.writer_threads) == 1 and bool(fault_times)
            and output.last_error == "heartbeat_failed" and bool(worker_ends)
            and result["writes_started_after_fault"] == 0
            and result["writes_started_after_stop"] == 0
            and audited.opens == 1 and audited.close_count == 1
            and result["stop_before_handle_close"]
            and result["no_reacquire_during_safe_events"]
            and result["no_frames_during_safe_events"]
            and core_alive_after_fault and listener_closed and listener_absent
            and runner_error is None):
        result["status"] = "stopped_on_deviation"
    (directory / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
