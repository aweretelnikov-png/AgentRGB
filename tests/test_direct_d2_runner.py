"""D2 execution policy exercised only with FakeHid and fake sleep."""

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "phase-04b"))

from descriptor_inspector import path_identity  # noqa: E402
from direct_d2_runner import run_burst, build_d2_burst_reports  # noqa: E402
from test_direct_d1_runner import FakeHid  # noqa: E402


def descriptor(_backend, device):
    return {**path_identity(device.path), "vid": "258A", "pid": "010C",
            "usage_page": "FF00", "usage": "0001", "feature_bytes": 520,
            "feature_ids": ["06"]}


class DirectD2RunnerTests(unittest.TestCase):
    def execute(self, fake, probe=descriptor):
        with tempfile.TemporaryDirectory() as temp:
            waits = []
            result = run_burst(fake, Path(temp) / "run", descriptor_probe=probe,
                               sleep=waits.append)
            self.assertTrue((Path(temp) / "run" / "summary.json").is_file())
            self.assertEqual((Path(temp) / "run" / "blue-frame.bin").stat().st_size, 520)
            return result, waits

    def test_exact_40_frames_only_and_no_post_read(self):
        fake = FakeHid()
        result, waits = self.execute(fake)
        self.assertEqual(result["status"], "burst_complete_wait_for_visual_observation")
        self.assertEqual((result["read_requests"], result["changing_write_attempts"],
                          result["changing_write_successes"], result["direct_frames"]),
                         (3, 40, 40, 40))
        self.assertEqual(fake.write_attempts, list(build_d2_burst_reports()))
        self.assertEqual(waits, [0.05] * 39)
        self.assertTrue(fake.closed)
        self.assertEqual((result["enable_writes"], result["disable_writes"],
                          result["config_writes"], result["color_profile_writes"]),
                         (0, 0, 0, 0))
        self.assertTrue(all(frame[0:2] == b"\x06\x08" for frame in fake.write_attempts))

    def test_missing_descriptor_report_stops_with_zero_writes(self):
        fake = FakeHid()
        def no_report(backend, device):
            return {**descriptor(backend, device), "feature_ids": ["05"]}
        result, _ = self.execute(fake, no_report)
        self.assertEqual(result["changing_write_attempts"], 0)
        self.assertEqual(fake.write_attempts, [])

    def test_baseline_deviation_stops_with_zero_writes(self):
        fake = FakeHid(wrong_config=True)
        result, _ = self.execute(fake)
        self.assertEqual(result["status"], "stopped_on_deviation")
        self.assertEqual(result["changing_write_attempts"], 0)
        self.assertEqual(fake.write_attempts, [])
        self.assertTrue(fake.closed)

    def test_first_frame_error_stops_without_retry(self):
        fake = FakeHid(fail_at_write=1)
        result, waits = self.execute(fake)
        self.assertEqual((result["changing_write_attempts"],
                          result["changing_write_successes"]), (1, 0))
        self.assertEqual(len(fake.write_attempts), 1)
        self.assertEqual(waits, [])
        self.assertTrue(fake.closed)

    def test_later_frame_error_stops_without_retry(self):
        fake = FakeHid(fail_at_write=5)
        result, waits = self.execute(fake)
        self.assertEqual((result["changing_write_attempts"],
                          result["changing_write_successes"]), (5, 4))
        self.assertEqual(len(fake.write_attempts), 5)
        self.assertEqual(waits, [0.05] * 4)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
