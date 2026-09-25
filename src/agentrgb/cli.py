"""Установка, запуск и диагностика локального AgentRGB."""
import argparse
import http.client
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
import platform
import socket
import sys


def core_status(port):
    # HTTPConnection обращается прямо к loopback, без HTTP_PROXY/HTTPS_PROXY.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        body = response.read(1025)
        if (response.status == 200 and len(body) <= 1024
                and json.loads(body) == {"status": "ok", "service": "agentrgb"}):
            return "running"
    except ConnectionRefusedError:
        return "not running"
    except (OSError, http.client.HTTPException, ValueError):
        pass
    finally:
        connection.close()
    return "unavailable"


def show_status(port):
    status = core_status(port)
    print(f"AgentRGB Core: {status}")
    print(f"Address: 127.0.0.1:{port}")
    return status


def port_available(port):
    # Отказ соединения ещё не исключает процесс, занявший порт без listen().
    with socket.socket() as probe:
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def doctor(port):
    print(f"Python: {platform.python_version()}")
    failed = False
    try:
        print(f"AgentRGB: {version('agentrgb')}")
    except PackageNotFoundError:
        print("AgentRGB: not installed")
        failed = True
    try:
        for module in ("protocol", "state", "fake", "server",
                       "outputs.aula_f75", "outputs.windows_hid"):
            importlib.import_module(f"agentrgb.{module}")
        from .outputs.aula_f75_diagnostics import check_f75
    except Exception:
        print("Production modules: import failed")
        return 1
    print("Production modules: ok")
    status = show_status(port)
    port_status = {"running": "in use (AgentRGB)", "not running": "available",
                   "unavailable": "in use or unavailable"}
    port_state = port_status[status]
    if status == "not running" and not port_available(port):
        port_state = "in use or unavailable"
    print(f"Port {port}: {port_state}")
    device_result = check_f75()
    return int(failed or port_state == "in use or unavailable" or device_result != 0)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentrgb", description="Локальная RGB-индикация агентов.")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="запустить Core в текущем терминале")
    start.add_argument("--output", choices=("fake", "aula-f75"), default="fake")
    commands.add_parser("status", help="проверить Core через localhost HTTP")
    commands.add_parser("doctor", help="проверить программу, Core и F75 (identity read)")
    args = parser.parse_args(argv)
    try:
        port = int(os.environ.get("AGENTRGB_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        parser.error("AGENTRGB_PORT must be an integer from 1 to 65535")
    try:
        if args.command == "start":
            from . import server
            server.main(["--output", args.output])
            return 0
        if args.command == "status":
            return int(show_status(port) != "running")
        return doctor(port)
    except KeyboardInterrupt:
        print("AgentRGB: interrupted", file=sys.stderr)
        return 1
    except (OSError, ValueError, ImportError):
        print(f"AgentRGB: {args.command} failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
