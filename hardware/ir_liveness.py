"""IR reflectance liveness / anti-spoof (heuristic; not ISO-certified).

Screens and printed photos reflect near-IR very differently from skin.
This module scores an IR face crop with simple reflectance statistics and
rejects obvious spoofs. It is an **additional** gate alongside the existing
hand-crafted-features PAD logreg — it does not replace it.

Extension point: pass a custom ``classifier`` callable
``(feats: np.ndarray) -> float`` returning a live-probability in ``[0, 1]``
to swap the heuristic for a learned head later (CPU or Hailo).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np

logger = logging.getLogger("driveauth.hardware.ir_liveness")

ClassifierFn = Callable[[np.ndarray], float]


@dataclass(frozen=True)
class LivenessResult:
    live: bool
    score: float
    features: np.ndarray
    reason: str = ""


def extract_ir_reflectance_features(ir_crop: np.ndarray) -> np.ndarray:
    """
    Feature vector from an IR face region (gray or single-channel float/uint8).

    Layout (8-d):
      mean, std, p10, p50, p90, contrast (p90-p10),
      high-freq energy ratio, saturation-bin fraction (near 0 or 255)
    """
    img = np.asarray(ir_crop, dtype=np.float32)
    if img.ndim == 3:
        img = img.mean(axis=2)
    flat = img.reshape(-1)
    if flat.size == 0:
        return np.zeros(8, dtype=np.float32)

    # Normalize to 0..255 scale for stable thresholds.
    if flat.max() <= 1.5:
        flat = flat * 255.0

    mean = float(np.mean(flat))
    std = float(np.std(flat))
    p10, p50, p90 = (float(x) for x in np.percentile(flat, [10, 50, 90]))
    contrast = p90 - p10

    # High-frequency energy via simple Laplacian-ish residual.
    g = flat.reshape(img.shape)
    if g.shape[0] >= 3 and g.shape[1] >= 3:
        center = g[1:-1, 1:-1]
        neigh = (
            g[:-2, 1:-1]
            + g[2:, 1:-1]
            + g[1:-1, :-2]
            + g[1:-1, 2:]
        ) * 0.25
        hf = float(np.mean((center - neigh) ** 2))
        energy = float(np.mean(center**2)) + 1e-6
        hf_ratio = hf / energy
    else:
        hf_ratio = 0.0

    sat = float(np.mean((flat <= 5.0) | (flat >= 250.0)))
    return np.array(
        [mean, std, p10, p50, p90, contrast, hf_ratio, sat],
        dtype=np.float32,
    )


def heuristic_live_proba(feats: np.ndarray) -> float:
    """
    Skin under IR tends to be mid-tone with moderate contrast and texture.
    Flat bright/dark plates (screens/prints) score low.
    """
    mean, std, _p10, _p50, _p90, contrast, hf_ratio, sat = (float(x) for x in feats)
    score = 0.5
    # Mid reflectance is good; blown-out or pitch-black is spoof-like.
    if 40.0 <= mean <= 200.0:
        score += 0.15
    else:
        score -= 0.25
    if 12.0 <= std <= 70.0:
        score += 0.15
    else:
        score -= 0.15
    if 25.0 <= contrast <= 160.0:
        score += 0.1
    else:
        score -= 0.1
    if hf_ratio >= 0.002:
        score += 0.1
    else:
        score -= 0.2
    if sat <= 0.08:
        score += 0.05
    else:
        score -= 0.25
    return float(np.clip(score, 0.0, 1.0))


class IRLivenessChecker:
    """Independent IR liveness gate (fail-closed on bad/missing crops)."""

    def __init__(
        self,
        *,
        threshold: float = 0.55,
        classifier: ClassifierFn | None = None,
    ):
        self.threshold = float(threshold)
        self._classifier: ClassifierFn = classifier or heuristic_live_proba

    def check(self, ir_crop: np.ndarray | None) -> LivenessResult:
        if ir_crop is None:
            return LivenessResult(
                live=False, score=0.0, features=np.zeros(8, dtype=np.float32), reason="missing_crop"
            )
        try:
            feats = extract_ir_reflectance_features(ir_crop)
            score = float(self._classifier(feats))
            live = score >= self.threshold
            return LivenessResult(
                live=live,
                score=score,
                features=feats,
                reason="live" if live else "spoof_suspect",
            )
        except Exception as exc:
            logger.warning("IRLivenessChecker: failed (%s)", type(exc).__name__)
            return LivenessResult(
                live=False,
                score=0.0,
                features=np.zeros(8, dtype=np.float32),
                reason="checker_error",
            )
