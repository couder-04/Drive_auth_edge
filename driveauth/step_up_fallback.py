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

# Stored PIN blob (Fernet-plaintext) versions:
#   v1 (legacy): salt(16) || hmac-sha256(salt, pin)(32)   — 48 bytes, no magic
#   v2:          b"DA2P" || iterations(uint32 BE) || salt(16) || pbkdf2-sha256(32)
# v1 still verifies so existing enrollments are not locked out; a successful
# v1 check re-writes the blob as v2 (lazy migration).
_PIN_V2_MAGIC = b"DA2P"
_PIN_KIND_HMAC = "hmac-sha256"
_PIN_KIND_PBKDF2 = "pbkdf2-sha256"


def _pbkdf2_iterations() -> int:
    return int(getattr(config, "PIN_PBKDF2_ITERATIONS", 600_000))


def _hash_pin_hmac(pin: str, salt: bytes) -> bytes:
    return hmac.new(salt, pin.encode("utf-8"), hashlib.sha256).digest()


def _hash_pin_pbkdf2(pin: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, iterations, dklen=32
    )


def _pack_v2(salt: bytes, digest: bytes, iterations: int) -> bytes:
    return _PIN_V2_MAGIC + int(iterations).to_bytes(4, "big") + salt + digest


def parse_pin_blob(raw: bytes) -> tuple[str, bytes, bytes, int]:
    """Return (kind, salt, digest, iterations). iterations is 0 for v1 HMAC."""
    if raw.startswith(_PIN_V2_MAGIC) and len(raw) >= 4 + 4 + 16 + 32:
        iterations = int.from_bytes(raw[4:8], "big")
        salt = raw[8:24]
        digest = raw[24:56]
        return _PIN_KIND_PBKDF2, salt, digest, iterations
    if len(raw) >= 48:
        return _PIN_KIND_HMAC, raw[:16], raw[16:48], 0
    raise ValueError("unrecognized PIN blob")


class StepUpFallback:
    def __init__(self, store_dir: str, driver_id: str = "driver1"):
        self._store = Path(store_dir)
        self._driver = driver_id
        self._pin_hash, self._pin_salt, self._pin_kind, self._pin_iters = self._load_pin()

    def _load_pin(self) -> tuple[bytes | None, bytes | None, str | None, int]:
        pin_path = self._store / "pins" / f"{self._driver}.enc"
        if not pin_path.exists():
            return None, None, None, 0
        try:
            from cryptography.fernet import Fernet  # type: ignore

            key_path = self._store / ".bio_key"
            if not key_path.exists():
                return None, None, None, 0
            f = Fernet(key_path.read_bytes())
            raw = f.decrypt(pin_path.read_bytes())
            kind, salt, digest, iters = parse_pin_blob(raw)
            return digest, salt, kind, iters
        except Exception as exc:
            logger.error("Fallback: PIN load failed (%s)", exc)
            return None, None, None, 0

    def verify_pin(self, pin: str) -> bool:
        if self._pin_hash is None or self._pin_salt is None or len(pin) < _PIN_MIN_LEN:
            return False
        if self._pin_kind == _PIN_KIND_PBKDF2:
            digest = _hash_pin_pbkdf2(pin, self._pin_salt, self._pin_iters or _pbkdf2_iterations())
            return hmac.compare_digest(digest, self._pin_hash)
        # Legacy HMAC-SHA256 (fast; not a KDF). Still accepted, then upgraded.
        digest = _hash_pin_hmac(pin, self._pin_salt)
        if not hmac.compare_digest(digest, self._pin_hash):
            return False
        if enroll_pin(str(self._store), self._driver, pin):
            self._pin_hash, self._pin_salt, self._pin_kind, self._pin_iters = self._load_pin()
        return True

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
        iterations = _pbkdf2_iterations()
        digest = _hash_pin_pbkdf2(pin, salt, iterations)
        f = Fernet(key_path.read_bytes())
        enc = f.encrypt(_pack_v2(salt, digest, iterations))
        out = store / "pins" / f"{driver_id}.enc"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(enc)
        return True
    except Exception as exc:
        logger.error("enroll_pin: %s", exc)
        return False
