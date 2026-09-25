"""Doctor F75 использует только fake transport, без физического HID."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import unittest
from unittest.mock import patch

from agentrgb.outputs.aula_f75 import read_request
from agentrgb.outputs.aula_f75_diagnostics import check_f75
from test_aula_direct import DEVICE, DirectHid


class DoctorF75Tests(unittest.TestCase):
    def run_check(self, hid):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("agentrgb.outputs.aula_f75_diagnostics.os.name", "nt"), \
                patch("agentrgb.outputs.aula_f75_diagnostics.WindowsHid", return_value=hid), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = check_f75()
        text = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(DEVICE.path, text)
        self.assertNotIn("hid#", text.lower())
        self.assertEqual(hid.frames, [])
        self.assertTrue(all(report == read_request(0x82) for report in hid.sent))
        self.assertLessEqual(len(hid.sent), 1)
        self.assertLessEqual(hid.reads, 1)
        return result, stdout.getvalue()

    def test_ready_uses_one_identity_read_without_rgb_or_persistent_reports(self):
        hid = DirectHid()
        result, text = self.run_check(hid)
        self.assertEqual(result, 0)
        for expected in ("AULA F75: ready", "identity read", "258A:010C", "MI_01/COL06",
                         "FF00/0001", "FeatureReportByteLength: 520", "report ID: 06",
                         "Model: 03", "PSD: 00CD"):
            self.assertIn(expected, text)
        self.assertEqual(hid.sent, [read_request(0x82)])
        self.assertEqual(hid.reads, 1)
        self.assertEqual(hid.closed, [1])

    def test_missing_and_ambiguous_devices_are_not_opened(self):
        for devices, status in (([], "not found"), ([DEVICE, DEVICE], "ambiguous")):
            with self.subTest(status=status):
                hid = DirectHid()
                hid.devices = devices
                result, text = self.run_check(hid)
                self.assertEqual(result, 1)
                self.assertIn(f"AULA F75: {status}", text)
                self.assertEqual(hid.opens, 0)
                self.assertEqual(hid.sent, [])
                self.assertEqual(hid.closed, [])

    def test_wrong_enumerated_identity_is_not_opened(self):
        for field, value in (("vid", 1), ("pid", 1), ("usage_page", 0xFF01),
                             ("usage", 2), ("feature_bytes", 64),
                             ("path", DEVICE.path.replace("col06", "col05")),
                             ("path", DEVICE.path.replace("mi_01", "mi_00"))):
            with self.subTest(field=field, value=value):
                hid = DirectHid()
                hid.devices = [replace(DEVICE, **{field: value})]
                result, text = self.run_check(hid)
                self.assertEqual(result, 1)
                self.assertIn("AULA F75: not found", text)
                self.assertEqual(hid.opens, 0)

    def test_opened_identity_and_report_id_are_gated_before_read(self):
        mutations = (
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, vid=1)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, pid=1)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, usage=2)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, usage_page=0xFF01)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, feature_bytes=64)),
            lambda hid: setattr(hid, "opened_device", replace(DEVICE, path=DEVICE.path + "-other")),
            lambda hid: setattr(hid, "ids", frozenset((5,))),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                hid = DirectHid()
                mutation(hid)
                result, text = self.run_check(hid)
                self.assertEqual(result, 1)
                self.assertIn("identity read failed", text)
                self.assertEqual(hid.sent, [])
                self.assertEqual(hid.closed, [1])

    def test_model_psd_header_and_length_mismatch_stop_after_one_read(self):
        mutations = (
            lambda hid: hid.model.__setitem__(8, 6),
            lambda hid: hid.model.__setitem__(slice(12, 14), b"\x00\x00"),
            lambda hid: hid.model.__setitem__(0, 0),
            lambda hid: setattr(hid, "model", hid.model[:8]),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                hid = DirectHid()
                mutation(hid)
                result, text = self.run_check(hid)
                self.assertEqual(result, 1)
                self.assertIn("identity read failed", text)
                self.assertEqual(hid.sent, [read_request(0x82)])
                self.assertEqual(hid.reads, 1)
                self.assertEqual(hid.closed, [1])

    def test_transport_errors_close_handle_and_hide_private_path(self):
        for method in ("enumerate", "open", "describe", "feature_report_ids", "set_feature", "get_feature"):
            with self.subTest(method=method):
                hid = DirectHid()
                with patch.object(hid, method, side_effect=OSError(DEVICE.path)):
                    result, text = self.run_check(hid)
                self.assertEqual(result, 1)
                self.assertIn("identity read failed", text)
                self.assertEqual(hid.closed, [] if method in ("enumerate", "open") else [1])

    def test_close_error_is_failure_and_does_not_leak_path(self):
        hid = DirectHid()
        with patch.object(hid, "close", side_effect=OSError(DEVICE.path)) as close:
            result, text = self.run_check(hid)
        self.assertEqual(result, 1)
        self.assertIn("identity read failed", text)
        self.assertNotIn("AULA F75: ready", text)
        close.assert_called_once_with(1)

    def test_cancellation_closes_handle(self):
        hid = DirectHid()
        with patch.object(hid, "get_feature", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_check(hid)
        self.assertEqual(hid.closed, [1])
        self.assertEqual(hid.sent, [read_request(0x82)])
        self.assertEqual(hid.frames, [])

    def test_backend_initialization_error_hides_private_path(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("agentrgb.outputs.aula_f75_diagnostics.os.name", "nt"), \
                patch("agentrgb.outputs.aula_f75_diagnostics.WindowsHid", side_effect=OSError(DEVICE.path)), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(check_f75(), 1)
        self.assertIn("identity read failed", stdout.getvalue())
        self.assertNotIn(DEVICE.path, stdout.getvalue() + stderr.getvalue())

    def test_unsupported_platform_does_not_construct_backend(self):
        stdout = io.StringIO()
        with patch("agentrgb.outputs.aula_f75_diagnostics.os.name", "posix"), \
                patch("agentrgb.outputs.aula_f75_diagnostics.WindowsHid") as backend, \
                redirect_stdout(stdout):
            self.assertEqual(check_f75(), 1)
        self.assertIn("AULA F75: unsupported platform", stdout.getvalue())
        backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
