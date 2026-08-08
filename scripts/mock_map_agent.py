#!/usr/bin/env python3
"""Dev-only stub: log MAP OTP payloads instead of pushing over OBEX.

Usage::

    python scripts/mock_map_agent.py
    # In another shell, inject delivery with map_send pointing at a logger.

Does NOT implement real OBEX — use for local ladder OTP wiring tests only.
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("mock_map_agent")


def map_send(mac: str, payload: str) -> bool:
    log.info("MOCK MAP -> %s : %s", mac, payload[:120])
    return True


if __name__ == "__main__":
    mac = sys.argv[1] if len(sys.argv) > 1 else "AA:BB:CC:DD:EE:FF"
    msg = sys.argv[2] if len(sys.argv) > 2 else '{"code":"123456"}'
    ok = map_send(mac, msg)
    raise SystemExit(0 if ok else 1)
