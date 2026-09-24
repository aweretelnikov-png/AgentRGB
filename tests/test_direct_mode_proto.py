"""Offline checks for the 0x08 candidate, with no physical HID access."""

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "experiments" / "phase-04b" / "direct_mode_proto.py"
SPEC = importlib.util.spec_from_file_location("direct_mode_proto", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
proto = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proto)


class FakeHid:
    def __init__(self):
        self.reports = []

    def send_feature_report(self, report):
        self.reports.append(report)


class DirectModePrototypeTests(unittest.TestCase):
    def test_enable_reports_match_pinned_webhid_bodies(self):
        reports = proto.build_enable_reports()
        self.assertEqual(len(reports), 3)
        self.assertEqual(tuple(report[0] for report in reports), (0x39, 0x3C, 0x39))
        prefixes = (bytes.fromhex("20 06 00 01 00"),
                    bytes.fromhex("20 01 00"),
                    bytes.fromhex("20 06 01 01 00"))
        for report, prefix in zip(reports, prefixes):
            self.assertEqual(len(report), 520)
            self.assertEqual(len(report[1:]), 519)
            self.assertEqual(report[1 : 1 + len(prefix)], prefix)
            self.assertEqual(report[1 + len(prefix):], bytes(519 - len(prefix)))

    def test_exact_blue_frame_and_padding(self):
        frame = proto.build_uniform_frame((0, 0, 255))
        self.assertEqual(len(frame), 520)
        self.assertEqual(frame[:8], bytes.fromhex("06 08 00 00 01 00 7a 01"))
        self.assertEqual(frame[8:374], bytes((0, 0, 255)) * 122)
        self.assertEqual(frame[374:], bytes(146))
        self.assertEqual(frame[0x202:0x204], b"\x00\x00")
        self.assertNotIn(frame[1], (0x04, 0x0A))

    def test_disable_is_separate_and_d1_never_sends_it(self):
        disable = proto.build_disable_report()
        self.assertEqual(len(disable), 520)
        self.assertEqual(disable[:4], bytes.fromhex("3c 20 00 00"))
        self.assertEqual(disable[4:], bytes(516))

        planned = proto.build_d1_burst_reports()
        self.assertEqual(proto.D1_FRAME_COUNT, 40)
        self.assertEqual(proto.D1_FRAME_INTERVAL_MS, 50)
        self.assertEqual(len(planned), 43)
        self.assertEqual(planned[:3], proto.build_enable_reports())
        self.assertEqual(sum(report[0] == 0x06 and report[1] == 0x08 for report in planned), 40)
        self.assertTrue(all(report[0] != 0x04 and report[1] not in (0x04, 0x0A)
                            for report in planned))
        self.assertNotIn(disable, planned)
        self.assertIsNot(planned[3], planned[4])

    def test_fresh_immutable_frame_and_fake_only(self):
        fake = FakeHid()
        blue = proto.build_uniform_frame((0, 0, 255))
        green = proto.build_uniform_frame((0, 255, 0))
        self.assertEqual(fake.reports, [])  # The builder cannot send anything.
        self.assertIsNot(blue, green)
        self.assertEqual(blue[8:11], b"\x00\x00\xff")
        self.assertEqual(green[8:11], b"\x00\xff\x00")
        for report in proto.build_d1_burst_reports():
            fake.send_feature_report(report)
        self.assertEqual(len(fake.reports), 43)
        self.assertEqual(fake.reports[-1], blue)

    def test_rejects_invalid_rgb(self):
        for value in ((), (1, 2), (1, 2, 3, 4), (-1, 0, 0), (0, 256, 0), (0, True, 0)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                proto.build_uniform_frame(value)


if __name__ == "__main__":
    unittest.main()
