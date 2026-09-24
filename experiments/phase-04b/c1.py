"""04B-C1: один ограниченный аппаратный цикл, без Core и Pi."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from agentrgb.outputs.aula_f75 import color_report, matches, read_request, select_device, validate_response
from agentrgb.outputs.windows_hid import WindowsHid
from run import save_get_diagnostic


REFERENCE = {
    'model': '40d4fc0f4a1091627643a59dfbfd42eab89749b55c6ea15031e04a8703196523',
    'config': '5a90dd25a6dd82b2d639193ba2e03d9e3d98ae909dad32531ae0a1924cd413e0',
    'color': '93f7fa0a46dc0c58f6bb5a117da5bd146a0933a598d48361c8425a0b51f286b5',
}


def config_report(snapshot, *, single):
    if len(snapshot) != 520 or snapshot[:8] != read_request(0x84)[:8] or snapshot[134:136] != b'\x5a\xa5':
        raise ValueError('invalid_config_snapshot')
    result = bytearray(bytes.fromhex('06 04 00 00 01 00 80 00') + snapshot[8:136] + bytes(384))
    if single:
        if (snapshot[17], snapshot[18], snapshot[66], snapshot[67]) != (0, 1, 9, 0x37):
            raise ValueError('unexpected_config_fields')
        result[67] = 0x30
    return bytes(result)


class C1:
    def __init__(self, directory, backend=None, confirm=input):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.backend = backend or WindowsHid(diagnostic_sink=lambda record: save_get_diagnostic(directory, record))
        self.confirm = confirm
        self.handle = None
        self.write_attempts = 0
        self.write_successes = 0
        self.config_attempted = False
        self.blue_attempted = False
        self.trace = []
        self.summary = dict(scenario='C1', status='pending', write_limit=4, writes=[], reads={},
                            visual={}, restore={})

    def record(self, event, **values):
        self.trace.append(dict(timestamp=datetime.now(timezone.utc).isoformat(), event=event, **values))

    def read(self, opcode, stage):
        self.backend.set_feature(self.handle, read_request(opcode))
        raw = self.backend.get_feature(self.handle, 6, 520)
        (self.directory / (stage + '-response.bin')).write_bytes(raw)
        validate_response(raw, opcode)
        self.summary['reads'][stage] = dict(opcode=f'{opcode:02X}', sha256=hashlib.sha256(raw).hexdigest(),
                                            rgb=raw[29:32].hex() if opcode == 0x8A else None)
        self.record('read', stage=stage, opcode=f'{opcode:02X}', sha256=self.summary['reads'][stage]['sha256'])
        return raw

    def write(self, stage, report, opcode):
        if self.handle is None or self.write_attempts >= 4 or len(report) != 520 or report[:2] != bytes((6, opcode)):
            raise RuntimeError('write_guard')
        expected = {'config_change':0x04, 'blue':0x0A, 'red_restore':0x0A, 'config_restore':0x04}
        if expected.get(stage) != opcode or any(row['stage'] == stage for row in self.summary['writes']):
            raise RuntimeError('stage_guard')
        if stage == 'config_change':
            self.config_attempted = True
        if stage == 'blue':
            self.blue_attempted = True
        self.write_attempts += 1
        path = self.directory / f'write-{self.write_attempts:03d}-{stage}.bin'
        path.write_bytes(report)
        row = dict(stage=stage, opcode=f'{opcode:02X}', sha256=hashlib.sha256(report).hexdigest(), success=False)
        self.summary['writes'].append(row)
        self.record('write_attempt', stage=stage, opcode=f'{opcode:02X}', count=self.write_attempts)
        self.backend.set_feature(self.handle, report)
        self.write_successes += 1
        row['success'] = True
        self.record('write_success', stage=stage, count=self.write_successes)

    def visual(self, stage, expected):
        answer = self.confirm(f'VISUAL {stage}: type {expected} only if observed; otherwise STOP: ').strip()
        accepted = answer == expected
        self.summary['visual'][stage] = accepted
        self.record('visual', stage=stage, confirmed=accepted)
        if not accepted:
            raise RuntimeError('visual_' + stage + '_not_confirmed')

    def run(self):
        snapshot = {}
        try:
            device = select_device(self.backend.enumerate())
            self.handle = self.backend.open(device.path)
            if not matches(self.backend.describe(self.handle, device.path)):
                raise RuntimeError('opened_device_mismatch')
            for name, opcode in [('model',0x82),('config',0x84),('color',0x8A)]:
                snapshot[name] = self.read(opcode, 'fresh_' + name)
            for name in REFERENCE:
                if hashlib.sha256(snapshot[name]).hexdigest() != REFERENCE[name]:
                    raise RuntimeError('baseline_mismatch_' + name)
            if snapshot['color'][29:32] != b'\xff\x00\x00':
                raise RuntimeError('baseline_rgb_mismatch')
            self.summary['fresh_baseline_confirmed'] = True
            original_config = config_report(snapshot['config'], single=False)
            single_config = config_report(snapshot['config'], single=True)
            assert [i for i,(a,b) in enumerate(zip(original_config,single_config)) if a!=b] == [67]
            self.summary['config_diff'] = {'report_offset':67,'payload_offset':59,'before':'37','after':'30'}
            self.write('config_change', single_config, 0x04)
            changed = self.read(0x84, 'after_config')
            expected_config = bytearray(snapshot['config']);expected_config[67]=0x30
            if changed != bytes(expected_config):
                raise RuntimeError('config_readback_mismatch')
            self.visual('single_red', 'RED')
            self.write('blue', color_report((0,0,255)), 0x0A)
            blue = self.read(0x8A, 'after_blue')
            if blue[29:32] != b'\x00\x00\xff':
                raise RuntimeError('blue_readback_mismatch')
            self.visual('blue', 'BLUE')
            self.summary['status'] = 'checks_passed_pending_restore'
        except BaseException as error:
            self.summary['status'] = 'stopped_on_deviation'
            self.summary['deviation'] = type(error).__name__ + ': ' + str(error)
        finally:
            # Даже при неуспешном SetFeature запись могла примениться: по одной
            # минимально необходимой попытке восстановления, без retry.
            if self.handle is not None:
                if self.blue_attempted:
                    try:
                        self.write('red_restore', color_report((255,0,0)), 0x0A)
                        self.summary['restore']['color_write'] = 'success'
                    except BaseException as error:
                        self.summary['restore']['color_write'] = type(error).__name__ + ': ' + str(error)
                    try:
                        restored_color = self.read(0x8A, 'after_color_restore')
                        self.summary['restore']['color_readback_red'] = restored_color[29:32] == b'\xff\x00\x00'
                    except BaseException as error:
                        self.summary['restore']['color_readback_error'] = type(error).__name__ + ': ' + str(error)
                if self.config_attempted:
                    try:
                        self.write('config_restore', config_report(snapshot['config'], single=False), 0x04)
                        self.summary['restore']['config_write'] = 'success'
                    except BaseException as error:
                        self.summary['restore']['config_write'] = type(error).__name__ + ': ' + str(error)
                if self.config_attempted:
                    for name,opcode in [('config',0x84),('color',0x8A)]:
                        try:
                            raw = self.read(opcode, 'final_' + name)
                            self.summary['restore'][name + '_matches_baseline'] = raw == snapshot[name]
                        except BaseException as error:
                            self.summary['restore'][name + '_error'] = type(error).__name__ + ': ' + str(error)
                try:
                    self.backend.close(self.handle)
                    self.summary['handle_closed'] = True
                except BaseException as error:
                    self.summary['handle_closed'] = False
                    self.summary['close_error'] = type(error).__name__ + ': ' + str(error)
                self.handle = None
            if self.config_attempted:
                try:
                    self.visual('original_profile', 'RESTORED')
                except BaseException as error:
                    self.summary['restore']['visual_error'] = type(error).__name__ + ': ' + str(error)
            self.summary['write_attempts'] = self.write_attempts
            self.summary['write_successes'] = self.write_successes
            fully_restored = (self.summary['restore'].get('config_matches_baseline') is True
                              and self.summary['restore'].get('color_matches_baseline') is True
                              and self.summary['visual'].get('original_profile') is True)
            self.summary['restore']['fully_confirmed'] = fully_restored
            if self.summary['status'] == 'checks_passed_pending_restore':
                self.summary['status'] = ('passed' if fully_restored
                    and self.summary['restore'].get('color_readback_red') is True
                    and self.write_attempts == 4 else 'restore_not_confirmed')
            (self.directory / 'trace.json').write_text(json.dumps(self.trace,indent=2)+'\n',encoding='utf-8')
            (self.directory / 'summary.json').write_text(json.dumps(self.summary,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(self.summary,indent=2),flush=True)
        return self.summary['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('explicit --execute required for approved C1')
    directory = Path(__file__).parent / 'results' / ('C1-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    raise SystemExit(0 if C1(directory).run() else 1)
