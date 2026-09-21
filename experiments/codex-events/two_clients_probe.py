"""Два подключения только к новому тестовому App Server; чужие threads не читаются."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from app_server_probe import BASE, Probe


def main():
    env=os.environ.copy()
    env['CODEX_HOME']=str(Path(os.environ['USERPROFILE'])/'.codex')
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0))
        port=reserved.getsockname()[1]
    endpoint='ws://127.0.0.1:'+str(port)
    server=subprocess.Popen([shutil.which('codex'),'app-server','--listen',endpoint],
                            env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    clients=[]
    try:
        deadline=time.monotonic()+15
        while server.poll() is None and time.monotonic()<deadline:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('socket_unavailable')
        stamp=str(time.time_ns())
        owner=Probe(BASE/'_local'/('two-clients-owner-'+stamp+'.jsonl'),websocket_url=endpoint)
        clients.append(owner)
        observer=Probe(BASE/'_local'/('two-clients-observer-'+stamp+'.jsonl'),websocket_url=endpoint)
        clients.append(observer)
        owner.initialize()
        observer.initialize()
        thread=owner.call('thread/start',{'cwd':str(BASE/'_local'/'workspace'),'ephemeral':False,
                           'sandbox':'read-only','approvalPolicy':'on-request',
                           'approvalsReviewer':'user','experimentalRawEvents':False})['thread']['id']
        initial=owner.call('turn/start',{'threadId':thread,'effort':'low','input':[
            {'type':'text','text':'Reply with OK only. Do not use tools or read files.'}]})['turn']['id']
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            event=owner.messages.get(timeout=max(.1,deadline-time.monotonic())).get('event',{})
            if event.get('method')=='turn/completed' and event.get('turnId')==initial:
                break
        else:
            raise TimeoutError('initial_completion_missing')
        try:
            result=observer.call('thread/resume',{'threadId':thread,'excludeTurns':True})
            print(json.dumps({'resume_succeeded':True,'returned_turns_count':len(result.get('thread',{}).get('turns',[]))}),flush=True)
        except RuntimeError as exc:
            print(json.dumps({'resume_succeeded':False,'code':str(exc)}),flush=True)
        turn=owner.call('turn/start',{'threadId':thread,'effort':'low','input':[
            {'type':'text','text':'Reply with OK only. Do not use tools or read files.'}]})['turn']['id']
        for client in clients:
            deadline=time.monotonic()+(120 if client is owner else 15)
            while time.monotonic()<deadline:
                msg=client.messages.get(timeout=max(.1,deadline-time.monotonic()))
                event=msg.get('event',{})
                if event.get('method')=='turn/completed' and event.get('turnId')==turn:
                    print(json.dumps({'client':'owner' if client is owner else 'observer',
                                      'threadId':thread,'turnId':turn,'status':event.get('status')}),flush=True)
                    break
                if msg.get('closed'):
                    raise RuntimeError('server_closed')
            else:
                raise TimeoutError('completion_missing')
        owner.call('thread/archive',{'threadId':thread})
    except Exception as exc:
        print(json.dumps({'probe_error':type(exc).__name__,
                          'code':str(exc) if isinstance(exc,RuntimeError) else None}),flush=True)
        raise SystemExit(1)
    finally:
        for client in reversed(clients):
            client.close()
        server.terminate()
        server.wait(timeout=10)


if __name__=='__main__':
    main()
