"""
Per-driver profile store — the single source of truth for "how well do we know
this driver yet" (fix #6: bootstrap/history unification).

Two subsystems previously disagreed about profile maturity:
  * FraudStateMachine tracked suspicion, not novelty.
  * RiskModel needed per-user amount_mean/std but nothing populated or aged them.

This module unifies both into one profile record with an explicit
``maturity`` derived from BOTH transaction count AND recency, so a returning
driver after a long gap, or a used car with a new owner, is treated as
"unknown" rather than "trusted-because-there-is-stale-history".

It also owns OOD-baseline versioning + a refresh guard (fix #6): an OOD baseline
may only be refreshed immediately after an independently-strong auth, closing
the same slow-drift attack surface the template-topup guard already closed.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from driveauth import config, geo
from driveauth.types import RiskContext

logger = logging.getLogger("driveauth.profile")

# Serialize atomic read-modify-write across ProfileStore instances that share
# the same on-disk path (dashboard mock vs live auth both touch profiles/).
_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _file_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


@dataclass
class DriverProfile:
    driver_id: str
    created_at: float = 0.0
    last_txn_at: float = 0.0
    txn_count: int = 0
    # Rolling transaction-amount stats consumed by RiskModel.
    amount_mean: float = 0.0
    amount_m2: float = 0.0  # Welford's aggregate for variance
    # OOD baseline provenance (fix #6): refreshes are gated + versioned.
    ood_version: int = 0
    ood_last_refresh_at: float = 0.0
    # Home location learned online from GPS on successful auths (review fix #3).
    # ``home_n`` counts the samples that have contributed so we can Welford-
    # update lat/lon incrementally. Left as ``None`` until at least one good
    # fix has been observed, so ``location_context`` stays fail-neutral in the
    # bootstrap window rather than treating an unlearned home as (0, 0).
    home_lat: float | None = None
    home_lon: float | None = None
    home_n: int = 0
    home_last_update_at: float = 0.0
    # Schema version for migration safety (fix #7); bumped to 3 in this
    # release to add the home-learning fields above.
    schema_version: int = config.PROFILE_SCHEMA_VERSION

    @property
    def amount_std(self) -> float:
        if self.txn_count < 2:
            return 0.0
        return (self.amount_m2 / (self.txn_count - 1)) ** 0.5


class ProfileStore:
    """Loads/persists a DriverProfile and derives maturity."""

    def __init__(self, path: Path, driver_id: str):
        self._path = path
        self._driver = driver_id
        self._lock = threading.Lock()
        self._p = DriverProfile(driver_id=driver_id, created_at=time.time())
        self._load()

    # ── persistence (schema-migration aware, fix #7) ─────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text()).get(self._driver)
            if not raw:
                return
            migrated = _migrate(raw)
            # Only assign known fields so a rolled-back binary reading a newer
            # record (or vice-versa) never crashes on an unexpected key.
            known = {
                k: migrated[k] for k in migrated if k in DriverProfile.__annotations__
            }
            self._p = DriverProfile(**{**asdict(self._p), **known})
        except Exception as exc:
            logger.warning("ProfileStore: load failed (%s) — starting fresh", exc)

    def _write_unlocked(self) -> None:
        """Persist ``self._p``; caller must hold ``_file_lock_for(self._path)``."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            alldata = {}
            if self._path.exists():
                try:
                    alldata = json.loads(self._path.read_text())
                except Exception:
                    alldata = {}
            alldata[self._driver] = asdict(self._p)
            # Unique tmp per write — shared ``driver1.tmp`` raced under load
            # (Errno 2 on replace + occasional concatenated JSON).
            tmp = self._path.with_name(
                f"{self._path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp.write_text(json.dumps(alldata))
            tmp.replace(self._path)  # atomic write — no half-written schema (fix #7)
        except Exception as exc:
            logger.warning("ProfileStore: save failed (%s)", exc)
            try:
                if "tmp" in locals() and tmp.exists():
                    tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _save(self) -> None:
        # Per-path lock (not self._lock): callers may already hold self._lock,
        # and distinct ProfileStore instances can share one JSON file.
        with _file_lock_for(self._path):
            self._write_unlocked()

    def _mutate(self, fn) -> None:
        """Reload from disk, apply ``fn(self._p)``, write — under the file lock."""
        with _file_lock_for(self._path):
            with self._lock:
                self._load()
                fn(self._p)
            self._write_unlocked()

    # ── maturity (fix #6) ────────────────────────────────────────────────────

    def is_mature(self) -> bool:
        """
        A profile is mature only if it has BOTH enough transactions AND recent
        activity. Stale-but-present history does not count as maturity.
        """
        with self._lock:
            enough = self._p.txn_count >= config.BOOTSTRAP_MIN_TXNS
            gap_days = (
                (time.time() - self._p.last_txn_at) / 86400.0
                if self._p.last_txn_at
                else 1e9
            )
            recent = gap_days <= config.PROFILE_STALE_DAYS
            age_days = (time.time() - self._p.created_at) / 86400.0
            old_enough = age_days >= config.BOOTSTRAP_MIN_DAYS
            return enough and recent and old_enough

    def maturity_reason(self) -> str:
        with self._lock:
            if self._p.txn_count < config.BOOTSTRAP_MIN_TXNS:
                return f"bootstrap_txns_{self._p.txn_count}/{config.BOOTSTRAP_MIN_TXNS}"
            gap_days = (
                (time.time() - self._p.last_txn_at) / 86400.0
                if self._p.last_txn_at
                else 1e9
            )
            if gap_days > config.PROFILE_STALE_DAYS:
                return f"stale_{int(gap_days)}d_gap"
            age_days = (time.time() - self._p.created_at) / 86400.0
            if age_days < config.BOOTSTRAP_MIN_DAYS:
                return f"bootstrap_age_{int(age_days)}d"
            return "mature"

    def seed_mature(self, typical_amount: float = 120.0) -> None:
        """
        Backfill enough recent history for demos/tests so ACCEPT is reachable.

        Fresh stores start in bootstrap (force_step_up). Without this, every
        happy-path micro payment is forced to STEP_UP_REQUIRED.
        """
        n = max(int(config.BOOTSTRAP_MIN_TXNS), 1)
        age_s = max(float(config.BOOTSTRAP_MIN_DAYS), 1.0) * 86400.0 + 3600.0

        def _reset(p: DriverProfile) -> None:
            p.created_at = time.time() - age_s
            p.txn_count = 0
            p.amount_mean = 0.0
            p.amount_m2 = 0.0
            p.last_txn_at = 0.0

        self._mutate(_reset)
        for _ in range(n):
            self.record_transaction(typical_amount)

    def reset_bootstrap(self) -> None:
        """Clear history so the next auth sees an immature (bootstrap) profile."""
        with _file_lock_for(self._path):
            with self._lock:
                self._p = DriverProfile(driver_id=self._driver, created_at=time.time())
            self._write_unlocked()

    def apply_to_context(self, ctx: RiskContext) -> RiskContext:
        """Populate the RiskContext's per-user history fields from the profile.

        Also computes ``dist_from_home_km`` / ``in_trusted_zone`` from the
        current GPS fix and the learned home (review fix #3). To stay
        backwards-compatible with callers that manually set these via
        :meth:`DriveAuth.update_vehicle_context` (see ``payment_step_up``
        example), we only overwrite when the fields still hold their
        RiskContext dataclass defaults *and* a GPS fix is available. That way
        an explicit override always wins; the profile only fills in the gap
        when nothing external supplied a value.
        """
        with self._lock:
            ctx.amount_mean = self._p.amount_mean
            ctx.amount_std = self._p.amount_std
        # Compute geo only when GPS is present and the caller hasn't already
        # supplied a value. The neutral defaults are dist_from_home_km=0.0 and
        # in_trusted_zone=True; treating them as "unset" is safe because the
        # only real thing they could mean coming from a caller is "definitely
        # at home" -- and the same values fall out of `location_context` in
        # that case, so we don't clobber real signals.
        if ctx.gps_lat is not None and ctx.gps_lon is not None:
            caller_set_dist = ctx.dist_from_home_km != 0.0
            caller_set_zone = ctx.in_trusted_zone is not True  # explicit False
            if not (caller_set_dist or caller_set_zone):
                dist, in_zone = self.location_context(ctx.gps_lat, ctx.gps_lon)
                ctx.dist_from_home_km = dist
                ctx.in_trusted_zone = in_zone
        return ctx

    # ── updates ──────────────────────────────────────────────────────────────

    def record_transaction(self, amount: float) -> None:
        """Welford online update of amount stats after a completed transaction."""

        def _apply(p: DriverProfile) -> None:
            p.txn_count += 1
            delta = amount - p.amount_mean
            p.amount_mean += delta / p.txn_count
            p.amount_m2 += delta * (amount - p.amount_mean)
            p.last_txn_at = time.time()

        self._mutate(_apply)

    def set_home(self, lat: float, lon: float) -> None:
        """Explicit home pin (register Maps picker) — distance live immediately."""

        def _apply(p: DriverProfile) -> None:
            p.home_lat = float(lat)
            p.home_lon = float(lon)
            p.home_n = max(int(p.home_n), int(config.HOME_LEARN_MIN_SAMPLES))
            p.home_last_update_at = time.time()

        self._mutate(_apply)

    def home_coords(self) -> tuple[float | None, float | None, int]:
        with self._lock:
            return self._p.home_lat, self._p.home_lon, int(self._p.home_n)

    def record_location(
        self,
        gps_lat: float | None,
        gps_lon: float | None,
        gps_accuracy_m: float | None = None,
    ) -> None:
        """
        Learn home location online from a successful-auth GPS fix (fix #3).

        Called by the API layer after ``Decision.ACCEPT`` so we only aggregate
        locations where we're confident the enrolled driver was really there.
        Bad fixes (accuracy above the configured threshold) are dropped; this
        keeps a single tunnel-exit drift or spoofed low-accuracy fix from
        yanking the learned centre. Uses a Welford-style running mean per
        coordinate -- adequate for the 5-15 km trusted-zone scale we're
        checking against.
        """
        if gps_lat is None or gps_lon is None:
            return
        if not geo.valid_gps_accuracy(gps_accuracy_m, config.HOME_LEARN_MAX_ACCURACY_M):
            return

        def _apply(p: DriverProfile) -> None:
            n = p.home_n + 1
            if p.home_lat is None or p.home_lon is None:
                p.home_lat = float(gps_lat)
                p.home_lon = float(gps_lon)
            else:
                p.home_lat += (float(gps_lat) - p.home_lat) / n
                p.home_lon += (float(gps_lon) - p.home_lon) / n
            p.home_n = n
            p.home_last_update_at = time.time()

        self._mutate(_apply)

    def location_context(
        self, gps_lat: float | None, gps_lon: float | None
    ) -> tuple[float, bool]:
        """
        Return ``(dist_from_home_km, in_trusted_zone)`` for a current fix.

        Stays fail-neutral until home is learned -- otherwise a fresh install
        would treat every payment as "at home distance 0", or worse "very far
        from (0, 0)" depending on which direction the code got wrong. This
        way the risk head sees the same neutral defaults during bootstrap
        that it does when GPS is unavailable.
        """
        with self._lock:
            home_lat = self._p.home_lat
            home_lon = self._p.home_lon
            home_learned = self._p.home_n >= config.HOME_LEARN_MIN_SAMPLES
        if not home_learned:
            return 0.0, True
        return geo.location_context(
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            home_lat=home_lat,
            home_lon=home_lon,
            trusted_zone_radius_km=config.TRUSTED_ZONE_RADIUS_KM,
        )

    def can_refresh_ood(self, strong_auth_passed: bool) -> bool:
        """
        Fix #6: OOD baseline may be refreshed ONLY after an independently-strong
        auth (fingerprint + OTP, verified by the caller), never silently. Same
        guardrail the template-topup path already uses.
        """
        return bool(strong_auth_passed)

    def bump_ood_version(self) -> int:
        out = {"v": 0}

        def _apply(p: DriverProfile) -> None:
            p.ood_version += 1
            p.ood_last_refresh_at = time.time()
            out["v"] = p.ood_version

        self._mutate(_apply)
        return int(out["v"])

    @property
    def ood_version(self) -> int:
        with self._lock:
            return self._p.ood_version


def _migrate(raw: dict) -> dict:
    """Forward-migrate an older profile record to the current schema (fix #7)."""
    v = int(raw.get("schema_version", 1))
    out = dict(raw)
    # v1 → v2: introduced OOD versioning + Welford m2.
    if v < 2:
        out.setdefault("amount_m2", 0.0)
        out.setdefault("ood_version", 0)
        out.setdefault("ood_last_refresh_at", 0.0)
        out["schema_version"] = 2
    # v2 → v3: home-learning fields for the risk-model geo producer (fix #3).
    # Absent home fields become ``None`` so the profile is treated as
    # "home not yet learned" -- fail-neutral rather than assuming (0, 0).
    if v < 3:
        out.setdefault("home_lat", None)
        out.setdefault("home_lon", None)
        out.setdefault("home_n", 0)
        out.setdefault("home_last_update_at", 0.0)
        out["schema_version"] = 3
    return out
