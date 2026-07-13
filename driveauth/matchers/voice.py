"""ECAPA-TDNN voice matcher (optional SpeechBrain dependency)."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np

from driveauth.template_store import load_embedding
from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.matchers.voice")

_PREEMPH = 0.97
_RMS_TGT = 0.08
_RMS_FLOOR = 1e-6


def preprocess(audio: np.ndarray) -> np.ndarray:
    out = np.empty_like(audio, dtype=np.float32)
    out[0] = audio[0]
    out[1:] = audio[1:] - _PREEMPH * audio[:-1]
    rms = float(np.sqrt(np.mean(out**2)))
    if rms > _RMS_FLOOR:
        out *= _RMS_TGT / rms
    return out


class VoiceMatcher:
    """Cosine similarity against an enrolled voiceprint."""

    def __init__(self, ecapa_model, driver_embedding: np.ndarray | None, device: str):
        self._model = ecapa_model
        self._emb = driver_embedding
        self._device = device

    @property
    def ready(self) -> bool:
        return self._model is not None and self._emb is not None

    @classmethod
    def load_ecapa(cls, savedir: str | Path, device: str = "cpu"):
        """Download/load pretrained SpeechBrain ECAPA (Phase 2a)."""
        from speechbrain.inference.speaker import SpeakerRecognition  # type: ignore

        # Prefer new API; fall back to deprecated path for older speechbrain.
        try:
            return SpeakerRecognition.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(savedir),
                run_opts={"device": device},
            )
        except Exception:
            from speechbrain.pretrained import SpeakerRecognition as SROld  # type: ignore

            return SROld.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(savedir),
                run_opts={"device": device},
            )

    @classmethod
    def load(
        cls,
        enroll_dir: str,
        driver_id: str = "driver1",
        device: str | None = None,
        store_dir: str | None = None,
    ) -> VoiceMatcher:
        if device is None:
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
                # Apple Silicon
                if device == "cpu" and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "cpu"  # SpeechBrain ECAPA is more reliable on CPU on Mac
            except ImportError:
                device = "cpu"

        enroll_path = Path(enroll_dir)
        store_path = Path(store_dir) if store_dir else enroll_path
        sys.path.insert(0, str(enroll_path))

        driver_embedding: np.ndarray | None = None

        # Prefer local Fernet template (Phase 2a enroll scripts).
        driver_embedding = load_embedding(store_path, f"voices/{driver_id}.enc")
        if driver_embedding is not None:
            logger.info("VoiceMatcher: voiceprint loaded from store for %s", driver_id)
        else:
            # Nova L-3 compatibility path
            try:
                from crypto_utils import load_array  # type: ignore

                vp_path = enroll_path / "data" / "voiceprints" / f"{driver_id}.enc"
                if vp_path.exists():
                    emb = load_array(vp_path)
                    norm = np.linalg.norm(emb)
                    driver_embedding = emb / norm if norm > 1e-8 else emb
                    logger.info("VoiceMatcher: Nova voiceprint loaded for %s", driver_id)
            except Exception as exc:
                logger.debug("VoiceMatcher: Nova voiceprint path unused (%s)", exc)

        ecapa_savedir = store_path / "models" / "ecapa_voxceleb"
        ecapa_model = None
        try:
            ecapa_model = cls.load_ecapa(ecapa_savedir, device=device)
            logger.info("VoiceMatcher: ECAPA-TDNN loaded (%s)", device)
        except Exception as exc:
            logger.warning("VoiceMatcher: ECAPA load failed (%s)", exc)

        return cls(ecapa_model, driver_embedding, device)

    def embed(self, audio_f32: np.ndarray, sample_rate: int = 16_000) -> np.ndarray | None:
        if self._model is None or audio_f32 is None or len(audio_f32) < sample_rate // 2:
            return None
        try:
            import torch

            proc = preprocess(audio_f32.astype(np.float32))
            wav = torch.from_numpy(proc).unsqueeze(0).to(self._device)
            with torch.no_grad():
                emb = self._model.encode_batch(wav)
            live = emb.squeeze().cpu().numpy().astype(np.float32)
            norm = float(np.linalg.norm(live))
            if norm > 1e-8:
                live /= norm
            return live
        except Exception as exc:
            logger.error("VoiceMatcher.embed: %s", exc)
            return None

    def score(self, audio_f32: np.ndarray, sample_rate: int = 16_000) -> ModalityResult:
        t0 = time.perf_counter()
        if not self.ready:
            return ModalityResult(score=None, confident=False, available=False)
        if len(audio_f32) < sample_rate:
            return ModalityResult(score=None, confident=False)

        try:
            live_emb = self.embed(audio_f32, sample_rate)
            if live_emb is None or self._emb is None:
                return ModalityResult(score=None, confident=False, available=False)
            sim = float(np.clip(float(np.dot(self._emb, live_emb)), 0.0, 1.0))
            lat = (time.perf_counter() - t0) * 1000
            return ModalityResult(sim, True, latency_ms=lat, embedding=live_emb)
        except Exception as exc:
            logger.error("VoiceMatcher.score: %s", exc)
            return ModalityResult(score=None, confident=False, available=False)
