"""AULA F75 USB: volatile Direct Mode через объявленный feature report 0x06."""
import logging
import re
import threading

from .windows_hid import WindowsHid

LOG = logging.getLogger("agentrgb.aula")
REPORT_BYTES = 520
DIRECT_INTERVAL_SECONDS = 0.05
LED_COUNT = 122
COLORS = {"working": (0, 0, 255), "waiting": (255, 255, 0), "completed": (0, 255, 0)}
READ_LENGTHS = {0x82: 6, 0x84: 0x80, 0x8A: 0x200}


class AulaError(Exception):
    pass


def matches(device):
    return (device.vid == 0x258A and device.pid == 0x010C
            and re.search(r"vid_258a&pid_010c&mi_01&col06(?:#|$)", device.path.lower()) is not None
            and device.usage_page == 0xFF00 and device.usage == 1 and device.feature_bytes == REPORT_BYTES)


def select_device(devices):
    candidates = [device for device in devices if matches(device)]
    if len(candidates) != 1:
        raise AulaError("device_missing_or_ambiguous")
    return candidates[0]


def read_request(opcode):
    size = READ_LENGTHS[opcode]
    report = bytearray(REPORT_BYTES)
    report[0:8] = bytes((6, opcode, 1, 0, 1, 0, size & 255, size >> 8))
    return bytes(report)


def direct_frame(rgb):
    """D2 frame: 122 RGB triples, zero tail; no persistent protocol writes."""
    if len(rgb) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
        raise ValueError("invalid_rgb")
    report = bytearray(REPORT_BYTES)
    report[:8] = bytes.fromhex("06 08 00 00 01 00 7A 01")
    report[8:374] = bytes(rgb) * LED_COUNT
    return bytes(report)


def color_report(rgb):
    """Исторический persistent builder для offline-исследований; output его не вызывает."""
    if len(rgb) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
        raise ValueError("invalid_rgb")
    report = bytearray(REPORT_BYTES)
    report[0], report[1], report[7] = 6, 0x0A, 2
    report[29:32] = bytes(rgb)
    report[0x202:0x204] = b"\x5a\xa5"
    return bytes(report)


def config_report(snapshot, *, single):
    """Исторический 0x04 builder из 0x84; production output его не вызывает."""
    validate_response(snapshot, 0x84)
    report = bytearray(REPORT_BYTES)
    report[:8] = bytes.fromhex("06 04 00 00 01 00 80 00")
    report[8:136] = snapshot[8:136]
    if single:
        if (snapshot[17], snapshot[18], snapshot[66], snapshot[67]) != (0, 1, 9, 0x37):
            raise AulaError("unsupported_config_baseline")
        report[67] = 0x30
    return bytes(report)


def validate_response(response, opcode):
    if len(response) != REPORT_BYTES or response[:8] != read_request(opcode)[:8]:
        LOG.warning("AULA invalid_response_header actual_first16=%s", response[:16].hex(" "))
        raise AulaError("invalid_response_header")
    if opcode == 0x82 and (response[8] != 3 or response[12:14] != b"\x00\xcd"):
        raise AulaError("model_or_psd_mismatch")
    end = {0x84: 134, 0x8A: 0x202}.get(opcode)
    if end is not None and response[end:end + 2] != b"\x5a\xa5":
        raise AulaError("invalid_response_terminator")
    return response


class AulaF75Output:
    """Volatile 0x06/0x08 output; the keyboard reverts after frames stop."""

    def __init__(self, backend=None):
        self.backend = backend
        self.handle = None
        self.desired_rgb = None
        self.last_error = None
        self.write_attempts = 0
        self.write_successes = 0
        self._lifecycle = threading.RLock()
        self._state = threading.Lock()
        self._stop = threading.Event()
        self._worker = None

    def _read_model(self, handle):
        self.backend.set_feature(handle, read_request(0x82))
        return validate_response(self.backend.get_feature(handle, 6, REPORT_BYTES), 0x82)

    def acquire(self):
        with self._lifecycle:
            if self.handle is not None:
                return True
            if self._worker is not None:
                return False  # Failed worker requires an explicit release before a new acquire.
            self.last_error = None
            handle = None
            try:
                if self.backend is None:
                    self.backend = WindowsHid()
                device = select_device(self.backend.enumerate())
                handle = self.backend.open(device.path)
                identity = self.backend.describe(handle, device.path)
                if not matches(identity) or identity.path.lower() != device.path.lower():
                    raise AulaError("opened_device_mismatch")
                if 6 not in self.backend.feature_report_ids(handle):
                    raise AulaError("feature_report_id_missing")
                self._read_model(handle)  # model=03 and PSD=00CD; no retry on mismatch.
                self.handle = handle
                return True
            except Exception as error:
                self.last_error = str(error) if isinstance(error, AulaError) else "acquire_failed"
                LOG.warning("AULA %s", self.last_error)
                self.handle = None
                if handle is not None:
                    try:
                        self.backend.close(handle)
                    except Exception:
                        LOG.warning("AULA close_failed")
                return False
            except BaseException:
                self.handle = None
                if handle is not None:
                    self.backend.close(handle)
                raise

    def render(self, rgb):
        direct_frame(rgb)  # Validate before changing the desired state.
        with self._lifecycle:
            with self._state:
                if self.handle is None or self._stop.is_set():
                    return False
                self.desired_rgb = tuple(rgb)
                if self._worker is not None:
                    return True
                self._worker = threading.Thread(target=self._heartbeat, name="aula-f75-direct", daemon=True)
                worker = self._worker
            try:
                worker.start()
            except Exception:
                with self._state:
                    self._worker = None
                    self.desired_rgb = None
                    handle, self.handle = self.handle, None
                self.last_error = "worker_start_failed"
                LOG.warning("AULA %s", self.last_error)
                try:
                    self.backend.close(handle)
                except Exception:
                    LOG.warning("AULA close_failed")
                return False
            return True

    def _after_direct_frame(self):
        """No-op in production; experimental subclasses may fault after a successful frame."""

    def _stop_failed_heartbeat(self, handle, reason):
        self.last_error = reason
        LOG.warning("AULA %s", reason)
        self._stop.set()
        self.desired_rgb = None
        self.handle = None
        try:
            self.backend.close(handle)
        except Exception:
            LOG.warning("AULA close_failed")

    def _heartbeat(self):
        while not self._stop.is_set():
            with self._state:
                if self._stop.is_set() or self.handle is None or self.desired_rgb is None:
                    break
                handle = self.handle
                report = direct_frame(self.desired_rgb)
                self.write_attempts += 1
                try:
                    self.backend.set_feature(handle, report)
                except Exception:
                    self._stop_failed_heartbeat(handle, "direct_write_failed")
                    break
                self.write_successes += 1
                try:
                    self._after_direct_frame()
                except Exception:
                    self._stop_failed_heartbeat(handle, "heartbeat_failed")
                    break
            if self._stop.wait(DIRECT_INTERVAL_SECONDS):
                break

    def show_activity(self, state):
        if state not in ("working", "waiting"):
            self.last_error = "unsupported_activity"
            self.release()
            return False
        return self.render(COLORS[state])

    def show_signal(self, signal):
        if signal != "completed":
            self.last_error = "unsupported_signal"
            self.release()
            return False
        return self.render(COLORS[signal])

    def resume_activity(self, state):
        return self.show_activity(state)

    def release(self):
        with self._lifecycle:
            with self._state:
                self._stop.set()
                self.desired_rgb = None
                worker = self._worker
            if worker is not None:
                worker.join()
            with self._state:
                handle, self.handle = self.handle, None
                self._worker = None
            ok = True
            if handle is not None:
                try:
                    self.backend.close(handle)
                except Exception:
                    ok = False
                    self.last_error = "close_failed"
                    LOG.warning("AULA close_failed")
            self._stop.clear()
            return ok
