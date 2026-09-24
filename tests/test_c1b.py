"""Фазовая C1B transaction на fake HID, без реального устройства и stdin."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_aula import DEVICE

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/phase-04b'))
from c1b import C1B
from c1 import config_report

BASE=ROOT/'experiments/phase-04b/results/manual-20260922T110723866453Z/baseline'


class FakeHid:
    def __init__(self):
        self.device=DEVICE
        self.reports={name:bytearray((BASE/(name+'-response.bin')).read_bytes())
                      for name in ('model','config','color')}
        self.opcode=None
        self.writes=[]
        self.closed=0
        self.fail_first_config=False
        self.bad_config_read_once=False
        self.bad_blue_read_once=False
        self.last_write=None

    def enumerate(self): return [self.device]
    def open(self,path): return 1
    def describe(self,handle,path): return self.device
    def close(self,handle): self.closed+=1

    def set_feature(self,handle,report):
        self.opcode=report[1]
        if self.opcode not in (0x04,0x0A,0x82,0x84,0x8A):
            raise AssertionError('forbidden command')
        if self.opcode in (0x04,0x0A):
            self.writes.append(bytes(report))
            self.last_write=self.opcode
            if self.opcode==0x04:
                if self.fail_first_config and len(self.writes)==1:
                    raise OSError('first_config_failed')
                self.reports['config'][8:136]=report[8:136]
            else:
                self.reports['color'][29:32]=report[29:32]

    def get_feature(self,handle,report_id,length):
        name={0x82:'model',0x84:'config',0x8A:'color'}[self.opcode]
        raw=bytearray(self.reports[name])
        if self.opcode==0x84 and self.last_write==0x04 and self.bad_config_read_once:
            self.bad_config_read_once=False
            raw[66]=8
        if self.opcode==0x8A and self.last_write==0x0A and self.bad_blue_read_once:
            self.bad_blue_read_once=False
            raw[29:32]=b'\x00\xff\x00'
        return bytes(raw)


class C1BTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)/('C1B-'+str(uuid4()))
        self.fake=FakeHid()
        self.runner=C1B(self.directory,backend_factory=lambda sink:self.fake)

    def prepared(self):
        with patch('builtins.input',side_effect=AssertionError('stdin used')):
            result=self.runner.prepare()
        self.assertEqual(result['status'],'prepared')
        self.assertEqual(self.fake.writes,[])
        self.assertEqual(len(result['prepared_sha256']),3)

    def test_apply_exits_blue_and_restore_is_idempotent(self):
        self.prepared()
        with patch('builtins.input',side_effect=AssertionError('stdin used')):
            result=self.runner.apply_blue()
            self.assertEqual(result['status'],'applied_blue_restore_required')
            self.assertEqual([report[1] for report in self.fake.writes],[4,10])
            self.assertEqual(self.fake.reports['color'][29:32],b'\x00\x00\xff')
            result=self.runner.restore()
            self.assertEqual(result['status'],'restored_closed')
            self.assertEqual([report[1] for report in self.fake.writes],[4,10,10,4])
            self.assertTrue(result['final_config_matches_baseline'])
            self.assertTrue(result['final_color_matches_baseline'])
            count=self.fake.closed
            result=self.runner.restore()
            self.assertEqual(result['status'],'restored_closed')
            self.assertEqual(self.fake.closed,count)
            self.assertEqual(len(self.fake.writes),4)

    def test_restore_uses_transaction_snapshot(self):
        self.prepared()
        self.runner.apply_blue()
        snapshot=(self.directory/'transaction-config.bin').read_bytes()
        self.runner.restore()
        self.assertEqual(self.fake.writes[-1],config_report(snapshot,single=False))
        self.assertEqual(snapshot,(self.directory/'prepared-config.bin').read_bytes())

    def test_restore_accepts_partially_changed_current_state(self):
        self.prepared()
        self.runner.apply_blue()
        self.fake.reports['config'][67]=0x31
        self.fake.reports['color'][29:32]=b'\x12\x34\x56'
        result=self.runner.restore()
        self.assertEqual(result['status'],'restored_closed')
        self.assertEqual([report[1] for report in self.fake.writes],[4,10,10,4])

    def test_restore_requires_model_and_psd_but_not_entire_model_response(self):
        self.prepared()
        self.runner.apply_blue()
        self.fake.reports['model'][9]=1
        result=self.runner.restore()
        self.assertEqual(result['status'],'restored_closed')
        self.assertEqual([report[1] for report in self.fake.writes],[4,10,10,4])

    def test_restore_stops_without_writes_if_model_changes(self):
        self.prepared()
        self.runner.apply_blue()
        self.fake.reports['model'][8]=6
        result=self.runner.restore()
        self.assertEqual(result['status'],'applied_blue_restore_required')
        self.assertEqual([report[1] for report in self.fake.writes],[4,10])

    def test_tampered_transaction_snapshot_blocks_restore(self):
        self.prepared()
        self.runner.apply_blue()
        path=self.directory/'transaction-config.bin'
        raw=bytearray(path.read_bytes());raw[66]=8;path.write_bytes(raw)
        with self.assertRaises(RuntimeError):
            self.runner.restore()
        self.assertEqual(len(self.fake.writes),2)

    def test_config_readback_error_restores_only_config(self):
        self.prepared()
        self.fake.bad_config_read_once=True
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'restored_closed')
        self.assertIn('config_readback_mismatch',result['apply_error'])
        self.assertEqual([report[1] for report in self.fake.writes],[4,4])

    def test_blue_readback_error_restores_color_then_config(self):
        self.prepared()
        self.fake.bad_blue_read_once=True
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'restored_closed')
        self.assertIn('blue_readback_mismatch',result['apply_error'])
        self.assertEqual([report[1] for report in self.fake.writes],[4,10,10,4])

    def test_first_write_failure_does_not_write_restore(self):
        self.prepared()
        self.fake.fail_first_config=True
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'apply_failed_no_successful_write')
        self.assertEqual(len(self.fake.writes),1)
        self.assertEqual(result['writes'][0]['success'],False)

    def test_stale_snapshot_blocks_apply_before_write(self):
        self.prepared()
        self.fake.reports['config'][66]=8
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'apply_failed_no_successful_write')
        self.assertEqual(self.fake.writes,[])

    def test_other_device_path_blocks_apply_and_restore(self):
        self.prepared()
        self.fake.device=replace(DEVICE,path=DEVICE.path+'other')
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'apply_failed_no_successful_write')
        self.assertEqual(self.fake.writes,[])
        self.fake.device=DEVICE
        self.runner.state['status']='prepared'
        self.runner._record('test_reset_only')
        result=self.runner.apply_blue()
        self.assertEqual(result['status'],'applied_blue_restore_required')
        self.fake.device=replace(DEVICE,path=DEVICE.path+'other')
        result=self.runner.restore()
        self.assertEqual(result['status'],'applied_blue_restore_required')
        self.assertEqual(len(self.fake.writes),2)

    def test_all_branches_respect_budget(self):
        for mode in ('success','config_error','blue_error'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                fake=FakeHid();runner=C1B(Path(temporary)/('C1B-'+str(uuid4())),lambda sink:fake)
                runner.prepare()
                if mode=='config_error': fake.bad_config_read_once=True
                if mode=='blue_error': fake.bad_blue_read_once=True
                state=runner.apply_blue()
                if mode=='success': state=runner.restore()
                self.assertLessEqual(len(state['writes']),4)
                self.assertLessEqual(len(fake.writes),4)
                self.assertEqual(len({w['stage'] for w in state['writes']}),len(state['writes']))


if __name__=='__main__': unittest.main()
