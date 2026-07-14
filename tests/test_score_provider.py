"""Manual score provider — HW stand-in contract."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from driveauth import DriveAuth
from driveauth.matchers.mock import MockBehavioralMonitor, MockFingerMatcher
from driveauth.matchers.score_provider import ManualScores, apply_manual_scores
from driveauth.types import Decision
from testsupport import good_audio, mature


def test_manual_scores_from_mapping():
    s = ManualScores.from_mapping({"finger": 0.2, "behavioral": 0.9})
    assert s.finger == 0.2
    assert s.behavioral == 0.9
    assert s.voice is None


def test_manual_scores_json_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.json"
        p.write_text(json.dumps({"finger": 0.15}))
        s = ManualScores.from_json_file(p)
        assert s.finger == 0.15


def test_apply_manual_finger_probes():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    apply_manual_scores(auth, ManualScores(finger=0.15, behavioral=0.95))
    assert isinstance(auth._engine._m.finger, MockFingerMatcher)
    assert isinstance(auth._engine._m.behavioral, MockBehavioralMonitor)
    assert auth._engine._m.fingerprint_available is True
    r = auth._engine._m.finger.capture_and_score()
    assert r.score == 0.15
    assert r.available is True


def test_happy_manual_finger_still_accepts_micro():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    apply_manual_scores(auth, ManualScores(finger=0.9, behavioral=0.95))
    result = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert result.decision == Decision.ACCEPT
