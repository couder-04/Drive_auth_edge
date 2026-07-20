"""Opt-in fleet telemetry reporter (Phase G).

Reports auth success/fail rates, sensor-availability flags, and firmware
version to a remote endpoint. **Never** includes biometric templates,
embeddings, raw audio/images, or transcripts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("driveauth.hardware.fleet_telemetry")

# Fields that must never appear in a telemetry payload.
FORBIDDEN_KEYS = frozenset(
    {
        "embedding",
        "template",
        "audio",
        "image",
        "face_crop",
        "fingerprint",
        "transcript",
        "voice_wav",
        "raw_bio",
        "bio_key",
        "modality_scores",  # may be sensitive enough — keep out of fleet rollup
    }
)

HttpPost = Callable[[str, bytes, dict[str, str]], None]


def _default_http_post(url: str, body: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def assert_no_biometric_content(payload: dict[str, Any]) -> None:
    """Raise ``AssertionError`` if payload looks like it contains biometrics."""
    blob = json.dumps(payload).lower()
    for key in FORBIDDEN_KEYS:
        if key in payload:
            raise AssertionError(f"telemetry must not include key {key!r}")
        # nested / accidental
        if f'"{key}"' in blob and key in (
            "embedding",
            "template",
            "audio",
            "image",
            "fingerprint",
            "transcript",
            "bio_key",
        ):
            raise AssertionError(f"telemetry blob mentions forbidden {key!r}")


def build_telemetry_payload(
    *,
    vehicle_id: str,
    firmware_version: str,
    accept_count: int,
    reject_count: int,
    step_up_count: int,
    sensor_flags: dict[str, bool],
    ts: float | None = None,
) -> dict[str, Any]:
    total = accept_count + reject_count + step_up_count
    payload = {
        "schema": "driveauth.fleet_telemetry.v1",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time())),
        "vehicle_id": vehicle_id,
        "firmware_version": firmware_version,
        "auth": {
            "accept": int(accept_count),
            "reject": int(reject_count),
            "step_up": int(step_up_count),
            "total": int(total),
            "accept_rate": (accept_count / total) if total else 0.0,
            "reject_rate": (reject_count / total) if total else 0.0,
        },
        "sensors": {k: bool(v) for k, v in sensor_flags.items()},
    }
    assert_no_biometric_content(payload)
    return payload


def summarize_audit_file(audit_path: Path) -> dict[str, int]:
    counts = {"accept": 0, "reject": 0, "step_up": 0}
    if not audit_path.is_file():
        return counts
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        d = str(entry.get("decision", "")).lower()
        if d == "accept":
            counts["accept"] += 1
        elif d == "reject":
            counts["reject"] += 1
        elif "step" in d:
            counts["step_up"] += 1
    return counts


class FleetTelemetryReporter:
    """Periodically POST aggregated health. Opt-in via URL env / constructor."""

    def __init__(
        self,
        *,
        url: str | None = None,
        vehicle_id: str | None = None,
        firmware_version: str = "0.2.0",
        audit_path: Path | None = None,
        sensor_flags: dict[str, bool] | None = None,
        interval_s: float = 60.0,
        http_post: HttpPost | None = None,
    ):
        self.url = (url if url is not None else os.getenv("DRIVEAUTH_FLEET_TELEMETRY_URL", "")).strip()
        self.vehicle_id = vehicle_id or os.getenv("DRIVEAUTH_VEHICLE_ID", "local")
        self.firmware_version = firmware_version or os.getenv(
            "DRIVEAUTH_FIRMWARE_VERSION", "0.2.0"
        )
        self.audit_path = audit_path
        self.sensor_flags = dict(sensor_flags or {})
        self.interval_s = max(1.0, float(interval_s))
        self._http = http_post or _default_http_post
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_payload: dict[str, Any] | None = None
        self.send_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def build_payload(self) -> dict[str, Any]:
        counts = {"accept": 0, "reject": 0, "step_up": 0}
        if self.audit_path is not None:
            counts = summarize_audit_file(self.audit_path)
        return build_telemetry_payload(
            vehicle_id=self.vehicle_id,
            firmware_version=self.firmware_version,
            accept_count=counts["accept"],
            reject_count=counts["reject"],
            step_up_count=counts["step_up"],
            sensor_flags=self.sensor_flags,
        )

    def report_once(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload = self.build_payload()
        body = json.dumps(payload).encode("utf-8")
        try:
            self._http(
                self.url,
                body,
                {"Content-Type": "application/json", "User-Agent": "driveauth-fleet/1"},
            )
            self.send_count += 1
            self.last_payload = payload
        except Exception as exc:
            logger.warning("FleetTelemetry: post failed (%s)", type(exc).__name__)
        return payload

    def start(self) -> bool:
        if not self.enabled:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="driveauth-fleet-telemetry", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.report_once()
