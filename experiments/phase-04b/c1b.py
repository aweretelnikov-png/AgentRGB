"""04B-C1B: неинтерактивные prepare / apply-blue / restore / status."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from agentrgb.outputs.aula_f75 import color_report, matches, read_request, select_device, validate_response
from agentrgb.outputs.windows_hid import WindowsHid
from c1 import REFERENCE, config_report
from run import save_get_diagnostic


RESULTS = Path(__file__).parent / 'results'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def transaction_directory(transaction_id):
    parsed = UUID(transaction_id)
    if str(parsed) != transaction_id:
        raise ValueError('invalid_transaction_id')
    return RESULTS / ('C1B-' + transaction_id)


class C1B:
    def __init__(self, directory, backend_factory=None):
        self.directory = Path(directory)
        self.backend_factory = backend_factory or (lambda sink: WindowsHid(diagnostic_sink=sink))
        self.backend = None
        self.handle = None
        self.state_path = self.directory/'transaction.json'
        self.state = None
        self.path_hash = None

    def _record(self, event, **details):
        self.state.setdefault('events', []).append(dict(timestamp=datetime.now(timezone.utc).isoformat(),
                                                          event=event, **details))
        save_json(self.state_path, self.state)

    def _open(self):
        diagnostics=self.directory/'diagnostics'/str(uuid4())
        diagnostics.mkdir(parents=True,exist_ok=False)
        self.backend = self.backend_factory(lambda record: save_get_diagnostic(diagnostics, record))
        device = select_device(self.backend.enumerate())
        self.handle = self.backend.open(device.path)
        opened = self.backend.describe(self.handle, device.path)
        if not matches(opened):
            raise RuntimeError('opened_device_mismatch')
        self.path_hash = sha(device.path.lower().encode('utf-8'))
        identity = dict(vid=f'{opened.vid:04X}', pid=f'{opened.pid:04X}',
                        collection='MI_01/COL06', usage_page=f'{opened.usage_page:04X}',
                        usage=f'{opened.usage:04X}', feature_bytes=opened.feature_bytes,
                        report_id='06', path_sha256=self.path_hash)
        self._record('identity', **identity)
        return identity

    def _close(self):
        if self.handle is not None:
            try:
                self.backend.close(self.handle)
                self._record('handle_closed')
            finally:
                self.handle = None

    def _read(self, opcode, stage):
        if opcode not in (0x82,0x84,0x8A):
            raise RuntimeError('forbidden_read_opcode')
        self.backend.set_feature(self.handle, read_request(opcode))
        raw = self.backend.get_feature(self.handle, 6, 520)
        (self.directory/(stage+'.bin')).write_bytes(raw)
        (self.directory/(stage+'.hex')).write_text(raw.hex(' ')+'\n',encoding='ascii')
        validate_response(raw, opcode)
        self._record('read', stage=stage, opcode=f'{opcode:02X}', sha256=sha(raw))
        return raw

    def _snapshot(self, prefix):
        return {name:self._read(opcode,prefix+'-'+name)
                for name,opcode in (('model',0x82),('config',0x84),('color',0x8A))}

    @staticmethod
    def _baseline_gate(snapshot):
        if any(sha(snapshot[name]) != REFERENCE[name] for name in REFERENCE):
            raise RuntimeError('baseline_mismatch')
        if snapshot['config'][66:68] != b'\x09\x37' or snapshot['color'][29:32] != b'\xff\x00\x00':
            raise RuntimeError('baseline_fields_mismatch')

    def _write(self, stage, report):
        allowed = {'config_acquire':0x04,'blue':0x0A,'color_restore':0x0A,'config_restore':0x04}
        if (stage not in allowed or len(report)!=520 or report[:2] != bytes((6,allowed[stage]))
                or len(self.state['writes']) >= 4
                or any(row['stage']==stage for row in self.state['writes'])):
            raise RuntimeError('write_guard')
        row = dict(stage=stage, opcode=f'{allowed[stage]:02X}',sha256=sha(report),success=False)
        (self.directory/('write-'+stage+'.bin')).write_bytes(report)
        self.state['writes'].append(row)  # Durable attempt precedes SetFeature.
        self._record('write_attempt', stage=stage, count=len(self.state['writes']))
        self.backend.set_feature(self.handle, report)
        row['success'] = True
        self._record('write_success', stage=stage)

    def prepare(self):
        self.directory.mkdir(parents=True,exist_ok=False)
        transaction_id=self.directory.name.removeprefix('C1B-')
        self.state=dict(transaction_id=transaction_id,status='preparing',writes=[],events=[],
                        created_at=datetime.now(timezone.utc).isoformat())
        save_json(self.state_path,self.state)
        try:
            identity=self._open()
            snapshot=self._snapshot('prepared')
            self._baseline_gate(snapshot)
            (self.directory/'prepared-config-payload.bin').write_bytes(snapshot['config'][8:136])
            self.state['prepared_identity']=identity
            self.state['prepared_sha256']={name:sha(raw) for name,raw in snapshot.items()}
            self.state['status']='prepared'
            self._record('prepared', baseline='FF0000', report_66='09',report_67='37')
        except BaseException as error:
            self.state['status']='prepare_failed'
            self._record('prepare_failed', reason=type(error).__name__+': '+str(error))
        finally:
            self._close()
        return self.state

    def _load(self):
        self.state=json.loads(self.state_path.read_text(encoding='utf-8'))
        if self.state['transaction_id'] != self.directory.name.removeprefix('C1B-'):
            raise RuntimeError('transaction_marker_mismatch')
        if len(self.state['writes']) > 4:
            raise RuntimeError('write_budget_corrupt')

    def _original(self):
        snapshot={name:(self.directory/('transaction-'+name+'.bin')).read_bytes()
                  for name in ('model','config','color')}
        self._baseline_gate(snapshot)
        if {name:sha(raw) for name,raw in snapshot.items()} != self.state['transaction_sha256']:
            raise RuntimeError('transaction_snapshot_hash_mismatch')
        return snapshot

    def _restore(self, original):
        # One attempt per stage; no retry even when read-back or write fails.
        blue=next((row for row in self.state['writes'] if row['stage']=='blue'),None)
        config=next((row for row in self.state['writes'] if row['stage']=='config_acquire'),None)
        if blue is not None and not any(row['stage']=='color_restore' for row in self.state['writes']):
            # A failed SetFeature can still have changed the device. A read-only
            # observation decides whether its uncertain attempt needs restore.
            restore_color=bool(blue['success'])
            if not restore_color:
                try:
                    current=self._read(0x8A,'uncertain-blue-color')
                    restore_color=current != original['color']
                except BaseException:
                    restore_color=True
            if restore_color:
                try:
                    self._write('color_restore',color_report(tuple(original['color'][29:32])))
                except BaseException as error:
                    self._record('color_restore_error',reason=type(error).__name__+': '+str(error))
                try:
                    response=self._read(0x8A,'after-color-restore')
                    self.state['color_restore_rgb_confirmed']=response[29:32]==original['color'][29:32]
                    self._record('color_restore_readback',confirmed=self.state['color_restore_rgb_confirmed'])
                except BaseException as error:
                    self._record('color_restore_readback_error',reason=type(error).__name__+': '+str(error))
        if config is not None and config['success'] and not any(row['stage']=='config_restore' for row in self.state['writes']):
            try:
                self._write('config_restore',config_report(original['config'],single=False))
            except BaseException as error:
                self._record('config_restore_error',reason=type(error).__name__+': '+str(error))
        if config is not None and config['success']:
            for name,opcode in (('config',0x84),('color',0x8A)):
                try:
                    response=self._read(opcode,'final-'+name)
                    self.state['final_'+name+'_matches_baseline']=response==original[name]
                    self._record('final_match',region=name,confirmed=self.state['final_'+name+'_matches_baseline'])
                except BaseException as error:
                    self._record('final_read_error',region=name,reason=type(error).__name__+': '+str(error))
        complete=(self.state.get('final_config_matches_baseline') is True
                  and self.state.get('final_color_matches_baseline') is True
                  and (blue is None or not blue['success'] or self.state.get('color_restore_rgb_confirmed') is True))
        self.state['status']='restored_closed' if complete else 'restore_unverified'
        self._record('restore_finished',confirmed=complete)

    def apply_blue(self):
        self._load()
        if self.state['status'] != 'prepared':
            raise RuntimeError('transaction_not_prepared')
        self.state['status']='applying'
        self._record('apply_started')
        try:
            identity=self._open()
            if identity['path_sha256'] != self.state['prepared_identity']['path_sha256']:
                raise RuntimeError('device_path_changed')
            snapshot=self._snapshot('transaction')  # Fresh gate immediately before writes.
            self._baseline_gate(snapshot)
            if any(snapshot[name] != (self.directory/('prepared-'+name+'.bin')).read_bytes()
                   for name in snapshot):
                raise RuntimeError('prepared_snapshot_stale')
            self.state['transaction_identity']=identity
            self.state['transaction_sha256']={name:sha(raw) for name,raw in snapshot.items()}
            self._record('fresh_transaction_snapshot_saved')
            changed=config_report(snapshot['config'],single=True)
            self._write('config_acquire',changed)
            observed=self._read(0x84,'after-config-acquire')
            expected=bytearray(snapshot['config']);expected[67]=0x30
            if observed != bytes(expected):
                raise RuntimeError('config_readback_mismatch')
            self._write('blue',color_report((0,0,255)))
            observed=self._read(0x8A,'after-blue')
            if observed[29:32] != b'\x00\x00\xff':
                raise RuntimeError('blue_readback_mismatch')
            self.state['status']='applied_blue_restore_required'
            self._record('applied_blue_restore_required',rgb='0000FF')
        except BaseException as error:
            self.state['apply_error']=type(error).__name__+': '+str(error)
            self._record('apply_error',reason=self.state['apply_error'])
            if 'transaction_sha256' in self.state and any(row['success'] for row in self.state['writes']):
                self._restore(self._original())
            else:
                self.state['status']='apply_failed_no_successful_write'
                self._record('apply_stopped_without_restore')
        finally:
            self._close()
        return self.state

    def restore(self):
        self._load()
        if self.state['status']=='restored_closed':
            return self.state  # Idempotent; no HID access.
        if self.state['status'] not in ('applied_blue_restore_required','applying','restore_unverified'):
            raise RuntimeError('transaction_not_open')
        original=self._original()
        try:
            self._open()
            if self.path_hash != self.state['transaction_identity']['path_sha256']:
                raise RuntimeError('device_path_changed')
            self._read(0x82,'restore-identity-model')  # Validates model 03 and PSD 00CD.
            self._restore(original)
        except BaseException as error:
            self.state['restore_error']=type(error).__name__+': '+str(error)
            self._record('restore_stopped',reason=self.state['restore_error'])
        finally:
            self._close()
        return self.state

    def status(self):
        self._load()
        return self.state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('prepare','apply-blue','restore','status'))
    parser.add_argument('--transaction')
    args=parser.parse_args()
    if args.phase=='prepare':
        if args.transaction: parser.error('prepare allocates transaction id')
        transaction_id=str(uuid4())
    else:
        if not args.transaction: parser.error('--transaction required')
        transaction_id=args.transaction
    runner=C1B(transaction_directory(transaction_id))
    result=getattr(runner,args.phase.replace('-','_'))()
    print(json.dumps(dict(transaction_id=transaction_id,status=result['status'],
                          writes=result['writes'],directory=str(runner.directory)),indent=2),flush=True)
    if result['status']=='applied_blue_restore_required':
        print('C1B_APPLIED_BLUE_RESTORE_REQUIRED',flush=True)
    return 0 if result['status'] in ('prepared','applied_blue_restore_required','restored_closed') else 1


if __name__=='__main__':
    raise SystemExit(main())
