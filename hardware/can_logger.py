"""Real CAN + GPS logging harness (Phase 10).

Writes timestamped CAN frames and GPS fixes to disk in schemas that drop
into the existing trainers:

* **Risk txn CSV** — same columns as ``scripts/generate_risk_txns.py`` export
  (``TXN_CSV_COLUMNS``), so real and synthetic logs are interchangeable for
  ``train_risk_gbt.py``.
* **Behavioral windows** — ``can_*.csv`` with ``BEHAVIORAL_FEATURE_KEYS``
  for ``train_behavioral_bakeoff.py``.

This does **not** invent real driving data — it only makes genuine vehicle
logs usable the moment a pilot fleet produces them. Until then, trainers
still warn when a run used zero real samples.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from driveauth.matchers.behavioral import BEHAVIORAL_FEATURE_KEYS

logger = logging.getLogger("driveauth.hardware.can_logger")

# Must match scripts/generate_risk_txns.py export_cols exactly.
TXN_CSV_COLUMNS: tuple[str, ...] = (
    "amount",
    "beneficiary",
    "beneficiary_known",
    "hour",
    "speed_kmh",
    "in_trusted_zone",
    "dist_from_home_km",
    "ignition_on",
    "is_tunnel",
    "behavioral_score",
    "label",
    "driver_id",
)

# Raw frame log (debug / replay); not used by trainers directly.
FRAME_CSV_COLUMNS: tuple[str, ...] = (
    "ts_utc",
    "arbitration_id",
    "dlc",
    "data_hex",
    "gps_lat",
    "gps_lon",
    "gps_accuracy_m",
    "speed_kmh",
)


@dataclass
class GpsFix:
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    speed_kmh: float = 0.0
    ts: float | None = None


@dataclass
class CanLoggerConfig:
    driver_id: str = "driver1"
    channel: str = "can0"
    bustype: str = "socketcan"
    bitrate: int | None = 500_000
    home_lat: float | None = None
    home_lon: float | None = None
    trusted_zone_radius_km: float = 10.0
    window_rows: int = 50
    # Payment fields are not on the CAN bus — left empty / 0 until labeled.
    default_label: str = "legit"


@dataclass
class CanLogger:
    """
    Subscribe to a ``python-can`` bus (or inject frames) and flush CSV logs.

    ``bus_factory`` is injectable for unit tests (returns an object with
    ``recv(timeout=)`` / ``shutdown()``). When omitted, imports ``can.interface``.
    """

    out_dir: Path
    config: CanLoggerConfig = field(default_factory=CanLoggerConfig)
    bus_factory: Callable[[], Any] | None = None
    gps_provider: Callable[[], GpsFix] | None = None

    def __post_init__(self) -> None:
        self.out_dir = Path(self.out_dir)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._bus: Any = None
        self._lock = threading.Lock()
        self._window: list[dict[str, float]] = []
        self._txn_rows: list[dict[str, Any]] = []
        self._frame_rows: list[dict[str, Any]] = []
        self._last_gps = GpsFix()
        self._window_idx = 0

    # ── paths ───────────────────────────────────────────────────────────────

    @property
    def txn_csv_path(self) -> Path:
        return self.out_dir / "transaction" / "txns_real.csv"

    @property
    def frames_csv_path(self) -> Path:
        return self.out_dir / "can_frames.csv"

    @property
    def behavioral_genuine_dir(self) -> Path:
        return self.out_dir / "behavioral" / "genuine"

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.behavioral_genuine_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "transaction").mkdir(parents=True, exist_ok=True)
        try:
            if self.bus_factory is not None:
                self._bus = self.bus_factory()
            else:
                import can  # type: ignore

                kwargs: dict[str, Any] = {
                    "channel": self.config.channel,
                    "bustype": self.config.bustype,
                }
                if self.config.bitrate is not None:
                    kwargs["bitrate"] = self.config.bitrate
                self._bus = can.interface.Bus(**kwargs)
        except Exception as exc:
            logger.warning("CanLogger: bus open failed (%s)", type(exc).__name__)
            self._bus = None
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="can-logger", daemon=True
        )
        self._thread.start()
        logger.info("CanLogger: started on %s → %s", self.config.channel, self.out_dir)
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None
        self.flush()

    def flush(self) -> None:
        with self._lock:
            self._write_txn_rows(self._txn_rows)
            self._write_frame_rows(self._frame_rows)
            if len(self._window) >= 5:
                self._flush_window_locked()

    # ── inject / decode ─────────────────────────────────────────────────────

    def ingest_frame(
        self,
        *,
        arbitration_id: int,
        data: bytes,
        timestamp: float | None = None,
        gps: GpsFix | None = None,
    ) -> None:
        """Test / alternate-path entry: push one frame without a live bus."""
        ts = timestamp if timestamp is not None else time.time()
        fix = gps if gps is not None else self._poll_gps()
        self._handle_frame(arbitration_id, data, ts, fix)

    def record_txn_snapshot(
        self,
        *,
        amount: float = 0.0,
        beneficiary: str = "",
        beneficiary_known: int = 0,
        label: str | None = None,
        behavioral_score: float | None = None,
    ) -> dict[str, Any]:
        """
        Append one risk-trainer row from the latest telematics snapshot.

        Payment fields are supplied by the caller (CAN cannot invent them).
        """
        fix = self._poll_gps()
        dist, in_zone = self._geo(fix)
        hour = datetime.now(timezone.utc).hour
        row = {
            "amount": float(amount),
            "beneficiary": beneficiary,
            "beneficiary_known": int(beneficiary_known),
            "hour": int(hour),
            "speed_kmh": float(fix.speed_kmh),
            "in_trusted_zone": int(in_zone),
            "dist_from_home_km": float(dist),
            "ignition_on": 1,
            "is_tunnel": 0,
            "behavioral_score": (
                float(behavioral_score) if behavioral_score is not None else 0.85
            ),
            "label": label or self.config.default_label,
            "driver_id": self.config.driver_id,
        }
        with self._lock:
            self._txn_rows.append(row)
        return row

    # ── internals ───────────────────────────────────────────────────────────

    def _loop(self) -> None:
        assert self._bus is not None
        while not self._stop.is_set():
            try:
                msg = self._bus.recv(timeout=0.25)
            except Exception as exc:
                logger.warning("CanLogger: recv failed (%s)", type(exc).__name__)
                continue
            if msg is None:
                continue
            data = bytes(getattr(msg, "data", b"") or b"")
            arb = int(getattr(msg, "arbitration_id", 0))
            ts = float(getattr(msg, "timestamp", time.time()) or time.time())
            self._handle_frame(arb, data, ts, self._poll_gps())

    def _poll_gps(self) -> GpsFix:
        if self.gps_provider is not None:
            try:
                fix = self.gps_provider()
                if fix is not None:
                    self._last_gps = fix
                    return fix
            except Exception as exc:
                logger.info("CanLogger: gps_provider failed (%s)", type(exc).__name__)
        return self._last_gps

    def _handle_frame(
        self, arbitration_id: int, data: bytes, ts: float, fix: GpsFix
    ) -> None:
        feat = self._decode_features(arbitration_id, data, fix)
        with self._lock:
            self._frame_rows.append(
                {
                    "ts_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "arbitration_id": f"0x{arbitration_id:X}",
                    "dlc": len(data),
                    "data_hex": data.hex(),
                    "gps_lat": fix.lat if fix.lat is not None else "",
                    "gps_lon": fix.lon if fix.lon is not None else "",
                    "gps_accuracy_m": (
                        fix.accuracy_m if fix.accuracy_m is not None else ""
                    ),
                    "speed_kmh": fix.speed_kmh,
                }
            )
            self._window.append(feat)
            if len(self._window) >= self.config.window_rows:
                self._flush_window_locked()

    def _flush_window_locked(self) -> None:
        if not self._window:
            return
        self._window_idx += 1
        path = self.behavioral_genuine_dir / f"can_{self._window_idx:04d}.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(BEHAVIORAL_FEATURE_KEYS))
            w.writeheader()
            for row in self._window:
                w.writerow({k: f"{row[k]:.6f}" for k in BEHAVIORAL_FEATURE_KEYS})
        self._window = []

    def _decode_features(
        self, arbitration_id: int, data: bytes, fix: GpsFix
    ) -> dict[str, float]:
        """
        Best-effort decode. Without a vehicle-specific DBC we derive a stable
        feature vector from GPS speed + raw bytes so windows remain schema-
        compatible; integrators should replace this with a DBC decoder.
        """
        b = list(data) + [0] * 8
        speed = float(fix.speed_kmh)
        return {
            "steering_angle_deg": (b[0] - 127) * 0.5,
            "steering_rate_dps": (b[1] - 127) * 0.25,
            "throttle_pct": min(100.0, b[2] / 2.55),
            "brake_pedal_pct": min(100.0, b[3] / 2.55),
            "longitudinal_accel_g": (b[4] - 127) / 127.0,
            "lateral_accel_g": (b[5] - 127) / 127.0,
            "yaw_rate_dps": (b[6] - 127) * 0.5,
            "vehicle_speed_kmh": speed if speed > 0 else float(b[7]),
        }

    def _geo(self, fix: GpsFix) -> tuple[float, bool]:
        if (
            fix.lat is None
            or fix.lon is None
            or self.config.home_lat is None
            or self.config.home_lon is None
        ):
            return 0.0, True
        from driveauth.geo import location_context

        return location_context(
            gps_lat=fix.lat,
            gps_lon=fix.lon,
            home_lat=self.config.home_lat,
            home_lon=self.config.home_lon,
            trusted_zone_radius_km=self.config.trusted_zone_radius_km,
        )

    def _write_txn_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        path = self.txn_csv_path
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(TXN_CSV_COLUMNS))
            if write_header:
                w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in TXN_CSV_COLUMNS})
        rows.clear()

    def _write_frame_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        path = self.frames_csv_path
        write_header = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(FRAME_CSV_COLUMNS))
            if write_header:
                w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in FRAME_CSV_COLUMNS})
        rows.clear()


def txn_schema_dtypes() -> dict[str, str]:
    """Canonical dtypes for schema-compatibility tests (logical types)."""
    return {
        "amount": "float",
        "beneficiary": "str",
        "beneficiary_known": "int",
        "hour": "int",
        "speed_kmh": "float",
        "in_trusted_zone": "int",
        "dist_from_home_km": "float",
        "ignition_on": "int",
        "is_tunnel": "int",
        "behavioral_score": "float",
        "label": "str",
        "driver_id": "str",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="DriveAuth CAN/GPS logger")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--channel", default="can0")
    ap.add_argument("--bustype", default="socketcan")
    ap.add_argument("--home-lat", type=float, default=None)
    ap.add_argument("--home-lon", type=float, default=None)
    args = ap.parse_args(argv)
    cfg = CanLoggerConfig(
        driver_id=args.driver_id,
        channel=args.channel,
        bustype=args.bustype,
        home_lat=args.home_lat,
        home_lon=args.home_lon,
    )
    logger_ = CanLogger(out_dir=args.out, config=cfg)
    if not logger_.start():
        return 1
    print(f"Logging to {args.out} (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        logger_.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
