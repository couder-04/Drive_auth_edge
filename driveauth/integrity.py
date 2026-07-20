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
    """ONNX / model files commonly loaded from a store (if present).

    Includes per-driver Stage-2 bio heads under ``faces/{id}/`` and
    ``voices/{id}/``, plus legacy store-root copies when still present.
    """
    from driveauth.stage2_artifacts import default_bio_model_relpaths

    store = Path(store_dir)
    candidates = [
        "risk_gbt.onnx",
        "trust_fusion.onnx",
        "orchestrator_mlp.onnx",
        "behavioral_model.onnx",
        "behavioral_lstm_int8.onnx",
        "fingernet_lite_int8.onnx",
        "models/mobilefacenet.onnx",
        "mobilefacenet.onnx",
    ]
    out = [c for c in candidates if (store / c).is_file()]
    out.extend(default_bio_model_relpaths(store))
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for rel in out:
        if rel not in seen:
            seen.add(rel)
            uniq.append(rel)
    return uniq


def check_driver_store(
    store_dir: Path | str,
    driver_id: str,
    *,
    allow_legacy: bool = True,
) -> dict[str, Any]:
    """Per-driver integrity-style checklist (templates + Stage-2 + meta).

    Returns a structured report; does not raise. Compatibility mode accepts
    legacy shared Stage-2 heads when ``allow_legacy`` is True.
    """
    from driveauth.stage2_artifacts import (
        BIO_ARTIFACTS,
        stage2_status_for_driver,
    )

    store = Path(store_dir)
    errors: list[str] = []
    warnings: list[str] = []
    face_enc = store / "faces" / f"{driver_id}.enc"
    voice_enc = store / "voices" / f"{driver_id}.enc"
    if not face_enc.is_file():
        errors.append(f"missing face template: faces/{driver_id}.enc")
    if not voice_enc.is_file():
        errors.append(f"missing voice template: voices/{driver_id}.enc")

    s2 = stage2_status_for_driver(store, driver_id, allow_legacy=allow_legacy)
    for art in BIO_ARTIFACTS:
        info = s2["artifacts"][art]
        if not info["present"]:
            errors.append(f"missing Stage-2 {art} for {driver_id}")
        elif info["source"] == "legacy_shared":
            warnings.append(
                f"{art} for {driver_id} is LEGACY shared (compatibility mode) — "
                "migrate / retrain per-driver"
            )
        elif info.get("training_origin") == "migrated_copy":
            warnings.append(
                f"{art} for {driver_id} is a migrated shared snapshot — "
                "retrain with scripts/train_*.py --driver-id before production use"
            )
    if s2.get("needs_retrain"):
        warnings.append(
            f"{driver_id} Stage-2 mode={s2.get('mode')} — independent retrain required"
        )

    # Threshold awareness: stock vs deployed
    try:
        from driveauth.config import policy_bar_overrides

        overrides = policy_bar_overrides()
        if overrides:
            warnings.append(
                f"{len(overrides)} policy bar(s) differ from policy.yaml stock"
            )
    except Exception as exc:  # pragma: no cover
        warnings.append(f"could not audit thresholds: {exc}")

    return {
        "driver_id": driver_id,
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "compatibility_mode": any(
            s2["artifacts"][a]["source"] == "legacy_shared" for a in BIO_ARTIFACTS
        ),
        "stage2": s2,
        "face_template": face_enc.is_file(),
        "voice_template": voice_enc.is_file(),
    }


def check_all_drivers(store_dir: Path | str, *, allow_legacy: bool = True) -> dict[str, Any]:
    from driveauth.stage2_artifacts import list_enrolled_driver_ids

    store = Path(store_dir)
    drivers = list_enrolled_driver_ids(store)
    per = {
        did: check_driver_store(store, did, allow_legacy=allow_legacy) for did in drivers
    }
    return {
        "store": str(store.resolve()),
        "drivers": drivers,
        "reports": per,
        "all_ok": all(r["ok"] for r in per.values()) if per else False,
    }


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
