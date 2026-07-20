"""Phase 6 — mid-capture disconnects + clean recovery on reconnect.

Each case asserts fail-closed (unavailable modality, no fabricated ACCEPT) and
that a subsequent call after reconnect can succeed again.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth.matchers.mock import MockFaceMatcher, MockFingerMatcher, MockVoiceMatcher
from driveauth.step_up_otp import OTPStepUp
from driveauth.types import Decision, ModalityResult
from hardware.bluetooth_otp import BluetoothOTPDelivery
from hardware.ladder_otp import LadderOTPLane
from testsupport import good_audio, make_auth, mature


class DisconnectableFaceMatcher:
    """Simulates camera disconnect mid-capture; reconnect restores frames."""

    face_frac = 0.35
    frontal_ok = True
    last_pad_reject = False

    def __init__(self, score: float = 0.94):
        self._score = score
        self.connected = True
        self.disconnect_next = False
        self.captures = 0

    def capture_frame(self):
        self.captures += 1
        if self.disconnect_next:
            self.disconnect_next = False
            self.connected = False
            return None
        if not self.connected:
            return None
        size = 112
        yy, xx = np.mgrid[0:size, 0:size]
        base = np.full((size, size), 130.0, dtype=np.float32)
        base += ((xx // 2 + yy // 2) % 2) * 40.0
        return base.astype(np.float32)

    def score_frame(self, frame_gray) -> ModalityResult:
        if frame_gray is None or not self.connected:
            return ModalityResult(None, False, available=False)
        return ModalityResult(
            self._score, True, embedding=np.zeros(512, dtype=np.float32)
        )

    def capture_and_score(self) -> ModalityResult:
        return self.score_frame(self.capture_frame())

    def reconnect(self) -> None:
        self.connected = True
        self.disconnect_next = False


class DropoutVoiceMatcher:
    """Mic dropout mid-utterance → unavailable; reconnect restores scoring."""

    def __init__(self, score: float = 0.95):
        self._score = score
        self.live = True
        self.drop_next = False

    def score(self, audio_f32, sample_rate: int = 16_000) -> ModalityResult:
        if self.drop_next:
            self.drop_next = False
            self.live = False
            return ModalityResult(None, False, available=False)
        if not self.live:
            return ModalityResult(None, False, available=False)
        if audio_f32 is None or audio_f32.size < sample_rate // 2:
            return ModalityResult(None, False, available=False)
        return ModalityResult(
            self._score, True, embedding=np.zeros(192, dtype=np.float32)
        )

    def reconnect(self) -> None:
        self.live = True
        self.drop_next = False


class FlakyLink:
    """BT link drop mid-OTP-delivery; reconnect allows MAP again."""

    def __init__(self):
        self.link_up = True
        self.drop_next = False
        self.attempts = 0

    def map_ok(self) -> bool:
        self.attempts += 1
        if self.drop_next:
            self.drop_next = False
            self.link_up = False
            return False
        return bool(self.link_up)

    def reconnect(self) -> None:
        self.link_up = True
        self.drop_next = False


def _wire_flaky_otp(auth, flaky: FlakyLink, paired: str = "AA:BB:CC:DD:EE:FF") -> None:
    contacts = Path(auth._store) / "contacts"
    contacts.mkdir(parents=True, exist_ok=True)
    (contacts / f"{auth.driver_id}.mobile").write_text("+919999000000\n")
    (contacts / f"{auth.driver_id}.bt_mac").write_text(f"{paired}\n")
    captured: dict[str, str] = {}

    def map_send(_mac: str, payload: str) -> bool:
        if not flaky.map_ok():
            return False
        captured["code"] = json.loads(payload)["code"]
        return True

    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=auth._registered_bt_mac,
        paired_mac_lookup=lambda: paired,
        map_send=map_send,
        ble_send=lambda *_: False,
    )
    auth._engine._ladder_otp = LadderOTPLane(
        otp=OTPStepUp(delivery=delivery),
        mobile_lookup=auth._registered_mobile,
        registered_mac_lookup=auth._registered_bt_mac,
        code_provider=lambda: captured.get("code"),
    )


def test_camera_disconnect_mid_capture_fail_closed_then_recover():
    auth = make_auth()
    mature(auth)
    face = DisconnectableFaceMatcher(score=0.95)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)  # force face stage
    auth._engine._m.face = face
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False

    face.disconnect_next = True
    r1 = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r1.decision != Decision.ACCEPT
    assert r1.modality_scores["face"]["score"] is None
    assert not any("ladder_accept_face" in e for e in r1.explanations)

    face.reconnect()
    r2 = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r2.decision == Decision.ACCEPT
    assert any("ladder_accept_face" in e for e in r2.explanations)


def test_mic_dropout_mid_utterance_fail_closed_then_recover():
    auth = make_auth()
    mature(auth)
    voice = DropoutVoiceMatcher(score=0.95)
    auth._engine._m.voice = voice
    auth._engine._m.face = MockFaceMatcher(available=False)
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False

    voice.drop_next = True
    r1 = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=True,
    )
    assert r1.decision != Decision.ACCEPT
    assert r1.modality_scores["voice"]["score"] is None

    voice.reconnect()
    r2 = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=True,
    )
    assert r2.decision == Decision.ACCEPT
    assert any("ladder_accept_voice" in e for e in r2.explanations)


def test_bluetooth_link_drop_mid_otp_fail_closed_then_recover(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    flaky = FlakyLink()
    _wire_flaky_otp(auth, flaky)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.fingerprint_available = False  # force OTP stage-3

    flaky.drop_next = True
    r1 = auth.authenticate(
        audio_np=good_audio(),
        amount=100.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r1.decision != Decision.ACCEPT
    assert r1.stage3_method is None

    flaky.reconnect()
    r2 = auth.authenticate(
        audio_np=good_audio(),
        amount=100.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r2.decision == Decision.ACCEPT
    assert r2.stage3_method == "otp_bluetooth"
