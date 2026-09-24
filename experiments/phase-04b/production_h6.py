"""H6 hardware runner: real EventServer/Core cleanup via KeyboardInterrupt.

No import-time I/O or CLI. A separate caller injects WindowsHid after approval.
A watchdog bounds the active heartbeat even if interrupt_main does not arrive.
"""
import _thread
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

FRAME_LIMIT = 100
ACTIVE_SECONDS = 3.5
MAX_SECONDS = 5.0


def run_h6(backend, directory: Path, *, port=8765, active_seconds=ACTIVE_SECONDS,
           max_seconds=MAX_SECONDS):
    if not 0 < active_seconds < max_seconds <= MAX_SECONDS:
        raise ValueError("invalid_h6_duration")
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    timeline = []
    timeline_lock = threading.Lock()
    first_frame = threading.Event()
    finished = threading.Event()

    def record(name, **details):
        with timeline_lock:
            timeline.append({"name": name, "monotonic": time.monotonic(),
                             "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                             **details})

    class AuditedHid(BudgetedHid):
        def __init__(self, wrapped):
            super().__init__(wrapped, frame_limit=FRAME_LIMIT)
            self.close_success = False
            self.identity = None
            self.report_ids = None

        def describe(self, handle, path):
            device = super().describe(handle, path)
            self.identity = {
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
                record("frame_write_started", index=self.frame_attempts + 1)
            try:
                super().set_feature(handle, report)
            except Exception as error:
                record("hid_api_error", kind=type(error).__name__, message=str(error))
                raise
            if direct:
                record("frame_write_succeeded", index=self.frame_successes)
                if self.frame_successes == 1:
                    first_frame.set()

        def close(self, handle):
            record("handle_close_started")
            try:
                super().close(handle)
            except Exception as error:
                record("handle_close_failed", kind=type(error).__name__)
                raise
            self.close_success = True
            record("handle_closed")

    audited = AuditedHid(backend)
    output = AulaF75Output(audited)

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
    interrupted = False
    trigger_sent = False
    watchdog_triggered = False
    post_status = None
    controller_threads = []

    def post_working(address):
        nonlocal post_status
        event = {
            "schema_version": 1, "source": "pi", "source_instance_id": "h6-synthetic",
            "session_id": "h6-session", "run_id": "h6-run",
            "event_id": "h6-run-started", "kind": "run_started",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        }
        connection = http.client.HTTPConnection(*address, timeout=2)
        try:
            connection.request("POST", "/v1/events", json.dumps(event),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            response.read()
            post_status = response.status
            record("working_http_response", status=response.status)
        except Exception as error:
            record("working_http_error", kind=type(error).__name__, message=str(error))
        finally:
            connection.close()

    def schedule_interrupt():
        nonlocal trigger_sent
        if not first_frame.wait(2):
            record("first_frame_missing")
            trigger_sent = True
            record("shutdown_signal_sent", reason="missing_frame")
            _thread.interrupt_main()
            return
        if finished.wait(active_seconds):
            return
        trigger_sent = True
        record("shutdown_signal_sent", reason="scheduled_keyboard_interrupt")
        _thread.interrupt_main()

    def watchdog():
        nonlocal watchdog_triggered
        if not first_frame.wait(2):
            if not finished.wait(0.1):
                watchdog_triggered = True
                record("watchdog_shutdown", reason="no_first_frame")
                server.shutdown()
            return
        if not finished.wait(max_seconds):
            watchdog_triggered = True
            record("watchdog_shutdown", reason="active_limit")
            server.shutdown()

    try:
        with EventServer(port, core) as server:
            record("listener_started", port=server.server_port)
            address = server.server_address
            for target in (lambda: post_working(address), schedule_interrupt, watchdog):
                thread = threading.Thread(target=target, daemon=True)
                controller_threads.append(thread)
                thread.start()
            try:
                server.serve_forever(poll_interval=0.01)
            except KeyboardInterrupt:
                interrupted = True
                record("shutdown_signal_received")
            record("serve_forever_exited")
        record("listener_closed")
    except Exception as error:
        record("runner_error", kind=type(error).__name__, message=str(error))
    finally:
        finished.set()
        for thread in controller_threads:
            thread.join(timeout=2)
        if server is not None:
            listener_closed = server.fileno() == -1
            port_number = server.server_port
        else:
            listener_closed = False
            port_number = port
        probe = socket.socket()
        probe.settimeout(0.2)
        try:
            listener_absent = probe.connect_ex(("127.0.0.1", port_number)) != 0
        finally:
            probe.close()

    stop_times = [event["monotonic"] for event in timeline
                  if event["name"] == "worker_stop_requested"]
    close_times = [event["monotonic"] for event in timeline
                   if event["name"] == "handle_closed"]
    worker_times = [event["monotonic"] for event in timeline
                    if event["name"] == "worker_ended"]
    write_times = [event["monotonic"] for event in timeline
                   if event["name"] == "frame_write_started"]
    active_duration = (max(stop_times) - audited.frame_times[0]
                       if stop_times and audited.frame_times else None)
    result = {
        "status": "pending_visual_confirmation", "started_at_utc": timeline[0]["timestamp_utc"] if timeline else None,
        "active_limit_seconds": max_seconds, "frame_limit": FRAME_LIMIT,
        "http_status": post_status, "keyboard_interrupt_sent": trigger_sent,
        "keyboard_interrupt_received": interrupted, "watchdog_triggered": watchdog_triggered,
        "read_requests": audited.read_requests,
        "identity": audited.identity, "feature_report_ids": audited.report_ids,
        "identity_model": f"{audited.identity_raw[8]:02X}" if audited.identity_raw and len(audited.identity_raw) > 8 else None,
        "identity_psd": audited.identity_raw[12:14].hex().upper() if audited.identity_raw and len(audited.identity_raw) >= 14 else None,
        "identity_sha256": hashlib.sha256(audited.identity_raw).hexdigest() if audited.identity_raw is not None else None,
        "frame_attempts": audited.frame_attempts, "frame_successes": audited.frame_successes,
        "frame_colors": [f"{r:02X}{g:02X}{b:02X}" for r, g, b in audited.frame_colors],
        "writer_thread_count": len(audited.writer_threads),
        "first_frame_monotonic": audited.frame_times[0] if audited.frame_times else None,
        "last_frame_monotonic": audited.frame_times[-1] if audited.frame_times else None,
        "active_duration_seconds": active_duration,
        "worker_ended": bool(worker_times), "handle_closed": audited.close_success,
        "listener_closed": listener_closed, "listener_absent": listener_absent,
        "writes_after_stop": sum(timestamp > min(stop_times) for timestamp in write_times) if stop_times else None,
        "last_write_before_worker_end": bool(write_times and worker_times and max(write_times) < min(worker_times)),
        "worker_end_before_handle_close": bool(worker_times and close_times and max(worker_times) < min(close_times)),
        "last_write_before_handle_close": bool(write_times and close_times and max(write_times) < min(close_times)),
        "output_last_error": output.last_error,
        "timeline": timeline,
        "total_elapsed_seconds": time.monotonic() - started,
    }
    if not (post_status == 200 and interrupted and not watchdog_triggered
            and result["identity_model"] == "03" and result["identity_psd"] == "00CD"
            and 0 < audited.frame_successes <= FRAME_LIMIT
            and audited.frame_attempts == audited.frame_successes
            and active_duration is not None and active_duration <= MAX_SECONDS
            and len(audited.writer_threads) == 1 and result["worker_ended"]
            and result["handle_closed"] and listener_closed and listener_absent
            and result["writes_after_stop"] == 0
            and result["last_write_before_worker_end"]
            and result["worker_end_before_handle_close"] and not output.last_error):
        result["status"] = "stopped_on_deviation"
    (directory / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
