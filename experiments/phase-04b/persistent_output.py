"""AULA F75 USB: подтверждённый single-color режим и best-effort restore.

Полный аппаратный профиль не восстанавливается. Команды могут сохраняться
в памяти устройства; ресурс записей неизвестен. Здесь нет анимаций,
повторных записей для polling или retries.
"""
from dataclasses import dataclass
import logging
import re

from agentrgb.outputs.windows_hid import Interface, WindowsHid

LOG = logging.getLogger("agentrgb.aula")
REPORT_BYTES = 520
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


def color_report(rgb):
    if len(rgb) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
        raise ValueError("invalid_rgb")
    report = bytearray(REPORT_BYTES)
    report[0], report[1], report[7] = 6, 0x0A, 2
    report[29:32] = bytes(rgb)
    report[0x202:0x204] = b"\x5a\xa5"
    return bytes(report)


def config_report(snapshot, *, single):
    """Полный 0x04 из свежего 0x84; в single меняется только report[67]."""
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


@dataclass(frozen=True)
class Snapshot:
    model: bytes
    config: bytes
    color: bytes
    identity: Interface

    @property
    def rgb(self):
        return tuple(self.color[29:32])


class AulaF75Output:
    def __init__(self, backend=None):
        self.backend = backend  # Windows DLL загружается только при acquire.
        self.handle = None
        self.snapshot = None
        self.last_rgb = None
        self.config_changed = False
        self.color_changed = False
        self.last_error = None
        self.restore_status = "not_needed"
        self.write_attempts = 0
        self.write_successes = 0

    def read(self, opcode):
        self.backend.set_feature(self.handle, read_request(opcode))
        return validate_response(self.backend.get_feature(self.handle, 6, REPORT_BYTES), opcode)

    def acquire(self):
        if self.handle is not None:
            return True
        self.last_error = None
        self.restore_status = "not_needed"
        try:
            if self.backend is None:
                self.backend = WindowsHid()
            device = select_device(self.backend.enumerate())
            self.handle = self.backend.open(device.path)
            # Проверить caps/attributes на том же открытом handle, не доверять старой enumeration.
            identity = self.backend.describe(self.handle, device.path)
            if not matches(identity) or identity.path.lower() != device.path.lower():
                raise AulaError("opened_device_mismatch")
            model, config, color = self.read(0x82), self.read(0x84), self.read(0x8A)
            report = config_report(config, single=True)  # Unsupported baseline: zero writes.
            self.snapshot = Snapshot(model, config, color, identity)
            self.last_rgb = self.snapshot.rgb
            LOG.info("AULA acquired original_rgb=#%02X%02X%02X", *self.last_rgb)
            self.config_changed = True  # A SetFeature failure may leave hardware changed.
            self._write(report)
            observed = self.read(0x84)
            expected = bytearray(config)
            expected[67] = 0x30
            if observed[8:136] != expected[8:136]:
                raise AulaError("config_readback_mismatch")
            return True
        except Exception as error:
            return self.fail(error, "acquire_failed")
        except BaseException:
            self.release()
            raise

    def _write(self, report):
        self.write_attempts += 1
        self.backend.set_feature(self.handle, report)
        self.write_successes += 1

    def write_rgb(self, rgb):
        self.last_rgb = None
        self.color_changed = True  # До SetFeature: при ошибке состояние может быть неизвестным.
        self._write(color_report(rgb))
        actual = tuple(self.read(0x8A)[29:32])
        LOG.info("AULA write expected=#%02X%02X%02X readback=#%02X%02X%02X", *rgb, *actual)
        if actual != rgb:
            raise AulaError("rgb_readback_mismatch")
        self.last_rgb = rgb

    def render(self, rgb):
        if self.handle is None or self.snapshot is None:
            return False
        if rgb == self.last_rgb:
            return True
        try:
            self.write_rgb(rgb)
            return True
        except Exception as error:
            return self.fail(error, "render_failed")
        except BaseException:
            self.release()
            raise

    def show_activity(self, state):
        if state not in ("working", "waiting"):
            return self.fail(AulaError("unsupported_activity"), "render_failed")
        return self.render(COLORS[state])

    def show_signal(self, signal):
        if signal != "completed":
            return self.fail(AulaError("unsupported_signal"), "render_failed")
        return self.render(COLORS[signal])

    def resume_activity(self, state):
        return self.show_activity(state)

    def fail(self, error, fallback):
        self.last_error = str(error) if isinstance(error, AulaError) else fallback
        LOG.warning("AULA %s", self.last_error)
        self.release()
        return False

    def release(self):
        if self.handle is None:
            return self.restore_status not in ("failed", "unverified")
        ok = True
        snapshot = self.snapshot
        needs_color = (self.color_changed and snapshot is not None
                       and self.last_rgb != snapshot.rgb)
        needs_config = self.config_changed and snapshot is not None
        try:
            if needs_color:
                try:
                    self._write(color_report(snapshot.rgb))
                except Exception:
                    ok = False
                    LOG.warning("AULA color_restore_write_failed")
                try:
                    if tuple(self.read(0x8A)[29:32]) != snapshot.rgb:
                        ok = False
                except Exception:
                    ok = False
                    LOG.warning("AULA color_restore_readback_failed")
            if needs_config:
                try:
                    self._write(config_report(snapshot.config, single=False))
                except Exception:
                    ok = False
                    LOG.warning("AULA config_restore_write_failed")
                for opcode, expected in ((0x84, snapshot.config), (0x8A, snapshot.color)):
                    try:
                        if self.read(opcode) != expected:
                            ok = False
                    except Exception:
                        ok = False
                        LOG.warning("AULA restore_readback_failed opcode=%02X", opcode)
            self.restore_status = ("readback_confirmed" if ok and needs_config
                                   else "unverified" if needs_config else "not_needed")
        finally:
            handle, self.handle = self.handle, None
            self.snapshot = None
            self.last_rgb = None
            self.config_changed = False
            self.color_changed = False
            try:
                self.backend.close(handle)
            except Exception:
                ok = False
                self.restore_status = "failed"
                LOG.warning("AULA close_failed")
        return ok
