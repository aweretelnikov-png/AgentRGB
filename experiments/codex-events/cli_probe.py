"""Одноразовый codex exec с пассивными hooks; постоянная конфигурация не меняется."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from hook_recorder import EVENTS

BASE=Path(__file__).resolve().parent


def hook_flags(output):
    command='python "'+(BASE/'hook_recorder.py').as_posix()+'" "'+Path(output).resolve().as_posix()+'"'
    flags=[]
    for event in sorted(EVENTS):
        # JSON string quoting is also valid for these TOML basic string values;
        # this is a subprocess argument, not a shell interpolation.
        value='[{hooks=[{type="command",command='+json.dumps(command)+',timeout=3}]}]'
        flags.extend(['-c','hooks.'+event+'='+value])
    return flags


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('scenario',choices=['normal','tools','stop','manual'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise SystemExit('Choose a fresh output file')
    folder=BASE/'_local'/'workspace'
    folder.mkdir(parents=True,exist_ok=True)
    prompt=('Reply with OK only. Do not use tools or read files.' if args.scenario in ('normal','stop') else
            'This is a safe tool lifecycle test. Execute two separate shell commands in order: '
            'first powershell -NoProfile -Command "exit 7", then powershell -NoProfile -Command "Write-Output 42". '
            'The first nonzero exit is expected. Do not read or modify any files. Finish normally after the second command.')
    env=os.environ.copy()
    env['CODEX_HOME']=str(Path(os.environ['USERPROFILE'])/'.codex')
    flags=hook_flags(output)
    if args.scenario == 'stop':
        index=next(i for i,x in enumerate(flags) if x.startswith('hooks.Stop='))
        command='python "'+(BASE/'stop_once.py').as_posix()+'" "'+output.with_suffix('.once').as_posix()+'"'
        # Второй обработчик той же группы, вместе с неизменённым регистратором.
        flags[index]=flags[index][:-3]+',{type="command",command='+json.dumps(command)+',timeout=3}]}]'
    cmd=[shutil.which('codex'),'exec','--ephemeral','--skip-git-repo-check',
         '--sandbox','read-only','--dangerously-bypass-hook-trust','--cd',str(folder),
         '-c','model_reasoning_effort="low"',*flags,prompt]
    if args.scenario == 'manual':
        prompt=('Safe approval test. Call exec_command once with cmd="Write-Output 42", '
                'sandbox_permissions="require_escalated", justification="Allow printing 42?". '
                'Do not read or modify any files. If denied, finish without retrying.')
        cmd=[shutil.which('codex'),'--no-alt-screen','--sandbox','read-only',
             '--ask-for-approval','on-request','--dangerously-bypass-hook-trust',
             '--cd',str(folder),'-c','model_reasoning_effort="low"',*flags,prompt]
        # Только пользовательский TUI: stdin/stdout не читаются регистратором.
        raise SystemExit(subprocess.call(cmd,env=env))
    # Ни модельный вывод, ни текст stderr не попадают в результаты опыта.
    process=subprocess.Popen(cmd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        code=process.wait(timeout=150)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
        print(json.dumps({'process_timeout':True}))
        return
    print(json.dumps({'process_exit_code':code,'hook_log_exists':output.exists()}))


if __name__=='__main__':
    main()
