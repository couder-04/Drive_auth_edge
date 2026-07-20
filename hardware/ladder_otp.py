"""Stage-3 ladder OTP lane (Bluetooth delivery).

Independent from payment ``OTPStepUp`` in ``api.py`` — two challenges must
never share state. Uses the same hash/expiry/tries logic via a dedicated
``OTPStepUp(delivery=BluetoothOTPDelivery(...))`` instance.
"""

from __future__ import annotations

import logging
from typing import Callable

from driveauth.step_up_otp import OTPDelivery, OTPStepUp
from driveauth.types import ModalityResult
from hardware.bluetooth_otp import BluetoothOTPDelivery

logger = logging.getLogger("driveauth.hardware.ladder_otp")


class LadderOTPLane:
    """Probeable stage-3 lane returning ``ModalityResult`` like a matcher."""

    def __init__(
        self,
        *,
        delivery: OTPDelivery | None = None,
        mobile_lookup: Callable[[], str | None],
        registered_mac_lookup: Callable[[], str | None],
        paired_mac_lookup: Callable[[], str | None] | None = None,
        code_provider: Callable[[], str | None] | None = None,
        otp: OTPStepUp | None = None,
    ):
        if otp is not None:
            self._otp = otp
        else:
            backend = delivery or BluetoothOTPDelivery(
                registered_mac_lookup=registered_mac_lookup,
                paired_mac_lookup=paired_mac_lookup,
            )
            self._otp = OTPStepUp(delivery=backend)
        self._mobile_lookup = mobile_lookup
        self._registered_mac_lookup = registered_mac_lookup
        self._code_provider = code_provider

    @property
    def otp(self) -> OTPStepUp:
        return self._otp

    def can_attempt(self) -> bool:
        """True when registered mobile + BT MAC exist (delivery still may fail)."""
        mobile = self._mobile_lookup()
        mac = self._registered_mac_lookup()
        return bool(mobile and mac)

    def probe(self, verify_code: str | None = None) -> ModalityResult:
        """
        Deliver a Bluetooth OTP and, when a code is available, verify it.

        * ``verify_code`` — explicit code (tests / second-pass reauth).
        * ``code_provider`` — sync supplier used when ``verify_code`` is None
          (unit tests capture the delivered code).

        If delivery fails → ``available=False`` (lane unavailable, fail-closed).
        If delivered but no code to verify yet → ``available=True``, no score
        (does not ACCEPT; caller may keep a pending challenge).
        """
        if not self.can_attempt():
            return ModalityResult(score=None, confident=False, available=False)

        mobile = self._mobile_lookup()
        assert mobile is not None
        challenge = self._otp.send(mobile)
        if challenge is None:
            return ModalityResult(score=None, confident=False, available=False)

        code = verify_code
        if code is None and self._code_provider is not None:
            try:
                code = self._code_provider()
            except Exception as exc:
                logger.warning("LadderOTP: code_provider failed (%s)", type(exc).__name__)
                code = None

        if not code:
            # Challenge is live; sync probe cannot ACCEPT without a spoken code.
            return ModalityResult(score=None, confident=False, available=True)

        if self._otp.verify(code):
            return ModalityResult(score=1.0, confident=True, available=True)
        return ModalityResult(score=0.0, confident=True, available=True)
