"""MobileFaceNet ONNX face matcher (optional OpenCV + ONNX Runtime)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth.matchers.face_pad_features import extract_face_pad_features
from driveauth.matchers.onnx_head import OnnxLogitHead
from driveauth.stage2_artifacts import (
    FACE_CALIBRATOR,
    FACE_PAD,
    load_artifact_meta,
    resolve_bio_artifact,
)
from driveauth.template_store import load_embedding
from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.matchers.face")

# Bonafide probability below this → PAD reject (overridable via env).
_DEFAULT_PAD_THRESHOLD = 0.45


def _ort_providers() -> list[str]:
    """Pick ORT providers.

    Override with comma-separated ``DRIVEAUTH_ORT_PROVIDERS``, e.g.
    ``CPUExecutionProvider`` when a CUDA wheel lacks this GPU's SM arch
    (``cudaErrorNoKernelImageForDevice``).
    """
    import os

    raw = (os.getenv("DRIVEAUTH_ORT_PROVIDERS") or "").strip()
    if raw:
        requested = [p.strip() for p in raw.split(",") if p.strip()]
        try:
            import onnxruntime as ort  # type: ignore

            available = set(ort.get_available_providers())
        except Exception:
            available = set()
        picked = [p for p in requested if p in available] or ["CPUExecutionProvider"]
        return picked

    try:
        import onnxruntime as ort  # type: ignore

        available = set(ort.get_available_providers())
    except Exception:
        return ["CPUExecutionProvider"]
    preferred = [
        "CUDAExecutionProvider",
        "CoreMLExecutionProvider",
        "CPUExecutionProvider",
    ]
    return [p for p in preferred if p in available] or ["CPUExecutionProvider"]


def _open_face_session(onnx_path: Path):
    """Load ONNX; if CUDA EP fails a smoke run, fall back to CPU."""
    import onnxruntime as ort  # type: ignore

    providers = _ort_providers()
    try:
        session = ort.InferenceSession(str(onnx_path), providers=providers)
    except Exception as exc:
        logger.warning("FaceMatcher: ONNX open failed (%s)", exc)
        return None

    # Probe once — CUDA wheels built for the wrong SM fail at Relu, not at load.
    try:
        inp = session.get_inputs()[0]
        shape = []
        for dim in inp.shape:
            if isinstance(dim, int) and dim > 0:
                shape.append(dim)
            else:
                shape.append(1)
        if len(shape) == 4:
            # NCHW MobileFaceNet: (1, 3, 112, 112)
            shape = [1, 3, 112, 112]
        dummy = np.zeros(shape, dtype=np.float32)
        session.run(None, {inp.name: dummy})
        logger.info(
            "FaceMatcher: ONNX loaded from %s (%s)",
            onnx_path.name,
            session.get_providers(),
        )
        return session
    except Exception as exc:
        if "CUDAExecutionProvider" not in providers:
            logger.warning("FaceMatcher: ONNX smoke failed (%s)", exc)
            return None
        logger.warning(
            "FaceMatcher: CUDA EP failed smoke (%s) — falling back to CPU",
            exc,
        )
        try:
            session = ort.InferenceSession(
                str(onnx_path), providers=["CPUExecutionProvider"]
            )
            logger.info(
                "FaceMatcher: ONNX loaded from %s (%s)",
                onnx_path.name,
                session.get_providers(),
            )
            return session
        except Exception as exc2:
            logger.warning("FaceMatcher: CPU fallback failed (%s)", exc2)
            return None


class FaceMatcher:
    _FACE_SIZE = (112, 112)
    _MIN_FACE_FRAC = config.FACE_MIN_FRAC

    def __init__(
        self,
        session,
        driver_embedding: np.ndarray | None,
        *,
        pad_head: OnnxLogitHead | None = None,
        calibrator: OnnxLogitHead | None = None,
        pad_threshold: float = _DEFAULT_PAD_THRESHOLD,
        driver_id: str = "driver1",
        stage2_info: dict | None = None,
    ):
        self._session = session
        self._emb = driver_embedding
        self._cam_idx = config.IR_CAMERA_INDEX
        self._inject_bgr: np.ndarray | None = None
        self._last_meta: dict = {}
        self._pad = pad_head
        self._calibrator = calibrator
        self._pad_threshold = pad_threshold
        self.driver_id = driver_id
        self.stage2_info = stage2_info or {}
        self.last_pad_score: float | None = None
        self.last_pad_reject: bool = False

    @property
    def ready(self) -> bool:
        return self._session is not None and self._emb is not None

    @property
    def has_pad(self) -> bool:
        return self._pad is not None

    @property
    def has_calibrator(self) -> bool:
        return self._calibrator is not None

    def inject_bgr(self, frame_bgr: np.ndarray | None) -> None:
        """Phase 2a / Mac: feed a still frame instead of the live camera."""
        self._inject_bgr = None if frame_bgr is None else np.asarray(frame_bgr)

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> FaceMatcher:
        store = Path(store_dir)
        session = None

        candidates = [
            store / "mobilefacenet_int8.onnx",
            store / "mobilefacenet.onnx",
            store / "models" / "mobilefacenet.onnx",
            store / "models" / "arcface_mobilefacenet.onnx",
        ]
        onnx_path = next((p for p in candidates if p.exists()), None)
        if onnx_path is not None:
            session = _open_face_session(onnx_path)
        else:
            logger.warning(
                "FaceMatcher: model not found (tried mobilefacenet*.onnx under %s)",
                store,
            )

        driver_embedding = load_embedding(store, f"faces/{driver_id}.enc")
        if driver_embedding is not None:
            logger.info("FaceMatcher: template loaded for %s", driver_id)

        pad_head = None
        calibrator = None
        pad_thr = _DEFAULT_PAD_THRESHOLD
        stage2_info: dict = {
            "driver_id": driver_id,
            "pad_source": "missing",
            "calibrator_source": "missing",
            "pad_enabled": False,
        }
        if os.getenv("DRIVEAUTH_STAGE2_RAW", "").strip() not in ("1", "true", "yes"):
            pad_ref = resolve_bio_artifact(store, driver_id, FACE_PAD)
            cal_ref = resolve_bio_artifact(store, driver_id, FACE_CALIBRATOR)
            stage2_info["pad_source"] = pad_ref.source
            stage2_info["calibrator_source"] = cal_ref.source
            stage2_info["pad_relpath"] = pad_ref.relpath
            stage2_info["calibrator_relpath"] = cal_ref.relpath
            if pad_ref.path is not None:
                pad_head = OnnxLogitHead.load(pad_ref.path)
            if cal_ref.path is not None:
                calibrator = OnnxLogitHead.load(cal_ref.path)
            thr_env = os.getenv("DRIVEAUTH_FACE_PAD_THRESHOLD", "").strip()
            if thr_env:
                try:
                    pad_thr = float(thr_env)
                except ValueError:
                    pass
            pad_meta = load_artifact_meta(pad_ref)
            if "threshold" in pad_meta and not thr_env:
                try:
                    pad_thr = float(pad_meta["threshold"])
                except (TypeError, ValueError):
                    pass
            # Honesty: LOO AUC ≈ 0.5 means chance — do not enforce as a live gate.
            loo_auc = pad_meta.get("loo_auc")
            try:
                loo_f = float(loo_auc) if loo_auc is not None else None
            except (TypeError, ValueError):
                loo_f = None
            stage2_info["pad_loo_auc"] = loo_f
            stage2_info["pad_threshold"] = pad_thr
            stage2_info["trained_at"] = pad_meta.get("trained_at") or pad_meta.get(
                "timestamp"
            )
            if pad_head is not None and loo_f is not None and loo_f <= 0.55:
                logger.error(
                    "FaceMatcher[%s]: face_pad LOO AUC=%.4f ≈ chance — PAD gate "
                    "DISABLED (onnx present but not enforced; source=%s). "
                    "Collect more separable attack data or leave PAD off; "
                    "see docs/security-assumptions.md.",
                    driver_id,
                    loo_f,
                    pad_ref.source,
                )
                pad_head = None
                stage2_info["pad_enabled"] = False
                stage2_info["pad_disabled_reason"] = f"loo_auc={loo_f:.4f}<=0.55"
            elif pad_head is not None:
                logger.info(
                    "FaceMatcher[%s]: Stage-2 PAD loaded (thr=%.3f, source=%s)",
                    driver_id,
                    pad_thr,
                    pad_ref.source,
                )
                stage2_info["pad_enabled"] = True
            if calibrator is not None:
                logger.info(
                    "FaceMatcher[%s]: Stage-2 face calibrator loaded (source=%s)",
                    driver_id,
                    cal_ref.source,
                )

        return cls(
            session,
            driver_embedding,
            pad_head=pad_head,
            calibrator=calibrator,
            pad_threshold=pad_thr,
            driver_id=driver_id,
            stage2_info=stage2_info,
        )

    def _run_pad(self, crop_bgr: np.ndarray) -> tuple[bool, float]:
        """Return (pass, bonafide_proba). pass=True when no PAD or score≥thr."""
        self.last_pad_score = None
        self.last_pad_reject = False
        if self._pad is None:
            return True, 1.0
        meta = self._last_meta or {}
        feats = extract_face_pad_features(
            crop_bgr,
            face_frac=meta.get("face_frac"),
            frontal_ok=meta.get("frontal_ok"),
        )
        proba = float(self._pad.predict_proba(feats))
        self.last_pad_score = proba
        ok = proba >= self._pad_threshold
        self.last_pad_reject = not ok
        return ok, proba

    def embed_bgr(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        if self._session is None or frame_bgr is None:
            return None
        try:
            import cv2  # type: ignore

            meta = self._extract_face_meta(frame_bgr, cv2)
            if meta is None:
                h, w = frame_bgr.shape[:2]
                side = min(h, w)
                y0, x0 = (h - side) // 2, (w - side) // 2
                crop = frame_bgr[y0 : y0 + side, x0 : x0 + side]
            else:
                crop, face_frac, frontal_ok = meta
                self._last_meta = {
                    "face_frac": face_frac,
                    "frontal_ok": frontal_ok,
                    "bgr": crop,
                }
            return self._embed_crop_bgr(crop)
        except Exception as exc:
            logger.error("FaceMatcher.embed_bgr: %s", exc)
            return None

    def _embed_crop_bgr(self, crop_bgr: np.ndarray) -> np.ndarray | None:
        import cv2  # type: ignore

        face_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        face_rgb = cv2.resize(face_rgb, self._FACE_SIZE)
        blob = (face_rgb.astype(np.float32) - 127.5) / 128.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis]
        input_name = self._session.get_inputs()[0].name
        emb = self._session.run(None, {input_name: blob})[0][0].astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb /= norm
        return emb

    def _read_camera_bgr(self):
        import cv2  # type: ignore

        if self._inject_bgr is not None:
            return self._inject_bgr
        cap = cv2.VideoCapture(self._cam_idx)
        if not cap.isOpened():
            return None
        for _ in range(3):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

    def capture_and_score(self) -> ModalityResult:
        t0 = time.perf_counter()
        if not self.ready:
            return ModalityResult(score=None, confident=False, available=False)
        try:
            import cv2  # type: ignore

            frame = self._read_camera_bgr()
            if frame is None:
                return ModalityResult(score=None, confident=False, available=False)
            # Must populate _last_meta the same way as capture_frame / train_face_pad
            # (_load_meta_for). _extract_face_crop alone drops face_frac/frontal_ok;
            # PAD then defaults face_frac→1.0 and attacks pass the gate.
            meta = self._extract_face_meta(frame, cv2)
            if meta is not None:
                crop, face_frac, frontal_ok = meta
                self._last_meta = {
                    "face_frac": face_frac,
                    "frontal_ok": frontal_ok,
                    "bgr": crop,
                }
            elif self._inject_bgr is not None:
                crop = self._center_crop(frame)
                self._last_meta = {
                    "face_frac": 1.0,
                    "frontal_ok": True,
                    "bgr": crop,
                    "inject_fallback": True,
                }
            else:
                crop = None
            if crop is None:
                return ModalityResult(
                    score=None, confident=False, quality=0.2, available=False
                )
            pad_ok, pad_p = self._run_pad(crop)
            if not pad_ok:
                lat = (time.perf_counter() - t0) * 1000
                return ModalityResult(
                    score=None,
                    confident=False,
                    latency_ms=lat,
                    quality=float(pad_p),
                    available=True,
                )
            emb = self._embed_crop_bgr(crop)
            if emb is None or self._emb is None:
                return ModalityResult(score=None, confident=False, available=False)
            # Cosine in [0,1] after L2-norm; higher = closer to enrolled identity.
            # Raw attack>genuine on driver1 stills is NOT a sign bug: many genuine
            # frames miss Haar and fall back to a loose center-crop (lower sim),
            # while same-identity PA attacks (blur/screen) get a tight face crop
            # and therefore score higher. PAD + calibrator are what separate them.
            sim = float(np.clip(float(np.dot(self._emb, emb)), 0.0, 1.0))
            score = sim
            if self._calibrator is not None:
                feats = np.array(
                    [sim, pad_p, float((self._last_meta or {}).get("face_frac") or 1.0)],
                    dtype=np.float32,
                )
                score = float(np.clip(self._calibrator.predict_proba(feats), 0.0, 1.0))
            lat = (time.perf_counter() - t0) * 1000
            return ModalityResult(score, True, latency_ms=lat, embedding=emb)
        except Exception as exc:
            logger.error("FaceMatcher.capture_and_score: %s", exc)
            return ModalityResult(score=None, confident=False, available=False)

    def _center_crop(self, frame_bgr: np.ndarray) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        return frame_bgr[y0 : y0 + side, x0 : x0 + side]

    def capture_frame(self):
        try:
            import cv2  # type: ignore

            if self._session is None:
                return None
            frame = self._read_camera_bgr()
            if frame is None:
                return None
            meta = self._extract_face_meta(frame, cv2)
            if meta is None:
                # Still-frame inject / hard images: center-crop like embed_bgr
                # so Phase 2a demos are not blocked by Haar misses.
                if self._inject_bgr is None:
                    return None
                crop_bgr = self._center_crop(frame)
                self._last_meta = {
                    "face_frac": 1.0,
                    "frontal_ok": True,
                    "bgr": crop_bgr,
                    "inject_fallback": True,
                }
                logger.info("FaceMatcher: Haar miss — center-crop fallback (inject)")
            else:
                crop_bgr, face_frac, frontal_ok = meta
                self._last_meta = {
                    "face_frac": face_frac,
                    "frontal_ok": frontal_ok,
                    "bgr": crop_bgr,
                }
            return cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        except Exception as exc:
            logger.debug("FaceMatcher.capture_frame: %s", exc)
            return None

    def score_frame(self, frame_gray: np.ndarray) -> ModalityResult:
        t0 = time.perf_counter()
        if not self.ready or frame_gray is None:
            return ModalityResult(score=None, confident=False, available=False)
        try:
            meta = getattr(self, "_last_meta", {}) or {}
            bgr = meta.get("bgr")
            if bgr is None:
                return ModalityResult(score=None, confident=False, available=False)
            pad_ok, pad_p = self._run_pad(bgr)
            if not pad_ok:
                lat = (time.perf_counter() - t0) * 1000
                return ModalityResult(
                    score=None,
                    confident=False,
                    latency_ms=lat,
                    quality=float(pad_p),
                    available=True,
                )
            emb = self._embed_crop_bgr(bgr)
            if emb is None or self._emb is None:
                return ModalityResult(score=None, confident=False, available=False)
            sim = float(np.clip(float(np.dot(self._emb, emb)), 0.0, 1.0))
            score = sim
            if self._calibrator is not None:
                feats = np.array(
                    [sim, pad_p, float(meta.get("face_frac") or 1.0)],
                    dtype=np.float32,
                )
                score = float(np.clip(self._calibrator.predict_proba(feats), 0.0, 1.0))
            lat = (time.perf_counter() - t0) * 1000
            return ModalityResult(score, True, latency_ms=lat, embedding=emb)
        except Exception as exc:
            logger.error("FaceMatcher.score_frame: %s", exc)
            return ModalityResult(score=None, confident=False, available=False)

    def _extract_face_meta(self, frame, cv2):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            detector = cv2.CascadeClassifier(cascade_path)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 0:
                return None
            frame_h, frame_w = frame.shape[0], frame.shape[1]
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
            face_frac = h / max(frame_h, 1)
            if face_frac < self._MIN_FACE_FRAC:
                return None
            cx = (x + w / 2.0) / max(frame_w, 1)
            aspect = w / max(h, 1)
            frontal_ok = 0.25 <= cx <= 0.75 and 0.65 <= aspect <= 1.35
            if not frontal_ok:
                return None
            pad = int(0.15 * h)
            x0 = max(0, x - pad)
            y0 = max(0, y - pad)
            x1 = min(frame_w, x + w + pad)
            y1 = min(frame_h, y + h + pad)
            return frame[y0:y1, x0:x1], face_frac, True
        except Exception as exc:
            logger.debug(
                "FaceMatcher: face-crop check failed (%s) — refusing full frame", exc
            )
            return None

    def _extract_face_crop(self, frame, cv2):
        meta = self._extract_face_meta(frame, cv2)
        return None if meta is None else meta[0]
