"""Приватный parent pipe проверяется на реальном subprocess с fake output."""
import http.client
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import unittest


class ParentStdioTests(unittest.TestCase):
    def test_parent_eof_closes_listener_and_releases_active_output(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        env = dict(os.environ, AGENTRGB_PORT=str(port), AGENTRGB_PARENT_STDIO="1")
        child = subprocess.Popen([sys.executable, "-m", "agentrgb.cli", "start", "--output", "fake"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
        try:
            self.assertEqual(ready.get(timeout=5).strip(), b"AGENTRGB_READY")
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/health")
                self.assertEqual(json.loads(connection.getresponse().read())["service"], "agentrgb")
                event = dict(schema_version=1, source="pi", source_instance_id="test", session_id="test",
                             run_id="test", event_id="test", kind="run_started",
                             timestamp="2026-09-25T00:00:00Z", metadata={})
                connection.request("POST", "/v1/events", json.dumps(event), {"Content-Type": "application/json"})
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                connection.close()
            child.stdin.close()
            self.assertEqual(child.wait(timeout=5), 0)
            self.assertIn(b"OUTPUT idle", child.stdout.read())
            with socket.socket() as probe:
                probe.settimeout(0.2)
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()


if __name__ == "__main__":
    unittest.main()
