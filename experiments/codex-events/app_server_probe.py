"""Минимальный опыт App Server; не клиент AgentRGB и не выбор его транспорта.

Входной поток немедленно проецируется на технические поля. Ответы модели,
аргументы инструментов, ошибки с текстом и stderr не записываются и не выводятся.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from hook_recorder import ID

BASE = Path(__file__).resolve().parent
METHODS = {'thread/started', 'thread/closed', 'thread/status/changed', 'turn/started',
           'turn/completed', 'serverRequest/resolved', 'item/commandExecution/requestApproval',
           'item/fileChange/requestApproval', 'item/permissions/requestApproval',
           'item/tool/requestUserInput', 'hook/started', 'hook/completed',
           'item/started', 'item/completed', 'error'}


def event_fields(message):
    method = message.get('method')
    if method not in METHODS:
        return None
    p = message.get('params', {})
    row = {'method': method}
    def put_id(name, value):
        if (name == 'requestId' and type(value) is int or
                isinstance(value,str) and ID.fullmatch(value)):
            row[name]=value
    for name in ('threadId','turnId','requestId'):
        put_id(name,p.get(name))
    if 'id' in message:
        put_id('requestId',message['id'])
    if method == 'thread/started':
        put_id('threadId',p['thread']['id'])
    if method.startswith('turn/'):
        put_id('turnId',p['turn']['id'])
        status=p['turn'].get('status')
        if status in ('inProgress','completed','interrupted','failed'):
            row['status']=status
    if method == 'thread/status/changed':
        status=p.get('status',{})
        if status.get('type') in ('active','idle','notLoaded','systemError'):
            row['status']=status['type']
            row['activeFlags']=[x for x in status.get('activeFlags',[]) if x in ('waitingOnApproval','waitingOnUserInput')]
    if method.startswith('hook/'):
        r=p.get('run',{})
        # Enum only, never hook entries/command/sourcePath.
        if r.get('eventName') in ('sessionStart','sessionEnd','userPromptSubmit','preToolUse',
                                  'postToolUse','permissionRequest','stop','interrupt','preCompact','postCompact'):
            row['hook_event_name']=r['eventName']
        if r.get('status') in ('running','completed','failed','blocked','stopped'):
            row['status']=r['status']
    if method.startswith('item/') and method in ('item/started','item/completed'):
        kind=p.get('item',{}).get('type')
        if kind not in ('commandExecution','fileChange'):
            return None
        row['item_type']=kind
        status=p.get('item',{}).get('status')
        if status in ('inProgress','completed','failed','declined'):
            row['status']=status
    if method == 'error':
        row['willRetry']=p.get('willRetry') if type(p.get('willRetry')) is bool else None
    return row


class Probe:
    def __init__(self, output, overrides=(), websocket_url=None):
        self.output=Path(output)
        self.output.parent.mkdir(parents=True,exist_ok=True)
        self.output.touch(exist_ok=False)
        self.sequence=0
        self.serial=0
        self.messages=queue.Queue()
        self.responses=queue.Queue()
        self.owned_threads=set()
        self.active_turns={}
        env=os.environ.copy()
        # Codex в Windows sandbox иначе выбирает профиль sandbox-пользователя.
        # Auth открывает только сам Codex; скрипт его не читает и не копирует.
        env['CODEX_HOME']=str(Path(os.environ['USERPROFILE'])/'.codex')
        cmd=[shutil.which('codex'),'app-server']
        if websocket_url:
            cmd=[shutil.which('node'),str(BASE/'websocket_proxy.mjs'),websocket_url]
        for override in overrides:
            cmd.extend(['-c',override])
        self.process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env)
        self.reader=threading.Thread(target=self.read,daemon=True)
        self.reader.start()

    def read(self):
        try:
            for line in self.process.stdout:
                try:
                    message=json.loads(line)
                    row=event_fields(message)
                    if row:
                        if row['method']=='turn/started':
                            self.active_turns[row['threadId']]=row['turnId']
                        elif row['method']=='turn/completed':
                            if self.active_turns.get(row['threadId'])==row['turnId']:
                                self.active_turns.pop(row['threadId'],None)
                        self.sequence+=1
                        row={'sequence':self.sequence,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),**row}
                        with self.output.open('a',encoding='utf-8') as f:
                            f.write(json.dumps(row)+'\n')
                    if 'id' in message and 'method' not in message:
                        self.responses.put(message)
                    elif row:
                        self.messages.put({'event':row})
                except (ValueError,KeyError,TypeError):
                    continue
        finally:
            self.messages.put({'closed':True})
            self.responses.put({'closed':True})

    def send(self,message):
        self.process.stdin.write(json.dumps(message)+'\n')
        self.process.stdin.flush()

    def call(self,method,params):
        self.serial+=1
        request_id=self.serial
        self.send({'id':request_id,'method':method,'params':params})
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            message=self.responses.get(timeout=max(.1,deadline-time.monotonic()))
            if message.get('closed'):
                raise RuntimeError('server_closed')
            if message.get('id')==request_id:
                if 'error' in message:
                    raise RuntimeError('rpc_error_'+str(message['error'].get('code')))
                result=message.get('result',{})
                if method=='thread/start':
                    self.owned_threads.add(result['thread']['id'])
                return result
        raise TimeoutError('rpc_timeout')

    def initialize(self):
        result=self.call('initialize',{'clientInfo':{'name':'agentrgb_phase03','version':'0.1'},
                         'capabilities':{'experimentalApi':True}})
        self.send({'method':'initialized','params':{}})
        return {k:result[k] for k in ('userAgent',) if k in result}

    def close(self):
        # Отмена только собственных тестовых запусков, никогда чужих подписок.
        for thread in self.owned_threads:
            turn=self.active_turns.get(thread)
            if turn and self.process.poll() is None:
                try:
                    self.call('turn/interrupt',{'threadId':thread,'turnId':turn})
                except (RuntimeError,OSError,queue.Empty):
                    pass
        deadline=time.monotonic()+3
        while any(t in self.active_turns for t in self.owned_threads) and time.monotonic()<deadline:
            time.sleep(.01)
        self.process.stdin.close()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)


def inspect(probe):
    cfg=probe.call('config/read',{'cwd':str(Path.cwd()),'includeLayers':True})
    hooks=probe.call('hooks/list',{'cwds':[str(Path.cwd())]})
    allowed=('approval_policy','approvals_reviewer','sandbox_mode','model','model_provider')
    result={'effective_config':{k:cfg.get('config',{}).get(k) for k in allowed},
            'layers':[{'type':x.get('name',{}).get('type'),'disabled':bool(x.get('disabledReason'))}
                      for x in (cfg.get('layers') or [])],
            'hooks':[], 'hook_errors':0,'hook_warnings':0}
    for entry in hooks.get('data',[]):
        result['hook_errors']+=len(entry.get('errors',[]))
        result['hook_warnings']+=len(entry.get('warnings',[]))
        for hook in entry.get('hooks',[]):
            result['hooks'].append({k:hook.get(k) for k in
                                   ('eventName','source','handlerType','enabled','trustStatus','isManaged')})
    return result


def run_normal(probe, scenario='normal', decision_file=None):
    folder=BASE/'_local'/'workspace'
    folder.mkdir(parents=True,exist_ok=True)
    thread=probe.call('thread/start',{'cwd':str(folder),'ephemeral':True,
                       'sandbox':'read-only','approvalPolicy':'on-request',
                       'approvalsReviewer':'user','experimentalRawEvents':False})['thread']['id']
    results=[]
    for i in range(2 if scenario == 'normal' else 1):
        prompt='Reply with OK only. Do not use tools or read files.'
        if scenario == 'tools':
            prompt=('Safe tool lifecycle test. Execute two separate shell commands in order: '
                    'first powershell -NoProfile -Command "exit 7", then '
                    'powershell -NoProfile -Command "Write-Output 42". '
                    'The first nonzero exit is expected. Do not read or modify any files. '
                    'Finish normally after the second command. Do not request escalation.')
        if scenario == 'approval':
            prompt=('Safe approval lifecycle test. Call exec_command exactly once with '
                    'cmd="Write-Output 42", sandbox_permissions="require_escalated", '
                    'justification="Allow printing the number 42 for the AgentRGB event test?". '
                    'The command has no side effects. Do not read or modify any files. '
                    'If the user denies, finish without retrying. Do not use other tools.')
        turn=probe.call('turn/start',{'threadId':thread,
                    'input':[{'type':'text','text':prompt}],
                    'effort':'low'})['turn']['id']
        if scenario == 'interrupt':
            probe.call('turn/interrupt',{'threadId':thread,'turnId':turn})
        deadline=time.monotonic()+(300 if scenario == 'approval' else 120)
        while time.monotonic()<deadline:
            msg=probe.messages.get(timeout=max(.1,deadline-time.monotonic()))
            event=msg.get('event',{})
            if event.get('method')=='item/commandExecution/requestApproval':
                print(json.dumps({'pending_approval':True,'threadId':thread,'turnId':turn,
                                  'requestId':event['requestId']}),flush=True)
                while time.monotonic()<deadline and not decision_file.exists():
                    time.sleep(.2)
                if not decision_file.exists():
                    probe.call('turn/interrupt',{'threadId':thread,'turnId':turn})
                    raise TimeoutError('approval_unanswered')
                decision=decision_file.read_text(encoding='utf-8').strip()
                if decision == 'interrupt':
                    probe.call('turn/interrupt',{'threadId':thread,'turnId':turn})
                elif decision in ('accept','decline'):
                    probe.send({'id':event['requestId'],'result':{'decision':decision}})
                else:
                    probe.call('turn/interrupt',{'threadId':thread,'turnId':turn})
                    raise ValueError('invalid_decision')
            if event.get('method')=='turn/completed' and event.get('turnId')==turn:
                results.append({'threadId':thread,'turnId':turn,'status':event.get('status')})
                break
            if msg.get('closed'):
                raise RuntimeError('server_closed')
        else:
            probe.call('turn/interrupt',{'threadId':thread,'turnId':turn})
            raise TimeoutError('turn_timeout')
    return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['inspect','normal','interrupt','approval','tools'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--decision-file',type=Path)
    args=parser.parse_args()
    if args.mode=='approval' and (args.decision_file is None or args.decision_file.exists()):
        parser.error('approval requires a new, nonexistent --decision-file')
    probe=Probe(args.output)
    try:
        probe.initialize()
        result=inspect(probe) if args.mode=='inspect' else run_normal(probe,args.mode,args.decision_file)
        print(json.dumps(result))
    except Exception as exc:
        # Исключения транспортных библиотек могут содержать приватные строки.
        print(json.dumps({'probe_error':type(exc).__name__}))
        raise SystemExit(1)
    finally:
        probe.close()


if __name__=='__main__':
    main()
