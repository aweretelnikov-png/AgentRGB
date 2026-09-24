"""Offline tests: no real HID handle is opened."""

import ctypes as C
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "phase-04b"))

from agentrgb.outputs.windows_hid import Caps, FeatureCaps, WindowsHid  # noqa: E402
from descriptor_inspector import (ButtonCaps, ValueCaps, _caps_ids, classification,
                                  feature_ids, path_identity)  # noqa: E402


class DescriptorInspectorTests(unittest.TestCase):
    def test_caps_layout_and_feature_length(self):
        self.assertEqual(C.sizeof(Caps), 64)
        raw = bytearray(64)
        raw[8:10] = (520).to_bytes(2, "little")
        raw[58:60] = (2).to_bytes(2, "little")
        raw[60:62] = (3).to_bytes(2, "little")
        caps = Caps.from_buffer_copy(raw)
        self.assertEqual(caps.feature_bytes, 520)
        self.assertEqual(caps.counts[7], 2)
        self.assertEqual(caps.counts[8], 3)

    def test_report_id_layout_and_unique_union(self):
        self.assertEqual(C.sizeof(ValueCaps), 72)
        self.assertEqual(C.sizeof(ButtonCaps), 72)
        self.assertEqual(ValueCaps.report_id.offset, 2)
        self.assertEqual(ButtonCaps.report_id.offset, 2)
        self.assertEqual(feature_ids([0x06, 0x39, 0x39], [0x3C, 0x06]),
                         [0x06, 0x39, 0x3C])
        self.assertEqual(C.sizeof(FeatureCaps), 72)

    def test_production_feature_id_gate_reads_opened_handle_caps(self):
        calls = []
        def get_preparsed(handle, pointer):
            self.assertEqual(handle, 7)
            C.cast(pointer, C.POINTER(C.c_void_p))[0] = 123
            return 1
        def get_caps(preparsed, pointer):
            caps = C.cast(pointer, C.POINTER(Caps))[0]
            caps.counts[8], caps.counts[7] = 2, 1
            return 0x00110000
        def get_values(report_type, buffer, count, preparsed):
            self.assertEqual(report_type, 2)
            entries = C.cast(buffer, C.POINTER(FeatureCaps))
            entries[0].raw[2], entries[1].raw[2] = 5, 6
            return 0x00110000
        def get_buttons(report_type, buffer, count, preparsed):
            C.cast(buffer, C.POINTER(FeatureCaps))[0].raw[2] = 6
            return 0x00110000
        hid = WindowsHid.__new__(WindowsHid)
        hid.hid = SimpleNamespace(HidD_GetPreparsedData=get_preparsed,
                                  HidP_GetCaps=get_caps, HidP_GetValueCaps=get_values,
                                  HidP_GetButtonCaps=get_buttons,
                                  HidD_FreePreparsedData=lambda pointer: calls.append(pointer.value))
        self.assertEqual(hid.feature_report_ids(7), frozenset((5, 6)))
        self.assertEqual(calls, [123])

    def test_fake_hidp_value_and_button_caps(self):
        class FakeHid:
            @staticmethod
            def HidP_GetValueCaps(report_type, buffer, actual, preparsed):
                self.assertEqual(report_type, 2)
                values = C.cast(buffer, C.POINTER(ValueCaps))
                values[0].report_id = 0x06
                values[1].report_id = 0x39
                C.cast(actual, C.POINTER(C.c_ushort))[0] = 2
                return 0x00110000

            @staticmethod
            def HidP_GetButtonCaps(report_type, buffer, actual, preparsed):
                self.assertEqual(report_type, 2)
                C.cast(buffer, C.POINTER(ButtonCaps))[0].report_id = 0x3C
                C.cast(actual, C.POINTER(C.c_ushort))[0] = 1
                return 0x00110000

        hid = FakeHid()
        values = _caps_ids(hid, C.c_void_p(), 2, ValueCaps, "HidP_GetValueCaps")
        buttons = _caps_ids(hid, C.c_void_p(), 1, ButtonCaps, "HidP_GetButtonCaps")
        self.assertEqual(feature_ids(values, buttons), [0x06, 0x39, 0x3C])

    def test_collections_do_not_mix_and_absent_39_classified(self):
        current = {"mi": "01", "col": "06", "feature_ids": ["06"]}
        other = {"mi": "01", "col": "05", "feature_ids": ["39", "3C"]}
        self.assertEqual(classification([current]), "enable_ids_absent_from_all_collections")
        self.assertEqual(classification([current, other]),
                         "enable_ids_in_other_collection_or_split")
        self.assertEqual(classification([other]), "current_collection_missing")

    def test_path_is_only_hashed(self):
        path = r"\\?\hid#vid_258a&pid_010c&mi_01&col06#private-instance"
        identity = path_identity(path)
        self.assertEqual(identity["mi"], "01")
        self.assertEqual(identity["col"], "06")
        self.assertEqual(len(identity["path_sha256"]), 64)
        self.assertNotIn("private-instance", str(identity))

    def test_inspector_has_no_hid_report_io(self):
        source = (ROOT / "experiments" / "phase-04b" / "descriptor_inspector.py").read_text(
            encoding="utf-8")
        for forbidden in (".set_feature(", "HidD_SetFeature(", ".get_feature(",
                          "HidD_GetFeature(", "ReadFile(", "WriteFile("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
