"""C1 model diagnostic: 5 x 82, затем максимум 1 x 84 и 1 x 8A; только read requests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response
from read_diagnostics import ReadOnlyHid
from run import save_get_diagnostic


BASELINE = Path(__file__).parent/'results/manual-20260922T110723866453Z/baseline'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(device):
    return dict(vid=f'{device.vid:04X}', pid=f'{device.pid:04X}',
                interface='MI_01/COL06', usage_page=f'{device.usage_page:04X}',
                usage=f'{device.usage:04X}', feature_bytes=device.feature_bytes,
                path_shape='HID#VID_258A&PID_010C&MI_01&COL06#<redacted>#<redacted>',
                path_sha256=digest(device.path.lower().encode('utf-8')))


def run():
    directory=Path(__file__).parent/'results'/('model-probe-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    directory.mkdir(parents=True,exist_ok=False)
    backend=ReadOnlyHid(lambda record: save_get_diagnostic(directory,record))
    summary=dict(status='pending', changing_writes=0, max_model_cycles=5,
                 model_cycles=[], supplemental={}, handles=[], read_requests=0)
    handle=None
    try:
        for cycle in range(1,6):
            if cycle in (1,3,5):
                if handle is not None:
                    backend.close(handle);handle=None
                device=select_device(backend.enumerate())
                handle=backend.open(device.path)
                opened=backend.describe(handle,device.path)
                if not matches(opened):
                    raise RuntimeError('opened_identity_mismatch')
                info=identity(opened)
                if summary['handles'] and info['path_sha256'] != summary['handles'][0]['path_sha256']:
                    raise RuntimeError('path_changed_between_handles')
                summary['handles'].append(dict(opened_for_cycle=cycle,**info))
            backend.set_feature(handle,read_request(0x82))
            raw=backend.get_feature(handle,6,520) # sink сохранил до проверок.
            (directory/f'model-{cycle:02d}.bin').write_bytes(raw)
            (directory/f'model-{cycle:02d}.hex').write_text(raw.hex(' ')+'\n',encoding='ascii')
            diagnostic=backend.last_get_diagnostic
            row=dict(cycle=cycle,handle_group=len(summary['handles']),
                     timestamp=diagnostic['timestamp'],sha256=digest(raw),
                     first14=raw[:14].hex(' '),model_byte=raw[8],
                     psd=raw[12:14].hex().upper(),
                     path_sha256=summary['handles'][-1]['path_sha256'],
                     api_success=diagnostic['api_success'])
            summary['model_cycles'].append(row)
            if len(raw)!=520 or raw[:8]!=read_request(0x82)[:8] or row['psd']!='00CD':
                raise RuntimeError('model_header_or_psd_changed')
        for name,opcode in [('config',0x84),('color',0x8A)]:
            backend.set_feature(handle,read_request(opcode))
            raw=backend.get_feature(handle,6,520) # sink прежде валидатора.
            (directory/(name+'-response.bin')).write_bytes(raw)
            (directory/(name+'-response.hex')).write_text(raw.hex(' ')+'\n',encoding='ascii')
            validate_response(raw,opcode)
            baseline=(BASELINE/(name+'-response.bin')).read_bytes()
            different=[i for i,(a,b) in enumerate(zip(baseline,raw)) if a!=b]
            row=dict(timestamp=backend.last_get_diagnostic['timestamp'],
                     sha256=digest(raw),baseline_sha256=digest(baseline),
                     matches_baseline=raw==baseline,different_indices=different)
            if name=='config':
                row.update(report_66=f'{raw[66]:02X}',report_67=f'{raw[67]:02X}',
                           terminator=raw[134:136].hex().upper())
            else:
                row.update(primary_rgb=raw[29:32].hex().upper(),
                           terminator=raw[0x202:0x204].hex().upper())
            summary['supplemental'][name]=row
        summary['status']='complete'
    except BaseException as error:
        summary.update(status='stopped_on_observation',error=type(error).__name__+': '+str(error))
    finally:
        if handle is not None:
            try:
                backend.close(handle);summary['handle_closed']=True
            except BaseException as error:
                summary['handle_closed']=False
                summary['close_error']=type(error).__name__+': '+str(error)
        summary['read_requests']=backend.read_count
        (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        print(directory)
        print(json.dumps(summary,indent=2))
    return summary['status']=='complete'


if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
