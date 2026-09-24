"""Finite 04C Core host. No HID access in fake mode or at import time."""
import argparse
from datetime import datetime, timezone
import json
import sys
import threading

from agentrgb.fake import FakeOutput
from agentrgb.server import EventServer
from agentrgb.state import Core

MAX_SECONDS = 150
MAX_FRAMES = 3000
RGB = {"working": "0000FF", "waiting": "FFFF00", "completed": "00FF00"}


def now():
    return datetime.now(timezone.utc).isoformat()


def host(mode, journal_path):
    journal = open(journal_path, "w", encoding="utf-8", buffering=1)
    lock = threading.Lock()

    def record(name, **fields):
        row = {"timestamp_utc": now(), "name": name, **fields}
        with lock:
            journal.write(json.dumps(row) + "\n")
        if name in {"listener_started", "core_event", "heartbeat_stopped", "deadline_reached", "output_unavailable"}:
            print("JOURNAL " + json.dumps(row), flush=True)

    if mode == "aula-f75":
        from agentrgb.outputs.aula_f75 import AulaF75Output, direct_frame, read_request
        from agentrgb.outputs.windows_hid import WindowsHid

        class BoundedHid:
            def __init__(self):
                self.backend = WindowsHid()
                self.frames = 0
                self.successes = 0
                self.first = None
                self.last = None
                self.reads = 0

            def enumerate(self):
                return self.backend.enumerate()

            def open(self, path):
                handle = self.backend.open(path)
                record("handle_opened")
                return handle

            def describe(self, handle, path):
                device = self.backend.describe(handle, path)
                record("identity", vid=f"{device.vid:04X}", pid=f"{device.pid:04X}",
                       usage_page=f"{device.usage_page:04X}", usage=f"{device.usage:04X}",
                       feature_bytes=device.feature_bytes,
                       collection="MI_01/COL06" if "mi_01&col06" in device.path.lower() else "other")
                return device

            def feature_report_ids(self, handle):
                ids = self.backend.feature_report_ids(handle)
                record("feature_report_ids", report_ids=[f"{value:02X}" for value in sorted(ids)])
                return ids

            def get_feature(self, handle, report_id, length):
                raw = self.backend.get_feature(handle, report_id, length)
                if self.reads == 1:
                    record("model_identity", model=f"{raw[8]:02X}" if len(raw) > 8 else None,
                           psd=raw[12:14].hex().upper() if len(raw) >= 14 else None)
                return raw

            def set_feature(self, handle, report):
                if report == read_request(0x82):
                    if self.reads:
                        raise RuntimeError("identity_read_repeated")
                    self.reads += 1
                    return self.backend.set_feature(handle, report)
                if len(report) != 520 or report[:2] != b"\x06\x08":
                    raise RuntimeError("forbidden_report")
                rgb = tuple(report[8:11])
                if report != direct_frame(rgb):
                    raise RuntimeError("invalid_direct_frame")
                if self.frames >= MAX_FRAMES:
                    record("frame_budget_exhausted", frame_count=self.frames)
                    raise RuntimeError("frame_budget_exhausted")
                self.frames += 1
                self.first = self.first or now()
                self.last = now()
                try:
                    self.backend.set_feature(handle, report)
                except Exception:
                    record("frame_failed", frame_count=self.frames)
                    raise
                self.successes += 1
                record("direct_frame", frame_count=self.frames, desired_rgb="".join(f"{x:02X}" for x in rgb),
                       first_frame_utc=self.first, last_frame_utc=self.last)

            def close(self, handle):
                try:
                    self.backend.close(handle)
                except Exception:
                    record("handle_close_failed", frame_count=self.frames)
                    raise
                record("handle_closed", frame_attempts=self.frames,
                       frame_successes=self.successes,
                       first_frame_utc=self.first, last_frame_utc=self.last)

        class TracedAula(AulaF75Output):
            def _heartbeat(self):
                record("heartbeat_started")
                try:
                    super()._heartbeat()
                finally:
                    record("heartbeat_stopped", frame_count=self.write_attempts,
                           output_error=self.last_error)
                    record("worker_stopped")

        output = TracedAula(BoundedHid())
    else:
        output = FakeOutput()

    class TracedCore(Core):
        def apply(self, event):
            result = super().apply(event)
            record("core_event", source_instance_id=event.source_instance_id,
                   run_id=event.run_id, event_id=event.event_id,
                   normalized_event=event.kind, outcome=event.outcome,
                   source_timestamp=event.timestamp, result=result,
                   aggregate_state=self.aggregate(), visible_state=self.visible,
                   desired_rgb=RGB.get(self.visible))
            if mode == "aula-f75" and self.visible != "idle" and output.handle is None:
                record("output_unavailable", output_error=output.last_error)
            return result

        def tick(self):
            before = self.visible
            super().tick()
            if self.visible != before:
                record("core_tick", aggregate_state=self.aggregate(),
                       visible_state=self.visible, desired_rgb=RGB.get(self.visible))

        def close(self):
            try:
                super().close()
            finally:
                record("core_shutdown", aggregate_state=self.aggregate(),
                       visible_state=self.visible)

    server = None
    serving = None
    stop = threading.Event()
    try:
        server = EventServer(8765, TracedCore(output))
        serving = threading.Thread(target=server.serve_forever,
                                   kwargs={"poll_interval": 0.02})
        serving.start()
        record("listener_started", output=mode, max_seconds=MAX_SECONDS,
               max_direct_frames=MAX_FRAMES if mode == "aula-f75" else 0)
        print("LISTEN http://127.0.0.1:8765/v1/events", flush=True)
        def await_stdin():
            try:
                sys.stdin.read()
            finally:
                stop.set()

        threading.Thread(target=await_stdin, daemon=True).start()
        if not stop.wait(MAX_SECONDS):
            record("deadline_reached")
    finally:
        if server is not None:
            server.shutdown()
            if serving is not None:
                serving.join()
            server.server_close()
            record("listener_closed")
        journal.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", choices=("fake", "aula-f75"), default="fake")
    parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    host(args.output, args.journal)


if __name__ == "__main__":
    main()
