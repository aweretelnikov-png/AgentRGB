"""Однократный config restore после недоступного интерактивного окна C1."""
import hashlib
import json
from pathlib import Path

from agentrgb.outputs.aula_f75 import matches, read_request, select_device, validate_response
from agentrgb.outputs.windows_hid import WindowsHid
from c1 import config_report
from run import save_get_diagnostic


ROOT = Path(__file__).parent/'results/C1-20260923T090447213540Z'


def main():
    directory=ROOT/'abort-restore'
    directory.mkdir(exist_ok=False)
    backend=WindowsHid(diagnostic_sink=lambda record: save_get_diagnostic(directory,record))
    original=(ROOT/'fresh_config-response.bin').read_bytes()
    original_color=(ROOT/'fresh_color-response.bin').read_bytes()
    assert hashlib.sha256(original).hexdigest() == '5a90dd25a6dd82b2d639193ba2e03d9e3d98ae909dad32531ae0a1924cd413e0'
    assert hashlib.sha256(original_color).hexdigest() == '93f7fa0a46dc0c58f6bb5a117da5bd146a0933a598d48361c8425a0b51f286b5'
    expected=bytearray(original);expected[67]=0x30
    summary=dict(write_attempts=0,write_successes=0,status='pending',reads={})
    handle=None

    def read(opcode,name):
        backend.set_feature(handle,read_request(opcode))
        raw=backend.get_feature(handle,6,520)
        (directory/(name+'.bin')).write_bytes(raw)
        validate_response(raw,opcode)
        summary['reads'][name]=dict(opcode=f'{opcode:02X}',sha256=hashlib.sha256(raw).hexdigest())
        return raw

    try:
        device=select_device(backend.enumerate())
        handle=backend.open(device.path)
        if not matches(backend.describe(handle,device.path)):
            raise RuntimeError('opened_identity_mismatch')
        current_config=read(0x84,'before_config')
        current_color=read(0x8A,'before_color')
        summary['before_config_expected_single']=current_config==bytes(expected)
        summary['before_color_baseline']=current_color==original_color
        if current_config != original:
            report=config_report(original,single=False)
            (directory/'write-001-config_restore.bin').write_bytes(report)
            summary['write_attempts']=1
            backend.set_feature(handle,report)
            summary['write_successes']=1
        final_config=read(0x84,'final_config')
        final_color=read(0x8A,'final_color')
        summary['config_matches_baseline']=final_config==original
        summary['color_matches_baseline']=final_color==original_color
        summary['status']='rgb_config_readback_restored' if summary['config_matches_baseline'] and summary['color_matches_baseline'] else 'readback_mismatch'
    except BaseException as error:
        summary['status']='stopped_on_error'
        summary['error']=type(error).__name__+': '+str(error)
    finally:
        if handle is not None:
            try:
                backend.close(handle);summary['handle_closed']=True
            except BaseException as error:
                summary['handle_closed']=False
                summary['close_error']=type(error).__name__+': '+str(error)
        (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(summary,indent=2))
    return summary['status']=='rgb_config_readback_restored'


if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
