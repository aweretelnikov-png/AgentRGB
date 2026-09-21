"""Разрешённый пользователем опыт 03H. Не подключён к постоянной конфигурации."""
import json
from pathlib import Path
import sys


def main():
    try:
        payload=json.load(sys.stdin)
        if payload.get('hook_event_name')!='Stop' or payload.get('stop_hook_active') is not False:
            return
        # Маркер общий для всего тестового процесса: продолжение не повторится,
        # даже если Codex изменит turn_id или не выставит stop_hook_active.
        marker=Path(sys.argv[1])
        with marker.open('x',encoding='ascii') as f:
            f.write('used')
        print(json.dumps({'decision':'block','reason':'Reply with OK only. Do not use tools or read files.'}))
    except Exception:
        pass


if __name__=='__main__':
    main()
