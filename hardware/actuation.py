"""Actuation layer — GPIO relay + speaker feedback on ACCEPT.

Thin listener on ``DriveAuthResult``; does not modify ``DecisionEngine``.
Fail-safe: relay defaults open/off; only closes on a freshly-computed ACCEPT
(no caching of previous decisions).

Phase C: :class:`ActuationWatchdog` forces the relay open if the main process
stops heartbeating within a bounded timeout — independent of the crashed
process's own cleanup (including kill -9 of the decision daemon).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Protocol, runtime_checkable

from driveauth.types import Decision, DriveAuthResult

logger = logging.getLogger("driveauth.hardware.actuation")

DEFAULT_WATCHDOG_TIMEOUT_S = float(
    os.getenv("DRIVEAUTH_ACTUATION_WATCHDOG_S", "2.0") or "2.0"
)


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


class FlakyAckRelay:
    """Test double: GPIO write succeeds; ack fails only when closing."""

    def __init__(self, inner: RelayBackend | None = None, *, fail_on_close: bool = True):
        self._inner = inner or NullRelay()
        self.fail_on_close = fail_on_close
        self.write_count = 0
        self.ack_failures = 0
        self.closed = False

    def setup(self) -> bool:
        return self._inner.setup()

    def set_closed(self, closed: bool) -> None:
        self._inner.set_closed(closed)
        self.closed = bool(getattr(self._inner, "closed", closed))
        self.write_count += 1
        if closed and self.fail_on_close:
            self.ack_failures += 1
            # Simulate: pin latched closed in hardware, but ack never returns.
            # Leave self.closed True so caller must fail-safe / watchdog reopen.
            raise RuntimeError("relay ack timeout")

    def cleanup(self) -> None:
        self._inner.cleanup()
        self.closed = False


class ActuationWatchdog:
    """Force relay open if heartbeats stop within ``timeout_s``.

    Runs in a daemon thread so a killed main process (or stuck decision loop)
    cannot leave the relay closed. Heartbeat is process-local; for multi-process
    deployments, share a relay backend that the watchdog owns exclusively.
    """

    def __init__(
        self,
        relay: RelayBackend,
        *,
        timeout_s: float = DEFAULT_WATCHDOG_TIMEOUT_S,
        poll_s: float = 0.05,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self._relay = relay
        self._timeout_s = max(0.05, float(timeout_s))
        self._poll_s = max(0.01, float(poll_s))
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_beat = self._clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.forced_open_count = 0

    def heartbeat(self) -> None:
        self._last_beat = self._clock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.heartbeat()
        self._thread = threading.Thread(
            target=self._run,
            name="driveauth-actuation-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            age = self._clock() - self._last_beat
            if age > self._timeout_s:
                try:
                    self._relay.set_closed(False)
                    self.forced_open_count += 1
                    logger.error(
                        "ActuationWatchdog: heartbeat stale (%.3fs); forced relay open",
                        age,
                    )
                except Exception as exc:
                    logger.error(
                        "ActuationWatchdog: force-open failed (%s)",
                        type(exc).__name__,
                    )
                # Keep forcing open until heartbeats resume.
                self._sleep(self._poll_s)


class ActuationListener:
    """Apply side-effects for a single fresh decision (no decision caching)."""

    def __init__(
        self,
        *,
        relay: RelayBackend | None = None,
        speaker: SpeakerBackend | None = None,
        accept_message: str = "Identity confirmed.",
        reject_message: str = "Authentication failed.",
        watchdog: ActuationWatchdog | None = None,
        watchdog_timeout_s: float | None = None,
        enable_watchdog: bool = True,
    ):
        self._relay: RelayBackend = relay or NullRelay()
        self._speaker: SpeakerBackend = speaker or NullSpeaker()
        self._accept_message = accept_message
        self._reject_message = reject_message
        self._ready = False
        self._watchdog = watchdog
        if self._watchdog is None and enable_watchdog:
            timeout = (
                DEFAULT_WATCHDOG_TIMEOUT_S
                if watchdog_timeout_s is None
                else float(watchdog_timeout_s)
            )
            self._watchdog = ActuationWatchdog(
                self._relay, timeout_s=timeout
            )

    def start(self) -> bool:
        self._ready = bool(self._relay.setup())
        # Fail-safe open even if setup partially failed.
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        if self._watchdog is not None:
            self._watchdog.start()
            self._watchdog.heartbeat()
        return self._ready

    def stop(self) -> None:
        if self._watchdog is not None:
            self._watchdog.stop()
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        try:
            self._relay.cleanup()
        except Exception:
            pass
        self._ready = False

    def heartbeat(self) -> None:
        if self._watchdog is not None:
            self._watchdog.heartbeat()

    def on_result(self, result: DriveAuthResult | Any) -> None:
        """
        Close relay only on a freshly-computed ACCEPT; otherwise force open.
        Never consults prior decisions.
        """
        self.heartbeat()
        decision = getattr(result, "decision", None)
        if decision == Decision.ACCEPT:
            try:
                self._relay.set_closed(True)
            except Exception as exc:
                logger.error("Actuation: relay close failed (%s)", type(exc).__name__)
                # Fail-safe: force open even if the close ack timed out mid-ACCEPT.
                try:
                    self._relay.set_closed(False)
                except Exception:
                    pass
                if hasattr(self._relay, "closed"):
                    try:
                        self._relay.closed = False  # type: ignore[attr-defined]
                    except Exception:
                        pass
            else:
                self._speaker.speak(self._accept_message)
            self.heartbeat()
            return

        # REJECT / STEP_UP / unknown → open (fail-safe)
        try:
            self._relay.set_closed(False)
        except Exception:
            pass
        if decision == Decision.REJECT:
            self._speaker.speak(self._reject_message)
        self.heartbeat()

    @property
    def relay_closed(self) -> bool:
        return bool(getattr(self._relay, "closed", False))

    @property
    def watchdog(self) -> ActuationWatchdog | None:
        return self._watchdog
