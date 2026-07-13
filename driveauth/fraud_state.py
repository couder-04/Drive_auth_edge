"""Fraud ladder state machine (§6.2)."""

from __future__ import annotations

import enum
import json
import logging
import threading
import time
from pathlib import Path

from driveauth import config

logger = logging.getLogger("driveauth.fraud")

_DECAY_HOURS = config.FRAUD_LADDER_DECAY_HOURS
_CLEAN_STREAK_TO_RELAX = config.FRAUD_CLEAN_STREAK


class FraudState(str, enum.Enum):
    # BOOTSTRAP is not "suspicious" — it's "unknown". A newly-enrolled (or stale)
    # driver has no learned risk baseline, so we apply extra rigor and an amount
    # cap independent of how good their biometrics look (fix #6). It sits
    # conceptually below NORMAL and is driven by ProfileStore maturity, not by
    # soft flags. It is never *entered* by the flag machinery below — the API
    # overlays it via effective_state() when the profile isn't mature yet.
    BOOTSTRAP = "bootstrap"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HEIGHTENED = "heightened"
    LOCKED = "locked"


def _rigor_for(state: FraudState) -> dict:
    raw = config.FRAUD_RIGOR.get(state.value, config.FRAUD_RIGOR["normal"])
    return {
        "min_modalities": int(raw["min_modalities"]),
        "force_step_up": bool(raw["force_step_up"]),
        "block": bool(raw["block"]),
        "trust_margin": float(raw["trust_margin"]),
    }


_RIGOR = {state: _rigor_for(state) for state in FraudState}


class FraudStateMachine:
    def __init__(self, state_path: Path, driver_id: str):
        self._path = state_path
        self._driver = driver_id
        self._lock = threading.Lock()
        self._state = FraudState.NORMAL
        self._flags: list[float] = []
        self._clean_streak = 0
        self._confirmed_fraud = 0
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text()).get(self._driver, {})
            self._state = FraudState(data.get("state", "normal"))
            self._flags = list(data.get("flags", []))
            self._clean_streak = int(data.get("clean_streak", 0))
            self._confirmed_fraud = int(data.get("confirmed_fraud", 0))
        except Exception as exc:
            logger.warning("FraudState: load failed (%s)", exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            alldata = {}
            if self._path.exists():
                try:
                    alldata = json.loads(self._path.read_text())
                except Exception:
                    alldata = {}
            alldata[self._driver] = {
                "state": self._state.value,
                "flags": self._flags,
                "clean_streak": self._clean_streak,
                "confirmed_fraud": self._confirmed_fraud,
                "updated": time.time(),
            }
            self._path.write_text(json.dumps(alldata))
        except Exception as exc:
            logger.warning("FraudState: save failed (%s)", exc)

    def _decay(self) -> None:
        now = time.time()
        window = _DECAY_HOURS * 3600.0
        self._flags = [t for t in self._flags if now - t < window]

    def _recompute(self) -> None:
        self._decay()
        n = len(self._flags)
        if self._state == FraudState.LOCKED:
            return
        if self._confirmed_fraud >= 1 or n >= 2:
            self._state = FraudState.HEIGHTENED
        elif n == 1:
            self._state = FraudState.ELEVATED
        else:
            self._state = FraudState.NORMAL

    def record_soft_flag(self, reason: str = "") -> FraudState:
        with self._lock:
            self._flags.append(time.time())
            self._clean_streak = 0
            self._recompute()
            logger.info(
                "FraudState[%s]: soft flag (%s) → %s",
                self._driver,
                reason,
                self._state.value,
            )
            self._save()
            return self._state

    def record_confirmed_fraud(self) -> FraudState:
        with self._lock:
            self._confirmed_fraud += 1
            self._clean_streak = 0
            if self._confirmed_fraud >= 2:
                self._state = FraudState.LOCKED
            else:
                self._recompute()
            logger.warning(
                "FraudState[%s]: confirmed fraud → %s", self._driver, self._state.value
            )
            self._save()
            return self._state

    def record_clean(self) -> FraudState:
        with self._lock:
            self._clean_streak += 1
            if (
                self._state in (FraudState.ELEVATED, FraudState.HEIGHTENED)
                and self._clean_streak >= _CLEAN_STREAK_TO_RELAX
            ):
                self._flags = self._flags[1:] if self._flags else []
                self._confirmed_fraud = max(0, self._confirmed_fraud - 1)
                self._clean_streak = 0
                self._recompute()
                self._save()
            return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = FraudState.NORMAL
            self._flags = []
            self._clean_streak = 0
            self._confirmed_fraud = 0
            self._save()

    @property
    def state(self) -> FraudState:
        with self._lock:
            self._decay()
            return self._state

    def rigor(self) -> dict:
        return dict(_RIGOR[self.state])

    def effective_state(self, profile_mature: bool) -> FraudState:
        """
        Overlay BOOTSTRAP when the driver profile isn't mature yet (fix #6),
        UNLESS an actual suspicion state is already stricter. Suspicion always
        wins over mere novelty — a flagged new driver is HEIGHTENED, not
        downgraded to BOOTSTRAP.
        """
        base = self.state
        if profile_mature:
            return base
        # Order of strictness: NORMAL < BOOTSTRAP < ELEVATED < HEIGHTENED < LOCKED
        rank = {
            FraudState.NORMAL: 0,
            FraudState.BOOTSTRAP: 1,
            FraudState.ELEVATED: 2,
            FraudState.HEIGHTENED: 3,
            FraudState.LOCKED: 4,
        }
        return base if rank[base] > rank[FraudState.BOOTSTRAP] else FraudState.BOOTSTRAP

    def effective_rigor(self, profile_mature: bool) -> dict:
        return dict(_RIGOR[self.effective_state(profile_mature)])
