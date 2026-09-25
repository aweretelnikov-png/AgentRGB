"""Запуск: python -m agentrgb.server [--output fake|aula-f75]."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import socket
import sys
import threading

from .protocol import MAX_BODY, validate
from .state import Core
from .fake import FakeOutput

LOG = logging.getLogger("agentrgb")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


class EventServer(HTTPServer):
    allow_reuse_address = False

    # Один поток HTTP сохраняет порядок применения; отдельный tick не зависит от body.
    def __init__(self, port, core):
        super().__init__(("127.0.0.1", port), Handler, bind_and_activate=False)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.server_bind()
            self.server_activate()
        except Exception:
            super().server_close()
            raise
        self.core = core
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.ticker = threading.Thread(target=self.tick_loop, daemon=True)
        self.ticker.start()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(0.2)
        return connection, address

    def tick_loop(self):
        while not self.stopped.wait(0.02):
            with self.lock:
                try:
                    self.core.tick()
                except Exception:
                    LOG.error("output_failed")

    def server_close(self):
        self.stopped.set()
        self.ticker.join()
        try:
            with self.lock:
                self.core.close()
        finally:
            super().server_close()

    def handle_error(self, request, client_address):
        LOG.warning("request_failed")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Не выводить URL, заголовки, body или исключения клиента.

    def reply(self, status, reason):
        body = json.dumps({"status": reason}).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_POST(self):
        try:
            self.receive()
        except (socket.timeout, ConnectionError):
            self.close_connection = True

    def do_GET(self):
        if self.path != "/health":
            return self.reply(404, "not_found")
        body = b'{"status":"ok","service":"agentrgb"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def receive(self):
        if self.path != "/v1/events":
            return self.reply(404, "not_found")
        if self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Content-Encoding"):
            return self.reply(400, "unsupported_encoding")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            return self.reply(400, "invalid_length")
        if len(lengths[0]) > 8 or int(lengths[0]) > MAX_BODY:
            return self.reply(413, "body_too_large")
        types = self.headers.get_all("Content-Type", [])
        if len(types) != 1 or types[0].lower() != "application/json":
            return self.reply(415, "json_required")
        length = int(lengths[0])
        raw = self.rfile.read(length)
        try:
            if len(raw) != length:
                raise ValueError("short_body")
            event = validate(json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object))
        except (ValueError, TypeError, RecursionError):
            return self.reply(400, "invalid_event")
        try:
            with self.server.lock:
                status = self.server.core.apply(event)
        except Exception:
            LOG.error("output_failed")
            return self.reply(500, "output_failed")
        LOG.info("EVENT %s outcome=%s result=%s", event.kind, event.outcome, status)
        self.reply(200, status)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", choices=("fake", "aula-f75"), default="fake")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    port = int(os.environ.get("AGENTRGB_PORT", "8765"))
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    if args.output == "aula-f75":
        from .outputs.aula_f75 import AulaF75Output
        output = AulaF75Output()
    else:
        output = FakeOutput()
    with EventServer(port, Core(output)) as server:
        LOG.info("LISTEN http://127.0.0.1:%d/v1/events", port)
        if os.environ.get("AGENTRGB_PARENT_STDIO") == "1":
            def parent_closed():
                try:
                    while sys.stdin.buffer.read(1):
                        pass
                finally:
                    server.shutdown()

            threading.Thread(target=parent_closed, daemon=True).start()
            print("AGENTRGB_READY", flush=True)
        try:
            server.serve_forever(poll_interval=0.05)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
