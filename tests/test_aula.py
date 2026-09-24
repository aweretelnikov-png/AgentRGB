"""Production AULA F75 на fake HID: физическое устройство не открывается."""
from dataclasses import replace
import http.client
import json
import threading
import unittest
from unittest.mock import patch

from agentrgb.outputs.aula_f75 import AulaF75Output as DirectAulaF75Output
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/phase-04b"))
from persistent_output import (
    AulaError, AulaF75Output, COLORS, color_report, config_report, read_request, select_device,
)
from agentrgb.outputs.windows_hid import Interface
from agentrgb.server import EventServer
from agentrgb import server as server_module
from agentrgb.fake import FakeOutput
from agentrgb.state import Core
from test_core import event
from test_transport import payload

DEVICE = Interface(r"\\?\hid#vid_258a&pid_010c&mi_01&col06#fixture", 0x258A, 0x010C, 0xFF00, 1, 520)


class FakeHid:
    def __init__(self):
        self.devices = [DEVICE]
        self.opened_device = DEVICE
        self.reports = {opcode: bytearray(read_request(opcode)) for opcode in (0x82, 0x84, 0x8A)}
        self.reports[0x82][8] = 3
        self.reports[0x82][12:14] = b"\x00\xcd"
        for index in range(8, 134):
            self.reports[0x84][index] = (index * 7) & 255
        self.reports[0x84][17:19] = b"\x00\x01"
        self.reports[0x84][66:68] = b"\x09\x37"
        self.reports[0x84][134:136] = b"\x5a\xa5"
        self.reports[0x8A][0x202:0x204] = b"\x5a\xa5"
        self.reports[0x8A][29:32] = b"\x12\x34\x56"
        self.reports[0x8A][37:40] = b"\xaa\xbb\xcc"
        self.sent = []
        self.reads = []
        self.opens = 0
        self.closes = 0
        self.opcode = None
        self.fail_write_numbers = set()
        self.write_count = 0
        self.fail_get = False
        self.mismatch_color = False
        self.bad_config_read_once = False
        self.fail_close = False

    def enumerate(self):
        return self.devices

    def open(self, path):
        assert path == DEVICE.path
        self.opens += 1
        return self.opens

    def describe(self, handle, path):
        return self.opened_device

    def close(self, handle):
        self.closes += 1
        if self.fail_close:
            raise OSError("fixture")

    def set_feature(self, handle, report):
        assert handle is not None and len(report) == 520
        assert report[1] in (0x82, 0x84, 0x8A, 0x04, 0x0A), "Forbidden opcode"
        self.sent.append(bytes(report))
        self.opcode = report[1]
        if self.opcode in (0x04, 0x0A):
            self.write_count += 1
            if self.write_count in self.fail_write_numbers:
                raise OSError("fixture")
            if self.opcode == 0x04:
                self.reports[0x84][8:136] = report[8:136]
            elif not self.mismatch_color:
                self.reports[0x8A][29:32] = report[29:32]

    def get_feature(self, handle, report_id, length):
        assert (report_id, length) == (6, 520)
        self.reads.append(self.opcode)
        if self.fail_get:
            raise OSError("fixture")
        raw = bytearray(self.reports[self.opcode])
        if self.opcode == 0x84 and self.write_count and self.bad_config_read_once:
            self.bad_config_read_once = False
            raw[66] = 8
        return bytes(raw)

    @property
    def writes(self):
        return [report for report in self.sent if report[1] in (0x04, 0x0A)]

    @property
    def color_writes(self):
        return [report for report in self.writes if report[1] == 0x0A]


class AulaTests(unittest.TestCase):
    def setUp(self):
        self.hid = FakeHid()
        self.output = AulaF75Output(self.hid)

    def tearDown(self):
        self.output.release()

    def test_idle_never_opens_device(self):
        core = Core(self.output)
        core.tick()
        core.close()
        self.assertEqual(self.hid.opens, 0)
        self.assertEqual(self.hid.sent, [])

    def test_cli_default_fake_and_real_only_when_explicit(self):
        selected = []
        class FakeServer:
            def __init__(self, port, core):
                selected.append(core.output)
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                pass
            def serve_forever(self, **unused):
                raise KeyboardInterrupt()
        with patch.object(server_module, "EventServer", FakeServer), \
             patch("sys.argv", ["agentrgb.server"]):
            server_module.main()
        self.assertIsInstance(selected[-1], FakeOutput)
        with patch.object(server_module, "EventServer", FakeServer), \
             patch("sys.argv", ["agentrgb.server", "--output", "aula-f75"]):
            server_module.main()
        self.assertIsInstance(selected[-1], DirectAulaF75Output)

    def test_exact_interface_and_absent_or_ambiguous_device(self):
        wrong = replace(DEVICE, path=DEVICE.path.replace("col06", "col05"))
        self.assertEqual(select_device([wrong, DEVICE]), DEVICE)
        for devices in ([], [DEVICE, replace(DEVICE, path=DEVICE.path + "2")]):
            with self.subTest(count=len(devices)):
                hid = FakeHid()
                hid.devices = devices
                self.assertFalse(AulaF75Output(hid).acquire())
                self.assertEqual(hid.writes, [])

    def test_identity_gate_all_fields_before_write(self):
        for field, value in (("vid", 1), ("pid", 2), ("usage_page", 0xFF13),
                             ("usage", 2), ("feature_bytes", 64), ("path", "Gaming Keyboard")):
            with self.subTest(field=field):
                hid = FakeHid()
                hid.devices = [replace(DEVICE, **{field: value})]
                self.assertFalse(AulaF75Output(hid).acquire())
                self.assertEqual(hid.writes, [])

    def test_opened_handle_identity_rechecked(self):
        self.hid.opened_device = replace(DEVICE, pid=5)
        self.assertFalse(self.output.acquire())
        self.assertEqual(self.hid.writes, [])
        self.assertEqual(self.hid.closes, 1)

    def test_model_psd_and_malformed_reads_block_writes(self):
        for opcode, offset, value in ((0x82, 8, 6), (0x82, 12, 1), (0x82, 13, 0),
                                      (0x84, 134, 0), (0x8A, 0, 0)):
            with self.subTest(opcode=opcode, offset=offset):
                hid = FakeHid()
                hid.reports[opcode][offset] = value
                self.assertFalse(AulaF75Output(hid).acquire())
                self.assertEqual(hid.writes, [])
                self.assertEqual(hid.closes, 1)

    def test_acquire_uses_fresh_snapshot_each_cycle(self):
        original_config = bytes(self.hid.reports[0x84])
        original_color = bytes(self.hid.reports[0x8A])
        self.assertTrue(self.output.acquire())
        self.assertEqual(self.output.snapshot.rgb, (0x12, 0x34, 0x56))
        self.assertEqual(self.output.snapshot.config, original_config)
        self.assertEqual(self.output.snapshot.color, original_color)
        self.assertEqual(self.output.snapshot.identity, DEVICE)
        self.output.acquire()
        self.assertEqual(self.hid.reads[:4], [0x82, 0x84, 0x8A, 0x84])
        self.output.release()
        self.hid.reports[0x8A][29:32] = b"\x99\x88\x77"
        self.assertTrue(self.output.acquire())
        self.assertEqual(self.output.snapshot.rgb, (0x99, 0x88, 0x77))
        self.assertEqual(self.hid.reads.count(0x82), 2)

    def test_config_acquire_changes_only_67_and_preserves_payload(self):
        original = bytes(self.hid.reports[0x84])
        self.assertTrue(self.output.acquire())
        self.assertEqual([r[1] for r in self.hid.writes], [0x04])
        report = self.hid.writes[0]
        self.assertEqual(report[67], 0x30)
        expected = bytearray(config_report(original, single=False))
        expected[67] = 0x30
        self.assertEqual(report, bytes(expected))
        self.assertEqual(self.hid.reads, [0x82, 0x84, 0x8A, 0x84])

    def test_unsupported_baseline_is_read_only(self):
        for offset, value in ((67, 0x31), (66, 8), (17, 1), (18, 0)):
            with self.subTest(offset=offset):
                hid = FakeHid()
                hid.reports[0x84][offset] = value
                self.assertFalse(AulaF75Output(hid).acquire())
                self.assertEqual(hid.writes, [])

    def test_config_readback_failure_restores_config_only(self):
        self.hid.bad_config_read_once = True
        self.assertFalse(self.output.acquire())
        self.assertEqual([r[1] for r in self.hid.writes], [0x04, 0x04])
        self.assertEqual(self.hid.reports[0x84][67], 0x37)
        self.assertEqual(self.output.restore_status, "readback_confirmed")
        self.assertEqual(self.hid.closes, 1)

    def test_config_get_failure_restores_config_only(self):
        original_get = self.hid.get_feature
        def fail_after_config(handle, report_id, length):
            if self.hid.opcode == 0x84 and self.hid.write_count == 1:
                raise OSError("fixture")
            return original_get(handle, report_id, length)
        self.hid.get_feature = fail_after_config
        self.assertFalse(self.output.acquire())
        self.assertEqual([r[1] for r in self.hid.writes], [4, 4])
        self.assertEqual(self.hid.closes, 1)

    def test_color_reports_and_deduped_h2_budget(self):
        core = Core(self.output, clock=lambda: 0)
        self.assertEqual(core.apply(event()), "applied")
        self.output.show_activity("working")
        core.apply(event("run_waiting"))
        self.output.show_activity("waiting")
        core.apply(event("run_resumed"))
        core.apply(event("run_ended", outcome="completed"))
        self.output.show_signal("completed")
        core.close()
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 10, 10, 10, 4])
        self.assertEqual([tuple(r[29:32]) for r in self.hid.color_writes],
                         [COLORS["working"], COLORS["waiting"], COLORS["working"],
                          COLORS["completed"], (0x12, 0x34, 0x56)])
        self.assertEqual(self.output.restore_status, "readback_confirmed")

    def test_release_restores_color_then_full_config_once(self):
        original_config = bytes(self.hid.reports[0x84])
        original_color = bytes(self.hid.reports[0x8A])
        self.assertTrue(self.output.acquire())
        self.assertTrue(self.output.show_activity("working"))
        self.assertTrue(self.output.release())
        self.assertTrue(self.output.release())
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(self.hid.writes[-1], config_report(original_config, single=False))
        self.assertEqual(bytes(self.hid.reports[0x84]), original_config)
        self.assertEqual(bytes(self.hid.reports[0x8A]), original_color)
        self.assertEqual(self.hid.closes, 1)
        self.assertIsNone(self.output.snapshot)

    def test_original_rgb_equal_target_skips_duplicate_color_write(self):
        self.hid.reports[0x8A][29:32] = bytes(COLORS["working"])
        self.assertTrue(self.output.acquire())
        self.output.show_activity("working")
        self.assertEqual([r[1] for r in self.hid.writes], [4])
        self.output.show_activity("waiting")
        self.output.resume_activity("working")
        self.output.release()
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])

    def test_failed_config_write_attempts_one_config_restore(self):
        self.hid.fail_write_numbers = {1}
        self.assertFalse(self.output.acquire())
        self.assertEqual([r[1] for r in self.hid.writes], [4, 4])
        self.assertEqual(self.hid.closes, 1)

    def test_color_readback_mismatch_restores_color_and_config(self):
        self.assertTrue(self.output.acquire())
        self.hid.mismatch_color = True
        self.assertFalse(self.output.show_activity("working"))
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertIsNone(self.output.handle)

    def test_failed_color_set_feature_attempts_color_then_config_restore(self):
        self.assertTrue(self.output.acquire())
        self.hid.fail_write_numbers = {2}
        self.assertFalse(self.output.show_activity("working"))
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(self.hid.closes, 1)

    def test_invalid_header_after_blue_restores_once(self):
        self.assertTrue(self.output.acquire())
        original_get = self.hid.get_feature
        def invalid_once(handle, report_id, length):
            raw = original_get(handle, report_id, length)
            if self.hid.write_count == 2:
                return b"\x00" + raw[1:]
            return raw
        self.hid.get_feature = invalid_once
        self.assertFalse(self.output.show_activity("working"))
        self.assertEqual(self.output.last_error, "invalid_response_header")
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.output.release()
        self.assertEqual(len(self.hid.writes), 4)

    def test_failed_get_after_color_attempts_both_restores(self):
        self.assertTrue(self.output.acquire())
        self.hid.fail_get = True
        self.assertFalse(self.output.show_activity("working"))
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(self.output.restore_status, "unverified")

    def test_restore_write_failure_does_not_retry_and_config_still_restores(self):
        self.output.acquire()
        self.output.show_activity("working")
        self.hid.fail_write_numbers = {3}
        self.assertFalse(self.output.release())
        self.assertFalse(self.output.release())
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(self.hid.closes, 1)

    def test_close_failure_is_controlled(self):
        self.output.acquire()
        self.hid.fail_close = True
        self.assertFalse(self.output.release())
        self.assertEqual(self.hid.closes, 1)

    def test_upper_layer_exception_and_keyboard_interrupt_cleanup(self):
        core = Core(self.output)
        try:
            core.apply(event())
            raise RuntimeError("controlled_failure_above_hid")
        except RuntimeError:
            pass
        finally:
            core.close()
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(self.output.restore_status, "readback_confirmed")

    def test_core_survives_output_unavailable_and_failed_render(self):
        for absent in (False, True):
            with self.subTest(absent=absent):
                hid = FakeHid()
                if absent:
                    hid.devices = []
                output = AulaF75Output(hid)
                core = Core(output)
                core.apply(event())
                hid.fail_write_numbers = {3}
                core.apply(event("run_waiting"))
                core.apply(event("run_ended"))
                core.close()
                self.assertEqual(core.aggregate(), "idle")
                self.assertLessEqual(len(hid.writes), 5)

    def test_http_shutdown_releases_and_closes_listener(self):
        with EventServer(0, Core(self.output)) as server:
            address = server.server_address
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
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
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(server.fileno(), -1)
        with EventServer(address[1], Core(AulaF75Output(FakeHid()))):
            pass

    def test_server_finally_releases_on_exception(self):
        with self.assertRaises(RuntimeError):
            with EventServer(0, Core(self.output)) as server:
                server.core.apply(event())
                raise RuntimeError("fixture")
        self.assertEqual([r[1] for r in self.hid.writes], [4, 10, 10, 4])
        self.assertEqual(server.fileno(), -1)

    def test_no_cleanup_does_not_promise_restore(self):
        hid = FakeHid()
        output = AulaF75Output(hid)
        output.acquire()
        output.show_activity("working")
        del output
        self.assertEqual([r[1] for r in hid.writes], [4, 10])
        self.assertEqual(hid.closes, 0)


if __name__ == "__main__":
    unittest.main()
