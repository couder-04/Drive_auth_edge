#!/usr/bin/env python3
"""Run the DriveAuth Edge dashboard server."""

from __future__ import annotations

import argparse
import os
import socket
import sys


def _port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _resolve_port(host: str, preferred: int, *, strict: bool) -> int:
    if _port_free(host, preferred):
        return preferred
    if strict:
        print(
            f"error: {host}:{preferred} is already in use "
            f"(another dashboard may be running). Pass --port <n> or free the port.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    for candidate in range(preferred + 1, preferred + 50):
        if _port_free(host, candidate):
            print(
                f"note: {host}:{preferred} busy — binding to {candidate} instead "
                f"(pass --port {preferred} to require that port)",
                file=sys.stderr,
            )
            return candidate
    print(f"error: no free port near {preferred}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="DriveAuth Edge dashboard server")
    parser.add_argument(
        "--host", default=os.getenv("DRIVEAUTH_DASHBOARD_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("DRIVEAUTH_DASHBOARD_PORT", "8765"))
    )
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail if --port is taken instead of trying the next free port",
    )
    parser.add_argument(
        "--reload", action="store_true", help="Auto-reload on code changes"
    )
    parser.add_argument(
        "--store",
        default=os.getenv("DRIVEAUTH_DASHBOARD_STORE", ""),
        help="Persistent store dir",
    )
    args = parser.parse_args()

    if args.store:
        os.environ["DRIVEAUTH_DASHBOARD_STORE"] = args.store

    port = _resolve_port(args.host, args.port, strict=args.strict_port)

    import uvicorn

    print(f"DriveAuth dashboard: http://{args.host}:{port}")
    uvicorn.run(
        "dashboard.app:app",
        host=args.host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
