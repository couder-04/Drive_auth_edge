"""Encrypted biometric template I/O (Fernet) — shared by voice/face enrollment."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("driveauth.templates")


def ensure_key(store_dir: str | Path) -> Path:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    key_path = store / ".bio_key"
    if not key_path.exists():
        from cryptography.fernet import Fernet

        key_path.write_bytes(Fernet.generate_key())
    return key_path


def save_embedding(store_dir: str | Path, relative: str, emb: np.ndarray) -> Path:
    """Save a float32 embedding under store_dir/relative (encrypted)."""
    from cryptography.fernet import Fernet

    store = Path(store_dir)
    key_path = ensure_key(store)
    out = store / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    vec = emb.astype(np.float32).ravel()
    norm = float(np.linalg.norm(vec))
    if norm > 1e-8:
        vec = vec / norm
    f = Fernet(key_path.read_bytes())
    out.write_bytes(f.encrypt(vec.tobytes()))
    return out


def load_embedding(store_dir: str | Path, relative: str) -> np.ndarray | None:
    from cryptography.fernet import Fernet

    store = Path(store_dir)
    path = store / relative
    key_path = store / ".bio_key"
    if not path.exists() or not key_path.exists():
        return None
    try:
        f = Fernet(key_path.read_bytes())
        raw = f.decrypt(path.read_bytes())
        emb = np.frombuffer(raw, dtype=np.float32).copy()
        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb /= norm
        return emb
    except Exception as exc:
        logger.warning("template load failed (%s): %s", relative, exc)
        return None
