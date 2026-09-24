"""Offline H5 plan and write-budget tests; no physical HID backend."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/phase-04b"))
from production_h5 import (BudgetedHid, FRAME_LIMIT, MAX_ACTIVE_SECONDS,
                           PLANNED_ACTIVE_SECONDS, run_h5)
from h5_identity import probe
from agentrgb.outputs.aula_f75 import direct_frame, read_request
from test_aula_direct import DirectHid


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class H5Tests(unittest.TestCase):
    def test_read_only_identity_saves_raw_before_validation(self):
        for model, expected in ((3, "identity_confirmed"), (6, "stopped_on_mismatch")):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as temporary:
                hid = DirectHid()
                hid.model[8] = model
                directory = Path(temporary) / "identity"
                result = probe(hid, directory)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["changing_hid_writes"], 0)
                self.assertEqual(result["read_requests"], 1)
                self.assertEqual((directory / "model-82.bin").read_bytes(), bytes(hid.model))
                self.assertEqual(hid.frames, [])
                self.assertEqual(hid.closed, [1])

    def test_finite_schedule_and_production_core_cycle(self):
        self.assertEqual(PLANNED_ACTIVE_SECONDS, 11.05)
        self.assertEqual(MAX_ACTIVE_SECONDS, 12.0)
        self.assertEqual(FRAME_LIMIT, 240)
        hid = DirectHid()
        clock = FakeClock()
        result = run_h5(hid, clock=clock, sleep=clock.sleep)
        self.assertEqual(result["status"], "cycle_complete_visual_observation_pending")
        self.assertEqual(result["states"], ["working", "waiting", "working", "completed"])
        self.assertEqual(result["elapsed_seconds"], 11.05)
        self.assertEqual(result["read_requests"], 1)
        self.assertTrue(result["handle_closed"])
        self.assertTrue(result["worker_stopped"])
        self.assertEqual(hid.closed, [1])
        self.assertLessEqual(result["direct_frame_attempts"], FRAME_LIMIT)
        self.assertTrue(all(report == read_request(0x82) or report[:2] == b"\x06\x08"
                            for report in hid.sent))

    def test_gate_failure_stops_with_zero_direct_frames(self):
        hid = DirectHid()
        hid.model[8] = 6
        clock = FakeClock()
        result = run_h5(hid, clock=clock, sleep=clock.sleep)
        self.assertEqual(result["status"], "stopped_on_deviation")
        self.assertEqual(result["read_requests"], 1)
        self.assertEqual(result["direct_frame_attempts"], 0)
        self.assertEqual(hid.closed, [1])

    def test_budget_rejects_unapproved_or_extra_reports_before_hid(self):
        hid = DirectHid()
        audited = BudgetedHid(hid)
        for report in (bytes.fromhex("06 04") + bytes(518),
                       bytes.fromhex("06 0A") + bytes(518),
                       bytes.fromhex("39 20") + bytes(518),
                       bytes.fromhex("3C 20") + bytes(518)):
            with self.subTest(opcode=report[:2]), self.assertRaisesRegex(
                    RuntimeError, "forbidden_h5_report"):
                audited.set_feature(1, report)
        audited.set_feature(1, read_request(0x82))
        with self.assertRaisesRegex(RuntimeError, "identity_retry_forbidden"):
            audited.set_feature(1, read_request(0x82))
        blue = direct_frame((0, 0, 255))
        for _ in range(FRAME_LIMIT):
            audited.set_feature(1, blue)
        with self.assertRaisesRegex(RuntimeError, "h5_frame_budget_exhausted"):
            audited.set_feature(1, blue)
        self.assertEqual(audited.frame_attempts, FRAME_LIMIT)
        self.assertEqual(audited.frame_successes, FRAME_LIMIT)
        self.assertEqual(len(hid.frames), FRAME_LIMIT)
        self.assertEqual(hid.sent[0], read_request(0x82))


if __name__ == "__main__":
    unittest.main()
