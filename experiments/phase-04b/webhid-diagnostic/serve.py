"""Loopback-only static page and validated metadata collector; no HID APIs."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT.parent / "results"
MAX_BODY = 100_000


def _number(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def validate_collection(node, depth=0):
    if depth > 16 or type(node) is not dict:
        raise ValueError("invalid_collection")
    if set(node) != {"usagePage", "usage", "inputReports", "outputReports",
                     "featureReports", "children"}:
        raise ValueError("unexpected_collection_fields")
    if not _number(node["usagePage"], 0xFFFF) or not _number(node["usage"], 0xFFFF):
        raise ValueError("invalid_usage")
    for key in ("inputReports", "outputReports", "featureReports"):
        if type(node[key]) is not list or len(node[key]) > 256:
            raise ValueError("invalid_reports")
        if any(not _number(item, 0xFF) for item in node[key]):
            raise ValueError("invalid_report_id")
    if type(node["children"]) is not list or len(node["children"]) > 256:
        raise ValueError("invalid_children")
    for child in node["children"]:
        validate_collection(child, depth + 1)


def validate_snapshot(data):
    if type(data) is not dict or set(data) != {"vendorId", "productId", "productName", "collections"}:
        raise ValueError("unexpected_device_fields")
    if data["vendorId"] != 0x258A or data["productId"] != 0x010C:
        raise ValueError("unexpected_device")
    if type(data["productName"]) is not str or len(data["productName"]) > 120:
        raise ValueError("invalid_product_name")
    if type(data["collections"]) is not list or len(data["collections"]) > 256:
        raise ValueError("invalid_collections")
    for collection in data["collections"]:
        validate_collection(collection)
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def _respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/snapshot.mjs": ("snapshot.mjs", "text/javascript; charset=utf-8")}
        if self.path not in files:
            self._respond(404, b"Not found", "text/plain")
            return
        name, kind = files[self.path]
        self._respond(200, (ROOT / name).read_bytes(), kind)

    def do_POST(self):
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        if (self.path != "/snapshot" or self.headers.get("Origin") != expected_origin
                or self.headers.get("Content-Type") != "application/json"):
            self._respond(403, b"Forbidden", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("invalid_body_length")
            data = validate_snapshot(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeError):
            self._respond(400, b"Invalid metadata", "text/plain")
            return
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = RESULTS / f"webhid-metadata-{stamp}.json"
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"SNAPSHOT_SAVED {output.name}", flush=True)
        self._respond(200, b"Saved", "text/plain")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(f"WEBHID_URL http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
