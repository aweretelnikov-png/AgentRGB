import unittest
from dataclasses import replace
from agentrgb.protocol import validate
from agentrgb.state import Core, HISTORY_LIMIT


def event(kind="run_started", run="r1", session="s1", outcome=None, **changes):
    value = dict(schema_version=1, source="pi", source_instance_id="i1", session_id=session,
                 run_id=run, event_id=f"{run}-{kind}", kind=kind,
                 timestamp="2026-09-21T00:00:00Z", metadata={} if outcome is None else {"outcome": outcome})
    value.update(changes)
    return validate(value)


class RecordingOutput:
    def __init__(self):
        self.commands = []
        self.acquired = 0
        self.released = 0

    def acquire(self):
        self.acquired += 1

    def show_activity(self, state):
        self.commands.append(state)

    def resume_activity(self, state):
        self.show_activity(state)

    def show_signal(self, signal):
        self.commands.append(signal)

    def release(self):
        self.released += 1
        self.commands.append("idle")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.output = RecordingOutput()
        self.core = Core(self.output, lambda: self.now)

    def apply(self, kind="run_started", **kwargs):
        return self.core.apply(event(kind, **kwargs))

    def test_work_wait_resume_unknown(self):
        for kind in ("run_started", "run_waiting", "run_resumed", "run_ended"):
            self.apply(kind)
        self.assertEqual(self.output.commands, ["working", "waiting", "working", "idle"])

    def test_completed_duration_and_release(self):
        self.apply()
        self.apply("run_ended", outcome="completed")
        self.now = 1.99
        self.core.tick()
        self.assertEqual(self.output.commands, ["working", "completed"])
        self.now = 2
        self.core.tick()
        self.assertEqual(self.output.commands, ["working", "completed", "idle"])
        self.assertEqual(self.output.released, 1)

    def test_end_while_waiting_unknown_or_completed(self):
        for outcome in ("unknown", "completed"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.apply()
                self.apply("run_waiting")
                self.apply("run_ended", outcome=outcome)
                self.assertEqual(self.output.commands[-1], "idle" if outcome == "unknown" else "completed")
                self.assertEqual(self.apply("run_resumed"), "unknown_run")

    def test_duplicates_and_closed_run_cannot_restart(self):
        self.apply()
        self.assertEqual(self.apply(), "duplicate")
        self.apply("run_ended", outcome="completed")
        self.assertEqual(self.apply("run_ended", outcome="completed"), "duplicate")
        self.assertEqual(self.apply("run_ended", event_id="new-end", outcome="completed"), "unknown_run")
        self.assertEqual(self.apply(event_id="new-start"), "known_run")
        self.assertEqual(self.output.commands.count("completed"), 1)

    def test_invalid_order_and_identity(self):
        self.assertEqual(self.apply("run_waiting"), "unknown_run")
        self.apply()
        self.assertEqual(self.apply("run_resumed"), "not_waiting")
        self.assertEqual(self.apply("run_ended", session="s2"), "unknown_run")
        self.assertEqual(self.apply(run="r2"), "session_busy")
        self.assertEqual(self.output.commands, ["working"])

    def test_parallel_waiting_priority_and_terminal_suppression(self):
        self.apply()
        self.apply(run="r2", session="s2")
        self.apply("run_waiting", run="r2", session="s2")
        self.apply("run_ended", outcome="completed")
        self.assertEqual(self.output.commands, ["working", "waiting"])
        self.apply("run_ended", run="r2", session="s2")
        self.assertEqual(self.output.commands[-1], "idle")

    def test_waiting_run_ends_leaving_working(self):
        self.apply()
        self.apply(run="r2", session="s2")
        self.apply("run_waiting", run="r2", session="s2")
        self.apply("run_ended", run="r2", session="s2")
        self.assertEqual(self.output.commands, ["working", "waiting", "working"])

    def test_waiting_cancels_completed_without_replay(self):
        self.apply()
        self.apply("run_ended", outcome="completed")
        self.apply(run="r2", session="s2")
        self.apply("run_waiting", run="r2", session="s2")
        self.apply("run_resumed", run="r2", session="s2")
        self.now = 5
        self.core.tick()
        self.assertEqual(self.output.commands, ["working", "completed", "waiting", "working"])

    def test_completed_uses_current_aggregate(self):
        self.apply()
        self.apply("run_ended", outcome="completed")
        self.apply(run="r2", session="s2")
        self.now = 2
        self.core.tick()
        self.assertEqual(self.output.commands, ["working", "completed", "working"])

    def test_same_session_in_other_instance_is_independent(self):
        self.apply()
        self.apply(source_instance_id="i2", event_id="other-instance")
        self.apply("run_ended")
        self.assertEqual(len(self.core.runs), 1)
        self.assertEqual(self.output.commands, ["working"])

    def test_second_completion_replaces_signal_deadline(self):
        self.apply()
        self.apply(run="r2", session="s2")
        self.apply("run_ended", outcome="completed")
        self.now = 1
        self.apply("run_ended", run="r2", session="s2", outcome="completed")
        self.now = 2
        self.core.tick()
        self.assertEqual(self.output.commands, ["working", "completed", "completed"])
        self.now = 3
        self.core.tick()
        self.assertEqual(self.output.commands[-1], "idle")

    def test_history_bounded(self):
        sample = event("run_resumed")
        for index in range(HISTORY_LIMIT + 10):
            self.core.apply(replace(sample, event_id=str(index)))
        self.assertEqual(len(self.core.seen), HISTORY_LIMIT)
        self.assertNotIn("0", self.core.seen)

    def test_shutdown_and_output_error_attempt_release(self):
        self.apply()
        self.core.close()
        self.core.close()
        self.assertEqual(self.output.released, 1)
        def fail(_):
            raise RuntimeError("fixture")
        self.setUp()
        self.output.show_activity = fail
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.output.released, 1)
        self.assertFalse(self.core.owned)


if __name__ == "__main__":
    unittest.main()
