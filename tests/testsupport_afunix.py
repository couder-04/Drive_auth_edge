"""Shared skip when AF_UNIX bind is denied (Cursor agent / seatbelt sandboxes)."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest


def af_unix_bind_denied() -> tuple[bool, str]:
    """Return (denied, detail) by probing a short-lived AF_UNIX bind.

    Cursor agent / macOS seatbelt sandboxes often allow TCP + filesystem writes
    but deny ``socket.AF_UNIX`` bind with ``PermissionError: [Errno 1]
    Operation not permitted``. That is environmental — not a FingerDaemon logic
    bug. A normal Terminal.app / CI runner without that restriction should bind.
    """
    path = f"/tmp/driveauth_afunix_probe_{os.getpid()}.sock"
    try:
        Path(path).unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(path)
            srv.listen(1)
        finally:
            srv.close()
            Path(path).unlink(missing_ok=True)
        return False, "AF_UNIX bind OK"
    except OSError as exc:
        return True, f"{type(exc).__name__}: {exc} (path={path})"


_DENIED, _DETAIL = af_unix_bind_denied()

requires_af_unix = pytest.mark.skipif(
    _DENIED,
    reason=(
        "AF_UNIX bind denied in this environment "
        f"({_DETAIL}). FingerDaemon needs a Unix domain socket; TCP bind still "
        "works here — Cursor/seatbelt sandbox limitation, not a daemon bug. "
        "Re-run in Terminal.app or unsandboxed CI to exercise these tests."
    ),
)
