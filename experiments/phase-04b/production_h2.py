"""Production H2: один Core/handle, фиксированные шаги по loopback без stdin.

Запускать физический serve только после отдельного разрешения на H2.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import socket
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

from persistent_output import AulaF75Output, matches, validate_response
from agentrgb.outputs.windows_hid import WindowsHid
from agentrgb.protocol import validate
from agentrgb.state import Core
from run import save_get_diagnostic


STEPS = (("run_started", "0000FF"), ("run_waiting", "FFFF00"),
         ("run_resumed", "0000FF"), ("run_ended", "00FF00"))


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class AuditedHid:
    """Экспериментальный write budget и gate поверх настоящего HID backend."""
    def __init__(self, backend, directory):
        self.backend = backend
        self.directory = Path(directory)
        self.opcode = None
        self.identity = None
        self.initial = {}
        self.last_raw = {}
        self.read_count = 0
        self.writes = []

    def enumerate(self):
        return self.backend.enumerate()

    def open(self, path):
        return self.backend.open(path)

    def describe(self, handle, path):
        self.identity = self.backend.describe(handle, path)
        return self.identity

    def close(self, handle):
        return self.backend.close(handle)

    def set_feature(self, handle, report):
        opcode = report[1]
        if opcode not in (0x82, 0x84, 0x8A, 0x04, 0x0A):
            raise RuntimeError("forbidden_opcode")
        self.opcode = opcode
        if opcode in (0x04, 0x0A):
            if len(self.writes) >= 7:
                raise RuntimeError("h2_write_budget_exhausted")
            if not self._baseline_ready():
                raise RuntimeError("h2_baseline_gate_failed")
            number = len(self.writes) + 1
            (self.directory / f"write-{number:02d}.bin").write_bytes(report)
            row = dict(number=number, opcode=f"{opcode:02X}",
                       rgb=report[29:32].hex().upper() if opcode == 0x0A else None,
                       sha256=hashlib.sha256(report).hexdigest(), success=False)
            self.writes.append(row)  # Attempt recorded before SetFeature.
            save_json(self.directory / "writes.json", self.writes)
            self.backend.set_feature(handle, report)
            row["success"] = True
            save_json(self.directory / "writes.json", self.writes)
        else:
            self.backend.set_feature(handle, report)

    def get_feature(self, handle, report_id, length):
        raw = self.backend.get_feature(handle, report_id, length)
        self.read_count += 1
        (self.directory / f"read-{self.read_count:02d}-{self.opcode:02X}.bin").write_bytes(raw)
        self.last_raw[self.opcode] = raw
        if not self.writes and self.opcode in (0x82, 0x84, 0x8A):
            self.initial[self.opcode] = raw
            if self.opcode == 0x8A and not self._baseline_ready():
                raise RuntimeError("h2_baseline_gate_failed")
        return raw

    def _baseline_ready(self):
        if set(self.initial) != {0x82, 0x84, 0x8A} or self.identity is None or not matches(self.identity):
            return False
        try:
            model, config, color = (validate_response(self.initial[opcode], opcode)
                                    for opcode in (0x82, 0x84, 0x8A))
        except Exception:
            return False
        return (model[8] == 3 and model[12:14] == b"\x00\xcd"
                and config[17:19] == b"\x00\x01"
                and config[66:68] == b"\x09\x37"
                and color[29:32] == b"\xff\x00\x00")


class H2Session:
    def __init__(self, backend, directory):
        self.directory = Path(directory)
        self.hid = AuditedHid(backend, directory)
        self.output = AulaF75Output(self.hid)
        # Фиксированные часы удерживают completed для ручной визуальной оценки.
        # Core и production-длительность сигнала не изменяются.
        self.core = Core(self.output, clock=lambda: 0.0)
        self.run_id = str(uuid4())
        self.step = 0
        self.closed = False
        self.summary = dict(status="ready", step=0, writes=[], visual=[],
                            fresh_baseline=None, restore_status="not_started")
        self._save()

    def _save(self):
        self.summary["writes"] = list(self.hid.writes)
        save_json(self.directory / "summary.json", self.summary)

    def _event(self, kind):
        metadata = {"outcome": "completed"} if kind == "run_ended" else {}
        return validate(dict(schema_version=1, source="pi", source_instance_id="synthetic-04b-h2",
                             session_id="synthetic-04b-h2", run_id=self.run_id,
                             event_id=str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(),
                             kind=kind, metadata=metadata))

    def next(self):
        if (self.closed or self.step >= len(STEPS)
                or self.summary["status"] not in ("ready", "visual_confirmed")):
            raise RuntimeError("h2_step_unavailable")
        kind, expected = STEPS[self.step]
        try:
            self.core.apply(self._event(kind))
        except Exception:
            self.summary["status"] = "stopped_on_core_error"
            self.finish(visual=False)
            raise
        if self.output.last_error:
            self.summary["status"] = "stopped_on_output_error"
            self.finish(visual=False)
            raise RuntimeError("h2_output_error")
        actual = self.hid.last_raw[0x8A][29:32].hex().upper()
        if actual != expected:
            self.summary["status"] = "stopped_on_readback_mismatch"
            self.finish(visual=False)
            raise RuntimeError("h2_readback_mismatch")
        self.step += 1
        self.summary["step"] = self.step
        self.summary["fresh_baseline"] = self.hid._baseline_ready()
        self.summary["status"] = "awaiting_visual"
        self._save()
        return dict(step=self.step, state=kind, rgb=actual,
                    changing_writes=len(self.hid.writes),
                    fresh_baseline=self.summary["fresh_baseline"])

    def confirm(self, expected_step):
        if self.closed or self.summary["status"] != "awaiting_visual" or expected_step != self.step:
            raise RuntimeError("h2_confirmation_out_of_order")
        self.summary["visual"].append(dict(step=self.step, confirmed=True))
        self.summary["status"] = "visual_confirmed"
        self._save()
        return dict(step=self.step, visual_confirmed=True)

    def finish(self, *, visual):
        if self.closed:
            return self.summary
        self.closed = True
        try:
            self.core.close()  # release even while completed test clock is held.
        except Exception as error:
            self.summary["cleanup_error"] = type(error).__name__
        finally:
            self.output.release()
        self.summary["restore_status"] = self.output.restore_status
        self.summary["final_config_matches_baseline"] = (
            self.hid.last_raw.get(0x84) == self.hid.initial.get(0x84))
        self.summary["final_color_matches_baseline"] = (
            self.hid.last_raw.get(0x8A) == self.hid.initial.get(0x8A))
        self.summary["status"] = ("readback_restored_visual_pending" if visual and self.step == 4
                                  and self.output.restore_status == "readback_confirmed"
                                  and self.summary["final_config_matches_baseline"]
                                  and self.summary["final_color_matches_baseline"]
                                  else "stopped_restored_or_unverified")
        self._save()
        return self.summary


class ControlServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, session, token):
        super().__init__(("127.0.0.1", 0), ControlHandler, bind_and_activate=False)
        self.session, self.token, self.done = session, token, False
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.server_bind()
        self.server_activate()


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *unused):
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256:
                raise ValueError("invalid_length")
            request = json.loads(self.rfile.read(length))
            if request.get("token") != self.server.token:
                raise ValueError("invalid_token")
            action = request.get("action")
            if action == "next":
                if self.server.session.summary["status"] not in ("ready", "visual_confirmed"):
                    raise ValueError("visual_confirmation_required")
                result = self.server.session.next()
            elif action == "confirm":
                result = self.server.session.confirm(request.get("step"))
            elif action in ("abort", "finish"):
                if action == "finish" and (self.server.session.step != 4
                                           or self.server.session.summary["status"] != "visual_confirmed"):
                    raise ValueError("final_visual_confirmation_required")
                result = self.server.session.finish(visual=action == "finish")
                self.server.done = True
            elif action == "status":
                result = self.server.session.summary
            else:
                raise ValueError("invalid_action")
            status = 200
        except Exception as error:
            if self.server.session.closed:
                self.server.done = True
            result = dict(error=type(error).__name__ + ": " + str(error),
                          status=self.server.session.summary["status"])
            status = 400
        raw = json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve():
    directory = Path(__file__).parent / "results" / ("production-h2-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(parents=True, exist_ok=False)
    native = WindowsHid(diagnostic_sink=lambda record: save_get_diagnostic(directory, record))
    session = H2Session(native, directory)
    token = secrets.token_hex(16)
    with ControlServer(session, token) as server:
        print(json.dumps(dict(port=server.server_port, token=token, directory=str(directory))), flush=True)
        try:
            while not server.done:
                server.handle_request()
        finally:
            session.finish(visual=False)


def client(action, port, token, step):
    body = json.dumps(dict(action=action, token=token, step=step)).encode("utf-8")
    request = Request(f"http://127.0.0.1:{port}/", body, {"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        print(response.read().decode("utf-8"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "next", "confirm", "abort", "finish", "status"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--token")
    parser.add_argument("--step", type=int)
    args = parser.parse_args()
    if args.action == "serve":
        if args.port or args.token or args.step:
            parser.error("serve accepts no client options")
        serve()
    else:
        if not args.port or not args.token:
            parser.error("client requires --port and --token")
        client(args.action, args.port, args.token, args.step)


if __name__ == "__main__":
    sys.exit(main())
