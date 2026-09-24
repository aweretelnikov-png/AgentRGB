"""Проверки ctypes-буферов с поддельными API, без физических HID-команд."""
import ctypes as C
from ctypes import wintypes as W
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/phase-04b"))
from persistent_output import AulaError, AulaF75Output, color_report, read_request, validate_response
from agentrgb.outputs.windows_hid import WindowsHid
from test_aula import FakeHid
from test_aula_experiment import experiment

SPEC = importlib.util.spec_from_file_location("readonly_diagnostics", Path(experiment.__file__).with_name("read_diagnostics.py"))
readonly = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"run": experiment}):
    SPEC.loader.exec_module(readonly)


def boundary(sink=None):
    native = WindowsHid.__new__(WindowsHid)
    native.diagnostic_sink = sink
    native.get_sequence = 0
    native.last_get_diagnostic = None
    native.requests = {}
    fake = FakeHid()
    input_buffers, set_buffers, get_buffers = [], [], []
    def set_feature(handle, buffer, length):
        set_buffers.append(buffer)
        fake.set_feature(handle, bytes(buffer))
        return 1
    def get_feature(handle, buffer, length):
        input_buffers.append(bytes(buffer))
        get_buffers.append(buffer)
        buffer[:] = fake.get_feature(handle, buffer[0], length)
        return 1
    native.hid = SimpleNamespace(HidD_SetFeature=set_feature, HidD_GetFeature=get_feature)
    native.enumerate, native.open, native.describe = fake.enumerate, fake.open, fake.describe
    native.kernel = SimpleNamespace(CloseHandle=lambda handle: (fake.close(handle), 1)[1])
    return native, fake, input_buffers, set_buffers, get_buffers


class DiagnosticTests(unittest.TestCase):
    def test_invalid_response_saved_before_validation_and_survives_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            native, fake, *_ = boundary(lambda record: experiment.save_get_diagnostic(directory, record))
            fake.reports[0x8A][0] = 0xEE
            native.set_feature(1, read_request(0x8A))
            response = native.get_feature(1, 6, 520)
            self.assertEqual((directory/'get-001-response.bin').read_bytes(), response)
            with self.assertLogs("agentrgb.aula", level="WARNING") as messages:
                with self.assertRaisesRegex(AulaError, "invalid_response_header"):
                    validate_response(response, 0x8A)
            self.assertIn(response[:16].hex(" "), messages.output[0])
            self.assertTrue((directory/'get-001-response.bin').exists())
            record = json.loads((directory/'get-001.json').read_text())
            self.assertEqual(record['first32_hex'], response[:32].hex(' '))
            self.assertEqual(record['request_header_hex'], '06 8a 01 00 01 00 00 02')
            self.assertEqual(record['terminator_hex'], '5a a5')
            self.assertEqual(record['initial_report_id'], 6)
            self.assertEqual(record['buffer_size'], 520)
            self.assertTrue(record['api_success'])
            self.assertNotIn('get_last_error', record)

    def test_each_actual_request_matches_01b_all_520_bytes(self):
        native, fake, _, set_buffers, _ = boundary()
        for opcode in (0x82, 0x84, 0x8A):
            native.set_feature(1, read_request(opcode))
            native.get_feature(1, 6, 520)
            self.assertEqual(bytes(set_buffers[-1]), readonly.prototype_request(opcode))
        self.assertEqual(len(fake.sent), 3)

    def test_response_initialized_and_no_alias_or_signed_bytes(self):
        native, fake, inputs, setters, getters = boundary()
        write = bytearray(color_report((128, 200, 255)))
        native.set_feature(1, write)
        write[:] = bytes(520)
        for _ in range(2):
            native.set_feature(1, read_request(0x8A))
            response = native.get_feature(1, 6, 520)
            self.assertEqual(response[29:32], bytes((128, 200, 255)))
        self.assertEqual(inputs, [b'\x06'+bytes(519)] * 2)
        addresses = [C.addressof(buffer) for buffer in setters + getters]
        self.assertEqual(len(addresses), len(set(addresses)))
        self.assertEqual(bytes(setters[0]), color_report((128, 200, 255)))

    def test_api_failure_saves_buffer_and_last_error_before_raising(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            native, *_ = boundary(lambda record: experiment.save_get_diagnostic(directory, record))
            def fail(handle, buffer, length):
                buffer[1] = 0xEF
                return 0
            native.hid.HidD_GetFeature = fail
            native.set_feature(1, read_request(0x8A))
            with patch.object(C, "get_last_error", return_value=31), self.assertRaises(OSError):
                native.get_feature(1, 6, 520)
            record = json.loads((directory/'get-001.json').read_text())
            self.assertFalse(record['api_success'])
            self.assertEqual(record['get_last_error'], 31)
            self.assertEqual((directory/'get-001-response.bin').read_bytes()[:2], b'\x06\xef')

    def test_success_never_reads_stale_last_error(self):
        native, *_ = boundary()
        native.set_feature(1, read_request(0x8A))
        with patch.object(C, "get_last_error", side_effect=AssertionError('must not read')):
            native.get_feature(1, 6, 520)

    def test_invalid_after_simulated_change_saved_and_restores_once(self):
        records = []
        native, fake, *_ = boundary(records.append)
        real_get = native.hid.HidD_GetFeature
        def invalid_once(handle, buffer, length):
            status = real_get(handle, buffer, length)
            if fake.write_count == 2 and fake.opcode == 0x8A:
                buffer[0] = 0xEE
            return status
        native.hid.HidD_GetFeature = invalid_once
        output = AulaF75Output(native)
        self.assertTrue(output.acquire())
        self.assertFalse(output.show_activity('working'))
        self.assertEqual(records[4]['raw_response'][0], 0xEE)
        self.assertEqual(records[4]['requested_opcode'], 0x8A)
        self.assertEqual(output.restore_status, 'readback_confirmed')
        self.assertEqual(len(fake.writes), 4)
        self.assertFalse(output.show_activity('waiting'))
        output.release()
        self.assertEqual(len(fake.writes), 4)

    def test_invalid_without_change_does_not_write_or_retry(self):
        records = []
        native, fake, *_ = boundary(records.append)
        fake.reports[0x8A][1] = 0x0A
        output = AulaF75Output(native)
        self.assertFalse(output.acquire())
        self.assertEqual(len(records), 3)
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.closes, 1)

    def test_noise_not_accepted_even_with_plausible_rgb(self):
        noise = bytearray(520)
        noise[0] = 6
        noise[29:32] = b'\xff\x00\x00'
        noise[514:516] = b'\x5a\xa5'
        with self.assertRaises(AulaError):
            validate_response(bytes(noise), 0x8A)

    def test_read_only_guard_blocks_every_state_write_and_bare_get(self):
        backend = readonly.ReadOnlyHid.__new__(readonly.ReadOnlyHid)
        backend.read_count, backend.awaiting_get = 0, False
        for opcode in (0x0A, 0x04, 0x06, 0x01):
            report = bytearray(520)
            report[0], report[1] = 6, opcode
            with self.assertRaisesRegex(RuntimeError, 'state_writes_forbidden'):
                backend.set_feature(1, bytes(report))
        with self.assertRaisesRegex(RuntimeError, 'bare_get_forbidden'):
            backend.get_feature(1, 6, 520)

    def test_native_signatures_load_without_opening_device(self):
        native = WindowsHid()
        for name in ('HidD_GetFeature', 'HidD_SetFeature'):
            function = getattr(native.hid, name)
            self.assertEqual(function.argtypes, [W.HANDLE, C.c_void_p, W.ULONG])
            self.assertEqual(function.restype, C.c_ubyte)
        self.assertEqual(C.sizeof(W.ULONG), 4)
        self.assertEqual(C.sizeof(W.HANDLE), C.sizeof(C.c_void_p))
