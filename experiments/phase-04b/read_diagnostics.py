"""Только read-запросы 82/84/8A, без color writes, retries и bare GET."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

from persistent_output import AulaF75Output, AulaError, read_request
from agentrgb.outputs.windows_hid import WindowsHid
from run import save_get_diagnostic


def prototype_request(opcode):
    # Независимая транскрипция FeatureRead из 01B: new byte[520], присваивания
    # [0],[1],[2],[4],[6],[7]; весь остальной буфер остаётся нулевым.
    header = {0x82: "06 82 01 00 01 00 06 00", 0x84: "06 84 01 00 01 00 80 00",
              0x8A: "06 8a 01 00 01 00 00 02"}[opcode]
    return bytes.fromhex(header) + bytes(512)


class ReadOnlyHid(WindowsHid):
    def __init__(self, diagnostic_sink):
        super().__init__(diagnostic_sink)
        self.read_count = 0
        self.awaiting_get = False

    def set_feature(self, handle, report):
        if len(report) != 520 or report[1] not in (0x82, 0x84, 0x8A):
            raise RuntimeError("state_writes_forbidden")
        if report != prototype_request(report[1]):
            raise RuntimeError("unexpected_request_bytes")
        if self.read_count >= 9 or self.awaiting_get:
            raise RuntimeError("read_budget_or_sequence_violation")
        self.read_count += 1
        super().set_feature(handle, report)
        self.awaiting_get = True

    def get_feature(self, handle, report_id, length):
        if not self.awaiting_get or (report_id, length) != (6, 520):
            raise RuntimeError("bare_get_forbidden")
        self.awaiting_get = False
        return super().get_feature(handle, report_id, length)


def main():
    directory = Path(__file__).parent / "results" / ("reads-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(parents=True)
    phase = "identification"
    def save(record):
        save_get_diagnostic(directory, {**record, "phase": phase})
    requests = {}
    for opcode in (0x82, 0x84, 0x8A):
        actual = read_request(opcode)
        assert actual == prototype_request(opcode)
        requests[f"{opcode:02X}"] = dict(header=actual[:8].hex(" "), bytes=len(actual),
                                        identical_to_01b=True, sha256=hashlib.sha256(actual).hexdigest())
    backend = ReadOnlyHid(save)
    output = AulaF75Output(backend)
    summary = dict(python=platform.python_version(), requests=requests, changing_writes=0,
                   bare_get="skipped", results=[], status="pending")
    try:
        if not output.acquire():
            raise RuntimeError("identification_failed")
        if output.snapshot.rgb != (255, 0, 0):
            raise RuntimeError("unexpected_original_rgb")
        summary["identity"] = dict(vid="258A", pid="010C", collection="MI_01/COL06", usage="FF00/0001",
                                   feature_bytes=520, report_id=6, model=3, psd="00CD", original_rgb="FF0000")
        reference = None
        for phase, opcode in (("R1", 0x8A), ("R2-1", 0x8A), ("R2-2", 0x8A), ("R2-3", 0x8A), ("R3-model", 0x82), ("R3-config", 0x84)):
            response = output.read(opcode)
            row = dict(phase=phase, header=response[:8].hex(" "), sha256=hashlib.sha256(response).hexdigest(), valid=True)
            if opcode == 0x8A:
                row.update(rgb=response[29:32].hex(), terminator=response[514:516].hex(" "))
                if response[29:32] != b"\xff\x00\x00":
                    raise RuntimeError("unexpected_rgb")
                if reference is None:
                    reference = response
                differences = [index for index in range(520) if response[index] != reference[index]]
                row["different_indices_vs_R1"] = differences
                row["outside_rgb_differences"] = sum(index not in (29, 30, 31) for index in differences)
            summary["results"].append(row)
        summary["status"] = "ordinary_reads_stable" if len({row["sha256"] for row in summary["results"][:4]}) == 1 else "ordinary_reads_valid_but_differ"
    except Exception as error:
        summary["status"] = "stopped_on_error"
        summary["failed_phase"] = phase
        summary["error"] = str(error) if isinstance(error, (AulaError, RuntimeError)) else type(error).__name__
    finally:
        output.release()  # changed=False: guard запрещает любую изменяющую команду.
        summary["read_requests"] = backend.read_count
        summary["handle_closed"] = output.handle is None
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
    return int(summary["status"] == "stopped_on_error")


if __name__ == "__main__":
    raise SystemExit(main())
