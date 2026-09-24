"""H7 runner tests use fake HID and ephemeral loopback ports only."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/phase-04b"))
from production_h7 import FAULT_AFTER, FRAME_LIMIT, MAX_ACTIVE_SECONDS, run_h7
from test_aula_direct import DirectHid
from agentrgb.outputs.aula_f75 import read_request


class H7RunnerTests(unittest.TestCase):
    def test_exact_fault_and_live_core_without_post_fault_hid_writes(self):
        hid = DirectHid()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "h7"
            result = run_h7(hid, directory, port=0, observe_seconds=0)
            self.assertTrue((directory / "summary.json").exists())
            self.assertEqual((directory / "model-82.bin").read_bytes(), bytes(hid.model))
        self.assertEqual(FAULT_AFTER, 20)
        self.assertEqual(FRAME_LIMIT, 60)
        self.assertEqual(MAX_ACTIVE_SECONDS, 3.0)
        self.assertEqual(result["status"], "pending_visual_confirmation")
        self.assertEqual(result["frames"], 20)
        self.assertEqual(result["frame_attempts"], 20)
        self.assertEqual(result["writer_thread_count"], 1)
        self.assertEqual(result["output_last_error"], "heartbeat_failed")
        self.assertEqual(result["writes_started_after_fault"], 0)
        self.assertEqual(result["safe_event_statuses"], [200, 200])
        self.assertTrue(result["core_alive_after_fault"])
        self.assertTrue(result["no_reacquire_during_safe_events"])
        self.assertTrue(result["no_frames_during_safe_events"])
        self.assertTrue(result["listener_absent_after_run"])
        self.assertEqual(hid.sent[0], read_request(0x82))
        self.assertEqual(len(hid.frames), 20)
        self.assertTrue(all(report[:2] == b"\x06\x08" for report in hid.sent[1:]))
        self.assertEqual(hid.opens, 1)
        self.assertEqual(hid.closed, [1])

    def test_identity_mismatch_stops_before_first_direct_frame(self):
        hid = DirectHid()
        hid.model[8] = 6
        with tempfile.TemporaryDirectory() as temporary:
            result = run_h7(hid, Path(temporary) / "h7", port=0,
                            observe_seconds=0)
        self.assertEqual(result["status"], "stopped_on_deviation")
        self.assertEqual(result["model"], "06")
        self.assertEqual(result["frames"], 0)
        self.assertEqual(hid.frames, [])
        self.assertEqual(hid.closed, [1])


if __name__ == "__main__":
    unittest.main()
