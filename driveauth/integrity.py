"""Application-level startup integrity check (Phase D).

Hashes ``policy.yaml`` and listed model files against a signed manifest.
This is **not** full secure boot — see ``docs/secure-boot.md``. Fail closed
when verification is enabled and the manifest mismatches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

logger = logging.getLogger("driveauth.integrity")

MANIFEST_NAME = "integrity_manifest.json"
SIG_NAME = "integrity_manifest.sig"


class IntegrityError(RuntimeError):
    """Raised when integrity check fails closed."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    *,
    root: Path,
    relative_paths: list[str],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files: dict[str, str] = {}
    for rel in relative_paths:
        path = (root / rel).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"manifest file missing: {rel}")
        files[rel.replace("\\", "/")] = sha256_file(path)
    return {
        "version": 1,
        "files": files,
        "meta": meta or {},
    }


def manifest_canonical_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict[str, Any], private_key: Ed25519PrivateKey) -> bytes:
    return private_key.sign(manifest_canonical_bytes(manifest))


def verify_manifest_signature(
    manifest: dict[str, Any],
    signature: bytes,
    public_key: Ed25519PublicKey,
) -> bool:
    try:
        public_key.verify(signature, manifest_canonical_bytes(manifest))
        return True
    except InvalidSignature:
        return False


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def dump_private_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def dump_public_key(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def load_private_key(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_public_key(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def default_model_relpaths(store_dir: Path) -> list[str]:
    """ONNX / model files commonly loaded from a store (if present)."""
    candidates = [
        "risk_gbt.onnx",
        "trust_fusion.onnx",
        "voice_calibrator.onnx",
        "face_pad.onnx",
        "face_calibrator.onnx",
        "orchestrator_mlp.onnx",
        "behavioral_model.onnx",
        "behavioral_lstm_int8.onnx",
        "fingernet_lite_int8.onnx",
        "models/mobilefacenet.onnx",
        "mobilefacenet.onnx",
    ]
    return [c for c in candidates if (store_dir / c).is_file()]


def verify_store_integrity(
    store_dir: str | Path,
    *,
    policy_path: Path | None = None,
    public_key: Ed25519PublicKey | None = None,
    public_key_path: Path | None = None,
    fail_closed: bool | None = None,
) -> tuple[bool, str]:
    """Verify signed manifest against on-disk hashes.

    When ``DRIVEAUTH_INTEGRITY_CHECK=1`` (or ``fail_closed=True``), mismatches
    raise :class:`IntegrityError`. When disabled, returns ``(True, "skipped")``.
    """
    enabled = fail_closed
    if enabled is None:
        enabled = os.getenv("DRIVEAUTH_INTEGRITY_CHECK", "").strip() in (
            "1",
            "true",
            "yes",
        )
    store = Path(store_dir)
    manifest_path = store / MANIFEST_NAME
    sig_path = store / SIG_NAME

    if not enabled:
        return True, "skipped"

    if not manifest_path.is_file() or not sig_path.is_file():
        raise IntegrityError(
            f"Integrity check enabled but missing {MANIFEST_NAME} / {SIG_NAME}"
        )

    if public_key is None:
        key_path = public_key_path or Path(
            os.getenv(
                "DRIVEAUTH_INTEGRITY_PUBKEY",
                str(store / "integrity_ed25519.pub"),
            )
        ).expanduser()
        if not key_path.is_file():
            raise IntegrityError(f"Integrity pubkey missing: {key_path}")
        public_key = load_public_key(key_path.read_bytes())

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signature = sig_path.read_bytes()
    if not verify_manifest_signature(manifest, signature, public_key):
        raise IntegrityError("Integrity manifest signature invalid")

    files = manifest.get("files") or {}
    # Always include policy if provided / packaged.
    if policy_path is not None and policy_path.is_file():
        # Policy may live outside store; compare via absolute hash if listed
        # under a stable key.
        pass

    for rel, expected in files.items():
        # Policy may be referenced as "policy.yaml" relative to package or store.
        if rel in ("policy.yaml", "driveauth/policy.yaml"):
            from driveauth import config as cfg

            p = policy_path or cfg._policy_path()
            if not p.is_file():
                raise IntegrityError(f"policy missing for integrity check: {rel}")
            actual = sha256_file(Path(p))
        else:
            path = store / rel
            if not path.is_file():
                raise IntegrityError(f"manifest file missing on disk: {rel}")
            actual = sha256_file(path)
        if actual != expected:
            raise IntegrityError(f"hash mismatch: {rel}")

    logger.info("Integrity check OK (%d file(s))", len(files))
    return True, "ok"
