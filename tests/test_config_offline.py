"""Офлайн-инварианты: разные координаты, полное восстановление, запрет HID."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentrgb.outputs.aula_f75 import color_report

SPEC = importlib.util.spec_from_file_location('config_offline', Path(__file__).resolve().parents[1] / 'experiments/phase-04b/config_offline.py')
offline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offline)


def fixture():
    raw = bytearray((i * 13 + 11) % 256 for i in range(520))
    raw[:8] = bytes.fromhex('06 84 01 00 01 00 80 00')
    raw[17:19] = b'\x00\x01'
    raw[25:27] = b'\x00\x01'
    raw[66:68] = b'\x09\x37'
    raw[74:76] = b'\x08\x37'
    raw[134:136] = b'\x5a\xa5'
    return raw


class ConfigOfflineTests(unittest.TestCase):
    def test_effect_offset_is_report_relative(self):
        raw = fixture(); raw[26] = 2
        self.assertEqual(offline.parse_config(raw)['effect'], 1)
        self.assertEqual(offline.parse_config(raw, payload_offsets=True)['effect'], 2)

    def test_brightness_coordinate_disagreement(self):
        self.assertEqual(offline.parse_config(fixture())['brightness'], 9)
        self.assertEqual(offline.parse_config(fixture(), payload_offsets=True)['brightness'], 8)

    def test_speed(self):
        self.assertEqual(offline.parse_config(fixture())['speed'], 3)

    def test_flags(self):
        self.assertEqual(offline.parse_config(fixture())['flags'], 7)

    def test_nibbles_are_independent(self):
        for packed, speed, flags in [(0x37,3,7),(0x30,3,0),(0x07,0,7),(0,0,0)]:
            raw=fixture(); raw[67]=packed
            parsed=offline.parse_config(raw)
            self.assertEqual((parsed['speed'],parsed['flags']),(speed,flags))

    def test_unknown_bytes_unchanged_for_both_candidates(self):
        raw=fixture()
        for preserve in (False,True):
            changed=offline.candidate_report(raw,preserve_speed=preserve)
            self.assertEqual([i for i in range(8,136) if raw[i]!=changed[i]],[67])

    def test_custom_mode_disabled_by_upstream(self):
        raw=fixture();raw[17]=1
        changed=offline.candidate_report(raw,preserve_speed=False)
        self.assertEqual([i for i in range(8,136) if raw[i]!=changed[i]],[17,67])

    def test_restore_all_payload_bytes(self):
        raw=fixture()
        self.assertEqual(offline.restore_report(raw)[8:136],raw[8:136])

    def test_buffers_do_not_alias(self):
        raw=fixture(); original=bytes(raw)
        restore=offline.restore_report(raw)
        changed=offline.candidate_report(raw,preserve_speed=False)
        changed[9]^=255
        self.assertEqual(bytes(raw),original)
        self.assertEqual(restore[8:136],raw[8:136])

    def test_wired_report_format(self):
        report=offline.restore_report(fixture())
        self.assertEqual(len(report),520)
        self.assertEqual(report[:8],bytes.fromhex('06 04 00 00 01 00 80 00'))
        self.assertEqual(report[134:136],b'\x5a\xa5')
        self.assertEqual(report[136:],bytes(384))

    def test_static_upstream_does_not_preserve_speed(self):
        raw=fixture()
        self.assertEqual(offline.candidate_report(raw,preserve_speed=False)[67],0)
        self.assertEqual(offline.candidate_report(raw,preserve_speed=True)[67],0x30)

    def test_color_writer_independent(self):
        before=color_report((0,0,255))
        offline.candidate_report(fixture(),preserve_speed=False)
        self.assertEqual(color_report((0,0,255)),before)
        self.assertEqual(before[1],0x0A)

    def test_entire_preparation_never_calls_hid(self):
        with tempfile.TemporaryDirectory() as temp, patch('agentrgb.outputs.windows_hid.WindowsHid.set_feature',side_effect=AssertionError('HID forbidden')) as hid:
            directory=Path(temp)
            (directory/'config-response.bin').write_bytes(fixture())
            result=offline.prepare(directory)
            self.assertEqual(result['status'],'BLOCKED_NOT_FOR_HARDWARE')
            self.assertEqual(len(list(directory.glob('*.hex'))),3)
            hid.assert_not_called()

    def test_reject_invalid_snapshot(self):
        for index in (0,1,6,134):
            raw=fixture();raw[index]^=255
            with self.assertRaises(ValueError): offline.restore_report(raw)

    def test_reject_wrong_effect(self):
        raw=fixture();raw[18]=2
        with self.assertRaises(ValueError): offline.candidate_report(raw,preserve_speed=False)
