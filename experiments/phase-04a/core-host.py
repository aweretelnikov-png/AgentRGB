"""Только стенд опыта: штатно закрыть Core после закрытия stdin родителем."""
import os
import sys
import threading
import logging
from agentrgb.server import EventServer
from agentrgb.state import Core
from agentrgb.fake import FakeOutput

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
with EventServer(int(os.environ.get("AGENTRGB_PORT", "8765")), Core(FakeOutput())) as server:
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    worker.start()
    print(f"LISTEN http://127.0.0.1:{server.server_port}/v1/events", flush=True)
    try:
        sys.stdin.read()
    finally:
        server.shutdown()
        worker.join()
