"""Старый 04B inspect остаётся read-only после перехода production на 0x04."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_aula import FakeHid

SPEC = importlib.util.spec_from_file_location("phase04b", Path(__file__).resolve().parents[1] / "experiments/phase-04b/run.py")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class ExperimentTests(unittest.TestCase):
    def test_inspect_reads_fresh_baseline_without_writes(self):
        fake = FakeHid()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "inspect"
            result = experiment.inspect(directory, fake)
            self.assertEqual(result["status"], "read_only_identified")
            self.assertEqual(result["identity"]["model"], "03")
            self.assertEqual(result["identity"]["psd"], "00CD")
            self.assertEqual(result["config_66_67"], "0937")
            self.assertEqual(result["original_rgb"], "123456")
            self.assertEqual(fake.reads, [0x82, 0x84, 0x8A])
            self.assertEqual(fake.writes, [])
            self.assertEqual(fake.closes, 1)
            for name in ("model", "config", "color"):
                self.assertEqual(len((directory / f"{name}-response.bin").read_bytes()), 520)

    def test_inspect_invalid_model_stops_without_write(self):
        fake = FakeHid()
        fake.reports[0x82][8] = 6
        with tempfile.TemporaryDirectory() as temporary:
            result = experiment.inspect(Path(temporary) / "inspect", fake)
        self.assertEqual(result["status"], "stopped_on_error")
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.closes, 1)

    def test_legacy_hardware_scenarios_rejected_before_open(self):
        for scenario in ("H1", "H2", "H3", "H4", "D1"):
            with self.subTest(scenario=scenario), patch("sys.argv", ["run.py", scenario]), \
                 patch.object(experiment, "WindowsHid", side_effect=AssertionError("opened")), \
                 self.assertRaises(SystemExit):
                experiment.main()


if __name__ == "__main__":
    unittest.main()
