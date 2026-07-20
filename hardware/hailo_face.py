"""Hailo-8 face matcher — same ``ModalityResult`` contract as ``matchers/face``.

Convert MobileFaceNet/ArcFace ``.onnx`` → ``.hef`` with the Hailo Dataflow
Compiler + Model Zoo, then point ``DRIVEAUTH_FACE_BACKEND=hailo`` (and
``DRIVEAUTH_HAILO_HEF``) at the artifact.

When the HailoRT runtime or device is absent, ``load()`` returns an unready
matcher that fail-closes (``available=False``) — never a fabricated pass.

IR liveness stays on CPU by default (Hailo ops for the heuristic classifier
are not required); see ``docs/security-assumptions.md``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from driveauth.template_store import load_embedding
from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.hardware.hailo_face")

_FACE_SIZE = (112, 112)
_EMB_DIM = 512


class HailoFaceMatcher:
    """Drop-in face matcher backed by a Hailo ``.hef`` network."""

    def __init__(
        self,
        hef_path: str | Path | None,
        driver_embedding: np.ndarray | None,
        *,
        infer_fn=None,
        vdevice=None,
    ):
        self._hef = Path(hef_path) if hef_path else None
        self._emb = driver_embedding
        self._infer_fn = infer_fn
        self._vdevice = vdevice
        self._inject_bgr: np.ndarray | None = None
        self._last_meta: dict = {}
        self.last_pad_score: float | None = None
        self.last_pad_reject: bool = False
        self.face_frac: float | None = None
        self.frontal_ok: bool | None = None

    @property
    def ready(self) -> bool:
        return self._infer_fn is not None and self._emb is not None

    def inject_bgr(self, frame_bgr: np.ndarray | None) -> None:
        self._inject_bgr = None if frame_bgr is None else np.asarray(frame_bgr)

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> HailoFaceMatcher:
        store = Path(store_dir)
        from driveauth import config

        hef = Path(config.HAILO_HEF) if config.HAILO_HEF else store / "mobilefacenet.hef"
        if not hef.is_file():
            alt = store / "models" / "mobilefacenet.hef"
            hef = alt if alt.is_file() else hef

        driver_embedding = load_embedding(store, f"faces/{driver_id}.enc")
        infer_fn = None
        vdevice = None
        if hef.is_file():
            infer_fn, vdevice = _try_open_hailo(hef)
        else:
            logger.info("HailoFaceMatcher: HEF not found at %s", hef)

        return cls(hef if hef.is_file() else None, driver_embedding, infer_fn=infer_fn, vdevice=vdevice)

    def capture_frame(self) -> np.ndarray | None:
        frame = self._inject_bgr
        if frame is None:
            return None
        gray = frame.astype(np.float32)
        if gray.ndim == 3:
            gray = gray.mean(axis=2)
        h, w = gray.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        crop = gray[y0 : y0 + side, x0 : x0 + side]
        self._last_meta = {
            "face_frac": 1.0,
            "frontal_ok": True,
            "bgr": frame[y0 : y0 + side, x0 : x0 + side]
            if frame.ndim == 3
            else frame,
        }
        self.face_frac = 1.0
        self.frontal_ok = True
        return crop.astype(np.float32)

    def score_frame(self, frame_gray: np.ndarray) -> ModalityResult:
        return self.capture_and_score()

    def capture_and_score(self) -> ModalityResult:
        t0 = time.perf_counter()
        if not self.ready:
            return ModalityResult(score=None, confident=False, available=False)
        try:
            bgr = self._inject_bgr
            if bgr is None:
                return ModalityResult(score=None, confident=False, available=False)
            emb = self._embed(bgr)
            if emb is None or self._emb is None:
                return ModalityResult(score=None, confident=False, available=False)
            sim = float(np.clip(float(np.dot(self._emb, emb)), 0.0, 1.0))
            lat = (time.perf_counter() - t0) * 1000
            return ModalityResult(sim, True, latency_ms=lat, embedding=emb)
        except Exception as exc:
            logger.error("HailoFaceMatcher.capture_and_score: %s", exc)
            return ModalityResult(score=None, confident=False, available=False)

    def _embed(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        blob = _preprocess_face(frame_bgr)
        out = self._infer_fn(blob)
        if out is None:
            return None
        emb = np.asarray(out, dtype=np.float32).reshape(-1)
        if emb.size < _EMB_DIM:
            padded = np.zeros(_EMB_DIM, dtype=np.float32)
            padded[: emb.size] = emb
            emb = padded
        else:
            emb = emb[:_EMB_DIM]
        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb = emb / norm
        return emb


def _preprocess_face(frame_bgr: np.ndarray) -> np.ndarray:
    img = np.asarray(frame_bgr)
    if img.ndim == 2:
        img = np.stack([img, img, img], axis=-1)
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    crop = img[y0 : y0 + side, x0 : x0 + side]
    try:
        import cv2  # type: ignore

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, _FACE_SIZE)
    except ImportError:
        rgb = crop[..., ::-1] if crop.shape[-1] == 3 else crop
        ys = (np.linspace(0, rgb.shape[0] - 1, _FACE_SIZE[1])).astype(np.int32)
        xs = (np.linspace(0, rgb.shape[1] - 1, _FACE_SIZE[0])).astype(np.int32)
        rgb = rgb[ys][:, xs]
    blob = (rgb.astype(np.float32) - 127.5) / 128.0
    return np.transpose(blob, (2, 0, 1))[np.newaxis]


def _try_open_hailo(hef_path: Path):
    """Open HailoRT VDevice + network. Returns (infer_fn, vdevice) or (None, None)."""
    try:
        from hailo_platform import (  # type: ignore
            HEF,
            ConfigureParams,
            FormatType,
            HailoStreamInterface,
            InferVStreams,
            InputVStreamParams,
            OutputVStreamParams,
            VDevice,
        )
    except ImportError:
        logger.info("HailoFaceMatcher: hailo_platform not installed")
        return None, None

    try:
        vdevice = VDevice()
        hef = HEF(str(hef_path))
        configure_params = ConfigureParams.create_from_hef(
            hef, interface=HailoStreamInterface.PCIe
        )
        network_group = vdevice.configure(hef, configure_params)[0]
        network_group_params = network_group.create_params()
        input_vstreams_params = InputVStreamParams.make_from_network_group(
            network_group, quantized=False, format_type=FormatType.FLOAT32
        )
        output_vstreams_params = OutputVStreamParams.make_from_network_group(
            network_group, quantized=False, format_type=FormatType.FLOAT32
        )
        input_name = hef.get_input_vstream_infos()[0].name

        def _infer(blob: np.ndarray) -> np.ndarray | None:
            with network_group.activate(network_group_params):
                with InferVStreams(
                    network_group, input_vstreams_params, output_vstreams_params
                ) as pipeline:
                    results = pipeline.infer({input_name: blob})
                    # First output tensor
                    for val in results.values():
                        return np.asarray(val)
            return None

        logger.info("HailoFaceMatcher: HEF loaded from %s", hef_path.name)
        return _infer, vdevice
    except Exception as exc:
        logger.warning("HailoFaceMatcher: device open failed (%s)", type(exc).__name__)
        return None, None
