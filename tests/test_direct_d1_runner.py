"""D1 execution policy exercised only against in-memory FakeHid."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "phase-04b"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(EXPERIMENT))
from agentrgb.outputs.windows_hid import Interface  # noqa: E402

SPEC = importlib.util.spec_from_file_location("direct_d1_runner", EXPERIMENT / "direct_d1_runner.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class FakeHid:
    def __init__(self, *, wrong_config=False, fail_at_write=None):
        self.device = Interface("HID#VID_258A&PID_010C&MI_01&COL06#FAKE", 0x258A, 0x010C,
                                0xFF00, 1, 520)
        self.responses = {opcode: (runner.BASELINE / filename).read_bytes()
                          for opcode, filename in runner.BASELINE_FILES.items()}
        if wrong_config:
            raw = bytearray(self.responses[0x84])
            raw[66] = 8
            self.responses[0x84] = bytes(raw)
        self.fail_at_write = fail_at_write
        self.read_requests = []
        self.write_attempts = []
        self.successful_writes = []
        self.pending = None
        self.closed = False

    def enumerate(self):
        return [self.device]

    def open(self, path):
        assert path == self.device.path
        return 1

    def describe(self, handle, path):
        assert (handle, path) == (1, self.device.path)
        return self.device

    def set_feature(self, handle, report):
        assert handle == 1
        if report[0] == 6 and report[1] in (0x82, 0x84, 0x8A):
            self.read_requests.append(report)
            self.pending = report[1]
            return
        self.write_attempts.append(report)
        if len(self.write_attempts) == self.fail_at_write:
            raise OSError("fake_send_failure")
        self.successful_writes.append(report)

    def get_feature(self, handle, report_id, length):
        assert (handle, report_id, length) == (1, 6, 520)
        assert self.pending is not None
        opcode, self.pending = self.pending, None
        return self.responses[opcode]

    def close(self, handle):
        assert handle == 1
        self.closed = True


class DirectD1RunnerTests(unittest.TestCase):
    def execute(self, fake):
        with tempfile.TemporaryDirectory() as temp:
            waits = []
            summary = runner.run_burst(fake, Path(temp) / "run", sleep=waits.append)
            self.assertTrue((Path(temp) / "run" / "summary.json").is_file())
            return summary, waits

    def test_exact_budget_and_no_restore(self):
        fake = FakeHid()
        result, waits = self.execute(fake)
        self.assertEqual(result["status"], "burst_complete_wait_for_timeout_observation")
        self.assertEqual((result["read_requests"], result["enable_writes"],
                          result["direct_frames"], result["changing_write_successes"]),
                         (3, 3, 40, 43))
        self.assertEqual(fake.write_attempts, list(runner.build_d1_burst_reports()))
        self.assertEqual(waits, [0.005] * 3 + [0.05] * 39)
        self.assertTrue(fake.closed)
        self.assertEqual(result["disable_writes"], 0)
        self.assertEqual(result["config_writes"], 0)
        self.assertEqual(result["color_profile_writes"], 0)
        self.assertTrue(all(report[0] != 0x04 and report[1] not in (0x04, 0x0A)
                            for report in fake.write_attempts))

    def test_mismatched_baseline_stops_before_first_write(self):
        fake = FakeHid(wrong_config=True)
        result, _ = self.execute(fake)
        self.assertEqual(result["status"], "stopped_on_deviation")
        self.assertEqual(result["changing_write_attempts"], 0)
        self.assertEqual(fake.write_attempts, [])
        self.assertTrue(fake.closed)

    def test_any_enable_failure_stops_without_later_reports(self):
        for failing_step in (1, 2, 3):
            with self.subTest(failing_step=failing_step):
                fake = FakeHid(fail_at_write=failing_step)
                result, _ = self.execute(fake)
                self.assertEqual(
                    (result["changing_write_attempts"], result["changing_write_successes"]),
                    (failing_step, failing_step - 1),
                )
                self.assertEqual(result["direct_frames"], 0)
                self.assertEqual(len(fake.write_attempts), failing_step)
                self.assertTrue(fake.closed)

    def test_direct_failure_stops_without_retry_or_disable(self):
        fake = FakeHid(fail_at_write=5)
        result, _ = self.execute(fake)
        self.assertEqual((result["changing_write_attempts"], result["changing_write_successes"]),
                         (5, 4))
        self.assertEqual(result["direct_frames"], 1)
        self.assertEqual(result["disable_writes"], 0)
        self.assertEqual(len(fake.write_attempts), 5)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
