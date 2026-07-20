"""Unix-socket fingerprint capture daemon.

Protocol (matches ``driveauth.matchers.finger.FingerMatcher``)::

    client → ``SCAN\\n``
    daemon → raw 256×256 uint8 image bytes (or empty / close on failure)

Decrypt-on-read of enrolled templates (``store/.bio_key`` +
``fingers/{driver_id}.enc``) stays in ``FingerMatcher.load`` — the daemon only
captures live scans. Fernet-only at-rest protection remains a known gap.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from pathlib import Path

from hardware.finger_uart import (
    FingerSensorAdapter,
    ManualFingerSensor,
    open_default_sensor,
)

logger = logging.getLogger("driveauth.hardware.finger_daemon")


class FingerDaemon:
    """Background thread accepting AF_UNIX SCAN requests."""

    def __init__(
        self,
        socket_path: str,
        sensor: FingerSensorAdapter | None = None,
        *,
        backlog: int = 4,
        sensor_kind: str | None = None,
    ):
        self._socket_path = socket_path
        self._sensor: FingerSensorAdapter = sensor or ManualFingerSensor()
        self._sensor_kind = sensor_kind or (
            "manual" if isinstance(self._sensor, ManualFingerSensor) else "injected"
        )
        self._backlog = backlog
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._sensor_ok = False

    @property
    def socket_path(self) -> str:
        return self._socket_path

    @property
    def sensor_ok(self) -> bool:
        return self._sensor_ok

    @property
    def sensor_kind(self) -> str:
        """``manual`` | ``pyfingerprint`` | ``manual_fallback`` | ``injected``."""
        return self._sensor_kind

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._ready.clear()
        self._sensor_ok = bool(self._sensor.open())
        if not self._sensor_ok:
            logger.error("FingerDaemon: sensor open failed — refusing to listen")
            return False
        path = Path(self._socket_path)
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.error("FingerDaemon: cannot clear stale socket (%s)", exc)
                self._sensor.close()
                self._sensor_ok = False
                return False
        path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(self._socket_path)
            srv.listen(self._backlog)
            srv.settimeout(0.5)
        except OSError as exc:
            logger.error("FingerDaemon: bind/listen failed (%s)", exc)
            srv.close()
            self._sensor.close()
            self._sensor_ok = False
            return False
        self._server = srv
        self._thread = threading.Thread(
            target=self._serve_loop, name="finger-daemon", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        try:
            self._sensor.close()
        except Exception:
            pass
        self._sensor_ok = False
        try:
            Path(self._socket_path).unlink(missing_ok=True)
        except OSError:
            pass

    def reconnect_sensor(self) -> bool:
        """Close and re-open the UART adapter after a drop."""
        try:
            self._sensor.close()
        except Exception:
            pass
        self._sensor_ok = bool(self._sensor.open())
        return self._sensor_ok

    def _serve_loop(self) -> None:
        assert self._server is not None
        self._ready.set()
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            try:
                self._handle_client(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(5.0)
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(64)
                if not chunk:
                    return
                buf += chunk
                if len(buf) > 64:
                    return
            cmd = buf.split(b"\n", 1)[0].strip().upper()
            if cmd != b"SCAN":
                return
            if not self._sensor_ok and not self.reconnect_sensor():
                return
            image = self._sensor.capture_image()
            if not image:
                # Soft reconnect once on empty capture, then fail closed.
                if self.reconnect_sensor():
                    image = self._sensor.capture_image()
            if image:
                conn.sendall(image)
        except Exception as exc:
            logger.warning("FingerDaemon: client handler error (%s)", type(exc).__name__)


def run_daemon_main(
    socket_path: str | None = None,
    *,
    port: str | None = None,
    manual: bool = False,
    allow_manual_fallback: bool | None = None,
) -> None:
    """CLI entry for ``python -m hardware.finger_daemon``.

    Default path: probe R307/AS608 UART via ``pyfingerprint``; if the sensor
    is absent, fall back to :class:`ManualFingerSensor` so the Unix-socket
    protocol stays available for demos (override with
    ``DRIVEAUTH_FINGER_NO_FALLBACK=1`` to fail hard instead).
    """
    from driveauth import config

    sock = socket_path or config.FINGER_SOCKET
    if allow_manual_fallback is None:
        allow_manual_fallback = os.getenv("DRIVEAUTH_FINGER_NO_FALLBACK", "0") != "1"
    try:
        sensor, kind = open_default_sensor(
            port=port,
            manual=manual,
            allow_manual_fallback=allow_manual_fallback,
        )
    except RuntimeError as exc:
        logger.error("FingerDaemon: %s", exc)
        raise SystemExit(1) from exc
    daemon = FingerDaemon(sock, sensor, sensor_kind=kind)
    if not daemon.start():
        raise SystemExit(1)
    logger.info(
        "FingerDaemon listening on %s (sensor=%s)",
        sock,
        daemon.sensor_kind,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daemon_main()
