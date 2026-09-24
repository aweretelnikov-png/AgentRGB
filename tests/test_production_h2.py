"""H2 controller на fake HID: фиксированный порядок и предел семи writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_aula import FakeHid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/phase-04b"))
SPEC = importlib.util.spec_from_file_location("production_h2", ROOT / "experiments/phase-04b/production_h2.py")
h2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h2)


class H2Tests(unittest.TestCase):
    def session(self, directory, rgb=b"\xff\x00\x00"):
        fake = FakeHid()
        fake.reports[0x8A][29:32] = rgb
        return h2.H2Session(fake, directory), fake

    def test_four_confirmed_states_and_full_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, fake = self.session(temporary)
            for step, expected in enumerate(("0000FF", "FFFF00", "0000FF", "00FF00"), 1):
                result = session.next()
                self.assertEqual(result["rgb"], expected)
                self.assertTrue(result["fresh_baseline"])
                self.assertEqual(result["changing_writes"], step + 1)
                session.confirm(step)
            result = session.finish(visual=True)
            self.assertEqual(result["status"], "readback_restored_visual_pending")
            self.assertEqual(result["restore_status"], "readback_confirmed")
            self.assertTrue(result["final_config_matches_baseline"])
            self.assertTrue(result["final_color_matches_baseline"])
            self.assertEqual([r[1] for r in fake.writes], [4, 10, 10, 10, 10, 10, 4])
            self.assertEqual(fake.closes, 1)
            self.assertEqual(len(session.finish(visual=False)["writes"]), 7)

    def test_each_visual_abort_restores_once(self):
        for step in range(1, 5):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                session, fake = self.session(temporary)
                for current in range(1, step + 1):
                    session.next()
                    if current != step:
                        session.confirm(current)
                summary = session.finish(visual=False)
                self.assertEqual(summary["status"], "stopped_restored_or_unverified")
                self.assertTrue(summary["final_config_matches_baseline"])
                self.assertTrue(summary["final_color_matches_baseline"])
                self.assertEqual(len(fake.writes), step + 3)
                self.assertLessEqual(len(fake.writes), 7)

    def test_baseline_mismatch_stops_before_first_write(self):
        for rgb in (b"\x12\x34\x56", b"\x00\x00\xff"):
            with self.subTest(rgb=rgb), tempfile.TemporaryDirectory() as temporary:
                session, fake = self.session(temporary, rgb)
                with self.assertRaisesRegex(RuntimeError, "h2_output_error"):
                    session.next()
                self.assertEqual(fake.writes, [])
                self.assertEqual(fake.closes, 1)
                self.assertEqual(session.summary["status"], "stopped_restored_or_unverified")

    def test_next_requires_visual_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, fake = self.session(temporary)
            session.next()
            with self.assertRaisesRegex(RuntimeError, "h2_step_unavailable"):
                session.next()
            with self.assertRaisesRegex(RuntimeError, "h2_confirmation_out_of_order"):
                session.confirm(2)
            session.finish(visual=False)
            self.assertEqual(len(fake.writes), 4)

    def test_loopback_control_requires_confirmation_between_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, fake = self.session(temporary)
            with h2.ControlServer(session, "fixture-token") as server:
                def serve():
                    while not server.done:
                        server.handle_request()
                thread = threading.Thread(target=serve)
                thread.start()
                def send(action, step=None):
                    body = json.dumps(dict(action=action, token="fixture-token", step=step)).encode()
                    request = Request(f"http://127.0.0.1:{server.server_port}/", body,
                                      {"Content-Type": "application/json"})
                    with urlopen(request, timeout=2) as response:
                        return json.load(response)
                try:
                    self.assertEqual(send("next")["rgb"], "0000FF")
                    with self.assertRaises(HTTPError):
                        send("next")
                    for step in range(1, 5):
                        self.assertTrue(send("confirm", step)["visual_confirmed"])
                        if step < 4:
                            send("next")
                    result = send("finish")
                    self.assertEqual(result["status"], "readback_restored_visual_pending")
                finally:
                    if not server.done:
                        send("abort")
                    thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(fake.writes), 7)


if __name__ == "__main__":
    unittest.main()
