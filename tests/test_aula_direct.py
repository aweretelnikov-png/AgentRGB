"""Volatile production AULA F75 tests; all HID operations use an in-memory fake."""
from dataclasses import replace
from pathlib import Path
import hashlib
import http.client
import json
import threading
import time
import unittest

from agentrgb.outputs.aula_f75 import AulaF75Output, COLORS, direct_frame, read_request
from agentrgb.outputs.windows_hid import Interface
from agentrgb.server import EventServer
from agentrgb.state import Core
from test_core import event
from test_transport import payload


DEVICE = Interface(r"\\?\hid#vid_258a&pid_010c&mi_01&col06#direct", 0x258A, 0x010C, 0xFF00, 1, 520)
BLUE = bytes((0, 0, 255))


class DirectHid:
    def __init__(self):
        self.devices = [DEVICE]
        self.opened_device = DEVICE
        self.ids = frozenset((5, 6))
        self.model = bytearray(read_request(0x82))
        self.model[8] = 3
        self.model[12:14] = b"\x00\xcd"
        self.sent = []
        self.closed = []
        self.opens = 0
        self.reads = 0
        self.fail_frame = None
        self.block_frame = None
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.condition = threading.Condition()
        self.writer_threads = set()

    def enumerate(self):
        return self.devices

    def open(self, path):
        assert path == DEVICE.path
        self.opens += 1
        return self.opens

    def describe(self, handle, path):
        return self.opened_device

    def feature_report_ids(self, handle):
        return self.ids

    def set_feature(self, handle, report):
        assert handle not in self.closed
        assert len(report) == 520
        with self.condition:
            self.sent.append(bytes(report))
            frame_number = sum(item[:2] == b"\x06\x08" for item in self.sent)
            if report[:2] == b"\x06\x08":
                self.writer_threads.add(threading.get_ident())
            self.condition.notify_all()
        if report[:2] == b"\x06\x08":
            if frame_number == self.block_frame:
                self.entered.set()
                if not self.resume.wait(2):
                    raise TimeoutError("test_write_block_timeout")
            if frame_number == self.fail_frame:
                raise OSError("fixture_direct_failure")

    def get_feature(self, handle, report_id, length):
        assert report_id == 6 and length == 520
        self.reads += 1
        return bytes(self.model)

    def close(self, handle):
        assert handle not in self.closed
        self.closed.append(handle)

    def wait_frames(self, count, timeout=2):
        deadline = time.monotonic() + timeout
        with self.condition:
            while len(self.frames) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.condition.wait(remaining):
                    raise AssertionError(f"only {len(self.frames)} frames, expected {count}")

    def wait_color(self, rgb, timeout=2):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not any(frame[8:11] == bytes(rgb) for frame in self.frames):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.condition.wait(remaining):
                    raise AssertionError(f"color {rgb} not sent")

    @property
    def frames(self):
        return [item for item in self.sent if item[:2] == b"\x06\x08"]


class DirectTests(unittest.TestCase):
    def setUp(self):
        self.hid = DirectHid()
        self.output = AulaF75Output(self.hid)

    def tearDown(self):
        self.hid.resume.set()
        self.output.release()

    def test_frame_exact_d2_raw_and_colors(self):
        saved = (Path(__file__).resolve().parents[1] /
                 "experiments/phase-04b/results/direct-d2-20260923T163834566887Z/blue-frame.bin").read_bytes()
        frame = direct_frame(COLORS["working"])
        self.assertEqual(frame, saved)
        self.assertEqual(hashlib.sha256(frame).hexdigest(),
                         "5446889ac334b8ad6722428f2fb583cc1a178709808679101e23c674a8cd5b54")
        self.assertEqual(frame[:8], bytes.fromhex("06 08 00 00 01 00 7A 01"))
        self.assertEqual(frame[8:374], BLUE * 122)
        self.assertEqual(frame[374:], bytes(146))
        for state, rgb in COLORS.items():
            with self.subTest(state=state):
                self.assertEqual(direct_frame(rgb)[8:374], bytes(rgb) * 122)

    def test_idle_gate_and_profile_independence(self):
        self.assertEqual(self.hid.sent, [])
        self.hid.model[8] = 3
        self.assertTrue(self.output.acquire())
        self.assertEqual(self.hid.sent, [read_request(0x82)])
        self.assertEqual(self.hid.reads, 1)
        self.output.release()
        self.assertEqual(self.hid.closed, [1])
        self.assertEqual(self.hid.frames, [])

    def test_gate_rejects_unexpected_identity_without_direct_frame(self):
        mutations = (
            lambda hid: setattr(hid, "devices", []),
            lambda hid: setattr(hid, "devices", [replace(DEVICE, vid=1)]),
            lambda hid: setattr(hid, "devices", [replace(DEVICE, pid=1)]),
            lambda hid: setattr(hid, "devices", [replace(DEVICE, path=DEVICE.path.replace("col06", "col05"))]),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, usage=2)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, usage_page=0xFF01)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, feature_bytes=64)),
            lambda hid: setattr(hid, "ids", frozenset((5,))),
            lambda hid: hid.model.__setitem__(8, 6),
            lambda hid: hid.model.__setitem__(slice(12, 14), b"\x00\x00"),
            lambda hid: hid.model.__setitem__(0, 0),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                hid = DirectHid()
                mutation(hid)
                output = AulaF75Output(hid)
                self.assertFalse(output.acquire())
                self.assertFalse(output.show_activity("working"))
                self.assertEqual(hid.frames, [])
                self.assertLessEqual(hid.reads, 1)
                self.assertEqual(hid.closed, list(range(1, hid.opens + 1)))

    def test_repeated_frames_and_state_changes_one_worker(self):
        self.assertTrue(self.output.acquire())
        self.assertTrue(self.output.show_activity("working"))
        self.hid.wait_frames(2)
        worker = self.output._worker
        self.assertTrue(self.output.show_activity("working"))
        self.assertIs(self.output._worker, worker)
        self.assertTrue(self.output.show_activity("waiting"))
        self.hid.wait_frames(3)
        self.assertTrue(self.output.show_signal("completed"))
        self.hid.wait_frames(4)
        self.assertEqual([frame[8:11] for frame in self.hid.frames[:4]],
                         [BLUE, BLUE, bytes(COLORS["waiting"]), bytes(COLORS["completed"])])
        self.assertEqual(len(self.hid.writer_threads), 1)
        before = len(self.hid.frames)
        self.assertTrue(self.output.release())
        self.assertEqual(len(self.hid.frames), before)
        self.assertEqual(self.hid.closed, [1])
        self.assertIsNone(self.output.desired_rgb)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.output.release())

    def test_release_waits_for_inflight_write_then_no_more_frames(self):
        self.hid.block_frame = 1
        self.assertTrue(self.output.acquire())
        self.output.show_activity("working")
        self.assertTrue(self.hid.entered.wait(1))
        done = threading.Event()
        release_thread = threading.Thread(target=lambda: (self.output.release(), done.set()))
        release_thread.start()
        try:
            self.assertFalse(done.wait(0.03))
            self.assertEqual(self.hid.closed, [])
        finally:
            self.hid.resume.set()
            release_thread.join(2)
        self.assertTrue(done.is_set())
        self.assertEqual(len(self.hid.frames), 1)
        self.assertEqual(self.hid.closed, [1])

    def test_first_and_later_frame_errors_stop_without_retry_or_restore(self):
        for failing_frame in (1, 3):
            with self.subTest(failing_frame=failing_frame):
                hid = DirectHid()
                hid.fail_frame = failing_frame
                output = AulaF75Output(hid)
                self.assertTrue(output.acquire())
                output.show_activity("working")
                hid.wait_frames(failing_frame)
                worker = output._worker
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(output.last_error, "direct_write_failed")
                self.assertEqual(len(hid.frames), failing_frame)
                self.assertEqual(hid.closed, [1])
                self.assertIsNone(output.handle)
                self.assertFalse(output.show_activity("waiting"))
                output.release()
                self.assertEqual(len(hid.frames), failing_frame)
                self.assertEqual(output.write_successes, failing_frame - 1)

    def test_core_keeps_processing_events_after_async_hid_error(self):
        self.hid.fail_frame = 1
        core = Core(self.output)
        self.assertEqual(core.apply(event()), "applied")
        self.hid.wait_frames(1)
        self.output._worker.join(1)
        self.assertEqual(self.output.last_error, "direct_write_failed")
        self.assertEqual(core.apply(event("run_waiting")), "applied")
        self.assertEqual(core.aggregate(), "waiting")
        self.assertEqual(core.apply(event("run_ended")), "applied")
        core.close()
        self.assertEqual(len(self.hid.frames), 1)
        self.assertEqual(self.hid.closed, [1])

    def test_core_waiting_priority_then_idle_stops_heartbeat(self):
        core = Core(self.output)
        core.apply(event(run="r1"))
        self.hid.wait_frames(1)
        core.apply(event(run="r2", session="s2"))
        self.assertEqual(core.visible, "working")
        core.apply(event("run_waiting", run="r2", session="s2"))
        self.hid.wait_color(COLORS["waiting"])
        self.assertEqual(self.hid.frames[-1][8:11], bytes(COLORS["waiting"]))
        core.apply(event("run_ended", run="r1", outcome="completed"))
        self.assertEqual(core.visible, "waiting")
        core.apply(event("run_ended", run="r2", session="s2"))
        self.assertEqual(core.visible, "idle")
        frame_count = len(self.hid.frames)
        self.assertEqual(self.hid.closed, [1])
        self.assertEqual(len(self.hid.frames), frame_count)
        self.assertNotIn(bytes(COLORS["completed"]),
                         [frame[8:11] for frame in self.hid.frames])

    def test_next_acquire_starts_only_after_old_worker_joined(self):
        self.assertTrue(self.output.acquire())
        self.output.show_activity("working")
        self.hid.wait_frames(1)
        old_worker = self.output._worker
        self.output.release()
        self.assertFalse(old_worker.is_alive())
        self.assertTrue(self.output.acquire())
        self.output.show_activity("waiting")
        self.hid.wait_frames(2)
        self.assertIsNot(self.output._worker, old_worker)
        self.assertEqual(self.hid.frames[-1][8:11], bytes(COLORS["waiting"]))
        self.output.release()
        self.assertEqual(self.hid.closed, [1, 2])

    def test_core_close_joins_worker_without_restore(self):
        core = Core(self.output)
        core.apply(event())
        self.hid.wait_frames(2)
        worker = self.output._worker
        core.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.hid.closed, [1])
        self.assertTrue(all(frame[:2] == b"\x06\x08" for frame in self.hid.frames))
        self.assertEqual(core.aggregate(), "working")  # Core.close releases output, not history.

    def test_http_shutdown_stops_frames_and_listener(self):
        with EventServer(0, Core(self.output)) as server:
            address = server.server_address
            serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            serving.start()
            try:
                connection = http.client.HTTPConnection(*address, timeout=2)
                try:
                    connection.request("POST", "/v1/events", json.dumps(payload()),
                                       {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                finally:
                    connection.close()
                self.hid.wait_frames(2)
            finally:
                server.shutdown()
                serving.join(2)
        count = len(self.hid.frames)
        self.assertFalse(serving.is_alive())
        self.assertEqual(server.fileno(), -1)
        self.assertEqual(self.hid.closed, [1])
        self.assertIsNone(self.output._worker)
        self.assertEqual(len(self.hid.frames), count)
        with EventServer(address[1], Core(AulaF75Output(DirectHid()))):
            pass


if __name__ == "__main__":
    unittest.main()
