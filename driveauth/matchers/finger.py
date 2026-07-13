"""FingerNet-lite ONNX fingerprint matcher."""

from __future__ import annotations

import logging
import socket
import time
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.matchers.finger")


class FingerMatcher:
    def __init__(self, session, driver_template: bytes | None):
        self._session = session
        self._template = driver_template
        self._socket = config.FINGER_SOCKET

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> FingerMatcher:
        store = Path(store_dir)
        session = None
        driver_template: bytes | None = None

        onnx_path = store / "fingernet_lite_int8.onnx"
        if onnx_path.exists():
            try:
                import onnxruntime as ort  # type: ignore

                session = ort.InferenceSession(
                    str(onnx_path),
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                logger.info("FingerMatcher: FingerNet-lite loaded")
            except Exception as exc:
                logger.warning("FingerMatcher: ONNX load failed (%s)", exc)

        finger_enc = store / "fingers" / f"{driver_id}.enc"
        if finger_enc.exists():
            try:
                from cryptography.fernet import Fernet  # type: ignore

                key_path = store / ".bio_key"
                if key_path.exists():
                    f = Fernet(key_path.read_bytes())
                    driver_template = f.decrypt(finger_enc.read_bytes())
                    logger.info("FingerMatcher: template loaded for %s", driver_id)
            except Exception as exc:
                logger.error("FingerMatcher: template load failed: %s", exc)

        return cls(session, driver_template)

    def capture_and_score(self) -> ModalityResult:
        t0 = time.perf_counter()
        if self._session is None or self._template is None:
            return ModalityResult(score=None, confident=False)

        raw_scan: bytes | None = None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect(self._socket)
            s.sendall(b"SCAN\n")
            chunks: list[bytes] = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            raw_scan = b"".join(chunks)
            s.close()
        except Exception as exc:
            logger.warning("FingerMatcher: sensor read failed (%s)", exc)
            return ModalityResult(score=None, confident=False)

        if not raw_scan or len(raw_scan) < 256 * 256:
            return ModalityResult(score=None, confident=False)

        try:
            img = np.frombuffer(raw_scan[: 256 * 256], dtype=np.uint8).reshape(
                1, 1, 256, 256
            )
            blob = img.astype(np.float32) / 255.0
            input_name = self._session.get_inputs()[0].name
            minutiae = self._session.run(None, {input_name: blob})[0][0]
            tmpl = np.frombuffer(self._template, dtype=np.float32)
            if len(tmpl) != len(minutiae):
                return ModalityResult(score=None, confident=False)
            sim = float(
                np.clip(
                    float(np.dot(minutiae, tmpl))
                    / (np.linalg.norm(minutiae) * np.linalg.norm(tmpl) + 1e-8),
                    0.0,
                    1.0,
                )
            )
            lat = (time.perf_counter() - t0) * 1000
            return ModalityResult(
                sim, True, latency_ms=lat, embedding=minutiae.astype(np.float32)
            )
        except Exception as exc:
            logger.error("FingerMatcher.capture_and_score: %s", exc)
            return ModalityResult(score=None, confident=False)
