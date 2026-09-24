"""Единственный свежий snapshot: строго 82 → 84 → 8A, без writes."""
from datetime import datetime, timezone
import json
from pathlib import Path

from persistent_output import AulaF75Output
from read_diagnostics import ReadOnlyHid
from run import save_get_diagnostic


class SnapshotOnlyHid(ReadOnlyHid):
    def set_feature(self, handle, report):
        expected = (0x82, 0x84, 0x8A)
        if self.read_count >= 3 or report[1] != expected[self.read_count]:
            raise RuntimeError("only_one_snapshot_allowed")
        super().set_feature(handle, report)


def main():
    directory = Path(__file__).parent / "results" / ("config-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(parents=True)
    backend = SnapshotOnlyHid(lambda record: save_get_diagnostic(directory, record))
    output = AulaF75Output(backend)
    summary = {"changing_writes": 0, "status": "pending"}
    try:
        if not output.acquire():
            raise RuntimeError(output.last_error)
        snapshot = output.snapshot
        for name in ("model", "config", "color"):
            (directory / (name + "-response.bin")).write_bytes(getattr(snapshot, name))
        (directory / "config-payload.bin").write_bytes(snapshot.config[8:136])
        summary.update(status="snapshot_valid", identity={"vid": "258A", "pid": "010C", "collection": "MI_01/COL06", "usage": "FF00/0001", "feature_bytes": 520, "report_id": 6, "model": 3, "psd": "00CD"}, primary_rgb=snapshot.color[29:32].hex())
    finally:
        output.release()
        summary.update(read_requests=backend.read_count, handle_closed=output.handle is None)
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(directory)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
