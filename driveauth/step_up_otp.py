"""OTP step-up via payment provider (§4.3a)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass

from driveauth import config

logger = logging.getLogger("driveauth.otp")


@dataclass
class OTPChallenge:
    salt: bytes
    digest: bytes
    expires_at: float
    tries_left: int
    delivered: bool


class OTPStepUp:
    def __init__(self, provider_url: str = config.OTP_PROVIDER_URL):
        self._provider = provider_url
        self._active: OTPChallenge | None = None

    def _hash(self, code: str, salt: bytes) -> bytes:
        return hmac.new(salt, code.encode("utf-8"), hashlib.sha256).digest()

    def send(self, mobile_number: str | None) -> OTPChallenge | None:
        if not mobile_number or not self._provider:
            logger.warning("OTP: missing mobile or provider URL")
            return None

        code = "".join(secrets.choice("0123456789") for _ in range(config.OTP_LENGTH))
        return self._activate(
            code, delivered=self._deliver_via_provider(mobile_number, code)
        )

    def create_local_challenge(
        self, code: str | None = None
    ) -> tuple[OTPChallenge, str]:
        """Test/helper: create an active OTP without calling a provider."""
        raw = code or "".join(
            secrets.choice("0123456789") for _ in range(config.OTP_LENGTH)
        )
        ch = self._activate(raw, delivered=True)
        assert ch is not None
        return ch, raw

    def _activate(self, code: str, *, delivered: bool) -> OTPChallenge | None:
        if not delivered:
            return None
        salt = secrets.token_bytes(16)
        digest = self._hash(code, salt)
        self._active = OTPChallenge(
            salt=salt,
            digest=digest,
            expires_at=time.time() + config.OTP_TTL_S,
            tries_left=config.OTP_MAX_TRIES,
            delivered=True,
        )
        return self._active

    def expire_active(self) -> None:
        """Test helper: force-expire the active challenge."""
        if self._active is not None:
            self._active.expires_at = time.time() - 1

    def _deliver_via_provider(self, mobile_number: str, code: str) -> bool:
        try:
            import json
            import urllib.request

            payload = json.dumps(
                {
                    "to": mobile_number,
                    "code": code,
                    "ttl_s": int(config.OTP_TTL_S),
                    "purpose": "driveauth_step_up",
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self._provider,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(
                req, timeout=config.OTP_PROVIDER_TIMEOUT_S
            ) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.warning("OTP: delivery failed (%s)", type(exc).__name__)
            return False

    def verify(self, code: str) -> bool:
        ch = self._active
        if ch is None or time.time() > ch.expires_at or ch.tries_left <= 0:
            self._active = None
            return False
        ch.tries_left -= 1
        ok = hmac.compare_digest(self._hash(code, ch.salt), ch.digest)
        if ok:
            self._active = None
        return ok

    @property
    def has_active_challenge(self) -> bool:
        return self._active is not None and time.time() <= self._active.expires_at
