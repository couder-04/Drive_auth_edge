"""End-to-end integration: capture → matchers → decision → policy → actuation.

Distinct from unit suites — each scenario exercises the full
``DriveAuth.authenticate`` path plus :class:`ActuationListener` side-effects.
"""

from __future__ import annotations

import json
from pathlib import Path

from driveauth import config
from driveauth.matchers.mock import MockFaceMatcher, MockFingerMatcher, MockVoiceMatcher
from driveauth.step_up_otp import OTPStepUp
from driveauth.types import Decision
from hardware.actuation import ActuationListener, NullRelay, NullSpeaker
from hardware.bluetooth_otp import BluetoothOTPDelivery
from hardware.ladder_otp import LadderOTPLane
from testsupport import good_audio, make_auth, mature


def _wire_ladder_otp(auth, *, paired: str = "AA:BB:CC:DD:EE:FF", map_ok: bool = True) -> None:
    contacts = Path(auth._store) / "contacts"
    contacts.mkdir(parents=True, exist_ok=True)
    (contacts / f"{auth.driver_id}.mobile").write_text("+919999000000\n")
    (contacts / f"{auth.driver_id}.bt_mac").write_text(f"{paired}\n")
    captured: dict[str, str] = {}
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=auth._registered_bt_mac,
        paired_mac_lookup=lambda: paired,
        map_send=lambda _m, payload: (
            captured.__setitem__("code", json.loads(payload)["code"]) or map_ok
        ),
        ble_send=lambda *_: False,
    )
    auth._engine._ladder_otp = LadderOTPLane(
        otp=OTPStepUp(delivery=delivery),
        mobile_lookup=auth._registered_mobile,
        registered_mac_lookup=auth._registered_bt_mac,
        code_provider=lambda: captured.get("code"),
    )


def test_e2e_clean_accept_actuates_relay():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.95)
    auth._engine._m.face = MockFaceMatcher(score=0.90)
    relay = NullRelay()
    speaker = NullSpeaker()
    act = ActuationListener(relay=relay, speaker=speaker, enable_watchdog=False)
    assert act.start() is True

    result = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    act.on_result(result)

    assert result.decision == Decision.ACCEPT
    assert any("ladder_accept_voice" in e for e in result.explanations)
    assert relay.closed is True
    assert speaker.last_message is not None
    act.stop()


def test_e2e_fail_to_stage3_otp(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    _wire_ladder_otp(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.20)
    auth._engine._m.fingerprint_available = True

    relay = NullRelay()
    act = ActuationListener(relay=relay, speaker=NullSpeaker(), enable_watchdog=False)
    act.start()

    result = auth.authenticate(
        audio_np=good_audio(),
        amount=100.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    act.on_result(result)

    assert result.decision == Decision.ACCEPT
    assert result.stage3_method == "otp_bluetooth"
    assert relay.closed is True
    act.stop()


def test_e2e_fail_closed_on_missing_sensor():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.99)
    auth._engine._m.fingerprint_available = False  # sensor missing → skip finger

    relay = NullRelay()
    speaker = NullSpeaker()
    act = ActuationListener(relay=relay, speaker=speaker, enable_watchdog=False)
    act.start()

    result = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    act.on_result(result)

    assert result.decision == Decision.REJECT
    assert result.modality_scores["finger"]["score"] is None
    assert relay.closed is False  # fail-closed: never fabricate ACCEPT
    act.stop()
