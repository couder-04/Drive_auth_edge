"""Actuation layer — GPIO relay + speaker feedback on ACCEPT.

Thin listener on ``DriveAuthResult``; does not modify ``DecisionEngine``.
Fail-safe: relay defaults open/off; only closes on a freshly-computed ACCEPT
(no caching of previous decisions).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, runtime_checkable

from driveauth.types import Decision, DriveAuthResult

logger = logging.getLogger("driveauth.hardware.actuation")


@runtime_checkable
class RelayBackend(Protocol):
    def setup(self) -> bool: ...
    def set_closed(self, closed: bool) -> None: ...
    def cleanup(self) -> None: ...


@runtime_checkable
class SpeakerBackend(Protocol):
    def speak(self, message: str) -> None: ...


class NullRelay:
    def __init__(self):
        self.closed = False

    def setup(self) -> bool:
        return True

    def set_closed(self, closed: bool) -> None:
        self.closed = bool(closed)

    def cleanup(self) -> None:
        self.closed = False


class NullSpeaker:
    def __init__(self):
        self.last_message: str | None = None

    def speak(self, message: str) -> None:
        self.last_message = message


class GPIORelay:
    """RPi.GPIO relay on a BCM pin. Defaults open (energized=False)."""

    def __init__(self, pin: int = 17, *, active_high: bool = True):
        self._pin = int(pin)
        self._active_high = active_high
        self._gpio = None
        self.closed = False

    def setup(self) -> bool:
        try:
            import RPi.GPIO as GPIO  # type: ignore
        except ImportError:
            logger.warning("GPIORelay: RPi.GPIO not installed")
            return False
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.LOW if self._active_high else GPIO.HIGH)
            self._gpio = GPIO
            self.closed = False
            return True
        except Exception as exc:
            logger.error("GPIORelay: setup failed (%s)", type(exc).__name__)
            self._gpio = None
            return False

    def set_closed(self, closed: bool) -> None:
        if self._gpio is None:
            self.closed = False
            return
        level_on = self._gpio.HIGH if self._active_high else self._gpio.LOW
        level_off = self._gpio.LOW if self._active_high else self._gpio.HIGH
        self._gpio.output(self._pin, level_on if closed else level_off)
        self.closed = bool(closed)

    def cleanup(self) -> None:
        try:
            self.set_closed(False)
            if self._gpio is not None:
                self._gpio.cleanup(self._pin)
        except Exception:
            pass
        self.closed = False
        self._gpio = None


class LogSpeaker:
    """Speaker stand-in that logs (and optionally calls a TTS hook)."""

    def __init__(self, tts: Callable[[str], None] | None = None):
        self._tts = tts
        self.last_message: str | None = None

    def speak(self, message: str) -> None:
        self.last_message = message
        logger.info("Actuation speaker: %s", message)
        if self._tts is not None:
            try:
                self._tts(message)
            except Exception as exc:
                logger.warning("Actuation TTS failed (%s)", type(exc).__name__)


class ActuationListener:
    """Apply side-effects for a single fresh decision (no decision caching)."""

    def __init__(
        self,
        *,
        relay: RelayBackend | None = None,
        speaker: SpeakerBackend | None = None,
        accept_message: str = "Identity confirmed.",
        reject_message: str = "Authentication failed.",
    ):
        self._relay: RelayBackend = relay or NullRelay()
        self._speaker: SpeakerBackend = speaker or NullSpeaker()
        self._accept_message = accept_message
        self._reject_message = reject_message
        self._ready = False

    def start(self) -> bool:
        self._ready = bool(self._relay.setup())
        # Fail-safe open even if setup partially failed.
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        return self._ready

    def stop(self) -> None:
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        try:
            self._relay.cleanup()
        except Exception:
            pass
        self._ready = False

    def on_result(self, result: DriveAuthResult | Any) -> None:
        """
        Close relay only on a freshly-computed ACCEPT; otherwise force open.
        Never consults prior decisions.
        """
        decision = getattr(result, "decision", None)
        if decision == Decision.ACCEPT:
            try:
                self._relay.set_closed(True)
            except Exception as exc:
                logger.error("Actuation: relay close failed (%s)", type(exc).__name__)
                try:
                    self._relay.set_closed(False)
                except Exception:
                    pass
            self._speaker.speak(self._accept_message)
            return

        # REJECT / STEP_UP / unknown → open (fail-safe)
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        if decision == Decision.REJECT:
            self._speaker.speak(self._reject_message)

    @property
    def relay_closed(self) -> bool:
        return bool(getattr(self._relay, "closed", False))
