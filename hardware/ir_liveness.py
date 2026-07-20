"""IR / multi-signal liveness — heuristic ensemble (not ISO-certified).

Liveness v2 is a stronger heuristic ensemble; still not independently
certified anti-spoofing. Certification requires third-party PAD testing
against ISO/IEC 30107-3, which is out of scope.

Signals (when ``ensemble=True``):
  (a) IR reflectance — existing mid-tone / contrast / texture heuristic
  (b) Micro-motion / blink — mean absolute change across a 2–3 frame burst
  (c) Moiré / screen-grid — frequency-domain peaks typical of display replay

Default ``ensemble=False`` preserves the Phase-3 reflectance-only gate
verbatim (fail-closed on missing crops). Opt in via
``DRIVEAUTH_IR_LIVENESS_ENSEMBLE=1`` / ``IRLivenessChecker(ensemble=True)``.

Extension point: pass a custom ``classifier`` callable
``(feats: np.ndarray) -> float`` returning a live-probability in ``[0, 1]``
to swap the reflectance heuristic for a learned head later (CPU or Hailo).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

logger = logging.getLogger("driveauth.hardware.ir_liveness")

ClassifierFn = Callable[[np.ndarray], float]

# Ensemble weights (sum = 1.0). Threshold comparison is still on the
# weighted average — no learned fusion, no robustness claim.
_DEFAULT_ENSEMBLE_WEIGHTS = {
    "reflectance": 0.45,
    "blink": 0.30,
    "moire": 0.25,
}


@dataclass(frozen=True)
class LivenessResult:
    live: bool
    score: float
    features: np.ndarray
    reason: str = ""
    signal_scores: dict[str, float] = field(default_factory=dict)


def _to_gray_f32(ir_crop: np.ndarray) -> np.ndarray:
    img = np.asarray(ir_crop, dtype=np.float32)
    if img.ndim == 3:
        img = img.mean(axis=2)
    if img.size and float(img.max()) <= 1.5:
        img = img * 255.0
    return img


def extract_ir_reflectance_features(ir_crop: np.ndarray) -> np.ndarray:
    """
    Feature vector from an IR face region (gray or single-channel float/uint8).

    Layout (8-d):
      mean, std, p10, p50, p90, contrast (p90-p10),
      high-freq energy ratio, saturation-bin fraction (near 0 or 255)
    """
    img = _to_gray_f32(ir_crop)
    flat = img.reshape(-1)
    if flat.size == 0:
        return np.zeros(8, dtype=np.float32)

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


def score_blink_motion(frames: Sequence[np.ndarray]) -> float:
    """
    Live-probability from micro-motion / blink across a short burst.

    Uses mean absolute frame-to-frame difference, with a soft boost when the
    upper face band (approx. eye region) darkens then recovers — a cheap
    blink proxy. Static prints / frozen screen replays score low.
    Returns a value in ``[0, 1]``. Fewer than 2 usable frames → 0.0
    (fail-closed when this signal is required by the ensemble).
    """
    grays: list[np.ndarray] = []
    for fr in frames:
        if fr is None:
            continue
        g = _to_gray_f32(fr)
        if g.size == 0:
            continue
        grays.append(g)
    if len(grays) < 2:
        return 0.0

    # Align to the smallest shared shape (synthetic tests are square; live
    # bursts should already be cropped to FACE_CROP_SIZE).
    h = min(g.shape[0] for g in grays)
    w = min(g.shape[1] for g in grays)
    stack = np.stack([g[:h, :w] for g in grays], axis=0)

    diffs = np.abs(np.diff(stack.astype(np.float64), axis=0))
    mad = float(np.mean(diffs))
    # Eye band ≈ upper-middle third of the crop.
    y0, y1 = h // 4, h // 2
    eye = stack[:, y0:y1, :]
    eye_means = eye.reshape(eye.shape[0], -1).mean(axis=1)
    eye_swing = float(np.max(eye_means) - np.min(eye_means)) if eye_means.size else 0.0

    # Static spoof: mad ≈ 0. Live skin micro-motion: mad often 1–8 on 0–255.
    # A blink deepens the eye band by tens of gray levels.
    score = 0.15
    if mad >= 1.5:
        score += 0.35
    elif mad >= 0.4:
        score += 0.15
    else:
        score -= 0.25
    if eye_swing >= 12.0:
        score += 0.35
    elif eye_swing >= 4.0:
        score += 0.15
    else:
        score -= 0.1
    if mad > 40.0:
        # Camera shake / cut — not a reliable blink; soften.
        score -= 0.15
    return float(np.clip(score, 0.0, 1.0))


def score_moire(ir_crop: np.ndarray) -> float:
    """
    Live-probability from a frequency-domain screen-grid / moiré check.

    Display replays often imprint a regular pixel / subpixel lattice that
    shows up as sharp mid/high-frequency peaks in the 2-D FFT (high
    max/median magnitude ratio). Natural skin reflectance is broader and
    less peaked. Returns a value in ``[0, 1]`` where **higher = more
    live-like** (less grid-like).
    """
    img = _to_gray_f32(ir_crop)
    if img.size == 0 or min(img.shape) < 16:
        return 0.0

    # Detrend so the DC blob does not dominate.
    g = img - float(np.mean(img))
    # Hann window reduces edge ringing that can look like a lattice.
    wy = np.hanning(g.shape[0]).astype(np.float64)
    wx = np.hanning(g.shape[1]).astype(np.float64)
    windowed = g.astype(np.float64) * wy[:, None] * wx[None, :]
    spec = np.fft.fftshift(np.abs(np.fft.fft2(windowed)))
    cy, cx = (spec.shape[0] // 2, spec.shape[1] // 2)
    # Zero a small DC neighbourhood.
    rad = max(2, min(spec.shape) // 16)
    yy, xx = np.ogrid[: spec.shape[0], : spec.shape[1]]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    mask = dist > rad
    band = spec[mask]
    if band.size == 0:
        return 0.5

    total = float(np.sum(band)) + 1e-9
    thr = float(np.percentile(band, 99.0))
    peak_share = float(np.sum(band[band >= thr])) / total
    # Peakiness vs broadband skin texture.
    max_med = float(np.max(band)) / (float(np.median(band)) + 1e-9)

    # High peak_share / max_med → spoof. Invert into live proba.
    score = 0.7
    if max_med >= 40.0:
        score -= 0.45
    elif max_med >= 15.0:
        score -= 0.25
    else:
        score += 0.15
    if peak_share >= 0.18:
        score -= 0.2
    elif peak_share >= 0.10:
        score -= 0.1
    return float(np.clip(score, 0.0, 1.0))


def combine_liveness_scores(
    scores: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted average over available signals; missing keys are dropped."""
    w = dict(weights or _DEFAULT_ENSEMBLE_WEIGHTS)
    num = 0.0
    den = 0.0
    for name, val in scores.items():
        wt = float(w.get(name, 0.0))
        if wt <= 0.0:
            continue
        num += wt * float(val)
        den += wt
    if den <= 1e-12:
        return 0.0
    return float(np.clip(num / den, 0.0, 1.0))


class IRLivenessChecker:
    """Independent IR liveness gate (fail-closed on bad/missing crops).

    ``ensemble=False`` (default): reflectance-only — identical to Phase 3.
    ``ensemble=True``: weighted reflectance + blink + moiré (Liveness v2).
    """

    def __init__(
        self,
        *,
        threshold: float = 0.55,
        classifier: ClassifierFn | None = None,
        ensemble: bool = False,
        weights: dict[str, float] | None = None,
    ):
        self.threshold = float(threshold)
        self._classifier: ClassifierFn = classifier or heuristic_live_proba
        self.ensemble = bool(ensemble)
        self._weights = dict(weights or _DEFAULT_ENSEMBLE_WEIGHTS)

    def check(
        self,
        ir_crop: np.ndarray | None,
        frames: Sequence[np.ndarray] | None = None,
    ) -> LivenessResult:
        if self.ensemble:
            return self._check_ensemble(ir_crop, frames)
        return self._check_reflectance_only(ir_crop)

    def check_sequence(self, frames: Sequence[np.ndarray | None]) -> LivenessResult:
        """Ensemble path from an explicit 2–3 frame burst."""
        usable = [f for f in frames if f is not None]
        crop = usable[0] if usable else None
        return self._check_ensemble(crop, usable)

    def _check_reflectance_only(self, ir_crop: np.ndarray | None) -> LivenessResult:
        if ir_crop is None:
            return LivenessResult(
                live=False,
                score=0.0,
                features=np.zeros(8, dtype=np.float32),
                reason="missing_crop",
                signal_scores={},
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
                signal_scores={"reflectance": score},
            )
        except Exception as exc:
            logger.warning("IRLivenessChecker: failed (%s)", type(exc).__name__)
            return LivenessResult(
                live=False,
                score=0.0,
                features=np.zeros(8, dtype=np.float32),
                reason="checker_error",
                signal_scores={},
            )

    def _check_ensemble(
        self,
        ir_crop: np.ndarray | None,
        frames: Sequence[np.ndarray] | None,
    ) -> LivenessResult:
        burst: list[np.ndarray] = []
        if frames:
            burst = [f for f in frames if f is not None]
        if ir_crop is None and burst:
            ir_crop = burst[0]
        if ir_crop is None and not burst:
            return LivenessResult(
                live=False,
                score=0.0,
                features=np.zeros(8, dtype=np.float32),
                reason="missing_crop",
                signal_scores={},
            )

        try:
            feats = extract_ir_reflectance_features(ir_crop)
            reflectance = float(self._classifier(feats))
            moire = score_moire(ir_crop)
            # Single frame → blink fail-closed (0.0) when ensemble is on.
            blink = score_blink_motion(burst) if len(burst) >= 2 else 0.0

            signal_scores = {
                "reflectance": reflectance,
                "blink": blink,
                "moire": moire,
            }
            score = combine_liveness_scores(signal_scores, self._weights)
            live = score >= self.threshold
            if live:
                reason = "live"
            else:
                weak = min(signal_scores, key=signal_scores.get)
                reason = f"spoof_suspect_{weak}"
            return LivenessResult(
                live=live,
                score=score,
                features=feats,
                reason=reason,
                signal_scores=signal_scores,
            )
        except Exception as exc:
            logger.warning("IRLivenessChecker: ensemble failed (%s)", type(exc).__name__)
            return LivenessResult(
                live=False,
                score=0.0,
                features=np.zeros(8, dtype=np.float32),
                reason="checker_error",
                signal_scores={},
            )
