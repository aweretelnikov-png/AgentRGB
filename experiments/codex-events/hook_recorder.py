"""Пассивный Windows-регистратор. Пустой stdout, exit 0 даже при ошибке записи."""
import datetime
import json
import os
from pathlib import Path
import re
import sys
import time

EVENTS = frozenset(('SessionStart', 'SessionEnd', 'UserPromptSubmit', 'PreToolUse',
                    'PostToolUse', 'PermissionRequest', 'Stop', 'Interrupt',
                    'PreCompact', 'PostCompact'))
MODES = frozenset(('default', 'acceptEdits', 'plan', 'dontAsk', 'bypassPermissions'))
TOOLS = frozenset(('Bash', 'apply_patch', 'exec_command', 'write_stdin',
                   'shell', 'shell_command', 'request_permissions', 'request_user_input'))
ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


def select_fields(payload):
    if not isinstance(payload, dict) or payload.get('hook_event_name') not in EVENTS:
        return None
    result = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'hook_event_name': payload['hook_event_name']}
    for name in ('session_id', 'turn_id'):
        value = payload.get(name)
        if isinstance(value, str) and ID.fullmatch(value):
            result[name] = value
    mode = payload.get('permission_mode')
    if isinstance(mode, str) and mode in MODES:
        result['permission_mode'] = mode
    if payload['hook_event_name'] == 'Stop' and type(payload.get('stop_hook_active')) is bool:
        result['stop_hook_active'] = payload['stop_hook_active']
    tool = payload.get('tool_name')
    if isinstance(tool, str):
        result['tool_type'] = tool if tool in TOOLS else 'other'
    return result


def append_record(path, record):
    # Отдельный lock защищает sequence между одновременно работающими hooks.
    # Ограниченное ожидание: потеря записи допустима, блокировка Codex — нет.
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        deadline = time.monotonic() + 0.25
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.01)
        try:
            sequence = 1
            if path.exists():
                with path.open('rb') as current:
                    current.seek(max(0, path.stat().st_size - 4096))
                    lines = current.read().splitlines()
                if lines:
                    sequence = json.loads(lines[-1])['sequence'] + 1
            with path.open('a', encoding='utf-8', newline='\n') as output:
                output.write(json.dumps({'sequence': sequence, **record}, ensure_ascii=True) + '\n')
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    try:
        # Не сохранять исходный stdin даже при ошибке JSON.
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            return
        record = select_fields(json.loads(raw))
        if record is not None and len(sys.argv) == 2:
            append_record(sys.argv[1], record)
    except Exception:
        pass


if __name__ == '__main__':
    main()
