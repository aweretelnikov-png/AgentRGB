"""CLI и localhost health без физических устройств."""
from contextlib import redirect_stderr, redirect_stdout
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import socket
import threading
import unittest
from unittest.mock import patch

from agentrgb import cli, server
from test_core import RecordingOutput


class CliTests(unittest.TestCase):
    def setUp(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"AGENTRGB_PORT": "8765"}).start()
        self.hid = patch("agentrgb.outputs.windows_hid.WindowsHid").start()
        self.hid.side_effect = AssertionError("physical HID must not be opened")
        patch.object(cli, "port_available", return_value=True).start()

    def call(self, args):
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return cli.main(args)

    def test_help_exits_successfully_without_hid(self):
        for args in (["--help"], ["start", "--help"], ["status", "--help"], ["doctor", "--help"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.call(args)
            self.assertEqual(raised.exception.code, 0)
        for command in ("start", "status", "doctor"):
            self.assertIn(command, self.stdout.getvalue())
        self.hid.assert_not_called()

    def test_invalid_arguments_exit_two(self):
        for args in ([], ["unknown"], ["start", "--output", "unknown"],
                     ["status", "--output", "fake"], ["doctor", "--unknown"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.call(args)
            self.assertEqual(raised.exception.code, 2)

    def test_invalid_environment_port_exit_two(self):
        for command in ("start", "status", "doctor"):
            for port in ("0", "65536", "bad"):
                with self.subTest(command=command, port=port), patch.dict(os.environ, {"AGENTRGB_PORT": port}):
                    with self.assertRaises(SystemExit) as raised:
                        self.call([command])
                    self.assertEqual(raised.exception.code, 2)

    def test_start_delegates_to_existing_server(self):
        for flags, output in (([], "fake"), (["--output", "fake"], "fake"),
                              (["--output", "aula-f75"], "aula-f75")):
            with self.subTest(flags=flags), patch.object(server, "main") as run:
                self.assertEqual(self.call(["start", *flags]), 0)
                run.assert_called_once_with(["--output", output])
        self.hid.assert_not_called()

    def test_existing_server_defaults_to_fake_and_supports_legacy_argv(self):
        with patch.object(server, "EventServer") as event_server, patch.object(server, "FakeOutput") as fake:
            with patch("sys.argv", ["agentrgb.server"]):
                server.main()
            fake.assert_called_once_with()
            self.assertIs(event_server.call_args.args[1].output, fake.return_value)
            self.assertEqual(event_server.call_args.args[0], 8765)
        self.hid.assert_not_called()

    def test_existing_server_selects_explicit_aula_output(self):
        with patch.object(server, "EventServer") as event_server:
            with patch("agentrgb.outputs.aula_f75.AulaF75Output") as aula:
                server.main(["--output", "aula-f75"])
                aula.assert_called_once_with()
                self.assertIs(event_server.call_args.args[1].output, aula.return_value)

    def test_start_operational_failure_exit_one_without_private_error(self):
        with patch.object(server, "main", side_effect=OSError("PRIVATE_PATH")):
            self.assertEqual(self.call(["start"]), 1)
        self.assertIn("start failed", self.stderr.getvalue())
        self.assertNotIn("PRIVATE_PATH", self.stderr.getvalue())

    def test_doctor_stopped_core_is_not_a_failure(self):
        with patch.object(cli, "version", return_value="0.1.0.dev0"):
            with patch.object(cli, "core_status", return_value="not running"):
                with patch("agentrgb.outputs.aula_f75_diagnostics.check_f75", return_value=0) as check:
                    self.assertEqual(self.call(["doctor"]), 0)
                    check.assert_called_once_with()
        for line in ("Python:", "AgentRGB: 0.1.0.dev0", "Production modules: ok",
                     "AgentRGB Core: not running", "Port 8765: available"):
            self.assertIn(line, self.stdout.getvalue())

    def test_doctor_core_and_device_exit_codes(self):
        for status, device, expected in (("running", 0, 0), ("unavailable", 0, 1),
                                         ("running", 1, 1), ("not running", 1, 1)):
            with self.subTest(status=status, device=device), patch.object(cli, "version", return_value="0.1.0.dev0"):
                with patch.object(cli, "core_status", return_value=status):
                    with patch("agentrgb.outputs.aula_f75_diagnostics.check_f75", return_value=device):
                        self.assertEqual(self.call(["doctor"]), expected)

    def test_doctor_failed_import_exit_one_without_hid_or_private_error(self):
        with patch.object(cli.importlib, "import_module", side_effect=ImportError("PRIVATE_PATH")):
            self.assertEqual(self.call(["doctor"]), 1)
        self.assertIn("Production modules: import failed", self.stdout.getvalue())
        self.assertNotIn("PRIVATE_PATH", self.stdout.getvalue() + self.stderr.getvalue())
        self.hid.assert_not_called()

    def test_doctor_missing_installation_exit_one(self):
        with patch.object(cli, "version", side_effect=cli.PackageNotFoundError):
            with patch.object(cli, "core_status", return_value="not running"):
                with patch("agentrgb.outputs.aula_f75_diagnostics.check_f75", return_value=0):
                    self.assertEqual(self.call(["doctor"]), 1)
        self.assertIn("AgentRGB: not installed", self.stdout.getvalue())


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.output = RecordingOutput()
        self.server = server.EventServer(0, server.Core(self.output))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_health_is_read_only_and_has_no_user_data(self):
        for path, status, body in (("/health", 200, {"status": "ok", "service": "agentrgb"}),
                                   ("/unknown", 404, {"status": "not_found"}),
                                   ("/v1/events", 404, {"status": "not_found"})):
            with self.subTest(path=path):
                connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.getheader("Content-Type"), "application/json")
                    self.assertEqual(json.loads(response.read()), body)
                finally:
                    connection.close()
        self.assertEqual(self.output.commands, [])
        self.assertEqual(self.server.core.runs, {})
        self.assertEqual(self.server.core.seen, {})

    def test_status_live_core_uses_custom_port_without_hid_or_proxy(self):
        stdout = io.StringIO()
        environment = {"AGENTRGB_PORT": str(self.server.server_port),
                       "HTTP_PROXY": "http://invalid.invalid:1", "HTTPS_PROXY": "http://invalid.invalid:1",
                       "NO_PROXY": ""}
        with patch.dict(os.environ, environment), redirect_stdout(stdout):
            with patch("agentrgb.outputs.windows_hid.WindowsHid") as hid:
                self.assertEqual(cli.main(["status"]), 0)
                hid.assert_not_called()
        self.assertIn("AgentRGB Core: running", stdout.getvalue())
        self.assertIn(f"Address: 127.0.0.1:{self.server.server_port}", stdout.getvalue())
        self.assertEqual(self.output.commands, [])

    def test_status_absent_core(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))  # Порт занят тестом, но listener отсутствует.
            with patch.dict(os.environ, {"AGENTRGB_PORT": str(reserved.getsockname()[1])}):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(cli.main(["status"]), 1)
                self.assertIn("AgentRGB Core: not running", stdout.getvalue())

    def test_doctor_detects_reserved_port_without_listener(self):
        with socket.socket() as reserved:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            self.assertFalse(cli.port_available(port))
            stdout = io.StringIO()
            with patch.object(cli, "core_status", return_value="not running"), redirect_stdout(stdout):
                with patch("agentrgb.outputs.aula_f75_diagnostics.check_f75", return_value=0):
                    self.assertEqual(cli.doctor(port), 1)
            self.assertIn("in use or unavailable", stdout.getvalue())
        self.assertTrue(cli.port_available(port))

    def test_unrelated_http_server_is_not_agentrgb(self):
        class OtherHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        with HTTPServer(("127.0.0.1", 0), OtherHandler) as other:
            thread = threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                self.assertEqual(cli.core_status(other.server_port), "unavailable")
            finally:
                other.shutdown()
                thread.join()

    def test_core_probe_handles_timeout_bad_json_and_oversized_body(self):
        for body in (b"PRIVATE_PATH", b"x" * 1025, b"\xff"):
            with self.subTest(body_size=len(body)), patch.object(http.client, "HTTPConnection") as connection:
                response = connection.return_value.getresponse.return_value
                response.status = 200
                response.read.return_value = body
                self.assertEqual(cli.core_status(8765), "unavailable")
                connection.return_value.close.assert_called_once_with()
        with patch.object(http.client, "HTTPConnection") as connection:
            connection.return_value.request.side_effect = TimeoutError
            self.assertEqual(cli.core_status(8765), "unavailable")
            connection.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
