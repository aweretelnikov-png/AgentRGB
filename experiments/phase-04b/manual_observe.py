"""Read-only снимки после ручных действий. Нет генерации/отправки state writes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from agentrgb.outputs.aula_f75 import matches, select_device, read_request, validate_response
from read_diagnostics import ReadOnlyHid
from run import save_get_diagnostic
from config_offline import parse_config


def differences(before, after):
    if len(before) != len(after):
        raise ValueError('different_lengths')
    return [dict(report_offset=i, payload_offset=i-8 if 8 <= i < 136 else None,
                 before=f'{a:02X}', after=f'{b:02X}')
            for i, (a, b) in enumerate(zip(before, after)) if a != b]


class StageReadOnlyHid(ReadOnlyHid):
    def __init__(self, sink, opcodes):
        super().__init__(sink)
        self.opcodes = opcodes

    def set_feature(self, handle, report):
        if self.read_count >= len(self.opcodes) or len(report) != 520 or report[1] != self.opcodes[self.read_count]:
            raise RuntimeError('unexpected_stage_request')
        super().set_feature(handle, report)


def capture(root, stage):
    if stage == 'baseline':
        root.mkdir(parents=True, exist_ok=False)
        opcodes = (0x82, 0x84, 0x8A)
    else:
        baseline = json.loads((root/'baseline/summary.json').read_text())
        if baseline['status'] != 'valid':
            raise RuntimeError('baseline_invalid')
        opcodes = (0x84, 0x8A) if stage.startswith(('M3-', 'wake-')) else (0x84,)
    directory = root/stage
    directory.mkdir(exist_ok=False)  # Нельзя перезаписать/повторить тот же этап.
    backend = StageReadOnlyHid(lambda record: save_get_diagnostic(directory, record), opcodes)
    handle = None
    summary = dict(stage=stage, changing_writes=0, status='pending', reads={})
    try:
        device = select_device(backend.enumerate())
        handle = backend.open(device.path)
        if not matches(backend.describe(handle, device.path)):
            raise RuntimeError('opened_device_mismatch')
        summary['identity'] = '258A:010C MI_01/COL06 FF00/0001 feature=520 report=06'
        for opcode in opcodes:
            backend.set_feature(handle, read_request(opcode))
            raw = backend.get_feature(handle, 6, 520)
            name = {0x82:'model', 0x84:'config', 0x8A:'color'}[opcode]
            (directory/(name+'-response.bin')).write_bytes(raw)
            (directory/(name+'-response.hex')).write_text(raw.hex(' ')+'\n',encoding='ascii')
            validate_response(raw, opcode)
            row = dict(sha256=hashlib.sha256(raw).hexdigest())
            if opcode == 0x82:
                row.update(model='03', psd='00CD')
            if opcode == 0x84:
                payload=raw[8:136]
                (directory/'config-payload.bin').write_bytes(payload)
                (directory/'config-payload.hex').write_text(payload.hex(' ')+'\n',encoding='ascii')
                row.update(payload_sha256=hashlib.sha256(payload).hexdigest(), code_relative=parse_config(raw), payload_relative=parse_config(raw,payload_offsets=True))
            if opcode == 0x8A:
                row['primary_rgb']=raw[29:32].hex()
            if stage != 'baseline':
                reference=(root/'baseline'/(name+'-response.bin')).read_bytes()
                row['diff_from_baseline']=differences(reference,raw)
                row['matches_baseline']=reference==raw
            summary['reads'][name]=row
        summary['status']='valid'
    except Exception as error:
        summary.update(status='stopped_on_error', error=str(error))
        raise
    finally:
        if handle is not None:
            backend.close(handle)
        summary.update(handle_closed=True, read_requests=backend.read_count)
        (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['baseline','M1-down','M1-restore','M2-left','M2-restore',
                                         'wake-down','wake-up']+[f'M3-{i}' for i in range(1,9)])
    parser.add_argument('--root',type=Path)
    args=parser.parse_args()
    root=args.root
    if root is None:
        if args.stage!='baseline': parser.error('--root required after baseline')
        root=Path(__file__).parent/'results'/('manual-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    print(str(root),flush=True)
    capture(root,args.stage)
