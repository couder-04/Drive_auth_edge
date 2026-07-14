"""Manual similarity scores now; hardware adapters later — same contract.

Hardware modules must eventually emit ``ModalityResult(score, confident, …)``
with score in ``[0, 1]``. Until sensors exist, call ``apply_manual_scores`` or
set ``DRIVEAUTH_MANUAL_SCORES=/path/to/scores.json``.

Example JSON::

    {"voice": 0.9, "face": 0.85, "finger": 0.2, "behavioral": 0.95}

Omit keys you want left unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from driveauth.matchers.mock import (
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)

logger = logging.getLogger("driveauth.score_provider")


@dataclass
class ManualScores:
    """Optional per-modality match scores in ``[0, 1]``."""

    voice: float | None = None
    face: float | None = None
    finger: float | None = None
    behavioral: float | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> ManualScores:
        if not data:
            return cls()
        out: dict[str, float | None] = {}
        for key in ("voice", "face", "finger", "behavioral"):
            if key not in data or data[key] is None:
                out[key] = None
                continue
            v = float(data[key])
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"score {key}={v} out of [0, 1]")
            out[key] = v
        return cls(**out)

    @classmethod
    def from_json_file(cls, path: str | Path) -> ManualScores:
        p = Path(path)
        return cls.from_mapping(json.loads(p.read_text()))

    @classmethod
    def from_json_str(cls, raw: str) -> ManualScores:
        return cls.from_mapping(json.loads(raw))

    @classmethod
    def from_env(cls, env_var: str = "DRIVEAUTH_MANUAL_SCORES") -> ManualScores | None:
        """Load from path or inline JSON in ``DRIVEAUTH_MANUAL_SCORES``."""
        raw = os.getenv(env_var, "").strip()
        if not raw:
            return None
        path = Path(raw)
        if path.is_file():
            return cls.from_json_file(path)
        if raw.startswith("{"):
            return cls.from_json_str(raw)
        logger.warning("%s set but not a file or JSON object: %s", env_var, raw)
        return None


def apply_manual_scores(auth: Any, scores: ManualScores) -> None:
    """Replace mock matchers (or score fields) so DecisionEngine sees HW-like scores.

    Real ``VoiceMatcher`` / ``FaceMatcher`` are left alone unless the
    corresponding score is set — then a mock with that score is swapped in
    (useful for offline scenario scripting). Finger / behavioral are always
    mocks until ONNX + sensors ship.
    """
    engine = auth._engine
    bundle = engine._m

    if scores.voice is not None:
        bundle.voice = MockVoiceMatcher(score=scores.voice)
        logger.info("manual score voice=%.3f", scores.voice)

    if scores.face is not None:
        bundle.face = MockFaceMatcher(score=scores.face)
        logger.info("manual score face=%.3f", scores.face)

    if scores.finger is not None:
        bundle.finger = MockFingerMatcher(score=scores.finger)
        # Mark fingerprint available so escalation can probe it
        bundle.fingerprint_available = True
        logger.info("manual score finger=%.3f", scores.finger)

    if scores.behavioral is not None:
        bundle.behavioral = MockBehavioralMonitor(score=scores.behavioral)
        logger.info("manual score behavioral=%.3f", scores.behavioral)


def apply_manual_scores_from_env(auth: Any) -> bool:
    scores = ManualScores.from_env()
    if scores is None:
        return False
    apply_manual_scores(auth, scores)
    return True
