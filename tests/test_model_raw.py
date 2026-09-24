"""Реальные 0x82 raw: проверка фактических offsets без ослабления guard."""
from pathlib import Path
import unittest

from agentrgb.outputs.aula_f75 import AulaError, validate_response


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'experiments/aula-f75-readonly/results/model-response-full.bin'
NEW = ROOT/'experiments/phase-04b/results/C1-20260923T085100265865Z/get-001-response.bin'


class ModelRawTests(unittest.TestCase):
    def test_old_response_uses_report_offset_8_and_psd_12_13(self):
        raw = OLD.read_bytes()
        self.assertEqual(len(raw), 520)
        self.assertEqual(raw[:14], bytes.fromhex('06 82 01 00 01 00 06 00 03 00 00 00 00 cd'))
        self.assertEqual(raw[8], 3)
        self.assertEqual(raw[12:14], b'\x00\xcd')
        self.assertEqual(validate_response(raw, 0x82), raw)

    def test_c1_response_has_two_changed_bytes_and_is_rejected(self):
        old, new = OLD.read_bytes(), NEW.read_bytes()
        self.assertEqual(len(new), 520)
        self.assertEqual([i for i,(a,b) in enumerate(zip(old,new)) if a!=b],[8,9])
        self.assertEqual(new[:8], old[:8])
        self.assertEqual(new[8:10], b'\x06\x82')
        self.assertEqual(new[12:14], b'\x00\xcd')
        with self.assertRaisesRegex(AulaError, '^model_or_psd_mismatch$'):
            validate_response(new, 0x82)
