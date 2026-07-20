"""Always-on performance telemetry (latency + CPU/RAM) — not a security audit.

Writes rotating CSV rows for per-decision modality inference latency and
periodic host utilization. Distinct from :mod:`driveauth.audit_log` (security
events) and :mod:`hardware.fleet_telemetry` (opt-in fleet rollup).
"""

from __future__ import annotations

import csv
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("driveauth.perf_telemetry")

SCHEMA_VERSION = "driveauth.perf_telemetry.v1"
CSV_COLUMNS = (
    "ts",
    "event",
    "session_id",
    "driver_id",
    "decision",
    "voice_ms",
    "face_ms",
    "finger_ms",
    "liveness_ms",
    "total_ms",
    "cpu_pct",
    "ram_pct",
    "ram_used_mb",
    "face_backend",
)

DEFAULT_LOG_PATH = os.getenv(
    "DRIVEAUTH_PERF_LOG",
    str(Path.home() / ".driveauth" / "perf" / "perf.csv"),
)
DEFAULT_MAX_BYTES = int(os.getenv("DRIVEAUTH_PERF_LOG_MAX_BYTES", str(2 * 1024 * 1024)))
DEFAULT_BACKUP_COUNT = int(os.getenv("DRIVEAUTH_PERF_LOG_BACKUPS", "3"))
DEFAULT_UTIL_INTERVAL_S = float(os.getenv("DRIVEAUTH_PERF_UTIL_INTERVAL_S", "30"))

PsutilSnapshot = Callable[[], dict[str, float | None]]


def _default_psutil_snapshot() -> dict[str, float | None]:
    try:
        import psutil  # type: ignore
    except ImportError:
        return {"cpu_pct": None, "ram_pct": None, "ram_used_mb": None}
    try:
        mem = psutil.virtual_memory()
        # Non-blocking after first call; interval=None uses last cached delta.
        cpu = float(psutil.cpu_percent(interval=None))
        return {
            "cpu_pct": cpu,
            "ram_pct": float(mem.percent),
            "ram_used_mb": float(mem.used) / (1024 * 1024),
        }
    except Exception as exc:
        logger.debug("perf_telemetry: psutil snapshot failed (%s)", type(exc).__name__)
        return {"cpu_pct": None, "ram_pct": None, "ram_used_mb": None}


def resolve_face_backend() -> str:
    """Return ``hailo`` or ``cpu``/``onnx`` indicator for the active face path."""
    try:
        from driveauth import config

        backend = str(getattr(config, "FACE_BACKEND", "onnx") or "onnx").strip().lower()
        if backend == "hailo":
            return "hailo"
        return "cpu"
    except Exception:
        return "cpu"


class PerfTelemetry:
    """Thread-safe CSV writer with size-based rotation."""

    def __init__(
        self,
        log_path: str | Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        util_interval_s: float = DEFAULT_UTIL_INTERVAL_S,
        psutil_snapshot: PsutilSnapshot | None = None,
        enabled: bool | None = None,
        recent_maxlen: int = 64,
        auto_util: bool = True,
    ):
        env_disabled = os.getenv("DRIVEAUTH_PERF_TELEMETRY", "1") == "0"
        self.enabled = (not env_disabled) if enabled is None else bool(enabled)
        self._path = Path(log_path or DEFAULT_LOG_PATH).expanduser()
        self._max_bytes = max(1024, int(max_bytes))
        self._backup_count = max(0, int(backup_count))
        self._util_interval_s = max(1.0, float(util_interval_s))
        self._psutil_snapshot = psutil_snapshot or _default_psutil_snapshot
        self._lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max(1, recent_maxlen))
        self._last_util: dict[str, Any] | None = None
        self._util_thread: threading.Thread | None = None
        self._util_stop = threading.Event()
        if self.enabled and auto_util:
            self.start_util_sampler()

    @property
    def path(self) -> Path:
        return self._path

    def start_util_sampler(self) -> None:
        if not self.enabled:
            return
        if self._util_thread is not None and self._util_thread.is_alive():
            return
        self._util_stop.clear()
        self._util_thread = threading.Thread(
            target=self._util_loop,
            name="driveauth-perf-util",
            daemon=True,
        )
        self._util_thread.start()

    def stop_util_sampler(self) -> None:
        self._util_stop.set()
        t = self._util_thread
        if t is not None:
            t.join(timeout=2.0)
        self._util_thread = None

    def _util_loop(self) -> None:
        # Prime psutil cpu_percent baseline.
        try:
            self._psutil_snapshot()
        except Exception:
            pass
        while not self._util_stop.wait(self._util_interval_s):
            try:
                self.record_utilization()
            except Exception as exc:
                logger.debug(
                    "perf_telemetry: util sample failed (%s)", type(exc).__name__
                )

    def record_decision(
        self,
        *,
        session_id: str = "",
        driver_id: str = "",
        decision: str = "",
        voice_ms: float | None = None,
        face_ms: float | None = None,
        finger_ms: float | None = None,
        liveness_ms: float | None = None,
        total_ms: float | None = None,
        face_backend: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        util = self._psutil_snapshot()
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "decision",
            "session_id": session_id,
            "driver_id": driver_id,
            "decision": decision,
            "voice_ms": _fmt_ms(voice_ms),
            "face_ms": _fmt_ms(face_ms),
            "finger_ms": _fmt_ms(finger_ms),
            "liveness_ms": _fmt_ms(liveness_ms),
            "total_ms": _fmt_ms(total_ms),
            "cpu_pct": _fmt_num(util.get("cpu_pct")),
            "ram_pct": _fmt_num(util.get("ram_pct")),
            "ram_used_mb": _fmt_num(util.get("ram_used_mb")),
            "face_backend": face_backend or resolve_face_backend(),
        }
        self._append(row)
        return row

    def record_from_modality_results(
        self,
        results: dict[str, Any],
        *,
        session_id: str = "",
        driver_id: str = "",
        decision: str = "",
        total_ms: float | None = None,
        liveness_ms: float | None = None,
        face_backend: str | None = None,
    ) -> dict[str, Any] | None:
        """Pull ``latency_ms`` off :class:`ModalityResult`-like objects."""

        def _lat(name: str) -> float | None:
            r = results.get(name)
            if r is None:
                return None
            val = getattr(r, "latency_ms", None)
            if val is None and isinstance(r, dict):
                val = r.get("latency_ms")
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        return self.record_decision(
            session_id=session_id,
            driver_id=driver_id,
            decision=decision,
            voice_ms=_lat("voice"),
            face_ms=_lat("face"),
            finger_ms=_lat("finger"),
            liveness_ms=liveness_ms if liveness_ms is not None else _lat("liveness"),
            total_ms=total_ms,
            face_backend=face_backend,
        )

    def record_utilization(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        util = self._psutil_snapshot()
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "util",
            "session_id": "",
            "driver_id": "",
            "decision": "",
            "voice_ms": "",
            "face_ms": "",
            "finger_ms": "",
            "liveness_ms": "",
            "total_ms": "",
            "cpu_pct": _fmt_num(util.get("cpu_pct")),
            "ram_pct": _fmt_num(util.get("ram_pct")),
            "ram_used_mb": _fmt_num(util.get("ram_used_mb")),
            "face_backend": resolve_face_backend(),
        }
        self._append(row)
        with self._lock:
            self._last_util = dict(row)
        return row

    def recent_rows(self, n: int = 32) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        return items[-max(0, n) :]

    def summary(self) -> dict[str, Any]:
        """Dashboard-friendly rollup of recent decision latencies + last util."""
        with self._lock:
            rows = [r for r in self._recent if r.get("event") == "decision"]
            last_util = dict(self._last_util) if self._last_util else None

        def _mean(key: str) -> float | None:
            vals = []
            for r in rows:
                try:
                    v = r.get(key)
                    if v is None or v == "":
                        continue
                    vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not vals:
                return None
            return sum(vals) / len(vals)

        return {
            "schema": SCHEMA_VERSION,
            "enabled": self.enabled,
            "path": str(self._path),
            "face_backend": resolve_face_backend(),
            "decisions_recent": len(rows),
            "latency_ms_avg": {
                "voice": _mean("voice_ms"),
                "face": _mean("face_ms"),
                "finger": _mean("finger_ms"),
                "liveness": _mean("liveness_ms"),
                "total": _mean("total_ms"),
            },
            "utilization": last_util
            or {
                "cpu_pct": None,
                "ram_pct": None,
                "ram_used_mb": None,
            },
            "recent": rows[-8:],
        }

    def _append(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._recent.append(dict(row))
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                write_header = not self._path.exists() or self._path.stat().st_size == 0
                with self._path.open("a", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                    if write_header:
                        writer.writeheader()
                    writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
            except OSError as exc:
                logger.warning(
                    "perf_telemetry: write failed (%s)", type(exc).__name__
                )

    def _rotate_if_needed(self) -> None:
        if not self._path.exists():
            return
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size < self._max_bytes:
            return
        if self._backup_count <= 0:
            try:
                self._path.unlink()
            except OSError:
                pass
            return
        oldest = Path(f"{self._path}.{self._backup_count}")
        oldest.unlink(missing_ok=True)
        for i in range(self._backup_count - 1, 0, -1):
            src = Path(f"{self._path}.{i}")
            dst = Path(f"{self._path}.{i + 1}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    pass
        try:
            self._path.replace(Path(f"{self._path}.1"))
        except OSError as exc:
            logger.warning("perf_telemetry: rotate failed (%s)", type(exc).__name__)


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return ""


def _fmt_num(v: Any) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return ""


# Process-wide default (lazy). Tests can replace via ``set_default_telemetry``.
_default: PerfTelemetry | None = None
_default_lock = threading.Lock()


def get_default_telemetry() -> PerfTelemetry:
    global _default
    with _default_lock:
        if _default is None:
            _default = PerfTelemetry()
        return _default


def set_default_telemetry(telemetry: PerfTelemetry | None) -> None:
    global _default
    with _default_lock:
        if _default is not None:
            try:
                _default.stop_util_sampler()
            except Exception:
                pass
        _default = telemetry


def reset_default_telemetry() -> None:
    set_default_telemetry(None)
