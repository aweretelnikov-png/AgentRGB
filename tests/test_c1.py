"""Проверка разрешённого C1 на фальшивом HID, без физического устройства."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from test_aula import DEVICE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/phase-04b'))
SPEC = importlib.util.spec_from_file_location('c1', ROOT/'experiments/phase-04b/c1.py')
c1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c1)
BASELINE = ROOT/'experiments/phase-04b/results/manual-20260922T110723866453Z/baseline'


class FakeC1Hid:
    def __init__(self):
        self.reports = {name: bytearray((BASELINE/(name+'-response.bin')).read_bytes())
                        for name in ('model','config','color')}
        self.opcode = None
        self.sent = []
        self.closes = 0
        self.reads = []
        self.mismatch_config = False

    def enumerate(self): return [DEVICE]
    def open(self, path): return 1
    def describe(self, handle, path): return DEVICE
    def close(self, handle): self.closes += 1

    def set_feature(self, handle, report):
        self.sent.append(bytes(report))
        self.opcode=report[1]
        if self.opcode==0x04 and not self.mismatch_config:
            self.reports['config'][8:136]=report[8:136]
        elif self.opcode==0x0A:
            self.reports['color'][29:32]=report[29:32]

    def get_feature(self, handle, report_id, length):
        self.reads.append(self.opcode)
        return bytes(self.reports[{0x82:'model',0x84:'config',0x8A:'color'}[self.opcode]])

    @property
    def writes(self): return [r for r in self.sent if r[1] in (0x04,0x0A)]


class C1Tests(unittest.TestCase):
    def run_cycle(self, answers, mutate=None):
        fake=FakeC1Hid()
        if mutate: mutate(fake)
        with tempfile.TemporaryDirectory() as temporary:
            it=iter(answers)
            cycle=c1.C1(Path(temporary)/'C1',backend=fake,confirm=lambda prompt: next(it))
            passed=cycle.run()
            return fake,cycle.summary,passed

    def test_happy_path_exact_order_and_restore(self):
        fake,result,passed=self.run_cycle(['RED','BLUE','RESTORED'])
        self.assertTrue(passed)
        self.assertEqual([r[1] for r in fake.writes],[4,10,10,4])
        self.assertEqual(fake.writes[0][67],0x30)
        self.assertEqual(fake.writes[3][67],0x37)
        self.assertEqual(fake.writes[0][8:67]+fake.writes[0][68:136],fake.writes[3][8:67]+fake.writes[3][68:136])
        self.assertTrue(result['restore']['fully_confirmed'])
        self.assertTrue(result['restore']['color_readback_red'])
        self.assertEqual(fake.reads,[0x82,0x84,0x8A,0x84,0x8A,0x8A,0x84,0x8A])
        self.assertEqual(fake.closes,1)

    def test_red_visual_rejection_restores_config_only(self):
        fake,result,passed=self.run_cycle(['STOP','RESTORED'])
        self.assertFalse(passed)
        self.assertEqual([r[1] for r in fake.writes],[4,4])
        self.assertEqual(fake.reads,[0x82,0x84,0x8A,0x84,0x84,0x8A])
        self.assertTrue(result['restore']['fully_confirmed'])

    def test_blue_visual_rejection_restores_color_then_config(self):
        fake,result,passed=self.run_cycle(['RED','STOP','RESTORED'])
        self.assertFalse(passed)
        self.assertEqual([r[1] for r in fake.writes],[4,10,10,4])
        self.assertEqual(fake.reads,[0x82,0x84,0x8A,0x84,0x8A,0x8A,0x84,0x8A])
        self.assertTrue(result['restore']['fully_confirmed'])

    def test_config_readback_mismatch_stops_before_blue(self):
        fake,result,passed=self.run_cycle(['RESTORED'],lambda f:setattr(f,'mismatch_config',True))
        self.assertFalse(passed)
        self.assertEqual([r[1] for r in fake.writes],[4,4])
        self.assertIn('config_readback_mismatch',result['deviation'])

    def test_baseline_mismatch_cannot_write(self):
        def drift(fake): fake.reports['config'][66]=8
        fake,result,passed=self.run_cycle([],drift)
        self.assertFalse(passed)
        self.assertEqual(fake.writes,[])
        self.assertIn('baseline_mismatch_config',result['deviation'])


if __name__ == '__main__': unittest.main()
