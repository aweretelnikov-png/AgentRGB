"""Выход без оборудования, таймеров и правил приоритета."""
class FakeOutput:
    def acquire(self):
        pass

    def show_activity(self, state):
        print(f"OUTPUT {state}", flush=True)

    def show_signal(self, signal):
        print(f"SIGNAL {signal}", flush=True)

    def resume_activity(self, state):
        self.show_activity(state)

    def release(self):
        self.show_activity("idle")
