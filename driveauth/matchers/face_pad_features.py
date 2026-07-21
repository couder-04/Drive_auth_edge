"""Hand-crafted face PAD features (Stage 2 — no deep PAD net)."""

from __future__ import annotations

import numpy as np

FACE_PAD_FEATURE_KEYS = (
    "sharpness",
    "brightness",
    "face_frac",
    "aspect",
    "lap_p90",
    "chroma_var",
    "sat_var",
    "edge_density",
)


def extract_face_pad_features(
    frame_bgr: np.ndarray,
    *,
    face_frac: float | None = None,
    frontal_ok: bool | None = None,
) -> np.ndarray:
    """Return float32 vector aligned with FACE_PAD_FEATURE_KEYS."""
    import cv2  # type: ignore

    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return np.zeros(len(FACE_PAD_FEATURE_KEYS), dtype=np.float32)

    bgr = np.asarray(frame_bgr)
    if bgr.ndim == 2:
        gray = bgr.astype(np.float32)
        bgr3 = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    else:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        bgr3 = bgr

    lap = cv2.Laplacian(gray, cv2.CV_32F)
    sharpness = float(lap.var())
    brightness = float(gray.mean())
    lap_p90 = float(np.percentile(np.abs(lap), 90))

    h, w = gray.shape[:2]
    aspect = float(w / max(h, 1))
    # Unknown face_frac must NOT default to 1.0 — that lied to PAD on Haar-miss
    # center-crops (attack_side scored as well-framed). Callers with a known
    # full-frame crop must pass face_frac=1.0 explicitly.
    frac = float(face_frac) if face_frac is not None else 0.0
    # Down-weight when non-frontal (side attacks) or unknown pose
    if frontal_ok is False:
        frac = min(frac, 0.25)
    elif frontal_ok is None and face_frac is None:
        frac = 0.0

    # Screen / print cues: high chroma regularity + saturation banding
    hsv = cv2.cvtColor(bgr3, cv2.COLOR_BGR2HSV).astype(np.float32)
    chroma_var = float(np.var(bgr3.astype(np.float32), axis=(0, 1)).mean())
    sat_var = float(hsv[:, :, 1].var())

    edges = cv2.Canny(gray.astype(np.uint8), 50, 150)
    edge_density = float(edges.mean() / 255.0)

    # Normalize loosely so logreg sees similar scales
    feats = np.array(
        [
            np.log1p(sharpness) / 10.0,
            brightness / 255.0,
            frac,
            aspect,
            np.log1p(lap_p90) / 8.0,
            np.log1p(chroma_var) / 12.0,
            np.log1p(sat_var) / 12.0,
            edge_density,
        ],
        dtype=np.float32,
    )
    return feats
