"""Offline-only builders for the pinned F75 Direct Mode WebHID sequence.

This module deliberately has no HID transport, device discovery, or send path.
The frame is a research candidate; it is not approved for this F75 hardware.
"""

REPORT_SIZE = 520
WEBHID_BODY_SIZE = REPORT_SIZE - 1
REPORT_ID = 0x06
COMMAND = 0x08
LED_COUNT = 122
RGB_OFFSET = 8
D1_FRAME_COUNT = 40
D1_FRAME_INTERVAL_MS = 50
D2_FRAME_COUNT = 40
D2_FRAME_INTERVAL_MS = 50

_ENABLE_STEPS = (
    (0x39, bytes.fromhex("20 06 00 01 00")),
    (0x3C, bytes.fromhex("20 01 00")),
    (0x39, bytes.fromhex("20 06 01 01 00")),
)
_DISABLE_STEP = (0x3C, bytes.fromhex("20 00 00"))


def _small_feature_report(report_id: int, body_prefix: bytes) -> bytes:
    """Represent WebHID's (report ID, 519-byte body) as one full buffer."""
    report = bytearray(REPORT_SIZE)
    report[0] = report_id
    report[1 : 1 + len(body_prefix)] = body_prefix
    return bytes(report)


def build_enable_reports() -> tuple[bytes, bytes, bytes]:
    """Return exactly three distinct, zero-padded full feature reports."""
    return tuple(_small_feature_report(report_id, body) for report_id, body in _ENABLE_STEPS)


def build_disable_report() -> bytes:
    """Build the separate explicit disable report; D1 must not use it."""
    return _small_feature_report(*_DISABLE_STEP)


def build_uniform_frame(rgb: tuple[int, int, int]) -> bytes:
    """Return a fresh 520-byte feature report with one RGB across 122 slots."""
    if len(rgb) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
        raise ValueError("rgb must contain exactly three bytes")

    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = COMMAND
    frame[4] = 0x01
    frame[6] = LED_COUNT
    frame[7] = 0x01
    for led_index in range(LED_COUNT):
        start = RGB_OFFSET + 3 * led_index
        frame[start : start + 3] = bytes(rgb)
    return bytes(frame)


def build_d1_burst_reports() -> tuple[bytes, ...]:
    """Finite offline D1 plan: three enables and exactly 40 blue frames."""
    return build_enable_reports() + tuple(
        build_uniform_frame((0, 0, 255)) for _ in range(D1_FRAME_COUNT)
    )


def build_d2_burst_reports() -> tuple[bytes, ...]:
    """Finite D2 plan: only declared report 06, command 08, uniform blue."""
    return tuple(build_uniform_frame((0, 0, 255)) for _ in range(D2_FRAME_COUNT))
