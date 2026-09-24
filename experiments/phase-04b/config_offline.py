"""Офлайн-разбор двух трактовок offsets; НЕ содержит HID или отправки reports.

Индексы upstream относятся к полному report. Кандидаты не разрешены к отправке:
документация расходится с кодом, а static Apply обнуляет nibble скорости.
"""
import argparse
import hashlib
import json
from pathlib import Path


def checked(response):
    raw = bytes(response)
    if len(raw) != 520 or raw[:8] != bytes.fromhex("06 84 01 00 01 00 80 00"):
        raise ValueError("unexpected_config_response")
    if raw[134:136] != b"\x5a\xa5":
        raise ValueError("unexpected_config_terminator")
    return raw


def parse_config(response, *, payload_offsets=False):
    raw = checked(response)
    origin = 8 if payload_offsets else 0
    effect = raw[origin + 18]
    pos = origin + 64 + 2 * effect
    if not 1 <= effect <= 18 or pos + 1 >= 134:
        raise ValueError("unsupported_effect")
    packed = raw[pos + 1]
    return dict(effect=effect, custom_mode=raw[origin + 17],
                brightness=raw[pos], speed=packed >> 4, flags=packed & 15,
                brightness_report_offset=pos, speed_flags_report_offset=pos + 1)


def restore_report(response):
    raw = checked(response)
    return bytearray(bytes.fromhex("06 04 00 00 01 00 80 00") + raw[8:136] + bytes(384))


def candidate_report(response, *, preserve_speed):
    """Две явно разделённые гипотезы, только offsets текущего upstream-кода."""
    config = parse_config(response)
    if config['effect'] != 1:
        raise ValueError("only_current_effect_1_supported")
    result = restore_report(response)
    result[17] = 0  # Apply отключает per-key custom mode.
    result[67] = (result[67] & 0xF0) if preserve_speed else 0
    return result


def prepare(directory):
    raw = checked((directory / 'config-response.bin').read_bytes())
    restore = restore_report(raw)
    candidates = {
        'restore-config': restore,
        'candidate-upstream-static': candidate_report(raw, preserve_speed=False),
        'candidate-preserve-speed': candidate_report(raw, preserve_speed=True),
    }
    evidence = dict(status='BLOCKED_NOT_FOR_HARDWARE',
                    upstream_offsets=parse_config(raw),
                    literal_document_payload_offsets=parse_config(raw, payload_offsets=True),
                    source_sha256=hashlib.sha256(raw).hexdigest(), reports={})
    for name, report in candidates.items():
        (directory / (name + '.bin')).write_bytes(report)
        (directory / (name + '.hex')).write_text(report.hex(' ') + '\n', encoding='ascii')
        evidence['reports'][name] = dict(sha256=hashlib.sha256(report).hexdigest(),
            diff_from_restore=[dict(report_offset=i, payload_offset=i-8,
                                   original=f'{a:02X}', proposed=f'{b:02X}')
                               for i, (a, b) in enumerate(zip(restore, report)) if a != b])
    (directory / 'offline-analysis.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot_directory', type=Path)
    print(json.dumps(prepare(parser.parse_args().snapshot_directory), indent=2))
