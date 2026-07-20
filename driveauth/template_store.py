"""Encrypted biometric template I/O (Fernet) — shared by voice/face enrollment.

Key material lives in ``store_dir/.bio_key``. By default a
:class:`~driveauth.key_protection.SoftwareKeyProtector` stores the Fernet
key verbatim (Phase-3 behaviour). Pass a :class:`KeyProtector` (e.g.
``TPMKeyProtector``) to seal that key with a secure element — defense in
depth on top of Fernet, not a replacement.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from driveauth.key_protection import (
    KEY_PATH_NAME,
    KeyProtector,
    SoftwareKeyProtector,
    default_protector,
    read_store_key,
    write_store_key,
)

logger = logging.getLogger("driveauth.templates")


class TemplateStore:
    """Fernet template I/O with pluggable key protection (default: software)."""

    def __init__(
        self,
        store_dir: str | Path,
        protector: KeyProtector | None = None,
    ):
        self.store_dir = Path(store_dir)
        self.protector: KeyProtector = protector or default_protector()

    def ensure_key(self) -> Path:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        key_path = self.store_dir / KEY_PATH_NAME
        if not key_path.exists():
            from cryptography.fernet import Fernet

            write_store_key(
                self.store_dir, Fernet.generate_key(), self.protector
            )
        return key_path

    def _fernet(self):
        from cryptography.fernet import Fernet

        self.ensure_key()
        return Fernet(read_store_key(self.store_dir, self.protector))

    def save_embedding(self, relative: str, emb: np.ndarray) -> Path:
        out = self.store_dir / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        vec = emb.astype(np.float32).ravel()
        norm = float(np.linalg.norm(vec))
        if norm > 1e-8:
            vec = vec / norm
        out.write_bytes(self._fernet().encrypt(vec.tobytes()))
        return out

    def load_embedding(self, relative: str) -> np.ndarray | None:
        path = self.store_dir / relative
        key_path = self.store_dir / KEY_PATH_NAME
        if not path.exists() or not key_path.exists():
            return None
        try:
            raw = self._fernet().decrypt(path.read_bytes())
            emb = np.frombuffer(raw, dtype=np.float32).copy()
            norm = float(np.linalg.norm(emb))
            if norm > 1e-8:
                emb /= norm
            return emb
        except Exception as exc:
            logger.warning("template load failed (%s): %s", relative, exc)
            return None


def ensure_key(
    store_dir: str | Path,
    protector: KeyProtector | None = None,
) -> Path:
    return TemplateStore(store_dir, protector=protector).ensure_key()


def save_embedding(
    store_dir: str | Path,
    relative: str,
    emb: np.ndarray,
    protector: KeyProtector | None = None,
) -> Path:
    """Save a float32 embedding under store_dir/relative (encrypted)."""
    return TemplateStore(store_dir, protector=protector).save_embedding(
        relative, emb
    )


def load_embedding(
    store_dir: str | Path,
    relative: str,
    protector: KeyProtector | None = None,
) -> np.ndarray | None:
    return TemplateStore(store_dir, protector=protector).load_embedding(relative)


# Re-export for callers that configure protection alongside the store.
__all__ = [
    "TemplateStore",
    "ensure_key",
    "save_embedding",
    "load_embedding",
    "KeyProtector",
    "SoftwareKeyProtector",
]
