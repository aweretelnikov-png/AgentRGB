"""Автомат, агрегация и время сигнала. Все вызовы сериализует сервер."""
from collections import OrderedDict
from time import monotonic
from typing import Protocol

COMPLETED_SECONDS = 2.0
HISTORY_LIMIT = 4096


class Output(Protocol):
    def acquire(self): ...
    def show_activity(self, state: str): ...
    def show_signal(self, signal: str): ...
    def resume_activity(self, state: str): ...
    def release(self): ...


class Core:
    def __init__(self, output: Output, clock=monotonic):
        self.output = output
        self.clock = clock
        self.runs = {}
        self.seen = OrderedDict()
        self.closed = OrderedDict()
        self.signal_until = None
        self.visible = "idle"
        self.owned = False

    @staticmethod
    def remember(history, key):
        history[key] = None
        if len(history) > HISTORY_LIMIT:
            history.popitem(last=False)

    def aggregate(self):
        return "waiting" if "waiting" in self.runs.values() else "working" if self.runs else "idle"

    def apply(self, event):
        self.tick()
        if event.event_id in self.seen:
            return "duplicate"
        self.remember(self.seen, event.event_id)
        key = event.key
        if event.kind == "run_started":
            if key in self.runs or key in self.closed:
                return "known_run"
            if any(existing[:3] == key[:3] for existing in self.runs):
                return "session_busy"
            self.runs[key] = "working"
        elif key not in self.runs:
            return "unknown_run"
        elif event.kind == "run_waiting":
            if self.runs[key] != "working":
                return "already_waiting"
            self.runs[key] = "waiting"
        elif event.kind == "run_resumed":
            if self.runs[key] != "waiting":
                return "not_waiting"
            self.runs[key] = "working"
        elif event.kind == "run_ended":
            del self.runs[key]
            self.remember(self.closed, key)
            if event.outcome == "completed" and self.aggregate() != "waiting":
                self.signal_until = self.clock() + COMPLETED_SECONDS
                # Новый независимый terminal заменяет текущий, без очереди.
                self.visible = None
        self.render()
        return "applied"

    def tick(self):
        if self.signal_until is not None and self.clock() >= self.signal_until:
            self.signal_until = None
            self.render()

    def render(self):
        activity = self.aggregate()
        if activity == "waiting":
            self.signal_until = None
        target = "completed" if self.signal_until is not None else activity
        if target == self.visible:
            return
        previous = self.visible
        try:
            if target == "idle":
                self.output.release()
                self.owned = False
            else:
                if not self.owned:
                    self.owned = True
                    self.output.acquire()
                if target == "completed":
                    self.output.show_signal(target)
                elif previous == "completed":
                    self.output.resume_activity(target)
                else:
                    self.output.show_activity(target)
            self.visible = target
        except Exception:
            self.close()
            raise

    def close(self):
        self.signal_until = None
        try:
            if self.owned:
                self.output.release()
        finally:
            self.owned = False
            self.visible = "idle"
