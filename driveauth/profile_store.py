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
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from driveauth import config
from driveauth.types import RiskContext

logger = logging.getLogger("driveauth.profile")


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
    # Schema version for migration safety (fix #7).
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

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            alldata = {}
            if self._path.exists():
                try:
                    alldata = json.loads(self._path.read_text())
                except Exception:
                    alldata = {}
            alldata[self._driver] = asdict(self._p)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(alldata))
            tmp.replace(self._path)  # atomic write — no half-written schema (fix #7)
        except Exception as exc:
            logger.warning("ProfileStore: save failed (%s)", exc)

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
        with self._lock:
            self._p.created_at = time.time() - age_s
            self._p.txn_count = 0
            self._p.amount_mean = 0.0
            self._p.amount_m2 = 0.0
            self._p.last_txn_at = 0.0
        for _ in range(n):
            self.record_transaction(typical_amount)

    def reset_bootstrap(self) -> None:
        """Clear history so the next auth sees an immature (bootstrap) profile."""
        with self._lock:
            self._p = DriverProfile(driver_id=self._driver, created_at=time.time())
            self._save()

    def apply_to_context(self, ctx: RiskContext) -> RiskContext:
        """Populate the RiskContext's per-user history fields from the profile."""
        with self._lock:
            ctx.amount_mean = self._p.amount_mean
            ctx.amount_std = self._p.amount_std
        return ctx

    # ── updates ──────────────────────────────────────────────────────────────

    def record_transaction(self, amount: float) -> None:
        """Welford online update of amount stats after a completed transaction."""
        with self._lock:
            self._p.txn_count += 1
            delta = amount - self._p.amount_mean
            self._p.amount_mean += delta / self._p.txn_count
            self._p.amount_m2 += delta * (amount - self._p.amount_mean)
            self._p.last_txn_at = time.time()
            self._save()

    def can_refresh_ood(self, strong_auth_passed: bool) -> bool:
        """
        Fix #6: OOD baseline may be refreshed ONLY after an independently-strong
        auth (fingerprint + OTP, verified by the caller), never silently. Same
        guardrail the template-topup path already uses.
        """
        return bool(strong_auth_passed)

    def bump_ood_version(self) -> int:
        with self._lock:
            self._p.ood_version += 1
            self._p.ood_last_refresh_at = time.time()
            self._save()
            return self._p.ood_version

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
    return out
