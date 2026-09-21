import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import tomllib
from types import SimpleNamespace
from unittest.mock import Mock

from hook_recorder import select_fields
from app_server_probe import event_fields, Probe
from cli_probe import hook_flags

SCRIPT = Path(__file__).with_name('hook_recorder.py')


class RecorderTests(unittest.TestCase):
    def invoke(self, target, payload):
        return subprocess.run([sys.executable, str(SCRIPT), str(target)],
                              input=json.dumps(payload).encode(), capture_output=True, timeout=10)

    def test_private_fields_never_reach_jsonl(self):
        private = 'PRIVATE_SENTINEL /private/file.txt SECRET_TOKEN'
        payload = dict(hook_event_name='Stop', session_id='test-session', turn_id='test-turn',
                       permission_mode='default', stop_hook_active=False,
                       prompt=private, last_assistant_message=private, tool_input={'command': private},
                       transcript_path=private, cwd=private, tool_response=private,
                       content=private, unknown={'nested': private})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'events.jsonl'
            result = self.invoke(target, payload)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))
            raw = target.read_text()
            row = json.loads(raw)
            self.assertNotIn('PRIVATE_SENTINEL', raw)
            self.assertEqual(set(row), {'sequence','timestamp','hook_event_name','session_id',
                                        'turn_id','permission_mode','stop_hook_active'})

    def test_values_are_validated_not_copied_blindly(self):
        row = select_fields(dict(hook_event_name='PreToolUse', session_id='/private/file',
                                 turn_id={'content':'secret'}, permission_mode='secret',
                                 stop_hook_active=True, tool_name='/private/tool'))
        self.assertEqual(set(row), {'timestamp','hook_event_name','tool_type'})
        self.assertEqual(row['tool_type'], 'other')
        self.assertIsNone(select_fields({'hook_event_name':'Unrecognized'}))

    def test_errors_are_silent_and_nonblocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.invoke(tmp, {'hook_event_name':'Stop'})
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0,b'',b''))
        result = subprocess.run([sys.executable,str(SCRIPT),'unused'],input=b'{broken',capture_output=True)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))

    def test_concurrent_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'events.jsonl'
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results=list(pool.map(lambda _:self.invoke(target,{'hook_event_name':'Stop'}),range(12)))
            self.assertTrue(all(x.returncode == 0 and not x.stdout and not x.stderr for x in results))
            rows=[json.loads(x) for x in target.read_text().splitlines()]
            self.assertEqual([r['sequence'] for r in rows],list(range(1,13)))

    def test_app_server_allowlist(self):
        private='PRIVATE_SENTINEL'
        event={'method':'turn/completed','params':{'threadId':'test-thread',
               'turn':{'id':'test-turn','status':'failed','error':{'message':private},
                       'items':[{'content':private}]},'reason':private,'command':private}}
        self.assertEqual(event_fields(event),{'method':'turn/completed','threadId':'test-thread',
                                             'turnId':'test-turn','status':'failed'})
        event={'id':0,'method':'item/commandExecution/requestApproval','params':{
               'threadId':'test-thread','turnId':'test-turn','command':private,'reason':private}}
        self.assertNotIn(private,json.dumps(event_fields(event)))
        self.assertEqual(event_fields(event)['requestId'],0)
        self.assertIsNone(event_fields({'method':'item/agentMessage/delta','params':{'delta':private}}))
        row=event_fields({'method':'turn/completed','params':{'threadId':'/private/file',
                         'turn':{'id':'/private/turn','status':'completed'}}})
        self.assertEqual(row,{'method':'turn/completed','status':'completed'})

    def test_hook_flags_are_valid_toml(self):
        flags=hook_flags(Path('test output.jsonl'))
        for value in flags[1::2]:
            parsed=tomllib.loads(value)
            hooks=next(iter(parsed['hooks'].values()))
            self.assertEqual(hooks[0]['hooks'][0]['timeout'],3)

    def test_stop_once_cannot_loop(self):
        script=SCRIPT.with_name('stop_once.py')
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'once'
            def run(active):
                return subprocess.run([sys.executable,str(script),str(marker)],
                    input=json.dumps({'hook_event_name':'Stop','stop_hook_active':active}).encode(),
                    capture_output=True,timeout=10)
            self.assertEqual(run(True).stdout,b'')
            first=run(False)
            self.assertEqual(json.loads(first.stdout)['decision'],'block')
            self.assertEqual(run(False).stdout,b'')
            self.assertEqual(run(True).stdout,b'')

    def test_cleanup_never_interrupts_observed_foreign_turn(self):
        probe=Probe.__new__(Probe)
        probe.owned_threads={'own'}
        probe.active_turns={'own':'own-turn','observed':'foreign-turn'}
        probe.process=SimpleNamespace(stdin=Mock(),poll=Mock(return_value=None),wait=Mock())
        probe.reader=Mock()
        def cancel(method,params):
            self.assertEqual(method,'turn/interrupt')
            self.assertEqual(params,{'threadId':'own','turnId':'own-turn'})
            probe.active_turns.pop('own')
        probe.call=Mock(side_effect=cancel)
        probe.close()
        probe.call.assert_called_once()
        probe.process.stdin.close.assert_called_once()
        self.assertEqual(probe.active_turns,{'observed':'foreign-turn'})

    def test_published_evidence_has_only_technical_fields(self):
        allowed={'sequence','timestamp','hook_event_name','session_id','turn_id',
                 'permission_mode','stop_hook_active','tool_type','method','threadId',
                 'turnId','requestId','status','activeFlags','item_type','willRetry'}
        files=list(SCRIPT.with_name('evidence').glob('*.jsonl'))
        self.assertTrue(files)
        for path in files:
            rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['sequence'] for r in rows],list(range(1,len(rows)+1)),path.name)
            for row in rows:
                self.assertLessEqual(set(row),allowed,path.name)
                for key in ('session_id','turn_id','threadId','turnId'):
                    if key in row:
                        self.assertRegex(row[key],r'^[A-Za-z0-9_-]{1,128}$')


if __name__ == '__main__':
    unittest.main()
