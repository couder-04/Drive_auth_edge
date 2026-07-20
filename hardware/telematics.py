"""Live GPS / CAN ingestion → ``DriveAuth.update_vehicle_context``.

Keeps the ``update_vehicle_context(**kwargs)`` signature unchanged. Malformed
or dropped frames must not crash or silently inject risk-relevant garbage —
bad samples are skipped (fail-closed for freshness, not for fabricating data).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger("driveauth.hardware.telematics")

# Keys accepted by RiskContext / update_vehicle_context.
_ALLOWED_KEYS = frozenset(
    {
        "gps_lat",
        "gps_lon",
        "gps_accuracy_m",
        "speed_kmh",
        "ignition_on",
        "is_tunnel",
        "time_hour",
    }
)


@runtime_checkable
class GPSReader(Protocol):
    def read(self) -> dict[str, Any] | None:
        """Return a fix dict or None when no fix available."""
        ...


@runtime_checkable
class CANReader(Protocol):
    def read(self) -> dict[str, Any] | None:
        """Return CAN-derived fields (speed, ignition, …) or None."""
        ...


class MockGPSReader:
    def __init__(self, fix: dict[str, Any] | None = None):
        self.fix = fix

    def read(self) -> dict[str, Any] | None:
        return None if self.fix is None else dict(self.fix)


class MockCANReader:
    def __init__(self, frame: dict[str, Any] | None = None):
        self.frame = frame

    def read(self) -> dict[str, Any] | None:
        return None if self.frame is None else dict(self.frame)


def sanitize_vehicle_fields(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Drop unknown keys and non-finite / out-of-range values."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key not in _ALLOWED_KEYS:
            continue
        try:
            if key in ("gps_lat", "gps_lon", "gps_accuracy_m", "speed_kmh", "time_hour"):
                num = float(val)
                if num != num or abs(num) == float("inf"):  # NaN / Inf
                    continue
                if key == "gps_lat" and not (-90.0 <= num <= 90.0):
                    continue
                if key == "gps_lon" and not (-180.0 <= num <= 180.0):
                    continue
                if key == "gps_accuracy_m" and not (0.0 <= num <= 50_000.0):
                    continue
                if key == "speed_kmh" and not (0.0 <= num <= 400.0):
                    continue
                if key == "time_hour" and not (0.0 <= num <= 24.0):
                    continue
                out[key] = num
            elif key in ("ignition_on", "is_tunnel"):
                out[key] = bool(val)
        except (TypeError, ValueError):
            continue
    return out


class TelematicsIngest:
    """Poll GPS/CAN backends and push sanitized fields into DriveAuth."""

    def __init__(
        self,
        update_fn: Callable[..., None],
        *,
        gps: GPSReader | None = None,
        can: CANReader | None = None,
        interval_s: float = 0.5,
    ):
        self._update = update_fn
        self._gps = gps
        self._can = can
        self._interval_s = float(interval_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_applied: dict[str, Any] = {}

    def poll_once(self) -> dict[str, Any]:
        """Read once, sanitize, and call ``update_vehicle_context`` if non-empty."""
        merged: dict[str, Any] = {}
        for reader in (self._gps, self._can):
            if reader is None:
                continue
            try:
                raw = reader.read()
            except Exception as exc:
                logger.warning("TelematicsIngest: reader failed (%s)", type(exc).__name__)
                continue
            merged.update(sanitize_vehicle_fields(raw))
        if merged:
            try:
                self._update(**merged)
                self.last_applied = merged
            except Exception as exc:
                logger.error("TelematicsIngest: update failed (%s)", type(exc).__name__)
                return {}
        return merged

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="telematics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._interval_s)
            # Keep loop responsive even if interval is large.
            time.sleep(0)
