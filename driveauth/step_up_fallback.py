"""Offline step-up fallback — biometric recapture + local PIN."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from pathlib import Path

from driveauth import config

logger = logging.getLogger("driveauth.fallback")

_PIN_MIN_LEN = config.PIN_MIN_LEN


class StepUpFallback:
    def __init__(self, store_dir: str, driver_id: str = "driver1"):
        self._store = Path(store_dir)
        self._driver = driver_id
        self._pin_hash, self._pin_salt = self._load_pin()

    def _load_pin(self) -> tuple[bytes | None, bytes | None]:
        pin_path = self._store / "pins" / f"{self._driver}.enc"
        if not pin_path.exists():
            return None, None
        try:
            from cryptography.fernet import Fernet  # type: ignore

            key_path = self._store / ".bio_key"
            if not key_path.exists():
                return None, None
            f = Fernet(key_path.read_bytes())
            raw = f.decrypt(pin_path.read_bytes())
            if len(raw) < 48:
                return None, None
            return raw[16:48], raw[:16]
        except Exception as exc:
            logger.error("Fallback: PIN load failed (%s)", exc)
            return None, None

    def verify_pin(self, pin: str) -> bool:
        if self._pin_hash is None or self._pin_salt is None or len(pin) < _PIN_MIN_LEN:
            return False
        digest = hmac.new(self._pin_salt, pin.encode("utf-8"), hashlib.sha256).digest()
        return hmac.compare_digest(digest, self._pin_hash)

    def run(
        self, pin: str | None, biometric_recheck, min_trust: float | None = None
    ) -> tuple[bool, list[str]]:
        if min_trust is None:
            min_trust = config.FALLBACK_MIN_TRUST
        reasons: list[str] = ["offline_fallback_used"]
        pin_ok = self.verify_pin(pin) if pin else False
        if not pin_ok:
            reasons.append("pin_failed_or_missing")
        try:
            trust = float(biometric_recheck())
        except Exception:
            trust = 0.0
        bio_ok = trust >= min_trust
        if not bio_ok:
            reasons.append("biometric_recheck_failed")
        passed = pin_ok and bio_ok
        reasons.append("fallback_passed" if passed else "fallback_failed")
        return passed, reasons


def enroll_pin(store_dir: str, driver_id: str, pin: str) -> bool:
    if len(pin) < _PIN_MIN_LEN:
        return False
    try:
        from cryptography.fernet import Fernet  # type: ignore

        store = Path(store_dir)
        key_path = store / ".bio_key"
        if not key_path.exists():
            store.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(Fernet.generate_key())
        salt = secrets.token_bytes(16)
        digest = hmac.new(salt, pin.encode("utf-8"), hashlib.sha256).digest()
        f = Fernet(key_path.read_bytes())
        enc = f.encrypt(salt + digest)
        out = store / "pins" / f"{driver_id}.enc"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(enc)
        return True
    except Exception as exc:
        logger.error("enroll_pin: %s", exc)
        return False
