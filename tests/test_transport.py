import http.client
import json
import socket
import threading
import unittest

from agentrgb.protocol import validate
from agentrgb.server import EventServer
from agentrgb.state import Core
from test_core import RecordingOutput


def payload(**changes):
    value = dict(schema_version=1, source="pi", source_instance_id="instance", session_id="session",
                 run_id="run", event_id="event", kind="run_started", timestamp="2026-09-21T00:00:00Z", metadata={})
    value.update(changes)
    return value


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.output = RecordingOutput()
        self.server = EventServer(0, Core(self.output))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def post(self, body, headers=None, path="/v1/events"):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request("POST", path, body, headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_loopback_and_applied_duplicate(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        body = json.dumps(payload())
        self.assertEqual(self.post(body), (200, {"status": "applied"}))
        self.assertEqual(self.post(body), (200, {"status": "duplicate"}))
        self.assertEqual(self.output.commands, ["working"])

    def test_rejects_bad_http_and_json(self):
        for body, headers, status in [
            ("{}", {"Content-Type": "text/plain"}, 415),
            ("x" * 4097, None, 413),
            ("[]", None, 400), ("{", None, 400), (b"\xff", None, 400),
            ('{"x":1,"x":2}', None, 400),
            ("", {"Transfer-Encoding": "chunked", "Content-Type": "application/json"}, 400),
        ]:
            with self.subTest(status=status, body_size=len(body)):
                self.assertEqual(self.post(body, headers)[0], status)
        self.assertEqual(self.post("{}", path="/private-sentinel")[0], 404)

    def test_contract_rejects_unknown_or_private_fields(self):
        for change in [dict(schema_version=True), dict(schema_version=2), dict(source="codex"),
                       dict(kind="tool_call"), dict(kind=[]), dict(session_id=""),
                       dict(timestamp="yesterday"), dict(timestamp="2026-09-21"),
                       dict(metadata={"content": "PRIVATE"}), dict(content="PRIVATE"),
                       dict(kind="run_ended", metadata={"outcome": "error"})]:
            with self.subTest(change=change):
                self.assertEqual(self.post(json.dumps(payload(**change)))[0], 400)
        self.assertEqual(self.output.commands, [])

    def test_absent_outcome_is_unknown(self):
        self.assertEqual(validate(payload(kind="run_ended")).outcome, "unknown")

    def test_stalled_client_does_not_block_next_request_indefinitely(self):
        with socket.create_connection(self.server.server_address, timeout=2) as stalled:
            stalled.sendall(b"POST /v1/events HTTP/1.0\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n{")
            self.assertEqual(self.post(json.dumps(payload()))[0], 200)

    def test_busy_port_preserves_bind_error(self):
        with self.assertRaises(OSError):
            with EventServer(self.server.server_port, Core(RecordingOutput())):
                pass


if __name__ == "__main__":
    unittest.main()
