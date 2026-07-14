"""Small sklearn-logreg ONNX heads (Stage 2 calibrators / PAD / trust fusion)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("driveauth.matchers.onnx_head")


class OnnxLogitHead:
    """Run a skl2onnx LogisticRegression graph → P(class=1) in [0, 1]."""

    def __init__(self, session, input_name: str, n_features: int):
        self._session = session
        self._input_name = input_name
        self._n_features = n_features

    @property
    def n_features(self) -> int:
        return self._n_features

    @classmethod
    def load(cls, path: str | Path) -> OnnxLogitHead | None:
        path = Path(path)
        if not path.exists():
            return None
        try:
            import onnxruntime as ort  # type: ignore

            sess = ort.InferenceSession(
                str(path), providers=["CPUExecutionProvider"]
            )
            inp = sess.get_inputs()[0]
            shape = inp.shape
            n_feat = 1
            if len(shape) >= 2 and isinstance(shape[1], int) and shape[1] > 0:
                n_feat = int(shape[1])
            return cls(sess, inp.name, n_feat)
        except Exception as exc:
            logger.warning("OnnxLogitHead: failed to load %s (%s)", path, exc)
            return None

    def predict_proba(self, feats: np.ndarray) -> float:
        x = np.asarray(feats, dtype=np.float32).reshape(1, -1)
        if x.shape[1] != self._n_features:
            raise ValueError(
                f"feature dim {x.shape[1]} != expected {self._n_features}"
            )
        outs = self._session.run(None, {self._input_name: x})
        # skl2onnx classifier: [label, probabilities] with shape (1, 2)
        if len(outs) >= 2:
            prob = np.asarray(outs[1], dtype=np.float64).reshape(-1)
            if prob.size >= 2:
                return float(np.clip(prob[1], 0.0, 1.0))
            return float(np.clip(prob[0], 0.0, 1.0))
        arr = np.asarray(outs[0], dtype=np.float64).ravel()
        return float(np.clip(arr[-1] if arr.size else 0.0, 0.0, 1.0))
