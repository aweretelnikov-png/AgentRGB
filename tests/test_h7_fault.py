"""H7 software-fault preparation; this module only uses in-memory HID."""
import http.client
import json
import threading
import time
import unittest

from agentrgb.outputs.aula_f75 import AulaF75Output, read_request
from agentrgb.server import EventServer
from agentrgb.state import Core
from test_aula_direct import DirectHid
from test_transport import payload


class FaultAfterFrames(AulaF75Output):
    """Test-only injection after N successful frames, above the HID backend."""

    def __init__(self, backend, fault_after):
        super().__init__(backend)
        self.fault_after = fault_after
        self.fault_count = 0
        self.fault_at_successes = None

    def _after_direct_frame(self):
        if self.write_successes == self.fault_after:
            self.fault_count += 1
            self.fault_at_successes = self.write_successes
            raise RuntimeError("h7_controlled_software_fault")


def post_event(address, **changes):
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        body = json.dumps(payload(**changes))
        connection.request("POST", "/v1/events", body,
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        status = response.status
        response.read()
        return status
    finally:
        connection.close()


class H7FaultTests(unittest.TestCase):
    def test_fault_after_exactly_three_successful_frames_keeps_core_and_listener_alive(self):
        hid = DirectHid()
        output = FaultAfterFrames(hid, fault_after=3)
        core = Core(output)
        server = EventServer(0, core)
        serving = threading.Thread(target=server.serve_forever,
                                   kwargs={"poll_interval": 0.01})
        serving.start()
        address = server.server_address
        try:
            self.assertEqual(post_event(address), 200)
            worker = output._worker
            self.assertIsNotNone(worker)
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(output.fault_count, 1)
            self.assertEqual(output.fault_at_successes, 3)
            self.assertEqual(output.write_attempts, 3)
            self.assertEqual(output.write_successes, 3)
            self.assertEqual(len(hid.frames), 3)
            self.assertEqual(len(hid.writer_threads), 1)
            self.assertEqual(output.last_error, "heartbeat_failed")
            self.assertEqual(hid.closed, [1])
            self.assertIsNone(output.handle)
            self.assertEqual(hid.opens, 1)
            self.assertTrue(output._stop.is_set())

            # Core remains responsive, but this failed run cannot restart output.
            self.assertEqual(post_event(address, event_id="waiting", kind="run_waiting"), 200)
            self.assertEqual(core.aggregate(), "waiting")
            self.assertEqual(post_event(address, event_id="resumed", kind="run_resumed"), 200)
            self.assertEqual(core.aggregate(), "working")
            self.assertIs(output._worker, worker)
            self.assertEqual(hid.opens, 1)
            self.assertEqual(len(hid.frames), 3)
            self.assertEqual(post_event(address, event_id="ended", kind="run_ended"), 200)
            self.assertEqual(core.aggregate(), "idle")
            self.assertEqual(len(hid.frames), 3)
            self.assertEqual(hid.closed, [1])
            self.assertEqual(hid.sent[0], read_request(0x82))
            self.assertTrue(all(report[:2] == b"\x06\x08" for report in hid.sent[1:]))
            self.assertNotIn(0x04, [report[1] for report in hid.sent])
            self.assertNotIn(0x0A, [report[1] for report in hid.sent])
            self.assertNotIn(0x39, [report[0] for report in hid.sent])
            self.assertNotIn(0x3C, [report[0] for report in hid.sent])
            time.sleep(0.08)
            self.assertEqual(len(hid.frames), 3)  # No retry or post-fault frame.
        finally:
            server.shutdown()
            serving.join(2)
            server.server_close()  # Production Core.close after fault.
        self.assertFalse(serving.is_alive())
        self.assertEqual(server.fileno(), -1)
        self.assertEqual(hid.closed, [1])
        self.assertEqual(len(hid.frames), 3)

    def test_test_only_fault_is_disabled_for_plain_production_output(self):
        hid = DirectHid()
        output = AulaF75Output(hid)
        try:
            self.assertTrue(output.acquire())
            self.assertTrue(output.show_activity("working"))
            hid.wait_frames(3)
            self.assertIsNone(output.last_error)
            self.assertTrue(output._worker.is_alive())
        finally:
            output.release()
        self.assertEqual(hid.closed, [1])


if __name__ == "__main__":
    unittest.main()
