"""Реальный Pi package → fake Core; Windows, установленный Pi и editable AgentRGB.

python experiments/phase-05b/smoke.py installed
python experiments/phase-05b/smoke.py once
Никакие тексты модели не сохраняются; временный launcher запрещает hardware.
"""
import json
import http.client
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from pip._vendor.distlib.scripts import ScriptMaker

ROOT = Path(__file__).resolve().parents[2]

# Используется только временным launcher; не меняет production output default.
LAUNCHER = '''
import json, os, sys
from pathlib import Path
from agentrgb import cli, server
from agentrgb.outputs import windows_hid, aula_f75
def forbidden(*args, **kwargs):
    raise AssertionError("hardware forbidden in smoke")
windows_hid.WindowsHid = forbidden
aula_f75.AulaF75Output = forbidden
assert sys.argv[1:] == ["start", "--output", "aula-f75"]
sys.argv[1:] = ["start", "--output", "fake"]
def record(kind, **fields):
    with Path(os.environ["AGENTRGB_SMOKE_JOURNAL"]).open("a", encoding="utf-8") as target:
        target.write(json.dumps(dict(kind=kind, pid=os.getpid(), **fields)) + "\\n")
OriginalCore = server.Core
class AuditedCore(OriginalCore):
    def apply(self, event):
        result = super().apply(event)
        record("event", event=event.kind, outcome=event.outcome, result=result)
        return result
    def close(self):
        super().close()
        record("core_closed")
server.Core = AuditedCore
record("spawned", output="fake", hardware_blocked=True)
try:
    code = cli.main()
finally:
    record("exited")
raise SystemExit(code)
'''


def verify(pi, journal, port, mode, forced=False):
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []
    normalized = [row for row in rows if row["kind"] == "event"]
    assert not forced and pi.returncode == 0, "Pi failed graceful shutdown"
    assert len([row for row in rows if row["kind"] == "spawned"]) == 1, rows
    assert [row["event"] for row in normalized] == ["run_started", "run_ended"], normalized
    assert all(row["result"] == "applied" for row in normalized), normalized
    assert normalized[-1]["outcome"] == "completed", normalized
    assert any(row["kind"] == "core_closed" for row in rows), rows
    assert rows[-1]["kind"] == "exited", rows
    with socket.socket() as probe:
        probe.settimeout(0.3)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    print(json.dumps(dict(mode=mode, pi_pid=pi.pid, core_pid=rows[0]["pid"], events=[r["event"] for r in normalized],
                          outcome=normalized[-1]["outcome"], core_closed=True, pi_exit=pi.returncode,
                          hardware_writes=0, hardware_blocked=True, forced_termination=forced), indent=2))


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in ("installed", "once", "tui"):
        raise SystemExit("Usage: smoke.py installed|once|tui")
    if os.name != "nt":
        raise SystemExit("Windows launcher smoke only")
    # Только проверка наличия process-scoped proxy, без записи адреса в repo.
    if not os.environ.get("HTTP_PROXY") or not os.environ.get("HTTPS_PROXY"):
        raise SystemExit("Set HTTP_PROXY and HTTPS_PROXY for this test process")
    pi_cli = Path(os.environ["APPDATA"]) / "npm/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="agentrgb-05b-") as temporary:
        directory = Path(temporary)
        maker = ScriptMaker(None, str(directory))
        maker.executable = sys.executable
        maker.variants = {""}
        maker.script_template = LAUNCHER
        maker.make("agentrgb = agentrgb.cli:main")
        journal = directory / "lifecycle.jsonl"
        env = dict(os.environ, AGENTRGB_PORT=str(port), AGENTRGB_SMOKE_JOURNAL=str(journal),
                   PATH=str(directory) + os.pathsep + os.environ.get("PATH", ""),
                   NO_PROXY="localhost,127.0.0.1,::1")
        env.pop("PYTHONPATH", None)
        args = [shutil.which("node"), str(pi_cli), "--mode", "rpc", "--no-session", "--no-tools",
                "--no-skills", "--no-themes", "--no-prompt-templates", "--no-context-files", "--no-approve",
                "--thinking", "off", "--system-prompt", "Reply briefly. Do not use tools or access files."]
        if mode == "once":
            args += ["--no-extensions", "-e", str(ROOT / "integrations/pi")]
        if mode == "tui":
            del args[2:4]  # Обычный Pi TUI, без --mode и без -e.
            print("Fake-only Pi: send 'Reply OK without using tools.', wait for completion, then /quit.", flush=True)
            pi = subprocess.Popen(args, cwd=directory, env=env)
            try:
                pi.wait(timeout=120)
            finally:
                if pi.poll() is None:
                    pi.kill()
                    pi.wait(timeout=5)
            verify(pi, journal, port, mode)
            return
        pi = subprocess.Popen(args, cwd=directory, env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        events = queue.Queue()
        seen = set()
        errors = set()
        def read_events():
            for line in pi.stdout:
                try:
                    row = json.loads(line)
                    events.put(row.get("type"))  # Не сохранять сообщения модели/инструментов.
                    if row.get("type") == "response" and row.get("success") is False:
                        events.put("command_failed")
                except ValueError:
                    events.put("invalid_json")
        threading.Thread(target=read_events, daemon=True).start()
        def drain_errors():
            for line in pi.stderr:
                for code in ("EPERM", "EACCES", "ENOENT"):
                    if code in line:
                        errors.add(code)
        threading.Thread(target=drain_errors, daemon=True).start()
        forced = False
        try:
            # Не отправлять prompt во время startup: события до ready намеренно no-op.
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
                try:
                    connection.request("GET", "/health")
                    if json.loads(connection.getresponse().read()).get("service") == "agentrgb":
                        break
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                time.sleep(0.1)
            else:
                raise RuntimeError("Core did not become healthy")
            time.sleep(0.4)  # Оставить extension один polling interval до первого prompt.
            pi.stdin.write(json.dumps({"id": "smoke", "type": "prompt", "message": "Reply OK without using tools."}) + "\n")
            pi.stdin.flush()
            deadline = time.monotonic() + 90
            settled = False
            while time.monotonic() < deadline and pi.poll() is None:
                try:
                    kind = events.get(timeout=0.2)
                    seen.add(kind)
                    if kind == "command_failed":
                        break
                    if kind == "agent_settled":
                        settled = True
                        break
                except queue.Empty:
                    pass
            if not settled:
                print(json.dumps(dict(events_seen=sorted(seen), errors=sorted(errors),
                                      core_started=journal.exists(), pi_exit=pi.poll())))
                raise RuntimeError("Pi did not settle within deadline")
            time.sleep(0.4)  # Дать best-effort final event закончить HTTP-запрос.
            pi.stdin.close()  # Документированный штатный RPC shutdown.
            pi.wait(timeout=12)
        finally:
            if pi.poll() is None:
                forced = True
                pi.kill()
                pi.wait(timeout=5)
            for stream in (pi.stdin, pi.stdout, pi.stderr):
                stream.close()
        verify(pi, journal, port, mode, forced)


if __name__ == "__main__":
    main()
